import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { BarChart3, Database, Search } from '@lucide/vue'
import { withRetry } from '../../../composables/useRetry'
import { notifyOperationError } from '../../../utils/requestError'
import {
  getWorkspaceBrief,
  type WorkspaceAlert,
  type WorkspaceBrief,
  type WorkspacePlatformHighlight,
  type WorkspaceSnapshot,
} from '../../../services/monitor'
import { platformLabelMap, platformAccentColor, supportedPlatforms } from '../portalMaps'
import { formatDateTime } from '../portalUtils'

export type WorkspaceHeroTone = 'empty' | 'calm' | 'warn'

export const workspaceQuickLinks = [
  {
    code: 'customer.competitor',
    title: '品牌洞察',
    note: '提及率 · 排名 · 情绪趋势',
    icon: BarChart3,
  },
  {
    code: 'customer.realtime',
    title: '实时检测',
    note: '调度轮次 · 排名矩阵 · 子任务详情',
    icon: Search,
  },
  {
    code: 'customer.sources',
    title: '信源分析',
    note: '含露出词引用 · 监测问题溯源',
    icon: Database,
  },
] as const

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
    return data.next_schedule_hint
      ? `近 7 日暂无已完成检测，下次监测计划：${data.next_schedule_hint}`
      : '近 7 日暂无已完成检测，请等待定时监测任务返回。'
  }
  if (tone === 'calm') {
    const latest = data.latest_schedule?.schedule_label
    return latest
      ? `${latest} 数据已更新，推荐露出与排名表现整体稳定。`
      : '近 7 日推荐类监测表现整体稳定。'
  }
  const firstWarn = data.alerts.find(alert => alert.level === 'warn')
  if (firstWarn) return firstWarn.message
  return '监测数据存在需关注项，请查看下方提醒。'
}

function resolvePrimaryAction(data: WorkspaceBrief, tone: WorkspaceHeroTone) {
  if (tone === 'empty') return null
  if (data.alerts.some(alert => alert.level === 'warn' && /负面|舆情/.test(alert.message))) {
    return { menu: 'customer.realtime', label: '查看实时检测' }
  }
  if (data.alerts.some(alert => alert.level === 'warn' && /排名|露出/.test(alert.message))) {
    return { menu: 'customer.realtime', label: '查看实时检测' }
  }
  if (tone === 'warn') {
    return { menu: 'customer.realtime', label: '查看检测详情' }
  }
  return null
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
  return [...rows].sort((a, b) => {
    if (a.sample_count === 0 && b.sample_count === 0) return 0
    if (a.sample_count === 0) return 1
    if (b.sample_count === 0) return -1
    if (b.mention_rate !== a.mention_rate) return b.mention_rate - a.mention_rate
    return (a.avg_rank ?? 999) - (b.avg_rank ?? 999)
  })
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

export function useCustomerWorkspace() {
  const router = useRouter()
  const route = useRoute()
  const brief = ref<WorkspaceBrief | null>(null)
  const loading = ref(false)
  const alertsExpanded = ref(false)

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
  const primaryAction = computed(() => (
    brief.value ? resolvePrimaryAction(brief.value, heroTone.value) : null
  ))
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

  async function loadBrief() {
    loading.value = true
    try {
      brief.value = await withRetry(() => getWorkspaceBrief())
    } catch (error: unknown) {
      notifyOperationError(error, '工作台数据加载失败')
    } finally {
      loading.value = false
    }
  }

  function navigateToMenu(menuCode: string) {
    router.push({ path: route.path, query: { ...route.query, menu: menuCode } }).catch(() => undefined)
  }

  function openSnapshot(snapshot: WorkspaceSnapshot) {
    const nextQuery: Record<string, string | string[]> = { ...route.query, menu: 'customer.realtime' }
    if (snapshot.task_id) nextQuery.task_id = snapshot.task_id
    nextQuery.subtask_id = snapshot.subtask_id
    router.push({ path: route.path, query: nextQuery }).catch(() => undefined)
  }

  onMounted(() => {
    loadBrief()
  })

  return {
    brief,
    loading,
    alertsExpanded,
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
    openSnapshot,
    workspaceQuickLinks,
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
  }
}
