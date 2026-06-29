import { computed, onMounted, reactive, ref, watch } from 'vue'
import { withRetry } from '../../../composables/useRetry'
import { notifyOperationError } from '../../../utils/requestError'
import { getBrandAsset, type BrandAsset, type BrandKeywordGroup } from '../../../services/brand'
import {
  getMonitorSubtask,
  getSentimentOverview,
  type MonitorSubtask,
  type SentimentOverview,
  type SentimentOverviewItem,
  type SentimentPlatformStat,
} from '../../../services/monitor'
import { platformLabelMap, sentimentLabelMap } from '../portalMaps'

export type SentimentListTab = 'negative' | 'all' | 'positive'
export type SentimentDatePreset = '7d' | '30d' | 'custom'

function dateRangeForDays(days: number) {
  const end = new Date()
  const start = new Date()
  start.setDate(start.getDate() - days)
  return {
    startDate: start.toISOString().slice(0, 10),
    endDate: end.toISOString().slice(0, 10),
  }
}

function defaultDateRange() {
  return dateRangeForDays(7)
}

function formatMonitorGroupLabel(group: BrandKeywordGroup) {
  const keyword = (group.monitor_keyword || '').trim()
  const exposure = (group.exposure_terms || []).map(term => term.trim()).filter(Boolean)
  if (!exposure.length) return keyword
  return `${keyword}（露出：${exposure.join('、')}）`
}

function formatDateTime(value?: string | null) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  const pad = (num: number) => String(num).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function sentimentClass(label: string) {
  if (label === '负面') return 'sentiment-tag negative'
  if (label === '正面') return 'sentiment-tag positive'
  if (label === '中性') return 'sentiment-tag neutral'
  return 'sentiment-tag unknown'
}

function cardToneClass(label: string) {
  if (label === '负面') return 'is-negative'
  if (label === '正面') return 'is-positive'
  if (label === '中性') return 'is-neutral'
  return ''
}

export function useMonitorSentiment() {
  const brandAsset = ref<BrandAsset | null>(null)
  const overview = ref<SentimentOverview | null>(null)
  const loading = ref(false)
  const listTab = ref<SentimentListTab>('negative')
  const datePreset = ref<SentimentDatePreset>('7d')
  const selectedItem = ref<SentimentOverviewItem | null>(null)
  const selectedSubtask = ref<MonitorSubtask | null>(null)
  const loadingDetail = ref(false)
  const detailVisible = ref(false)

  const defaultDates = defaultDateRange()
  const filters = reactive({
    platform: 'all',
    monitorGroup: '',
    scheduleWindowKey: '',
    startDate: defaultDates.startDate,
    endDate: defaultDates.endDate,
  })

  let debounceTimer: ReturnType<typeof setTimeout> | null = null

  const monitorGroupOptions = computed(() => {
    const groups = brandAsset.value?.keyword_groups?.length
      ? brandAsset.value.keyword_groups
      : (overview.value?.keyword_group_options || []).map(item => ({
          id: null,
          monitor_keyword: item.monitor_keyword,
          exposure_terms: item.exposure_terms,
          sort_order: 0,
          status: true,
        }))
    return groups
      .filter(group => group.status !== false && (group.monitor_keyword || '').trim())
      .sort((left, right) => (left.sort_order ?? 0) - (right.sort_order ?? 0))
  })

  const platformOptions = computed(() => {
    const purchased = brandAsset.value?.monitored_platforms?.length
      ? brandAsset.value.monitored_platforms
      : overview.value?.purchased_platforms || []
    return purchased.filter(Boolean)
  })

  const listItems = computed(() => overview.value?.items || [])

  const tabCounts = computed(() => {
    const counts = overview.value?.sentiment_counts || {}
    return {
      negative: Number(counts['负面'] || 0),
      all: overview.value?.sample_count || 0,
      positive: Number(counts['正面'] || 0),
    }
  })

  const heroStackSegments = computed(() => {
    const positive = overview.value?.positive_rate || 0
    const neutral = overview.value?.neutral_rate || 0
    const negative = overview.value?.negative_rate || 0
    const counts = overview.value?.sentiment_counts || {}
    return [
      { key: 'positive' as const, label: '正面', rate: positive, count: Number(counts['正面'] || 0) },
      { key: 'neutral' as const, label: '中性', rate: neutral, count: Number(counts['中性'] || 0) },
      { key: 'negative' as const, label: '负面', rate: negative, count: Number(counts['负面'] || 0) },
    ]
  })

  const warnPlatformStats = computed(() => {
    const rows = overview.value?.platform_stats || []
    if (!rows.length) return [] as SentimentPlatformStat[]
    const avgNegative = rows.reduce((sum, row) => sum + row.negative_rate, 0) / rows.length
    return rows.filter(row => row.negative_count > 0 && row.negative_rate >= Math.max(15, avgNegative))
  })

  const heroCalm = computed(() => (overview.value?.negative_count || 0) === 0 && (overview.value?.sample_count || 0) > 0)

  async function loadBrandAssetData() {
    try {
      const response = await withRetry(() => getBrandAsset(null))
      brandAsset.value = response.asset
    } catch (error: unknown) {
      notifyOperationError(error, '品牌资产加载失败')
    }
  }

  async function loadOverview() {
    loading.value = true
    try {
      await loadBrandAssetData()
      overview.value = await withRetry(() => getSentimentOverview({
        platform: filters.platform === 'all' ? undefined : filters.platform,
        start_date: filters.startDate || undefined,
        end_date: filters.endDate || undefined,
        monitor_group: filters.monitorGroup.trim() || undefined,
        schedule_window_key: filters.scheduleWindowKey.trim() || undefined,
        sentiment: listTab.value,
      }))
    } catch (error: unknown) {
      notifyOperationError(error, '舆情数据加载失败')
    } finally {
      loading.value = false
    }
  }

  function scheduleLoad(delay = 300) {
    if (debounceTimer) clearTimeout(debounceTimer)
    debounceTimer = setTimeout(() => {
      loadOverview()
    }, delay)
  }

  function applyDatePreset(preset: SentimentDatePreset) {
    datePreset.value = preset
    if (preset === '7d') {
      const range = dateRangeForDays(7)
      filters.startDate = range.startDate
      filters.endDate = range.endDate
      scheduleLoad()
      return
    }
    if (preset === '30d') {
      const range = dateRangeForDays(30)
      filters.startDate = range.startDate
      filters.endDate = range.endDate
      scheduleLoad()
    }
  }

  function onCustomDateChange() {
    datePreset.value = 'custom'
    scheduleLoad()
  }

  function resetFilters() {
    filters.platform = 'all'
    filters.monitorGroup = ''
    filters.scheduleWindowKey = ''
    applyDatePreset('7d')
  }

  function switchListTab(tab: SentimentListTab) {
    if (listTab.value === tab) return
    listTab.value = tab
  }

  function switchTabFromHero(key: 'positive' | 'neutral' | 'negative') {
    const map: Record<'positive' | 'neutral' | 'negative', SentimentListTab> = {
      positive: 'positive',
      neutral: 'all',
      negative: 'negative',
    }
    switchListTab(map[key])
    document.getElementById('sentiment-sample-list')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  async function openDetail(item: SentimentOverviewItem) {
    selectedItem.value = item
    selectedSubtask.value = null
    detailVisible.value = true
    loadingDetail.value = true
    try {
      selectedSubtask.value = await withRetry(() => getMonitorSubtask(item.subtask_id))
    } catch (error: unknown) {
      notifyOperationError(error, '详情加载失败')
    } finally {
      loadingDetail.value = false
    }
  }

  function closeDetail() {
    detailVisible.value = false
    selectedItem.value = null
    selectedSubtask.value = null
  }

  function scrollToList() {
    switchListTab('negative')
    document.getElementById('sentiment-sample-list')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  function filterByPlatform(platform: string) {
    filters.platform = platform
    scheduleLoad(0)
    document.getElementById('sentiment-sample-list')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  function exportCsv() {
    if (!overview.value) return
    const rows = [
      ['调度轮次', '平台', '监测词组', '监测问题', '情感', '品牌提及', '回答摘要', '更新时间'],
      ...listItems.value.map(item => [
        item.schedule_label || '',
        platformLabelMap[item.platform] || item.platform,
        item.keyword_group || '',
        item.prompt,
        item.sentiment,
        item.brand_mentioned ? '已提及' : '未提及',
        item.answer_excerpt,
        formatDateTime(item.updated_at),
      ]),
    ]
    const csv = rows
      .map(row => row.map(cell => `"${String(cell || '').replace(/"/g, '""')}"`).join(','))
      .join('\n')
    const blob = new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    const brand = overview.value.brand_name || 'brand'
    link.href = url
    link.download = `${brand}-舆情报告-${filters.endDate || 'export'}.csv`
    link.click()
    URL.revokeObjectURL(url)
  }

  watch(listTab, () => {
    loadOverview()
  })

  watch(
    () => [filters.platform, filters.monitorGroup, filters.scheduleWindowKey],
    () => scheduleLoad(),
  )

  onMounted(() => {
    loadOverview()
  })

  return {
    brandAsset,
    overview,
    loading,
    filters,
    datePreset,
    listTab,
    monitorGroupOptions,
    platformOptions,
    heroStackSegments,
    warnPlatformStats,
    heroCalm,
    listItems,
    tabCounts,
    selectedItem,
    selectedSubtask,
    loadingDetail,
    detailVisible,
    loadOverview,
    resetFilters,
    applyDatePreset,
    onCustomDateChange,
    switchListTab,
    switchTabFromHero,
    openDetail,
    closeDetail,
    scrollToList,
    filterByPlatform,
    exportCsv,
    formatMonitorGroupLabel,
    formatDateTime,
    sentimentClass,
    cardToneClass,
    platformLabelMap,
    sentimentLabelMap,
  }
}
