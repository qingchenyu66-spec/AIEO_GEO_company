import { computed, inject, onMounted, onUnmounted, ref, watch, type Ref } from 'vue'
import { ElMessage } from 'element-plus'
import { withRetry } from '../../../composables/useRetry'
import { usePortalCharts } from '../../../composables/usePortalCharts'
import { getMonitorSummary, type MonitorSummary } from '../../../services/monitor'
import { PortalAnalyticsKey } from '../injectionKeys'
import { platformLabelMap } from '../portalMaps'
import { formatDateTime } from '../portalUtils'

export type SourceCategory = 'official' | 'media' | 'qa' | 'social' | 'encyclopedia'

export const sourceCategoryLabels: Record<SourceCategory, string> = {
  official: '官网/企业库',
  media: '行业媒体',
  qa: '问答社区',
  social: '社交媒体',
  encyclopedia: '百科',
}

export type SourceDatePreset = '7' | '30' | 'all'

export type SourceRow = MonitorSummary['source_stats'][number] & {
  category: SourceCategory
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : String(error)
}

export function sourceCategory(source: { title?: string; url?: string }): SourceCategory {
  const text = `${source.title || ''} ${source.url || ''}`.toLowerCase()
  if (text.includes('baike') || text.includes('百科')) return 'encyclopedia'
  if (text.includes('zhihu') || text.includes('知乎') || text.includes('问答')) return 'qa'
  if (text.includes('weibo') || text.includes('微博') || text.includes('douyin') || text.includes('小红书')) return 'social'
  if (text.includes('sohu') || text.includes('163.com') || text.includes('媒体') || text.includes('新闻') || text.includes('资讯')) return 'media'
  return 'official'
}

function domainFromUrl(url: string) {
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return url
  }
}

export function useSourceAnalysis(options?: {
  structureChartRef?: Ref<HTMLDivElement | null>
  trendChartRef?: Ref<HTMLDivElement | null>
}) {
  const analytics = inject(PortalAnalyticsKey)!
  const brandAsset = analytics.brandAsset

  const loading = ref(false)
  const monitorSummary = ref<MonitorSummary | null>(null)
  const datePreset = ref<SourceDatePreset>('30')
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

  const platformRanking = computed(() => monitorSummary.value?.platform_stats || [])

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
      const dateMatched = !rangeStart || (sourceTime != null && sourceTime >= rangeStart)
      return platformMatched && categoryMatched && keywordMatched && dateMatched
        && (source.exposure_terms || []).length > 0
    }).sort((a, b) => b.count - a.count)
  })

  const sourceTotalCount = computed(() => filteredSources.value.reduce((sum, item) => sum + item.count, 0))
  const uniqueSourceCount = computed(() => filteredSources.value.length)
  const platformWithSourcesCount = computed(() => {
    const codes = new Set<string>()
    filteredSources.value.forEach(source => (source.platforms || []).forEach(code => codes.add(code)))
    return codes.size
  })

  const platformTabs = computed(() => {
    const counts = new Map<string, number>()
    allSources.value.forEach(source => {
      ;(source.platforms || []).forEach(platform => counts.set(platform, (counts.get(platform) || 0) + source.count))
    })
    return [
      { code: 'all', name: '全部平台', count: allSources.value.reduce((sum, source) => sum + source.count, 0) },
      ...Array.from(counts.entries())
        .map(([code, count]) => ({ code, name: platformLabelMap[code] || code, count }))
        .sort((a, b) => b.count - a.count),
    ]
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

  const sourceStructureRows = computed(() => platformRanking.value.slice(0, 6).map(platform => {
    const platformSources = filteredSources.value.filter(source => (source.platforms || []).includes(platform.platform))
    const total = Math.max(1, platformSources.reduce((sum, source) => sum + source.count, 0))
    const categoryMap = platformSources.reduce((map, source) => {
      map[source.category] = (map[source.category] || 0) + source.count
      return map
    }, {} as Record<string, number>)
    return {
      platform: platform.platform,
      total,
      categories: (Object.keys(sourceCategoryLabels) as SourceCategory[]).map(type => ({
        type,
        value: Math.round(((categoryMap[type] || 0) / total) * 100),
      })),
    }
  }))

  const sourceTrendRows = computed(() => {
    const days = datePreset.value === 'all' ? 14 : Math.min(Number(datePreset.value), 14)
    const now = new Date()
    return Array.from({ length: days }).map((_, index) => {
      const day = new Date(now)
      day.setDate(now.getDate() - (days - 1 - index))
      const label = `${String(day.getMonth() + 1).padStart(2, '0')}-${String(day.getDate()).padStart(2, '0')}`
      const value = filteredSources.value.reduce((sum, source) => {
        if (!source.latest_time) return sum
        const sourceDate = new Date(source.latest_time)
        const matched = sourceDate.getFullYear() === day.getFullYear()
          && sourceDate.getMonth() === day.getMonth()
          && sourceDate.getDate() === day.getDate()
        return matched ? sum + source.count : sum
      }, 0)
      return { label, value }
    })
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
      monitorSummary.value = await withRetry(() => getMonitorSummary())
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
    datePreset.value = '30'
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

  watch([filteredSources, sourceStructureRows, sourceTrendRows, loading], () => { void refreshCharts() }, { deep: true })

  onMounted(() => {
    void loadSummary()
    window.addEventListener('resize', refreshCharts)
  })

  onUnmounted(() => {
    window.removeEventListener('resize', refreshCharts)
  })

  return {
    brandAsset,
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
    insight,
    loadSummary,
    resetFilters,
    exportCsv,
    platformLabelMap,
    sourceCategoryLabels,
    domainFromUrl,
  }
}
