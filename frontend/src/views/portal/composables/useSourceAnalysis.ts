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
import { sourceCategory, sourceCategoryLabels, type SourceCategory } from '../sourceCategory'
import { isCustomerPreviewActive } from '../customerPreview'
import { useRoute } from 'vue-router'

export type { SourceCategory }
export { sourceCategoryLabels, sourceCategory }

export type SourceDatePreset = '7' | '30' | 'all'

export type SourceRow = MonitorSummary['source_stats'][number] & {
  category: SourceCategory
}

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

export function useSourceAnalysis(options?: {
  structureChartRef?: Ref<HTMLDivElement | null>
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

  const structureChartRef = options?.structureChartRef ?? ref<HTMLDivElement | null>(null)
  const trendChartRef = options?.trendChartRef ?? ref<HTMLDivElement | null>(null)
  const { renderCharts } = usePortalCharts({
    sourceStructure: structureChartRef,
    sourceTrend: trendChartRef,
  })

  const allSources = computed<SourceRow[]>(() => (
    (monitorSummary.value?.source_stats || [])
      .filter(item => (item.exposure_terms || []).length > 0)
      .map(item => ({
        ...item,
        category: sourceCategory(item),
      }))
  ))

  const platformRanking = computed(() => sortPlatformRows(monitorSummary.value?.platform_stats || []))

  const structurePlatformCodes = computed(() => resolvePurchasedPlatformCodes(
    brandAsset.value?.monitored_platforms,
    platformRanking.value.map(item => item.platform),
  ))

  const filteredSources = computed(() => {
    const keyword = keywordFilter.value.trim().toLowerCase()
    const now = Date.now()
    const dayMs = 86400000
    const rangeDays = datePreset.value === 'all' ? null : Number(datePreset.value)
    const rangeStart = rangeDays ? now - rangeDays * dayMs : null
    return allSources.value.filter(source => {
      const platformMatched = platformFilter.value === 'all'
        || (source.platforms || []).includes(platformFilter.value)
      const categoryMatched = categoryFilter.value === 'all' || source.category === categoryFilter.value
      const text = `${source.title || ''} ${(source.exposure_terms || []).join(' ')} ${(source.questions || []).join(' ')} ${source.url || ''}`.toLowerCase()
      const keywordMatched = !keyword || text.includes(keyword)
      const sourceTime = source.latest_time ? new Date(source.latest_time).getTime() : null
      // 客户样本后端已按监测日截到昨日；勿再用 latest_time 二次卡——补录刷 updated_at 后会被误杀成个位数。
      // 客户：后端已按监测日截到昨日且已过露出词门槛；勿再按近 N 天截断
      const dateMatched = isCustomerView.value
        ? true
        : (!rangeStart || (sourceTime != null && sourceTime >= rangeStart))
      return platformMatched && categoryMatched && keywordMatched && dateMatched
        && (source.exposure_terms || []).length > 0
    }).sort((a, b) => b.count - a.count)
  })

  const sourceTotalCount = computed(() => filteredSources.value.reduce((sum, item) => sum + item.count, 0))
  const uniqueSourceCount = computed(() => filteredSources.value.length)
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
    // 与列表同口径：客户侧不再用 latest_time 二次截断
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
    const bucket: Record<SourceCategory, number> = {
      official: 0,
      media: 0,
      qa: 0,
      social: 0,
      encyclopedia: 0,
    }
    filteredSources.value.forEach(source => {
      bucket[source.category] += source.count
    })
    const total = Object.values(bucket).reduce((sum, value) => sum + value, 0) || 1
    return (Object.keys(sourceCategoryLabels) as SourceCategory[]).map(key => ({
      key,
      name: sourceCategoryLabels[key],
      count: bucket[key],
      percent: Math.round(bucket[key] / total * 100),
    })).sort((a, b) => b.count - a.count)
  })

  const topCategory = computed(() => categoryStats.value.find(item => item.count > 0) || null)
  const officialRate = computed(() => categoryStats.value.find(item => item.key === 'official')?.percent ?? 0)

  const topSources = computed(() => filteredSources.value.slice(0, 5))

  const sourceStructureRows = computed(() => structurePlatformCodes.value.map(platform => {
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
      categories: (Object.keys(sourceCategoryLabels) as SourceCategory[]).map(type => ({
        type,
        value: total ? Math.round(((categoryMap[type] || 0) / denom) * 100) : 0,
      })),
    }
  }))

  const structureChartHeight = computed(() => Math.max(280, sourceStructureRows.value.length * 46 + 48))

  const hasStructurePanel = computed(() => sourceStructureRows.value.length > 0)

  const sourceTrendRows = computed(() => {
    const backendPoints = monitorSummary.value?.source_citation_trend?.points || []
    if (backendPoints.length) {
      // 客户：整段历史至昨日；运营：按预设截取
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

  const insight = computed(() => {
    if (!filteredSources.value.length) {
      return {
        level: 'empty' as const,
        title: '暂无含露出词的信源',
        body: '仅展示引用标题/链接中包含品牌露出词的文章。若 AI 引用的多为行业通用资讯，此处可能较少；请完成更多监测或切换「全部」时间范围。',
      }
    }
    return {
      level: 'ok' as const,
      title: '数据口径说明',
      body: '本页仅展示引用标题或链接中包含品牌露出词的信源。点击标题可打开原文；「问题」为触发该引用的监测问题，「露出词」为文中实际命中的品牌词。',
    }
  })

  async function loadSummary() {
    loading.value = true
    try {
      await analytics.loadMonitorSummary()
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
      sourceStructureRows: sourceStructureRows.value,
      sourceTrendRows: sourceTrendRows.value,
      sourceCategoryLabels,
    })
  }

  function resetFilters() {
    platformFilter.value = 'all'
    categoryFilter.value = 'all'
    keywordFilter.value = ''
    datePreset.value = isCustomerView.value ? 'all' : '30'
  }

  function exportCsv() {
    if (!filteredSources.value.length) {
      ElMessage.warning('暂无可导出数据')
      return
    }
    const lines = [
      ['标题', '链接', '引用次数', '监测问题', '露出词', '最近检测'].join(','),
      ...filteredSources.value.map(source => [
        `"${(source.title || '').replace(/"/g, '""')}"`,
        `"${source.url || ''}"`,
        source.count,
        `"${(source.questions || []).join('；')}"`,
        `"${(source.exposure_terms || []).join('、')}"`,
        source.latest_time ? formatDateTime(source.latest_time) : '',
      ].join(',')),
    ]
    const blob = new Blob([`\uFEFF${lines.join('\n')}`], { type: 'text/csv;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `${brandAsset.value?.brand_name || '信源'}-分析.csv`
    link.click()
    URL.revokeObjectURL(url)
    ElMessage.success('已导出 CSV')
  }

  watch([filteredSources, sourceStructureRows, sourceTrendRows, hasStructurePanel, loading], () => { void refreshCharts() }, { deep: true })

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
    platformTabs,
    filteredSources,
    topSources,
    sourceTotalCount,
    uniqueSourceCount,
    platformWithSourcesCount,
    categoryStats,
    topCategory,
    officialRate,
    sourceStructureRows,
    sourceTrendRows,
    structureChartHeight,
    hasStructurePanel,
    insight,
    loadSummary,
    resetFilters,
    exportCsv,
    platformLabelMap,
    sourceCategoryLabels,
    domainFromUrl,
  }
}
