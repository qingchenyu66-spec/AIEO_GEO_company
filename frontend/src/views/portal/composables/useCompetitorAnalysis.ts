import { computed, inject, onMounted, onUnmounted, ref, watch, type Ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { withRetry } from '../../../composables/useRetry'
import { usePortalCharts } from '../../../composables/usePortalCharts'
import { getCompetitorCompare, getSentimentKeywords, type CompetitorCompareSummary, type SentimentKeywordItem, type SentimentKeywordsSummary } from '../../../services/analytics'
import { useSentimentWordCloud, preloadSentimentWordCloudRuntime } from '../../../composables/useSentimentWordCloud'
import { useAuthStore } from '../../../stores/auth'
import {
  customerDisplayCutoffDate,
  workspaceTrendDateRange,
  workspaceTrendPeriodLabel,
  type WorkspaceTrendPreset,
} from '../../../utils/customerMonitorDate'
import { PortalAnalyticsKey } from '../injectionKeys'
import { resolveRealtimeMenu } from '../portalNavigation'
import { platformLabelMap } from '../portalMaps'
import { sortPlatformTabs } from '../platformOrder'
import { isCustomerPreviewActive, parsePreviewTenantId } from '../customerPreview'

export type CompetitorDatePreset = '7' | '30' | '90'

const MENTION_TREND_FOCUS_COUNT = 8

export type CompetitorLeaderboardRow = {
  name: string
  is_brand: boolean
  mention: number
  mention_count: number
  first_mention_rate: number
  rank: number | null
  rank_sample_count: number
}

export type SentimentLeaderboardRow = {
  name: string
  is_brand: boolean
  positive_rate: number
  negative_rate: number
  sentiment_sample: number
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : String(error)
}

export function useBrandInsights(options?: {
  mentionTrendChartRef?: Ref<HTMLDivElement | null>
  sentimentTrendChartRef?: Ref<HTMLDivElement | null>
  sentimentWordCloudRef?: Ref<HTMLDivElement | null>
}) {
  const route = useRoute()
  const router = useRouter()
  const auth = useAuthStore()
  const isCustomerView = computed(() => (
    auth.session?.identity?.identity_type === 'CUSTOMER'
    || isCustomerPreviewActive(route, auth.session?.identity?.identity_type === 'PLATFORM')
  ))
  const analytics = inject(PortalAnalyticsKey)!
  const brandAsset = analytics.brandAsset
  const brandCompetitors = analytics.brandCompetitors

  const datePreset = ref<CompetitorDatePreset>('30')
  // 客户首屏默认近7日，减轻冷启动聚合量；仍可切月/季/年
  const trendPreset = ref<WorkspaceTrendPreset>('7d')
  const initialTrendRange = workspaceTrendDateRange('7d')
  const trendStartDate = ref(initialTrendRange.startDate)
  const trendEndDate = ref(initialTrendRange.endDate)
  const trendMaxDate = customerDisplayCutoffDate()
  const trendPeriodLabel = computed(() => (
    workspaceTrendPeriodLabel(trendPreset.value, trendStartDate.value, trendEndDate.value)
  ))
  const selectedPlatforms = ref<string[]>([])
  const promptFilter = ref('')
  const loading = ref(false)
  const keywordsLoading = ref(false)
  const summary = ref<CompetitorCompareSummary | null>(null)
  const sentimentKeywords = ref<SentimentKeywordsSummary | null>(null)
  const sentimentKeywordTab = ref<'positive' | 'negative'>('positive')
  let loadVersion = 0

  const mentionTrendChartRef = options?.mentionTrendChartRef ?? ref<HTMLDivElement | null>(null)
  const sentimentTrendChartRef = options?.sentimentTrendChartRef ?? ref<HTMLDivElement | null>(null)
  const sentimentWordCloudRef = options?.sentimentWordCloudRef ?? ref<HTMLDivElement | null>(null)
  const { renderCharts } = usePortalCharts({
    mentionTrend: mentionTrendChartRef,
    sentimentTrend: sentimentTrendChartRef,
  })
  const { render: renderWordCloud } = useSentimentWordCloud(
    sentimentWordCloudRef,
    item => drillDownToSnapshot(item),
  )

  const days = computed(() => Number(datePreset.value))

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
    void loadSummary()
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
    void loadSummary()
  }

  function buildCompareParams() {
    const base = {
      platforms: selectedPlatforms.value.length ? selectedPlatforms.value.join(',') : undefined,
      prompt: promptFilter.value || undefined,
      tenant_id: platformTenantId.value,
    }
    if (isCustomerView.value) {
      return {
        ...base,
        start_date: trendStartDate.value,
        end_date: trendEndDate.value,
      }
    }
    return {
      ...base,
      days: days.value,
    }
  }

  function drillDownDateDays() {
    if (!isCustomerView.value) return datePreset.value
    const start = new Date(`${trendStartDate.value}T00:00:00`)
    const end = new Date(`${trendEndDate.value}T00:00:00`)
    const span = Math.ceil((end.getTime() - start.getTime()) / 86400000) + 1
    if (span <= 7) return '7'
    if (span <= 30) return '30'
    return '90'
  }

  const platformTabs = computed(() => {
    const counts = new Map<string, number>()
    ;(summary.value?.platform_rows || []).forEach(row => counts.set(row.platform, row.sample_count))
    ;(brandAsset.value?.monitored_platforms || []).forEach(code => {
      if (!counts.has(code)) counts.set(code, 0)
    })
    const total = summary.value?.sample_total || 0
    return sortPlatformTabs([
      { code: 'all', name: '全部平台', count: total },
      ...Array.from(counts.entries())
        .map(([code, count]) => ({ code, name: platformLabelMap[code] || code, count })),
    ])
  })

  const promptOptions = computed(() => summary.value?.prompt_options || [])

  const leaderboardRows = computed<CompetitorLeaderboardRow[]>(() => (
    (summary.value?.rows || []).map(row => ({
      name: row.name,
      is_brand: Boolean(row.is_brand),
      mention: row.mention_rate,
      mention_count: row.mention_count,
      first_mention_rate: row.first_mention_rate ?? 0,
      rank: row.avg_rank,
      rank_sample_count: row.rank_sample_count || 0,
    }))
  ))

  const sentimentLeaderboardRows = computed<SentimentLeaderboardRow[]>(() => (
    (summary.value?.sentiment_rows || []).map(row => ({
      name: row.name,
      is_brand: Boolean(row.is_brand),
      positive_rate: row.positive_rate,
      negative_rate: row.negative_rate,
      sentiment_sample: row.sentiment_sample,
    }))
  ))

  const brandRow = computed(() => leaderboardRows.value.find(row => row.is_brand) || null)
  const brandSentimentRow = computed(() => sentimentLeaderboardRows.value.find(row => row.is_brand) || null)
  const sampleTotal = computed(() => summary.value?.sample_total || 0)
  const configuredCount = computed(() => brandCompetitors.value.length || summary.value?.competitor_count || 0)
  const mentionTrendSeries = computed(() => summary.value?.mention_trends || { labels: [], series: [] })

  const focusedMentionTrendSeries = computed(() => {
    const trend = mentionTrendSeries.value
    const labels = trend.labels || []
    const allSeries = trend.series || []
    if (!labels.length || !allSeries.length) {
      return { labels, series: [], hidden_count: 0 }
    }
    const brand = allSeries.find(item => item.is_brand)
    const competitors = allSeries
      .filter(item => !item.is_brand)
      .map(item => ({
        ...item,
        avg: item.values.length
          ? item.values.reduce((sum, value) => sum + value, 0) / item.values.length
          : 0,
      }))
      .sort((a, b) => b.avg - a.avg)
    const focusLimit = Math.max(MENTION_TREND_FOCUS_COUNT, configuredCount.value)
    const focused = [
      ...(brand ? [brand] : []),
      ...competitors.slice(0, focusLimit),
    ]
    return {
      labels,
      series: focused.map(({ name, is_brand, values }) => ({ name, is_brand, values })),
      hidden_count: Math.max(0, allSeries.length - focused.length),
    }
  })

  const mentionTrendHiddenCount = computed(() => focusedMentionTrendSeries.value.hidden_count || 0)

  const trendDayKeys = computed(() => summary.value?.trend_day_keys || [])

  const sentimentTrendRows = computed(() => {
    const trend = summary.value?.sentiment_trends
    if (!trend?.labels?.length) return []
    return trend.labels.map((label, index) => ({
      label,
      positive: trend.positive[index] ?? 0,
      neutral: trend.neutral[index] ?? 0,
      negative: trend.negative[index] ?? 0,
    }))
  })

  const activeSentimentKeywords = computed(() => {
    const data = sentimentKeywords.value
    if (!data) return []
    return sentimentKeywordTab.value === 'positive' ? data.positive : data.negative
  })

  const activeSentimentKeywordSample = computed(() => {
    const data = sentimentKeywords.value
    if (!data) return 0
    return sentimentKeywordTab.value === 'positive' ? data.positive_sample : data.negative_sample
  })

  const sentimentKeywordSource = computed(() => sentimentKeywords.value?.source || 'rule')

  const insight = computed(() => {
    if (!sampleTotal.value) {
      return {
        level: 'sample' as const,
        title: '等待监测样本',
        body: '定时检测完成后会自动汇总提及率、排名与情绪趋势。点击图表数据点可下钻到实时检测查看明细。',
      }
    }
    if (!configuredCount.value) {
      return {
        level: 'config' as const,
        title: '建议配置竞品库',
        body: '提及对比与排行榜依赖竞品库。可在企业管理中录入同场景会被 AI 一起推荐的品牌，便于横向比较。',
      }
    }
    return {
      level: 'ok' as const,
      title: '数据口径说明',
      body: '提及率 = 品牌在推荐列表中出现次数 / 样本总数。情绪指数按品牌出现在推荐列表时的回答情感标签统计。点击趋势图、排行榜或情绪词可下钻实时检测。',
    }
  })

  function resolveTrendDayIso(label: string) {
    const index = mentionTrendSeries.value.labels.indexOf(label)
    if (index < 0) return undefined
    return trendDayKeys.value[index]
  }

  const platformTenantId = computed(() => {
    const previewId = parsePreviewTenantId(route)
    if (previewId != null) return previewId
    if (isCustomerView.value && auth.session?.identity?.identity_type === 'CUSTOMER') return undefined
    const raw = route.query.tenant_id
    const text = Array.isArray(raw) ? raw[0] : raw
    const parsed = Number(text)
    if (Number.isFinite(parsed)) return parsed
    return brandAsset.value?.tenant_id
  })

  function drillDownToRealtime(options?: { platform?: string; prompt?: string; dayLabel?: string }) {
    const target = resolveRealtimeMenu(!isCustomerView.value, platformTenantId.value ?? null)
    const query: Record<string, string> = {
      ...Object.fromEntries(
        Object.entries(route.query).filter(([, value]) => value != null).map(([key, value]) => [key, String(value)]),
      ),
      menu: target.menu,
      ...target.query,
    }
    delete query.task_id
    delete query.subtask_id

    const platform = options?.platform
      || (selectedPlatforms.value.length === 1 ? selectedPlatforms.value[0] : '')
    if (platform) query.platform = platform

    const prompt = options?.prompt ?? promptFilter.value
    if (prompt) query.monitor_prompt = prompt

    query.date_days = drillDownDateDays()
    query.view = 'matrix'

    const dayIso = options?.dayLabel ? resolveTrendDayIso(options.dayLabel) : undefined
    if (dayIso) query.insights_day = dayIso

    router.push({ path: route.path, query }).catch(() => undefined)
  }

  function drillDownToSnapshot(item: SentimentKeywordItem) {
    const query: Record<string, string> = {
      ...Object.fromEntries(
        Object.entries(route.query).filter(([, value]) => value != null).map(([key, value]) => [key, String(value)]),
      ),
      menu: isCustomerView.value ? 'customer.realtime' : 'platform.snapshot_backfill',
      view: 'matrix',
      task_id: item.task_id,
      subtask_id: item.subtask_id,
      date_days: datePreset.value,
    }

    if (selectedPlatforms.value.length === 1) {
      query.platform = selectedPlatforms.value[0]
    }
    if (promptFilter.value) {
      query.monitor_prompt = promptFilter.value
    }

    router.push({ path: route.path, query }).catch(() => undefined)
  }

  function togglePlatform(code: string) {
    if (code === 'all') {
      selectedPlatforms.value = []
      return
    }
    const set = new Set(selectedPlatforms.value)
    if (set.has(code)) set.delete(code)
    else set.add(code)
    selectedPlatforms.value = [...set]
  }

  async function loadSummary() {
    const version = ++loadVersion
    loading.value = true
    keywordsLoading.value = true
    sentimentKeywords.value = null
    try {
      const params = buildCompareParams()
      const keywordParams = { ...params, limit: 55 }
      const comparePromise = withRetry(() => getCompetitorCompare(params))
      const keywordsPromise = withRetry(() => getSentimentKeywords(keywordParams)).catch(() => null)

      const compareData = await comparePromise
      if (version !== loadVersion) return
      summary.value = compareData
      loading.value = false

      void keywordsPromise.then(keywordData => {
        if (version !== loadVersion) return
        if (keywordData) sentimentKeywords.value = keywordData
        keywordsLoading.value = false
      })
    } catch (error: unknown) {
      if (version !== loadVersion) return
      keywordsLoading.value = false
      ElMessage.error(`品牌洞察数据加载失败：${errorMessage(error)}`)
    } finally {
      if (version === loadVersion) loading.value = false
    }
  }

  async function refreshTrendCharts() {
    await renderCharts({
      chartTrend: [],
      platformRanking: [],
      sentimentPieRows: [],
      positiveRate: brandSentimentRow.value?.positive_rate ?? 0,
      diagnosisScore: 0,
      competitorCompareRows: [],
      mentionTrendSeries: focusedMentionTrendSeries.value,
      sentimentTrendRows: sentimentTrendRows.value,
      sourceStructureRows: [],
      sourceTrendRows: [],
      sourceCategoryLabels: {},
      chartClickHandlers: {
        mentionTrend: payload => drillDownToRealtime({ dayLabel: payload.label }),
        sentimentTrend: payload => drillDownToRealtime({ dayLabel: payload.label }),
      },
    })
  }

  async function refreshWordCloud() {
    if (loading.value || keywordsLoading.value) return
    await renderWordCloud(activeSentimentKeywords.value, sentimentKeywordTab.value)
  }

  async function refreshCharts() {
    await refreshTrendCharts()
    await refreshWordCloud()
  }

  function resetFilters() {
    selectedPlatforms.value = []
    promptFilter.value = ''
    if (isCustomerView.value) {
      trendPreset.value = '7d'
      syncTrendRange('7d')
    } else {
      datePreset.value = '30'
    }
  }

  function exportCsv() {
    if (!leaderboardRows.value.length) {
      ElMessage.warning('暂无可导出数据')
      return
    }
    const lines = [
      ['名称', '类型', '提及率', '首位提及率', '提及次数', '平均排名'].join(','),
      ...leaderboardRows.value.map(row => [
        `"${row.name.replace(/"/g, '""')}"`,
        row.is_brand ? '本品牌' : '竞品',
        row.mention,
        row.first_mention_rate,
        row.mention_count,
        row.rank ?? '',
      ].join(',')),
    ]
    const blob = new Blob([`\uFEFF${lines.join('\n')}`], { type: 'text/csv;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `${brandAsset.value?.brand_name || '品牌'}-洞察-${datePreset.value}天.csv`
    link.click()
    URL.revokeObjectURL(url)
    ElMessage.success('已导出 CSV')
  }

  watch([datePreset], () => {
    if (!isCustomerView.value) void loadSummary()
  })
  watch([selectedPlatforms, promptFilter], () => { void loadSummary() })
  watch(promptOptions, (options) => {
    if (promptFilter.value && !options.includes(promptFilter.value)) {
      promptFilter.value = ''
    }
  })
  watch(
    () => (brandAsset.value?.keyword_groups || [])
      .map(group => `${group.id}:${group.status}:${(group.monitor_keywords || []).join('|')}`)
      .join('||'),
    (next, prev) => {
      if (prev && next !== prev) void loadSummary()
    },
  )
  watch(
    () => brandCompetitors.value.map(item => `${item.id}:${item.name}`).join('|'),
    (next, prev) => {
      if (prev && next !== prev) void loadSummary()
    },
  )
  watch([focusedMentionTrendSeries, sentimentTrendRows, loading], () => {
    void refreshTrendCharts()
  }, { deep: true, flush: 'post' })

  watch([activeSentimentKeywords, sentimentKeywordTab, keywordsLoading], () => {
    if (keywordsLoading.value) return
    void refreshWordCloud()
  }, { deep: true, flush: 'post' })

  onMounted(() => {
    preloadSentimentWordCloudRuntime()
    void loadSummary()
    window.addEventListener('resize', refreshCharts)
  })

  onUnmounted(() => {
    window.removeEventListener('resize', refreshCharts)
  })

  return {
    brandAsset,
    brandCompetitors,
    isCustomerView,
    trendPreset,
    trendStartDate,
    trendEndDate,
    trendMaxDate,
    trendPeriodLabel,
    applyTrendPreset,
    onCustomTrendDateChange,
    datePreset,
    selectedPlatforms,
    promptFilter,
    promptOptions,
    platformTabs,
    loading,
    keywordsLoading,
    summary,
    leaderboardRows,
    sentimentLeaderboardRows,
    brandRow,
    brandSentimentRow,
    sampleTotal,
    configuredCount,
    mentionTrendHiddenCount,
    focusedMentionTrendSeries,
    sentimentTrendRows,
    sentimentKeywords,
    sentimentKeywordTab,
    activeSentimentKeywords,
    activeSentimentKeywordSample,
    sentimentKeywordSource,
    insight,
    mentionTrendChartRef,
    sentimentTrendChartRef,
    sentimentWordCloudRef,
    loadSummary,
    resetFilters,
    exportCsv,
    togglePlatform,
    drillDownToRealtime,
    drillDownToSnapshot,
    platformLabelMap,
  }
}

/** @deprecated use useBrandInsights */
export const useCompetitorAnalysis = useBrandInsights
