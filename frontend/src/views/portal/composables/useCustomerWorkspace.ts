import { computed, inject, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { PortalNavigateKey } from '../injectionKeys'
import { withRetry } from '../../../composables/useRetry'
import { extractErrorDetail, notifyOperationError } from '../../../utils/requestError'
import { customerDisplayPeriodLabel, customerDisplayCutoffDate, workspaceTrendDateRange, workspaceTrendPeriodLabel, type WorkspaceTrendPreset } from '../../../utils/customerMonitorDate'
import { onMonitorRefresh } from '../../../utils/monitorRefresh'
import { useAuthStore } from '../../../stores/auth'
import {
  getWorkspaceBrief,
  type WorkspaceAlert,
  type WorkspaceBrief,
  type WorkspacePlatformHighlight,
  type WorkspaceSnapshot,
} from '../../../services/monitor'
import { platformLabelMap, platformAccentColor, supportedPlatforms, formatPlatformLabels } from '../portalMaps'
import { sortPlatformRows } from '../platformOrder'
import { formatDateTime } from '../portalUtils'
import { parsePreviewTenantId, parsePreviewTenantName, previewQueryFields } from '../customerPreview'

export type WorkspaceHeroTone = 'empty' | 'calm' | 'warn'

function formatRank(value: number | null | undefined) {
  if (value === null || value === undefined) return '-'
  return Number.isInteger(value) ? String(value) : value.toFixed(1)
}

function formatExposureLabel(mentioned?: boolean) {
  return mentioned ? '已提及' : '未提及'
}

function formatKpiDelta(
  value: number | null | undefined,
  unit: string,
  betterWhenLower = false,
  deltaKind: 'default' | 'rank' | 'count' = 'default',
) {
  if (value === null || value === undefined) return null
  if (Math.abs(value) < 0.05) return '较上一轮 持平'
  const steps = Math.abs(value)
  const label = Number.isInteger(steps) ? String(steps) : steps.toFixed(1)
  if (betterWhenLower && deltaKind === 'rank') {
    return value < 0 ? `前移 ${label}${unit} · 较上一轮` : `后移 ${label}${unit} · 较上一轮`
  }
  if (betterWhenLower && deltaKind === 'count') {
    return value < 0 ? `减少 ${label}${unit} · 较上一轮` : `增加 ${label}${unit} · 较上一轮`
  }
  const sign = value > 0 ? '+' : ''
  return `${sign}${value}${unit} · 较上一轮`
}

function kpiDeltaClass(value: number | null | undefined, betterWhenLower = false) {
  if (value === null || value === undefined || Math.abs(value) < 0.05) return ''
  const improved = betterWhenLower ? value < 0 : value > 0
  return improved ? 'delta-up' : 'delta-down'
}

function snapshotMetric(snapshot: WorkspaceSnapshot) {
  if (snapshot.prompt_intent === 'ranking') {
    return snapshot.brand_rank != null ? `排名第 ${formatRank(snapshot.brand_rank)} 位` : formatExposureLabel(snapshot.brand_mentioned)
  }
  if (snapshot.sentiment === '负面') return `情感：负面`
  if (snapshot.sentiment === '正面') return `情感：正面`
  return formatExposureLabel(snapshot.brand_mentioned)
}

function snapshotIntentClass(snapshot: WorkspaceSnapshot) {
  if (snapshot.prompt_intent === 'ranking') return 'intent-ranking'
  if (snapshot.sentiment === '负面') return 'intent-negative'
  if (snapshot.sentiment === '正面') return 'intent-positive'
  return 'intent-exposure'
}

function snapshotIntentLabel(snapshot: WorkspaceSnapshot) {
  if (snapshot.prompt_intent === 'ranking') return '排名'
  if (snapshot.sentiment === '负面') return '负面'
  if (snapshot.sentiment === '正面') return '正面'
  return '口碑'
}

function resolveActiveRound(data: WorkspaceBrief) {
  const latest = data.latest_schedule
  const previous = data.previous_schedule
  const kpiTotal = data.kpis.ranking_sample_count + data.kpis.exposure_sample_count

  const latestCompleted = latest?.completed_subtasks ?? 0
  if (latestCompleted > 0) {
    return {
      schedule: latest,
      completed: latestCompleted,
      usingPrevious: false as const,
    }
  }

  const prevCompleted = previous?.completed_subtasks ?? 0
  if (prevCompleted > 0) {
    return {
      schedule: previous,
      completed: prevCompleted,
      usingPrevious: true as const,
    }
  }

  if (kpiTotal > 0) {
    return {
      schedule: latest ?? previous,
      completed: kpiTotal,
      usingPrevious: false as const,
    }
  }

  return null
}

function resolveHeroTone(data: WorkspaceBrief | null): WorkspaceHeroTone {
  if (!data) return 'empty'
  const hasData = data.kpis.ranking_sample_count > 0
    || data.kpis.exposure_sample_count > 0
    || data.recent_snapshots.length > 0
  if (!hasData) return 'empty'
  const hasWarn = data.alerts.some(alert => alert.level === 'warn')
  return hasWarn ? 'warn' : 'calm'
}

function resolveStatusSummary(data: WorkspaceBrief, tone: WorkspaceHeroTone) {
  if (tone === 'empty') {
    return '截至昨日暂无已完成检测，请等待监测任务返回。'
  }
  if (tone === 'calm') {
    const latest = data.latest_schedule?.schedule_label
    return latest
      ? `${latest.replace(/\d{1,2}:\d{2}/g, '').replace(/[·•]\s*$/g, '').trim() || '最新监测'} 数据已更新，推荐露出与排名表现整体稳定。`
      : '截至昨日，推荐类监测表现整体稳定。'
  }
  const firstWarn = data.alerts.find(alert => alert.level === 'warn')
  if (firstWarn) return firstWarn.message
  return '监测数据存在需关注项，请查看下方提醒。'
}

function resolvePrimaryAction(data: WorkspaceBrief, tone: WorkspaceHeroTone) {
  if (tone === 'empty') return null
  if (data.kpis.competitor_count > 0 && tone === 'calm') {
    return { menu: 'customer.competitor', label: '查看竞品对比' }
  }
  return { menu: 'customer.realtime', label: '查看实时检测' }
}

function alertTargetMenu(alert: WorkspaceAlert) {
  if (/竞品/.test(alert.message)) return 'customer.competitor'
  if (/信源|引用/.test(alert.message)) return 'customer.sources'
  if (/负面|口碑/.test(alert.message)) return 'customer.realtime'
  if (/排名|露出/.test(alert.message)) return 'customer.realtime'
  return 'customer.realtime'
}

function formatPlatformDelta(value: number | null | undefined, unit: string, betterWhenLower = false) {
  if (value === null || value === undefined) return null
  if (Math.abs(value) < 0.05) return '持平'
  if (betterWhenLower) {
    const steps = Math.abs(value)
    const label = Number.isInteger(steps) ? String(steps) : steps.toFixed(1)
    return value < 0 ? `前移 ${label}${unit}` : `后移 ${label}${unit}`
  }
  const sign = value > 0 ? '+' : ''
  return `${sign}${value}${unit}`
}

function platformDeltaClass(value: number | null | undefined, betterWhenLower = false) {
  if (value === null || value === undefined || Math.abs(value) < 0.05) return ''
  const improved = betterWhenLower ? value < 0 : value > 0
  return improved ? 'delta-up' : 'delta-down'
}

function sortPlatformHighlights(rows: WorkspacePlatformHighlight[]) {
  return sortPlatformRows(rows)
}

function platformLeaderRank(row: WorkspacePlatformHighlight, sorted: WorkspacePlatformHighlight[]) {
  if (row.sample_count === 0) return 0
  const active = sorted.filter(item => item.sample_count > 0)
  const index = active.findIndex(item => item.platform === row.platform)
  return index >= 0 && index < 3 ? index + 1 : 0
}

function kpiTrendValues(brief: WorkspaceBrief | null, key: 'mention_rate' | 'avg_brand_rank' | 'top3_rate' | 'negative_count') {
  return (brief?.kpi_trends || []).map(point => point[key] ?? null)
}

function greetingLabel() {
  const hour = new Date().getHours()
  if (hour < 12) return '早上好'
  if (hour < 18) return '下午好'
  return '晚上好'
}

function computeHealthScore(data: WorkspaceBrief) {
  if (data.health_score != null) return data.health_score
  const visibility = computeVisibilityScore(data)
  const rankScore = computeRankScore(data)
  const competitorScore = computeCompetitorScore(data)
  const hasCompetitor = (data.kpis.competitor_count || 0) > 0 && competitorScore != null
  if (hasCompetitor) {
    if (rankScore != null) {
      return Math.round(visibility * 0.5 + rankScore * 0.3 + competitorScore * 0.2)
    }
    return Math.round(visibility * 0.65 + competitorScore * 0.35)
  }
  if (rankScore == null) return visibility
  return Math.round(visibility * 0.6 + rankScore * 0.4)
}

function computeVisibilityScore(data: WorkspaceBrief) {
  const mention = data.kpis.brand_mention_rate
  const top3 = data.kpis.top3_rate ?? 0
  return Math.round(mention * 0.6 + top3 * 0.4)
}

function computeRankScore(data: WorkspaceBrief) {
  const avgRank = data.kpis.avg_brand_rank
  if (avgRank == null) return null
  return Math.round(Math.max(0, Math.min(100, 100 - (avgRank - 1) * 20)))
}

function computeCompetitorScore(data: WorkspaceBrief) {
  if (data.competitor_score != null) return data.competitor_score
  if ((data.kpis.competitor_count || 0) <= 0) return null
  const delta = data.competitor_lead_delta
  if (delta == null) return null
  return Math.round(Math.max(0, Math.min(100, 50 + delta)))
}

function resolveWorkspaceHeadline(data: WorkspaceBrief, tone: WorkspaceHeroTone) {
  if (tone === 'empty') {
    return '截至昨日暂无已完成检测，请等待监测任务返回'
  }
  const rc = data.round_comparison
  if (rc?.has_previous) {
    const parts: string[] = []
    if (rc.mention_rate_delta != null && Math.abs(rc.mention_rate_delta) >= 0.05) {
      parts.push(`提及率${rc.mention_rate_delta > 0 ? '上升' : '下降'} ${Math.abs(rc.mention_rate_delta).toFixed(1)}%`)
    }
    if (rc.avg_brand_rank_delta != null && Math.abs(rc.avg_brand_rank_delta) >= 0.05) {
      parts.push(`均排名${rc.avg_brand_rank_delta < 0 ? '前移' : '后移'} ${Math.abs(rc.avg_brand_rank_delta).toFixed(1)} 位`)
    }
    if (parts.length) {
      return `较上一轮，${parts.join('，')}`
    }
  }
  const leader = data.platform_highlights
    .filter(row => row.sample_count > 0)
    .sort((a, b) => b.mention_rate - a.mention_rate)[0]
  if (leader && tone === 'warn') {
    const label = platformLabelMap[leader.platform] || leader.platform
    return `${label} 等平台的露出或排名需关注，建议查看实时监测详情`
  }
  if (tone === 'warn') {
    const firstWarn = data.alerts.find(alert => alert.level === 'warn')
    if (firstWarn) return firstWarn.message
  }
  const latest = data.latest_schedule?.schedule_label
  const latestLabel = latest?.replace(/\d{1,2}:\d{2}/g, '').replace(/[·•]\s*$/g, '').trim()
  return latestLabel
    ? `${latestLabel} 数据已更新，推荐露出与排名表现整体稳定`
    : '截至昨日，推荐类监测表现整体稳定'
}

function gaugeDashOffset(score: number, circumference = 176) {
  const clamped = Math.max(0, Math.min(100, score))
  return circumference - (circumference * clamped) / 100
}

export function useCustomerWorkspace() {
  const router = useRouter()
  const route = useRoute()
  const auth = useAuthStore()
  const portalNavigate = inject(PortalNavigateKey, null)
  const brief = ref<WorkspaceBrief | null>(null)
  const loading = ref(false)
  const loadError = ref('')
  const alertsExpanded = ref(false)
  const alertsSectionRef = ref<HTMLElement | null>(null)
  const alertsFocused = ref(false)
  const trendPreset = ref<WorkspaceTrendPreset>('7d')
  const initialTrendRange = workspaceTrendDateRange('7d')
  const trendStartDate = ref(initialTrendRange.startDate)
  const trendEndDate = ref(initialTrendRange.endDate)
  const trendMaxDate = customerDisplayCutoffDate()

  const realtimeMenuName = computed(() => (
    auth.allowedMenus.find(menu => menu.menu_code === 'customer.realtime')?.menu_name || '监测'
  ))
  const hasMenu = (menuCode: string) => auth.allowedMenus.some(menu => menu.menu_code === menuCode)

  const previewTenantId = computed(() => {
    if (auth.session?.identity?.identity_type !== 'PLATFORM') return null
    const fromPreview = parsePreviewTenantId(route)
    if (fromPreview != null) return fromPreview
    // 预览态下 sticky tenant_id 可作兜底（首跳竞态时 name 可能先于 id 可见）
    if (!parsePreviewTenantName(route)) return null
    const raw = route.query.tenant_id
    const text = Array.isArray(raw) ? raw[0] : raw
    const parsed = Number(text)
    return Number.isFinite(parsed) && parsed > 0 ? parsed : null
  })
  const previewTenantName = computed(() => parsePreviewTenantName(route))
  const isPreviewMode = computed(() => (
    auth.session?.identity?.identity_type === 'PLATFORM'
    && (parsePreviewTenantId(route) != null || Boolean(previewTenantName.value))
  ))
  const previewAccessRecorded = ref(false)

  const canOpenRealtime = computed(() => hasMenu('customer.realtime') || isPreviewMode.value)

  const heroTone = computed(() => resolveHeroTone(brief.value))
  const statusBadge = computed(() => {
    const tone = heroTone.value
    if (tone === 'empty') return { label: '等待数据', tone: 'neutral' as const }
    if (tone === 'calm') return { label: '整体稳定', tone: 'calm' as const }
    const warnCount = brief.value?.alerts.filter(alert => alert.level === 'warn').length || 0
    if (warnCount > 0) return { label: `${warnCount} 项需关注`, tone: 'warn' as const }
    return { label: '需关注', tone: 'warn' as const }
  })
  const statusSummary = computed(() => (
    brief.value ? resolveStatusSummary(brief.value, heroTone.value) : ''
  ))
  const primaryAction = computed(() => {
    const action = brief.value ? resolvePrimaryAction(brief.value, heroTone.value) : null
    if (!action) return null
    if (isPreviewMode.value) {
      return action
    }
    if (!hasMenu(action.menu)) return null
    const menuName = auth.allowedMenus.find(menu => menu.menu_code === action.menu)?.menu_name
    const useMenuName = action.label === '查看实时检测' && menuName
    return {
      ...action,
      label: useMenuName ? `查看${menuName}` : action.label,
    }
  })
  const warnAlerts = computed(() => brief.value?.alerts.filter(alert => alert.level === 'warn') || [])
  const infoAlerts = computed(() => brief.value?.alerts.filter(alert => alert.level === 'info') || [])
  const visibleAlerts = computed(() => {
    const alerts: WorkspaceAlert[] = [...warnAlerts.value, ...infoAlerts.value]
    if (alertsExpanded.value || alerts.length <= 2) return alerts
    return alerts.slice(0, 1)
  })
  const hiddenAlertCount = computed(() => {
    const total = warnAlerts.value.length + infoAlerts.value.length
    if (alertsExpanded.value || total <= 2) return 0
    return total - 1
  })

  const platformHighlightsSorted = computed(() => (
    sortPlatformHighlights(brief.value?.platform_highlights || [])
  ))

  const platformPeriodLabel = computed(() => (
    brief.value?.platform_period_label || customerDisplayPeriodLabel()
  ))

  const maxPlatformMentionRate = computed(() => {
    const rates = (brief.value?.platform_highlights || [])
      .filter(row => row.sample_count > 0)
      .map(row => row.mention_rate)
    return Math.max(1, ...rates)
  })

  const platformMatrixSummary = computed(() => {
    const rows = brief.value?.platform_highlights || []
    const active = rows.filter(row => row.sample_count > 0)
    const leader = platformHighlightsSorted.value.find(row => row.sample_count > 0) || null
    const avgMention = active.length
      ? active.reduce((sum, row) => sum + row.mention_rate, 0) / active.length
      : 0
    return {
      total: rows.length,
      activeCount: active.length,
      emptyCount: rows.length - active.length,
      avgMention,
      leader,
    }
  })

  function platformMentionBarWidth(mentionRate: number) {
    return Math.max(0, Math.min(100, (mentionRate / maxPlatformMentionRate.value) * 100))
  }

  const unpurchasedPlatforms = computed(() => {
    const purchased = new Set(brief.value?.purchased_platforms || [])
    return supportedPlatforms.filter(platform => !purchased.has(platform.code))
  })

  const showUnpurchasedDeck = computed(() => unpurchasedPlatforms.value.length > 0)

  const healthScore = computed(() => (brief.value ? computeHealthScore(brief.value) : null))

  const workspaceHeadline = computed(() => (
    brief.value ? resolveWorkspaceHeadline(brief.value, heroTone.value) : ''
  ))

  const visibilityScore = computed(() => (
    brief.value?.visibility_score ?? (brief.value ? computeVisibilityScore(brief.value) : null)
  ))

  const rankScore = computed(() => (
    brief.value?.rank_score !== undefined
      ? brief.value.rank_score
      : (brief.value ? computeRankScore(brief.value) : null)
  ))

  const competitorScore = computed(() => (
    brief.value ? computeCompetitorScore(brief.value) : null
  ))

  const healthScoreExplanation = computed(() => {
    const data = brief.value
    if (!data) return []
    const vis = visibilityScore.value ?? 0
    const rank = rankScore.value
    const comp = competitorScore.value
    const mention = data.kpis.brand_mention_rate
    const top3 = data.kpis.top3_rate ?? 0
    const avgRank = data.kpis.avg_brand_rank
    const total = healthScore.value
    const hasCompetitor = (data.kpis.competitor_count || 0) > 0 && comp != null
    const lines = [
      '基于本轮已完成的推荐类监测样本，满分 100：',
      `可见度分 ${vis} = 品牌提及率 ${mention}% × 60% + 前三占比 ${top3}% × 40%`,
    ]
    if (rank != null) {
      lines.push(`排名分 ${rank} = 均排名 ${avgRank}（第 1 位 100 分，每后移 1 位减 20 分）`)
    } else {
      lines.push('本轮暂无排名样本，健康分暂不纳入排名维度')
    }
    if (hasCompetitor) {
      const delta = data.competitor_lead_delta
      const topComp = data.top_competitor_mention_rate
      lines.push(
        `竞品分 ${comp} = 品牌提及率较最强竞品${delta != null && delta >= 0 ? '领先' : '落后'} ${delta != null ? Math.abs(delta) : 0}%（最强竞品 ${topComp ?? '-'}%）`,
      )
      lines.push(
        rank != null
          ? `健康分 ${total} = 可见度 × 50% + 排名 × 30% + 竞品 × 20%`
          : `健康分 ${total} = 可见度 × 65% + 竞品 × 35%`,
      )
    } else if (rank != null) {
      lines.push(`健康分 ${total} = 可见度分 × 60% + 排名分 × 40%`)
    } else {
      lines.push(`健康分 ${total} = 可见度分（无排名样本时不计入排名维度）`)
    }
    return lines
  })

  const healthScoreSummary = computed(() => {
    const vis = visibilityScore.value
    const rank = rankScore.value
    if (vis == null && rank == null) return ''
    if (rank == null) return `可见度 ${vis}%`
    if (vis == null) return `排名 ${rank}%`
    return `可见度 ${vis}% · 排名 ${rank}%`
  })

  const dimensionBars = computed(() => {
    const data = brief.value
    if (!data) return []
    const bars = [
      {
        key: 'visibility',
        label: '可见度',
        value: visibilityScore.value ?? 0,
        hint: `提及 ${data.kpis.brand_mention_rate}%`,
      },
      {
        key: 'rank',
        label: '排名',
        value: rankScore.value ?? 0,
        hint: data.kpis.avg_brand_rank != null ? `均排名 ${data.kpis.avg_brand_rank}` : '暂无排名样本',
      },
    ]
    if (data.kpis.competitor_count > 0) {
      const comp = competitorScore.value
      const delta = data.competitor_lead_delta
      bars.push({
        key: 'competitor',
        label: '较竞品',
        value: comp ?? 50,
        hint: delta != null
          ? `较最强竞品${delta >= 0 ? '领先' : '落后'} ${Math.abs(delta)}%`
          : `已配置 ${data.kpis.competitor_count} 个竞品`,
      })
    }
    return bars
  })

  const miniKpis = computed(() => {
    const data = brief.value
    if (!data) return []
    const rc = data.round_comparison
    return [
      {
        key: 'mention',
        label: '品牌提及率',
        value: data.kpis.brand_mention_rate,
        unit: '%',
        decimals: 1,
        delta: rc?.has_previous ? rc.mention_rate_delta : null,
        lowerIsBetter: false,
      },
      {
        key: 'rank',
        label: '平均推荐排名',
        value: data.kpis.avg_brand_rank,
        unit: '',
        decimals: 1,
        delta: rc?.has_previous ? rc.avg_brand_rank_delta : null,
        lowerIsBetter: true,
        deltaKind: 'rank' as const,
      },
      {
        key: 'top3',
        label: 'Top3 占比',
        value: data.kpis.top3_rate ?? 0,
        unit: '%',
        decimals: 1,
        delta: rc?.has_previous ? rc.top3_rate_delta : null,
        lowerIsBetter: false,
      },
    ]
  })

  const intentStats = computed(() => {
    const ranking = brief.value?.kpis.ranking_sample_count ?? 0
    const exposure = brief.value?.kpis.exposure_sample_count ?? 0
    const total = ranking + exposure || 1
    return {
      total: ranking + exposure,
      ranking,
      exposure,
      other: 0,
      rankingPct: Math.round(ranking / total * 100),
      exposurePct: Math.round(exposure / total * 100),
    }
  })

  const mentionDonut = computed(() => {
    const rate = brief.value?.kpis.brand_mention_rate ?? 0
    const mentioned = Math.max(0, Math.min(100, rate))
    return { mentioned, notMentioned: Math.round((100 - mentioned) * 10) / 10 }
  })

  const intentDonutSegments = computed(() => {
    const { rankingPct, exposurePct, total } = intentStats.value
    if (!total) return { ranking: 0, exposure: 0, circumference: 301.6 }
    const circumference = 2 * Math.PI * 48
    const rankingLen = (rankingPct / 100) * circumference
    const exposureLen = (exposurePct / 100) * circumference
    return { ranking: rankingLen, exposure: exposureLen, circumference }
  })

  const mentionDonutSegments = computed(() => {
    const circumference = 2 * Math.PI * 48
    const mentionedLen = (mentionDonut.value.mentioned / 100) * circumference
    return { mentioned: mentionedLen, notMentioned: circumference - mentionedLen, circumference }
  })

  const trendBars = computed(() => {
    const points = brief.value?.kpi_trends || []
    if (!points.length) return [] as Array<{ label: string; height: number; value: number }>
    const max = Math.max(...points.map(point => point.mention_rate), 1)
    return points.map(point => ({
      label: point.label,
      height: Math.max(4, (point.mention_rate / max) * 100),
      value: point.mention_rate,
    }))
  })

  const platformRankList = computed(() => {
    const active = platformHighlightsSorted.value.filter(row => row.sample_count > 0)
    const sorted = [...active].sort((a, b) => b.mention_rate - a.mention_rate)
    const empty = platformHighlightsSorted.value.filter(row => row.sample_count === 0)
    return [...sorted, ...empty]
  })

  const todoItems = computed(() => {
    const data = brief.value
    if (!data) return []
    return [
      {
        key: 'empty-platform',
        label: '平台待返回',
        count: platformMatrixSummary.value.emptyCount,
        tone: platformMatrixSummary.value.emptyCount > 0 ? 'warn' as const : '',
        menu: 'customer.realtime',
      },
      {
        key: 'competitor',
        label: '竞品对比',
        count: data.kpis.competitor_count,
        tone: '',
        menu: 'customer.competitor',
      },
    ].filter(item => hasMenu(item.menu))
  })

  const showTodoStrip = computed(() => (
    todoItems.value.some(item => item.count > 0)
  ))

  const activeRound = computed(() => (brief.value ? resolveActiveRound(brief.value) : null))

  const roundSummaryLine = computed(() => {
    const data = brief.value
    if (!data) return ''

    const active = activeRound.value
    if (!active) return '暂无已完成监测批次，请等待监测任务返回'

    const { schedule, completed, usingPrevious } = active
    const parts: string[] = [`${usingPrevious ? '上一轮' : '本轮'}完成 ${completed} 条`]

    const leader = platformMatrixSummary.value.leader
    if (leader) {
      const label = platformLabelMap[leader.platform] || leader.platform
      parts.push(`${label}提及最高（${leader.mention_rate.toFixed(1)}%）`)
    }

    const purchased = new Set(data.purchased_platforms || [])
    const pending = (data.platform_highlights || [])
      .filter(row => row.sample_count === 0 && purchased.has(row.platform))
      .map(row => platformLabelMap[row.platform] || row.platform)

    if (pending.length === 1) {
      parts.push(`${pending[0]} 待返回`)
    } else if (pending.length === 2) {
      parts.push(`${pending.join('、')} 待返回`)
    } else if (pending.length > 2) {
      parts.push(`${pending.slice(0, 2).join('、')} 等 ${pending.length} 个平台待返回`)
    }

    const batchLabel = schedule?.schedule_label
      || (usingPrevious
        ? data.round_comparison?.previous_schedule_label
        : data.round_comparison?.latest_schedule_label)
    if (batchLabel) {
      parts.push(`${usingPrevious ? '参考批次' : '最新批次'} ${batchLabel}`)
    }

    return parts.join(' · ')
  })

  const trendPeriodLabel = computed(() => (
    workspaceTrendPeriodLabel(trendPreset.value, trendStartDate.value, trendEndDate.value)
  ))

  function syncTrendRange(preset: WorkspaceTrendPreset) {
    const range = workspaceTrendDateRange(
      preset,
      trendStartDate.value,
      trendEndDate.value,
    )
    trendStartDate.value = range.startDate
    trendEndDate.value = range.endDate
  }

  function applyTrendPreset(preset: WorkspaceTrendPreset) {
    trendPreset.value = preset
    if (preset === 'custom') return
    syncTrendRange(preset)
    void loadBrief()
  }

  function onCustomTrendDateChange() {
    if (trendStartDate.value > trendEndDate.value) {
      trendStartDate.value = trendEndDate.value
    }
    if (trendEndDate.value > trendMaxDate) {
      trendEndDate.value = trendMaxDate
    }
    if (trendStartDate.value > trendMaxDate) {
      trendStartDate.value = trendMaxDate
    }
    trendPreset.value = 'custom'
    void loadBrief()
  }

  async function loadBrief() {
    const isPlatform = auth.session?.identity?.identity_type === 'PLATFORM'
    // 平台预览：query 未带齐企业 id 时不请求，等路由就绪后 watch 再拉
    if (isPlatform && isPreviewMode.value && previewTenantId.value == null) {
      return
    }
    loading.value = true
    loadError.value = ''
    try {
      const recordAccess = isPreviewMode.value && !previewAccessRecorded.value
      brief.value = await withRetry(() => getWorkspaceBrief({
        start_date: trendStartDate.value,
        end_date: trendEndDate.value,
        tenant_id: previewTenantId.value ?? undefined,
        record_access: recordAccess || undefined,
      }))
      if (recordAccess) previewAccessRecorded.value = true
    } catch (error: unknown) {
      notifyOperationError(error, '工作台数据加载失败')
      loadError.value = extractErrorDetail(error)
    } finally {
      loading.value = false
    }
  }

  function navigateToMenu(menuCode: string) {
    if (isPreviewMode.value) {
      if (portalNavigate) {
        portalNavigate(menuCode)
        return
      }
      router.push({
        path: route.path,
        query: {
          ...route.query,
          menu: menuCode,
          ...previewQueryFields(previewTenantId.value!, previewTenantName.value),
        },
      }).catch(() => undefined)
      return
    }
    if (portalNavigate) {
      portalNavigate(menuCode)
      return
    }
    router.push({ path: route.path, query: { ...route.query, menu: menuCode } }).catch(() => undefined)
  }

  function exitCustomerPreview() {
    if (portalNavigate) {
      portalNavigate('platform.audit')
      return
    }
    router.push({ path: route.path, query: { menu: 'platform.audit' } }).catch(() => undefined)
  }

  function focusWorkspaceAlerts() {
    const warns = warnAlerts.value
    if (!warns.length && !visibleAlerts.value.length) {
      const action = primaryAction.value
      if (action) navigateToMenu(action.menu)
      return
    }
    if (hiddenAlertCount.value > 0 || (brief.value?.alerts.length || 0) > 2) {
      alertsExpanded.value = true
    }
    nextTick(() => {
      alertsSectionRef.value?.scrollIntoView({ behavior: 'smooth', block: 'center' })
      alertsFocused.value = true
      window.setTimeout(() => {
        alertsFocused.value = false
      }, 2200)
    })
  }

  function openAlertTarget(alert: WorkspaceAlert) {
    const menu = alertTargetMenu(alert)
    if (!isPreviewMode.value && !hasMenu(menu)) return
    navigateToMenu(menu)
  }

  function openSnapshot(snapshot: WorkspaceSnapshot) {
    if (!isPreviewMode.value && !hasMenu('customer.realtime')) return
    const nextQuery: Record<string, string | string[]> = {
      ...route.query,
      menu: 'customer.realtime',
    }
    if (isPreviewMode.value && previewTenantId.value) {
      Object.assign(nextQuery, previewQueryFields(previewTenantId.value, previewTenantName.value))
    }
    if (snapshot.task_id) nextQuery.task_id = snapshot.task_id
    nextQuery.subtask_id = snapshot.subtask_id
    router.push({ path: route.path, query: nextQuery }).catch(() => undefined)
  }

  onMounted(() => {
    void loadBrief()
  })

  watch(
    () => previewTenantId.value,
    (tenantId, prev) => {
      if (tenantId != null && tenantId !== prev) void loadBrief()
    },
  )

  const stopMonitorRefresh = onMonitorRefresh(() => {
    void loadBrief()
  })
  onUnmounted(stopMonitorRefresh)

  return {
    brief,
    loading,
    loadError,
    alertsExpanded,
    alertsSectionRef,
    alertsFocused,
    heroTone,
    statusBadge,
    statusSummary,
    primaryAction,
    warnAlerts,
    infoAlerts,
    visibleAlerts,
    hiddenAlertCount,
    loadBrief,
    navigateToMenu,
    exitCustomerPreview,
    isPreviewMode,
    previewTenantName,
    focusWorkspaceAlerts,
    openAlertTarget,
    openSnapshot,
    alertTargetMenu,
    realtimeMenuName,
    canOpenRealtime,
    formatDateTime,
    formatRank,
    formatExposureLabel,
    formatKpiDelta,
    kpiDeltaClass,
    formatPlatformDelta,
    platformDeltaClass,
    platformHighlightsSorted,
    platformMatrixSummary,
    platformAccentColor,
    platformLeaderRank,
    platformMentionBarWidth,
    unpurchasedPlatforms,
    showUnpurchasedDeck,
    kpiTrendValues,
    snapshotMetric,
    snapshotIntentClass,
    snapshotIntentLabel,
    platformLabelMap,
    formatPlatformLabels,
    greetingLabel,
    customerPeriodLabel: customerDisplayPeriodLabel(),
    trendPreset,
    trendStartDate,
    trendEndDate,
    trendMaxDate,
    trendPeriodLabel,
    applyTrendPreset,
    onCustomTrendDateChange,
    platformPeriodLabel,
    healthScore,
    healthScoreExplanation,
    healthScoreSummary,
    workspaceHeadline,
    visibilityScore,
    rankScore,
    dimensionBars,
    miniKpis,
    intentStats,
    mentionDonut,
    intentDonutSegments,
    mentionDonutSegments,
    trendBars,
    platformRankList,
    todoItems,
    showTodoStrip,
    activeRound,
    roundSummaryLine,
    gaugeDashOffset,
  }
}
