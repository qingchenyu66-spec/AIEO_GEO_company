import { computed, onMounted, onUnmounted, ref, watch, type ComputedRef, type Ref } from 'vue'
import { ElMessage } from 'element-plus'
import { withRetry } from '../../../composables/useRetry'
import { getSystemConfigs, type SystemConfigRecord, type TenantInfo } from '../../../services/management'
import { getMonitorSummary, syncMonitorTask, type MonitorSummary } from '../../../services/monitor'
import type { BrandAsset, BrandCompetitor } from '../../../services/brand'
import { getPlatformMatrix, type PlatformMatrix } from '../../../services/platforms'
import { useAuthStore } from '../../../stores/auth'
import { buildFunctionalPage } from '../functionalPageConfig'
import { platformLabelMap, supportedPlatforms } from '../portalMaps'
import { sortPlatformCodes, sortPlatformRows, sortPlatformTabs } from '../platformOrder'

export const monitorSummaryMenuCodes = new Set([
  'platform.dashboard',
  'platform.diagnosis',
  'platform.reports',
  'customer.workspace',
  'customer.diagnosis',
  'customer.reports',
  'platform.models',
])

const terminalTaskStatuses = new Set(['completed', 'partial_completed', 'failed', 'stopped'])


export const sourceCategoryLabels: Record<string, string> = {
  official: '官网/企业库',
  media: '行业媒体',
  qa: '问答社区',
  social: '社交媒体',
  encyclopedia: '百科',
}

function sourceCategory(source: { title?: string; url?: string }) {
  const text = `${source.title || ''} ${source.url || ''}`.toLowerCase()
  if (text.includes('baike') || text.includes('百科')) return 'encyclopedia'
  if (text.includes('zhihu') || text.includes('知乎') || text.includes('问答')) return 'qa'
  if (text.includes('weibo') || text.includes('微博') || text.includes('douyin') || text.includes('小红书')) return 'social'
  if (text.includes('sohu') || text.includes('163.com') || text.includes('媒体') || text.includes('新闻') || text.includes('资讯')) return 'media'
  return 'official'
}

type MonitorAnalyticsOptions = {
  activeMenuCode: Ref<string>
  isPlatform: ComputedRef<boolean>
  isDashboardPage: ComputedRef<boolean>
  brandAsset: Ref<BrandAsset | null>
  brandCompetitors: Ref<BrandCompetitor[]>
  tenants: Ref<TenantInfo[]>
  notifyError: (error: unknown, context: string) => void
  errorMessage: (error: unknown) => string
}

export function useMonitorAnalytics(options: MonitorAnalyticsOptions) {
  const { activeMenuCode, isPlatform, isDashboardPage, brandAsset, brandCompetitors, tenants, notifyError, errorMessage } = options
  const auth = useAuthStore()

  const monitorSummary = ref<MonitorSummary | null>(null)
  const loadingSummary = ref(false)
  const syncingMonitorResults = ref(false)
  let monitorSummaryTimer: number | null = null
  let lastSummaryErrorAt = 0

  const selectedSourcePlatform = ref('all')
  const sourceKeywordFilter = ref('')
  const sourceStartDate = ref('')
  const sourceEndDate = ref('')

  const systemConfigRows = ref<SystemConfigRecord[]>([])

  const platformMatrix = ref<PlatformMatrix | null>(null)
  const loadingPlatformMatrix = ref(false)
  let platformMatrixTimer: number | null = null

  const shouldLoadMonitorSummary = computed(() => monitorSummaryMenuCodes.has(activeMenuCode.value))
  const shouldLoadPlatformMatrix = computed(() => activeMenuCode.value === 'platform.models')

  const stats = computed(() => {
    const summary = monitorSummary.value
    if (isPlatform.value) {
      return [
        ['企业客户', String(summary?.tenant_count ?? tenants.value.length), '来自企业库'],
        ['监测任务', String(summary?.task_count ?? 0), `${summary?.subtask_count ?? 0} 个子任务`],
        ['接口消耗', `${summary?.total_cost ?? 0}`, '模力真实扣费'],
        ['异常预警', String(summary?.failed_count ?? 0), '失败或待复核'],
      ]
    }
    return [
      ['总检测次数', String(summary?.subtask_count ?? 0), '累计检测结果'],
      ['品牌曝光率', `${summary?.mention_rate ?? 0}%`, '品牌被提及占比'],
      ['平均推荐排名', summary?.avg_rank ? String(summary.avg_rank) : '-', '越靠前越好'],
      ['监控词', String(monitorKeywordList.value.length), '当前监测范围'],
    ]
  })

  const chartTrend = computed(() => {
    const rows = monitorSummary.value?.daily_trend || []
    return rows.filter(item => item.value > 0)
  })

  const platformRanking = computed(() => sortPlatformRows(monitorSummary.value?.platform_stats || []))
  const allSourceRanking = computed(() => monitorSummary.value?.source_stats || [])
  const recentSubtasks = computed(() => monitorSummary.value?.recent_subtasks || [])

  const platformCoverage = computed(() => {
    const known = monitorSummary.value?.platform_stats || []
    const purchasedCodes = brandAsset.value?.monitored_platforms?.length ? brandAsset.value.monitored_platforms : []
    const codes = sortPlatformCodes(purchasedCodes.length ? purchasedCodes : known.map(item => item.platform))
    return codes.map((code, index) => {
      const row = known.find(item => item.platform === code)
      return {
        code,
        name: platformLabelMap[code] || code,
        rate: row?.mention_rate ?? 0,
        total: row?.total ?? 0,
        status: row?.completed ? '已返回' : index < 5 ? '监测中' : '待接入',
      }
    })
  })

  const customerPlatformServices = computed(() => {
    const purchased = new Set(brandAsset.value?.monitored_platforms || [])
    return supportedPlatforms.map(platform => ({
      ...platform,
      purchased: purchased.has(platform.code),
    }))
  })

  const purchasedPlatformCount = computed(() => customerPlatformServices.value.filter(item => item.purchased).length)

  const sourcePlatformTabs = computed(() => {
    const counts = new Map<string, number>()
    allSourceRanking.value.forEach(source => {
      ;(source.platforms || []).forEach(platform => counts.set(platform, (counts.get(platform) || 0) + source.count))
    })
    return sortPlatformTabs([
      { code: 'all', name: '全部信源', count: allSourceRanking.value.reduce((sum, source) => sum + source.count, 0) },
      ...Array.from(counts.entries())
        .map(([code, count]) => ({ code, name: platformLabelMap[code] || code, count })),
    ])
  })

  const sourceRanking = computed(() => {
    const keyword = sourceKeywordFilter.value.trim().toLowerCase()
    const start = sourceStartDate.value ? new Date(`${sourceStartDate.value} 00:00:00`).getTime() : null
    const end = sourceEndDate.value ? new Date(`${sourceEndDate.value} 23:59:59`).getTime() : null
    return allSourceRanking.value.filter(source => {
      const platformMatched = selectedSourcePlatform.value === 'all' || (source.platforms || []).includes(selectedSourcePlatform.value)
      const text = `${source.title || ''} ${(source.exposure_terms || []).join(' ')} ${(source.questions || []).join(' ')}`.toLowerCase()
      const keywordMatched = !keyword || text.includes(keyword)
      const sourceTime = source.latest_time ? new Date(source.latest_time).getTime() : null
      const startMatched = !start || (sourceTime && sourceTime >= start)
      const endMatched = !end || (sourceTime && sourceTime <= end)
      return platformMatched && keywordMatched && startMatched && endMatched
    })
  })

  const sourceTrendRows = computed(() => {
    const backendPoints = monitorSummary.value?.source_citation_trend?.points || []
    if (backendPoints.length) {
      const points = backendPoints.length > 7 ? backendPoints.slice(-7) : backendPoints
      return points.map(point => ({ label: point.label, value: point.value }))
    }
    return []
  })

  const sourceStructureRows = computed(() => platformRanking.value.slice(0, 6).map(platform => {
    const platformSources = sourceRanking.value.filter(source => (source.platforms || []).includes(platform.platform))
    const total = Math.max(1, platformSources.reduce((sum, source) => sum + source.count, 0))
    const categoryMap = platformSources.reduce((map, source) => {
      const category = sourceCategory(source)
      map[category] = (map[category] || 0) + source.count
      return map
    }, {} as Record<string, number>)
    return {
      platform: platform.platform,
      total,
      categories: Object.keys(sourceCategoryLabels).map(type => ({
        type,
        value: Math.round(((categoryMap[type] || 0) / total) * 100),
      })),
    }
  }))

  const contentPreferenceRows = computed(() => {
    const rows = [
      { name: '案例研究', keys: ['案例', '客户', '项目'] },
      { name: '产品指南', keys: ['产品', '服务', '功能'] },
      { name: '问答内容', keys: ['怎么样', '什么', '推荐', '对比'] },
      { name: '行业报告', keys: ['报告', '行业', '趋势'] },
      { name: '新闻资讯', keys: ['新闻', '资讯', '媒体'] },
    ].map(row => {
      const value = sourceRanking.value.reduce((sum, source) => {
        const text = `${source.title || ''} ${(source.questions || []).join(' ')}`.toLowerCase()
        return sum + (row.keys.some(key => text.includes(key.toLowerCase())) ? source.count : 0)
      }, 0)
      return { name: row.name, value }
    })
    const total = rows.reduce((sum, row) => sum + row.value, 0) || 1
    return rows.map(row => ({ ...row, percent: Math.round((row.value / total) * 100) }))
  })

  const monitorKeywordList = computed(() => [...new Set([...(brandAsset.value?.monitor_keywords || []), ...(brandAsset.value?.product_keywords || [])])].filter(Boolean))
  const monitorKeywordTooltip = computed(() => monitorKeywordList.value.length ? monitorKeywordList.value.join('、') : '当前企业暂未配置监控词')

  const statTooltipMap = computed<Record<string, string>>(() => ({
    总检测次数: '计算方式：监测问题数 × 已购买模型平台数。每个平台回答一个问题，计为 1 条检测结果。',
    品牌曝光率: '计算方式：已返回结果中提及品牌的数量 ÷ 已返回结果总量 × 100%。任务同步过程中会按最新返回结果重新计算。',
    平均推荐排名: '计算方式：所有已提及品牌结果的排名位置求平均。数值越小，说明推荐位置越靠前。',
    监控词: `当前监控词：${monitorKeywordTooltip.value}`,
  }))

  const sentimentTotal = computed(() => Object.values(monitorSummary.value?.sentiment_counts || {}).reduce((sum: number, value) => sum + Number(value || 0), 0))
  const positiveRate = computed(() => {
    const total = sentimentTotal.value
    return total ? Math.round(((monitorSummary.value?.sentiment_counts?.['正面'] || 0) / total) * 100) : 0
  })
  const negativeRate = computed(() => {
    const total = sentimentTotal.value
    return total ? Math.round(((monitorSummary.value?.sentiment_counts?.['负面'] || 0) / total) * 100) : 0
  })
  const sourceTotalCount = computed(() => sourceRanking.value.reduce((sum, item) => sum + item.count, 0))

  const recentQuestionGroups = computed(() => {
    const expectedPlatforms = sortPlatformCodes(
      brandAsset.value?.monitored_platforms?.length
        ? brandAsset.value.monitored_platforms
        : platformRanking.value.map(item => item.platform),
    )
    const groups = new Map<string, {
      prompt: string
      tenant_name?: string | null
      platforms: string[]
      missing_platforms: string[]
      statuses: string[]
      completed: number
      total: number
      expected_total: number
      best_rank: number | null
      latest_time: string | null
    }>()
    recentSubtasks.value.forEach(item => {
      const prompt = item.prompt || '未命名检测问题'
      const row = groups.get(prompt) || {
        prompt,
        tenant_name: item.tenant_name,
        platforms: [],
        missing_platforms: [],
        statuses: [],
        completed: 0,
        total: 0,
        expected_total: expectedPlatforms.length || 0,
        best_rank: null,
        latest_time: null,
      }
      row.total += 1
      if (item.status === 'completed' || item.status === 'partial_completed') row.completed += 1
      if (item.platform && !row.platforms.includes(item.platform)) row.platforms.push(item.platform)
      if (item.status && !row.statuses.includes(item.status)) row.statuses.push(item.status)
      if (item.mention_position && (!row.best_rank || item.mention_position < row.best_rank)) row.best_rank = item.mention_position
      const itemTime = item.updated_at || null
      if (itemTime && (!row.latest_time || new Date(itemTime).getTime() > new Date(row.latest_time).getTime())) {
        row.latest_time = itemTime
      }
      groups.set(prompt, row)
    })
    return Array.from(groups.values()).map(row => ({
      ...row,
      expected_total: row.expected_total || row.platforms.length,
      missing_platforms: expectedPlatforms.filter(platform => !row.platforms.includes(platform)),
    }))
      .sort((a, b) => new Date(b.latest_time || 0).getTime() - new Date(a.latest_time || 0).getTime())
      .slice(0, 6)
  })

  const systemSettings = computed(() => systemConfigRows.value.map(row => {
    const isSecret = /key|token|secret|password/i.test(row.config_key)
    const value = isSecret && row.config_value ? `${row.config_value.slice(0, 4)}****${row.config_value.slice(-4)}` : row.config_value
    return [
      row.config_key,
      value || '-',
      row.remark || row.scope || '平台运行配置',
      row.status ? '启用' : '停用',
    ]
  }))

  const functionalPage = computed(() => {
    const menuName = auth.allowedMenus.find(item => item.menu_code === activeMenuCode.value)?.menu_name
    return buildFunctionalPage(
      activeMenuCode.value,
      monitorSummary.value,
      sourceTotalCount.value,
      sourceRanking.value.length,
      menuName,
    )
  })

  const sentimentPieRows = computed(() => {
    const counts = monitorSummary.value?.sentiment_counts || {}
    return Object.entries(counts)
      .filter(([, value]) => Number(value) > 0)
      .map(([name, value]) => ({ name, value: Number(value) }))
  })

  const diagnosisScore = computed(() => {
    if (!monitorSummary.value || !sentimentTotal.value) return 0
    const mentionScore = Math.min(100, monitorSummary.value.mention_rate || 0)
    const rankScore = monitorSummary.value.avg_rank ? Math.max(0, 100 - monitorSummary.value.avg_rank * 12) : 0
    return Math.round(mentionScore * 0.45 + positiveRate.value * 0.35 + rankScore * 0.2)
  })

  async function syncPendingTasksFromSummary(summary: MonitorSummary) {
    if (syncingMonitorResults.value) return false
    const pendingTasks = (summary.recent_tasks || [])
      .filter(task => !terminalTaskStatuses.has(task.status))
      .slice(0, 5)
    if (!pendingTasks.length) return false
    syncingMonitorResults.value = true
    try {
      await Promise.allSettled(pendingTasks.map(task => withRetry(() => syncMonitorTask(task.task_id), 1)))
      return true
    } finally {
      syncingMonitorResults.value = false
    }
  }

  async function loadMonitorSummary(syncRemote = false) {
    if (!shouldLoadMonitorSummary.value && !syncRemote) return
    loadingSummary.value = true
    try {
      const summary = await withRetry(() => getMonitorSummary())
      monitorSummary.value = summary
      if (syncRemote) {
        const synced = await syncPendingTasksFromSummary(summary)
        if (synced) {
          monitorSummary.value = await withRetry(() => getMonitorSummary())
        }
      }
    } catch (error: unknown) {
      const now = Date.now()
      if (!monitorSummary.value && now - lastSummaryErrorAt > 120000) {
        ElMessage.warning(`首页数据暂时加载较慢，已保留当前页面：${errorMessage(error)}`)
        lastSummaryErrorAt = now
      } else {
        console.warn('首页真实数据加载失败', error)
      }
    } finally {
      loadingSummary.value = false
    }
  }

  async function loadPlatformMatrix(force = false) {
    if (!shouldLoadPlatformMatrix.value) return
    loadingPlatformMatrix.value = true
    try {
      platformMatrix.value = await withRetry(() => getPlatformMatrix(force))
    } catch (error: unknown) {
      notifyError(error, '模型平台服务状态加载失败')
    } finally {
      loadingPlatformMatrix.value = false
    }
  }

  async function loadPlatformSystemData() {
    if (!isPlatform.value) return
    const code = activeMenuCode.value
    try {
      if (code === 'platform.settings') systemConfigRows.value = await withRetry(() => getSystemConfigs())
    } catch (error: unknown) {
      notifyError(error, '平台系统数据加载失败')
    }
  }

  function resetSourceFilters() {
    sourceKeywordFilter.value = ''
    sourceStartDate.value = ''
    sourceEndDate.value = ''
    selectedSourcePlatform.value = 'all'
  }

  watch(activeMenuCode, () => loadMonitorSummary(isDashboardPage.value))
  watch(activeMenuCode, loadPlatformSystemData)
  watch(activeMenuCode, () => loadPlatformMatrix())
  watch(sourcePlatformTabs, tabs => {
    if (!tabs.some(tab => tab.code === selectedSourcePlatform.value)) {
      selectedSourcePlatform.value = 'all'
    }
  })

  onMounted(() => {
    if (shouldLoadMonitorSummary.value) loadMonitorSummary(isDashboardPage.value)
    monitorSummaryTimer = window.setInterval(() => {
      if (document.visibilityState === 'visible' && shouldLoadMonitorSummary.value) {
        loadMonitorSummary(true)
      }
    }, 30000)
    loadPlatformSystemData()
    loadPlatformMatrix()
    platformMatrixTimer = window.setInterval(() => {
      if (document.visibilityState === 'visible' && shouldLoadPlatformMatrix.value) {
        loadPlatformMatrix()
      }
    }, 30000)
  })

  onUnmounted(() => {
    if (monitorSummaryTimer) window.clearInterval(monitorSummaryTimer)
    if (platformMatrixTimer) window.clearInterval(platformMatrixTimer)
  })

  return {
    brandAsset,
    brandCompetitors,
    monitorSummary,
    loadingSummary,
    syncingMonitorResults,
    selectedSourcePlatform,
    sourceKeywordFilter,
    sourceStartDate,
    sourceEndDate,
    systemConfigRows,
    stats,
    chartTrend,
    platformRanking,
    allSourceRanking,
    recentSubtasks,
    platformCoverage,
    platformMatrix,
    loadingPlatformMatrix,
    loadPlatformMatrix,
    customerPlatformServices,
    purchasedPlatformCount,
    sourcePlatformTabs,
    sourceRanking,
    sourceTrendRows,
    sourceStructureRows,
    contentPreferenceRows,
    monitorKeywordList,
    statTooltipMap,
    sentimentTotal,
    positiveRate,
    negativeRate,
    sourceTotalCount,
    recentQuestionGroups,
    systemSettings,
    functionalPage,
    sentimentPieRows,
    diagnosisScore,
    loadMonitorSummary,
    loadPlatformSystemData,
    resetSourceFilters,
  }
}
