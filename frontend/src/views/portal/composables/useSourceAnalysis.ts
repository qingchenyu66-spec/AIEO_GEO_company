import { computed, inject, onMounted, onUnmounted, ref, watch, type Ref } from 'vue'
import { ElMessage } from 'element-plus'
import { usePortalCharts } from '../../../composables/usePortalCharts'
import type { MonitorSummary } from '../../../services/monitor'
import { useAuthStore } from '../../../stores/auth'
import {
  customerDisplayPeriodLabel,
  customerTrendPeriodLabel,
} from '../../../utils/customerMonitorDate'
import { PortalAnalyticsKey } from '../injectionKeys'
import { platformLabelMap } from '../portalMaps'
import { resolvePurchasedPlatformCodes, sortPlatformRows, sortPlatformTabs } from '../platformOrder'
import { formatDateTime } from '../portalUtils'
import {
  createEmptyCategoryBucket,
  collectBrandKnownHosts,
  sourceCategory,
  sourceCategoryIds,
  sourceCategoryLabel,
  sourceCategoryLabels,
  type SourceCategory,
} from '../sourceCategory'
import { isCustomerPreviewActive } from '../customerPreview'
import { useRoute } from 'vue-router'

export type { SourceCategory }
export { sourceCategoryLabels, sourceCategory, sourceCategoryLabel }

export type SourceDatePreset = '7' | '30' | 'all'
export type SourceRankTab = 'branded' | 'all'

export type SourceRow = MonitorSummary['source_stats'][number] & {
  category: SourceCategory
  has_exposure: boolean
}

const RANK_PAGE_SIZE = 20

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : String(error)
}

function domainFromUrl(url: string) {
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return url
  }
}

function sliceTrendPoints<T extends { label: string; value: number }>(points: T[], days: number) {
  if (!points.length || days >= points.length) return points
  return points.slice(points.length - days)
}

function mapSourceRows(
  rows: MonitorSummary['source_stats'],
  brandOfficialHost: string | null | undefined,
  brandKnownHosts: string[],
): SourceRow[] {
  return rows.map(item => ({
    ...item,
    has_exposure: item.has_exposure ?? (item.exposure_terms || []).length > 0,
    category: sourceCategory(item, {
      brandOfficialHost,
      brandKnownHosts,
    }),
  }))
}

export function useSourceAnalysis(options?: {
  structureChartRef?: Ref<HTMLDivElement | null>
  categoryChartRef?: Ref<HTMLDivElement | null>
  trendChartRef?: Ref<HTMLDivElement | null>
}) {
  const analytics = inject(PortalAnalyticsKey)!
  const auth = useAuthStore()
  const route = useRoute()
  const isCustomerView = computed(() => (
    auth.session?.identity?.identity_type === 'CUSTOMER'
    || isCustomerPreviewActive(route, auth.session?.identity?.identity_type === 'PLATFORM')
  ))
  const customerPeriodLabel = computed(() => customerDisplayPeriodLabel())
  const trendPeriodLabel = computed(() => {
    if (!isCustomerView.value) {
      const days = datePreset.value === '7' ? 7 : datePreset.value === '30' ? 30 : 14
      return `近 ${days} 日引用趋势`
    }
    return customerTrendPeriodLabel(14)
  })
  const brandAsset = analytics.brandAsset

  const loading = ref(false)
  const monitorSummary = analytics.monitorSummary
  // 客户页不展示近 7/30；运营端默认近 30 天
  const datePreset = ref<SourceDatePreset>('all')
  if (!isCustomerView.value) datePreset.value = '30'
  const platformFilter = ref('all')
  const categoryFilter = ref<'all' | SourceCategory>('all')
  const keywordFilter = ref('')
  const rankTab = ref<SourceRankTab>('branded')
  const rankPage = ref(1)

  const structureChartRef = options?.structureChartRef ?? ref<HTMLDivElement | null>(null)
  const categoryChartRef = options?.categoryChartRef ?? ref<HTMLDivElement | null>(null)
  const trendChartRef = options?.trendChartRef ?? ref<HTMLDivElement | null>(null)
  const { renderCharts } = usePortalCharts({
    sourceStructure: structureChartRef,
    sourceCategoryDistribution: categoryChartRef,
    sourceTrend: trendChartRef,
  })

  const brandKnownHosts = computed(() => collectBrandKnownHosts(brandAsset.value))

  const brandedSources = computed<SourceRow[]>(() => (
    mapSourceRows(
      (monitorSummary.value?.source_stats || []).filter(item => (item.exposure_terms || []).length > 0),
      brandAsset.value?.official_url,
      brandKnownHosts.value,
    )
  ))

  const allCitationSources = computed<SourceRow[]>(() => (
    mapSourceRows(
      monitorSummary.value?.source_stats_all || monitorSummary.value?.source_stats || [],
      brandAsset.value?.official_url,
      brandKnownHosts.value,
    )
  ))

  // 图表 / Hero / 平台 chips 仍用品牌相关口径
  const allSources = brandedSources

  const platformRanking = computed(() => sortPlatformRows(monitorSummary.value?.platform_stats || []))

  const structurePlatformCodes = computed(() => resolvePurchasedPlatformCodes(
    brandAsset.value?.monitored_platforms,
    platformRanking.value.map(item => item.platform),
  ))

  function applySourceFilters(rows: SourceRow[]) {
    const keyword = keywordFilter.value.trim().toLowerCase()
    const now = Date.now()
    const dayMs = 86400000
    const rangeDays = datePreset.value === 'all' ? null : Number(datePreset.value)
    const rangeStart = rangeDays ? now - rangeDays * dayMs : null
    return rows.filter(source => {
      const platformMatched = platformFilter.value === 'all'
        || (source.platforms || []).includes(platformFilter.value)
      const categoryMatched = categoryFilter.value === 'all' || source.category === categoryFilter.value
      const text = `${source.title || ''} ${(source.exposure_terms || []).join(' ')} ${(source.questions || []).join(' ')} ${source.url || ''}`.toLowerCase()
      const keywordMatched = !keyword || text.includes(keyword)
      const sourceTime = source.latest_time ? new Date(source.latest_time).getTime() : null
      const dateMatched = isCustomerView.value
        ? true
        : (!rangeStart || (sourceTime != null && sourceTime >= rangeStart))
      return platformMatched && categoryMatched && keywordMatched && dateMatched
    }).sort((a, b) => b.count - a.count)
  }

  const filteredSources = computed(() => applySourceFilters(brandedSources.value))
  const filteredAllSources = computed(() => applySourceFilters(allCitationSources.value))

  const activeRankSources = computed(() => (
    rankTab.value === 'all' ? filteredAllSources.value : filteredSources.value
  ))

  const rankTotalPages = computed(() => Math.max(1, Math.ceil(activeRankSources.value.length / RANK_PAGE_SIZE)))
  const pagedRankSources = computed(() => {
    const page = Math.min(Math.max(rankPage.value, 1), rankTotalPages.value)
    const start = (page - 1) * RANK_PAGE_SIZE
    return activeRankSources.value.slice(start, start + RANK_PAGE_SIZE)
  })

  const sourceTotalCount = computed(() => filteredSources.value.reduce((sum, item) => sum + item.count, 0))
  const uniqueSourceCount = computed(() => filteredSources.value.length)
  const allCitationTotalCount = computed(() => filteredAllSources.value.reduce((sum, item) => sum + item.count, 0))
  const allCitationUniqueCount = computed(() => filteredAllSources.value.length)
  const brandedCitationShare = computed(() => {
    if (!allCitationTotalCount.value) return 0
    return Math.round((sourceTotalCount.value / allCitationTotalCount.value) * 100)
  })

  const platformWithSourcesCount = computed(() => {
    const allowed = new Set(structurePlatformCodes.value)
    const codes = new Set<string>()
    filteredSources.value.forEach(source => {
      ;(source.platforms || []).forEach(code => {
        if (allowed.size && !allowed.has(code)) return
        codes.add(code)
      })
    })
    return codes.size
  })

  const platformTabs = computed(() => {
    const allowed = new Set(structurePlatformCodes.value)
    const scopeSources = allSources.value
    const counts = new Map<string, number>()
    scopeSources.forEach(source => {
      ;(source.platforms || []).forEach(platform => {
        if (allowed.size && !allowed.has(platform)) return
        counts.set(platform, (counts.get(platform) || 0) + source.count)
      })
    })
    const platformEntries = allowed.size
      ? structurePlatformCodes.value.map(code => ({
        code,
        name: platformLabelMap[code] || code,
        count: counts.get(code) || 0,
      }))
      : Array.from(counts.entries()).map(([code, count]) => ({
        code,
        name: platformLabelMap[code] || code,
        count,
      }))
    const totalCount = platformEntries.reduce((sum, item) => sum + item.count, 0)
    return sortPlatformTabs([
      { code: 'all', name: '全部平台', count: totalCount },
      ...platformEntries,
    ])
  })

  const categoryStats = computed(() => {
    const bucket = createEmptyCategoryBucket()
    filteredSources.value.forEach(source => {
      bucket[source.category] = (bucket[source.category] || 0) + source.count
    })
    const total = Object.values(bucket).reduce((sum, value) => sum + value, 0) || 1
    return sourceCategoryIds.map(key => ({
      key,
      name: sourceCategoryLabels[key],
      count: bucket[key] || 0,
      percent: Math.round((bucket[key] || 0) / total * 100),
    }))
      .filter(item => item.count > 0)
      .sort((a, b) => b.count - a.count)
  })

  const activeCategoryKeys = computed(() => categoryStats.value.map(item => item.key))

  const activeSourceCategoryLabels = computed(() => (
    Object.fromEntries(categoryStats.value.map(item => [item.key, item.name]))
  ))

  const categorySummaryLabel = computed(() => {
    const names = categoryStats.value.map(item => item.name)
    if (!names.length) return '—'
    if (names.length <= 3) return names.join(' / ')
    return `共 ${names.length} 类`
  })

  const topCategory = computed(() => categoryStats.value.find(item => item.count > 0) || null)
  const officialRate = computed(() => categoryStats.value.find(item => item.key === 'official')?.percent ?? 0)

  const sourceStructureRows = computed(() => {
    const platforms = platformFilter.value === 'all'
      ? structurePlatformCodes.value
      : structurePlatformCodes.value.filter(code => code === platformFilter.value)
    return platforms.map(platform => {
    const platformSources = filteredSources.value.filter(source => (source.platforms || []).includes(platform))
    const total = platformSources.reduce((sum, source) => sum + source.count, 0)
    const categoryMap = platformSources.reduce((map, source) => {
      map[source.category] = (map[source.category] || 0) + source.count
      return map
    }, {} as Record<string, number>)
    const denom = total || 1
    return {
      platform,
      total,
      categories: activeCategoryKeys.value.map(type => ({
        type,
        value: total ? Math.round(((categoryMap[type] || 0) / denom) * 100) : 0,
      })),
    }
  })
  })

  const sourceTrendRows = computed(() => {
    const trendByPlatform = monitorSummary.value?.source_citation_trend_by_platform
    const selected = platformFilter.value !== 'all' ? platformFilter.value : null
    const backendTrend = selected
      ? trendByPlatform?.[selected]
      : monitorSummary.value?.source_citation_trend
    const backendPoints = backendTrend?.points || []
    if (backendPoints.length) {
      const points = isCustomerView.value
        ? backendPoints
        : sliceTrendPoints(
          backendPoints,
          datePreset.value === '7' ? 7 : datePreset.value === '30' ? 30 : 14,
        )
      return points.map(point => ({
        label: point.label,
        value: point.value,
      }))
    }
    return []
  })

  const structureChartRows = computed(() => {
    if (platformFilter.value === 'all') return sourceStructureRows.value
    const active = sourceStructureRows.value.filter(row => row.total > 0)
    return active.length ? active : sourceStructureRows.value
  })

  const analyticsPairMinHeight = computed(() => {
    const rows = Math.max(structureChartRows.value.length, 1)
    return Math.max(280, rows * 36 + 56)
  })

  const hasStructurePanel = computed(() => (
    platformFilter.value === 'all'
      ? sourceStructureRows.value.length > 0
      : sourceStructureRows.value.some(row => row.total > 0)
  ))

  const hasPageContent = computed(() => (
    hasStructurePanel.value
    || filteredSources.value.length > 0
    || filteredAllSources.value.length > 0
  ))

  const insight = computed(() => {
    if (!hasPageContent.value) {
      return {
        level: 'empty' as const,
        title: '暂无信源引用',
        body: '当前筛选下没有可展示的 AI 引用。请完成更多监测或放宽筛选条件。',
      }
    }
    return {
      level: 'ok' as const,
      title: '数据口径说明',
      body: '图表与「品牌相关」榜仅统计标题/链接含露出词的引用；「全部引用」榜不过滤露出词，行内 chip 标记是否含露出词。',
    }
  })

  async function loadSummary(force = false) {
    loading.value = true
    try {
      await analytics.loadMonitorSummary(force)
    } catch (error: unknown) {
      ElMessage.error(`信源数据加载失败：${errorMessage(error)}`)
    } finally {
      loading.value = false
    }
  }

  async function refreshCharts() {
    await renderCharts({
      chartTrend: [],
      platformRanking: [],
      sentimentPieRows: [],
      positiveRate: 0,
      diagnosisScore: 0,
      competitorCompareRows: [],
      sourceStructureRows: structureChartRows.value,
      sourceTrendRows: sourceTrendRows.value,
      sourceCategoryLabels: activeSourceCategoryLabels.value,
      sourceCategoryStats: categoryStats.value,
    })
  }

  function resetFilters() {
    platformFilter.value = 'all'
    categoryFilter.value = 'all'
    keywordFilter.value = ''
    datePreset.value = isCustomerView.value ? 'all' : '30'
    rankPage.value = 1
  }

  function setRankTab(tab: SourceRankTab) {
    rankTab.value = tab
    rankPage.value = 1
  }

  function exportCsv() {
    const rows = activeRankSources.value
    if (!rows.length) {
      ElMessage.warning('暂无可导出数据')
      return
    }
    const tabLabel = rankTab.value === 'all' ? '全部引用' : '品牌相关'
    const lines = [
      ['标题', '链接', '引用次数', '监测问题', '露出词', '含露出词', '最近检测'].join(','),
      ...rows.map(source => [
        `"${(source.title || '').replace(/"/g, '""')}"`,
        `"${source.url || ''}"`,
        source.count,
        `"${(source.questions || []).join('；')}"`,
        `"${(source.exposure_terms || []).join('、')}"`,
        source.has_exposure ? '是' : '否',
        source.latest_time ? formatDateTime(source.latest_time) : '',
      ].join(',')),
    ]
    const blob = new Blob([`\uFEFF${lines.join('\n')}`], { type: 'text/csv;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `${brandAsset.value?.brand_name || '信源'}-${tabLabel}.csv`
    link.click()
    URL.revokeObjectURL(url)
    ElMessage.success('已导出 CSV')
  }

  watch([filteredSources, structureChartRows, sourceTrendRows, activeSourceCategoryLabels, hasStructurePanel, loading], () => { void refreshCharts() }, { deep: true })
  watch([platformFilter, categoryFilter, keywordFilter, datePreset, rankTab], () => {
    rankPage.value = 1
  })
  watch(rankTotalPages, pages => {
    if (rankPage.value > pages) rankPage.value = pages
  })

  onMounted(() => {
    void loadSummary()
    window.addEventListener('resize', refreshCharts)
  })

  onUnmounted(() => {
    window.removeEventListener('resize', refreshCharts)
  })

  return {
    brandAsset,
    isCustomerView,
    customerPeriodLabel,
    trendPeriodLabel,
    loading,
    datePreset,
    platformFilter,
    categoryFilter,
    keywordFilter,
    rankTab,
    rankPage,
    rankPageSize: RANK_PAGE_SIZE,
    rankTotalPages,
    platformTabs,
    filteredSources,
    filteredAllSources,
    activeRankSources,
    pagedRankSources,
    sourceTotalCount,
    uniqueSourceCount,
    allCitationTotalCount,
    allCitationUniqueCount,
    brandedCitationShare,
    platformWithSourcesCount,
    categoryStats,
    activeSourceCategoryLabels,
    categorySummaryLabel,
    topCategory,
    officialRate,
    sourceStructureRows,
    sourceTrendRows,
    analyticsPairMinHeight,
    hasStructurePanel,
    hasPageContent,
    insight,
    loadSummary,
    resetFilters,
    setRankTab,
    exportCsv,
    platformLabelMap,
    sourceCategoryLabels,
    sourceCategoryLabel,
    domainFromUrl,
  }
}
