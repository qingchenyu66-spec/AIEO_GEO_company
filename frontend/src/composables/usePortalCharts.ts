import { nextTick, onUnmounted, ref, type Ref } from 'vue'
import type { ECharts } from 'echarts/core'
import { loadEchartsRuntime } from '../utils/echartsLoader'
import { platformLabelMap } from '../views/portal/portalMaps'
import { sourceCategoryColor } from '../views/portal/sourceCategory'
import type { BrandInsightsTrends } from '../services/analytics'

export type PortalChartRefs = {
  trend?: Ref<HTMLDivElement | null>
  exposureRank?: Ref<HTMLDivElement | null>
  sentiment?: Ref<HTMLDivElement | null>
  sentimentTrend?: Ref<HTMLDivElement | null>
  diagnosis?: Ref<HTMLDivElement | null>
  competitor?: Ref<HTMLDivElement | null>
  competitorRank?: Ref<HTMLDivElement | null>
  mentionTrend?: Ref<HTMLDivElement | null>
  sourceStructure?: Ref<HTMLDivElement | null>
  sourceTrend?: Ref<HTMLDivElement | null>
}

export type PortalChartData = {
  chartTrend: Array<{ label: string; value: number }>
  sentimentTrendRows?: Array<{ label: string; positive: number; neutral: number; negative: number }>
  mentionTrendSeries?: BrandInsightsTrends
  platformRanking: Array<{ platform: string; mention_rate: number }>
  sentimentPieRows: Array<{ name: string; value: number }>
  positiveRate: number
  diagnosisScore: number
  competitorCompareRows: Array<{ name: string; mention: number; mention_count?: number; rank?: number | null; is_brand?: boolean }>
  competitorRankRows?: Array<{ name: string; rank: number; is_brand?: boolean }>
  sourceStructureRows: Array<{
    platform: string
    total?: number
    categories: Array<{ type: string; value: number }>
  }>
  sourceTrendRows: Array<{ label: string; value: number }>
  sourceCategoryLabels: Record<string, string>
  chartClickHandlers?: {
    mentionTrend?: (payload: { label: string; seriesName?: string }) => void
    sentimentTrend?: (payload: { label: string }) => void
  }
}

type EchartsRuntime = Awaited<ReturnType<typeof loadEchartsRuntime>>

let echartsRuntime: EchartsRuntime | null = null

async function ensureEchartsRuntime(): Promise<EchartsRuntime> {
  if (!echartsRuntime) {
    echartsRuntime = await loadEchartsRuntime('portal')
  }
  return echartsRuntime
}

export function usePortalCharts(refs: PortalChartRefs) {
  const chartInstances: ECharts[] = []
  const chartsReady = ref(false)

  function getChart(el: HTMLDivElement | null) {
    if (!el || !echartsRuntime) return null
    const current = echartsRuntime.getInstanceByDom(el)
    if (current) return current
    const instance = echartsRuntime.init(el)
    chartInstances.push(instance)
    return instance
  }

  async function renderCharts(data: PortalChartData) {
    await ensureEchartsRuntime()
    chartsReady.value = true
    await nextTick()

    const { graphic } = echartsRuntime!
    if (!graphic) return

    const trendChart = getChart(refs.trend?.value ?? null)
    if (trendChart) {
      trendChart.setOption({
        color: ['#25b7d3'],
        grid: { left: 38, right: 18, top: 34, bottom: 32 },
        tooltip: {
          trigger: 'axis',
          formatter: (params: unknown) => {
            const item = (params as Array<{ name: string; value: number }>)?.[0]
            return item ? `${item.name}<br/>曝光次数：${item.value}` : ''
          },
        },
        xAxis: { type: 'category', data: data.chartTrend.map(item => item.label), axisTick: { show: false } },
        yAxis: { type: 'value', splitLine: { lineStyle: { color: '#e8eff7' } } },
        series: [{
          type: 'line',
          smooth: true,
          symbolSize: 8,
          data: data.chartTrend.map(item => item.value),
          label: { show: true, position: 'top', color: '#174078', fontWeight: 700 },
          lineStyle: { width: 4 },
          areaStyle: {
            color: new graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: 'rgba(37,183,211,.28)' },
              { offset: 1, color: 'rgba(37,183,211,0)' },
            ]),
          },
        }],
      })
    }

    const exposureRankChart = getChart(refs.exposureRank?.value ?? null)
    if (exposureRankChart) {
      const rows = data.platformRanking.slice(0, 8).reverse()
      exposureRankChart.setOption({
        color: ['#35c58f'],
        grid: { left: 86, right: 42, top: 18, bottom: 24 },
        tooltip: {
          trigger: 'axis',
          axisPointer: { type: 'shadow' },
          formatter: (params: unknown) => {
            const item = (params as Array<{ name: string; value: number }>)?.[0]
            return item ? `${item.name}<br/>曝光率：${item.value}%` : ''
          },
        },
        xAxis: { type: 'value', max: 100, axisLabel: { formatter: '{value}%' }, splitLine: { lineStyle: { color: '#e8eff7' } } },
        yAxis: {
          type: 'category',
          data: rows.map(item => platformLabelMap[item.platform] || item.platform),
          axisTick: { show: false },
        },
        series: [{
          type: 'bar',
          data: rows.map(item => item.mention_rate),
          barWidth: 16,
          label: { show: true, position: 'right', formatter: '{c}%', color: '#17324d', fontWeight: 700 },
          itemStyle: {
            borderRadius: [0, 8, 8, 0],
            color: new graphic.LinearGradient(0, 0, 1, 0, [
              { offset: 0, color: '#38a3ff' },
              { offset: 1, color: '#35d39b' },
            ]),
          },
        }],
      })
    }

    const pieChart = getChart(refs.sentiment?.value ?? null)
    if (pieChart) {
      pieChart.setOption({
        color: ['#58ddb0', '#4b8dff', '#ff6b7d', '#aab8c7'],
        tooltip: { trigger: 'item' },
        legend: { bottom: 0, itemWidth: 10, itemHeight: 10, textStyle: { color: '#23415f' } },
        series: [{
          type: 'pie',
          radius: ['54%', '76%'],
          center: ['50%', '44%'],
          data: data.sentimentPieRows,
          label: { formatter: '{b} {d}%', color: '#17324d', fontWeight: 700 },
          labelLine: { length: 10, length2: 8 },
        }],
        graphic: [{
          type: 'text',
          left: 'center',
          top: '38%',
          style: {
            text: `${data.positiveRate}%\n正面占比`,
            textAlign: 'center',
            fill: '#10233f',
            fontSize: 22,
            fontWeight: 800,
            lineHeight: 30,
          },
        }],
      })
    }

    const trendMini = getChart(refs.sentimentTrend?.value ?? null)
    if (trendMini) {
      if (data.sentimentTrendRows?.length) {
        const rows = data.sentimentTrendRows
        trendMini.setOption({
          color: ['#58ddb0', '#aab8c7', '#ff6b7d'],
          grid: { left: 36, right: 12, top: 28, bottom: 24 },
          tooltip: { trigger: 'axis' },
          legend: { top: 0, itemWidth: 10, itemHeight: 10, textStyle: { color: '#58708f', fontSize: 11 } },
          xAxis: { type: 'category', data: rows.map(item => item.label), axisLabel: { color: '#6a7f9a', fontSize: 11 } },
          yAxis: { type: 'value', max: 100, axisLabel: { formatter: '{value}%', color: '#8aa0ba', fontSize: 11 }, splitLine: { lineStyle: { color: '#eef2f7' } } },
          series: [
            { name: '正面', type: 'line', smooth: true, symbolSize: 6, data: rows.map(item => item.positive) },
            { name: '中性', type: 'line', smooth: true, symbolSize: 6, data: rows.map(item => item.neutral) },
            { name: '负面', type: 'line', smooth: true, symbolSize: 6, data: rows.map(item => item.negative) },
          ],
        })
        trendMini.off('click')
        if (data.chartClickHandlers?.sentimentTrend) {
          trendMini.on('click', (params: { dataIndex?: number }) => {
            const index = params.dataIndex ?? 0
            data.chartClickHandlers?.sentimentTrend?.({ label: rows[index]?.label || '' })
          })
        }
      } else {
        trendMini.clear()
      }
    }

    const mentionTrendChart = getChart(refs.mentionTrend?.value ?? null)
    if (mentionTrendChart) {
      const trend = data.mentionTrendSeries
      if (trend?.labels?.length && trend.series?.length) {
        const palette = ['#2d6cdf', '#94a3b8', '#a8b4c4', '#b8c2d0', '#c8d0dc', '#d0d8e4']
        mentionTrendChart.setOption({
          color: palette,
          grid: { left: 42, right: 18, top: trend.series.length > 4 ? 48 : 36, bottom: 28 },
          tooltip: {
            trigger: 'axis',
            confine: true,
            formatter: (params: unknown) => {
              const items = (Array.isArray(params) ? params : [params]) as Array<{
                axisValue?: string
                marker?: string
                seriesName?: string
                value?: number
              }>
              if (!items.length) return ''
              const header = items[0]?.axisValue || ''
              const lines = [...items]
                .sort((a, b) => Number(b.value || 0) - Number(a.value || 0))
                .map(item => `${item.marker || ''}${item.seriesName || ''}：${item.value ?? 0}%`)
              return [header, ...lines].join('<br/>')
            },
          },
          legend: {
            type: 'plain',
            top: 0,
            left: 8,
            right: 8,
            itemWidth: 14,
            itemHeight: 4,
            itemGap: 14,
            textStyle: { color: '#58708f', fontSize: 11 },
          },
          xAxis: {
            type: 'category',
            data: trend.labels,
            boundaryGap: false,
            axisLabel: { color: '#6a7f9a', fontSize: 11 },
            axisTick: { show: false },
          },
          yAxis: {
            type: 'value',
            max: 100,
            axisLabel: { formatter: '{value}%', color: '#8aa0ba', fontSize: 11 },
            splitLine: { lineStyle: { color: '#eef2f7' } },
          },
          series: trend.series.map((item, index) => ({
            name: item.name,
            type: 'line',
            smooth: 0.35,
            showSymbol: item.is_brand,
            symbolSize: item.is_brand ? 7 : 4,
            z: item.is_brand ? 3 : 1,
            data: item.values,
            lineStyle: {
              width: item.is_brand ? 3 : 1.5,
              type: item.is_brand ? 'solid' : 'dashed',
              opacity: item.is_brand ? 1 : 0.82,
            },
            itemStyle: {
              color: item.is_brand ? palette[0] : palette[Math.min(index, palette.length - 1)],
            },
            emphasis: {
              focus: 'series',
              lineStyle: { width: item.is_brand ? 3.5 : 2.5 },
            },
            areaStyle: item.is_brand ? {
              color: new graphic.LinearGradient(0, 0, 0, 1, [
                { offset: 0, color: 'rgba(45,108,223,.14)' },
                { offset: 1, color: 'rgba(45,108,223,0)' },
              ]),
            } : undefined,
          })),
        })
        mentionTrendChart.off('click')
        if (data.chartClickHandlers?.mentionTrend) {
          mentionTrendChart.on('click', (params: { dataIndex?: number; seriesIndex?: number }) => {
            const index = params.dataIndex ?? 0
            const seriesIndex = params.seriesIndex ?? 0
            data.chartClickHandlers?.mentionTrend?.({
              label: trend.labels[index] || '',
              seriesName: trend.series[seriesIndex]?.name,
            })
          })
        }
      } else {
        mentionTrendChart.clear()
      }
    }

    const diagnosisChart = getChart(refs.diagnosis?.value ?? null)
    if (diagnosisChart) {
      diagnosisChart.setOption({
        series: [{
          type: 'gauge',
          min: 0,
          max: 100,
          radius: '92%',
          axisLine: { lineStyle: { width: 14, color: [[0.35, '#ff6b7d'], [0.7, '#f6c85f'], [1, '#52d4a4']] } },
          pointer: { width: 4 },
          detail: { valueAnimation: true, formatter: '{value}分', fontSize: 28, fontWeight: 800, color: '#10233f' },
          data: [{ value: data.diagnosisScore }],
        }],
      })
    }

    const compareChart = getChart(refs.competitor?.value ?? null)
    if (compareChart) {
      const rows = data.competitorCompareRows
      if (!rows.length) {
        compareChart.clear()
      } else {
      compareChart.setOption({
        color: ['#36cfc9'],
        grid: { left: 90, right: 36, top: 20, bottom: 20 },
        tooltip: {
          trigger: 'axis',
          axisPointer: { type: 'shadow' },
          formatter: (params: unknown) => {
            const list = params as Array<{ dataIndex: number }>
            const index = list?.[0]?.dataIndex ?? 0
            const row = rows[index]
            if (!row) return ''
            return `${row.name}<br/>提及率：${row.mention}%<br/>平均排名：${row.rank ?? '—'}<br/>提及次数：${row.mention_count ?? 0}`
          },
        },
        xAxis: { type: 'value', max: 100, axisLabel: { formatter: '{value}%' }, splitLine: { lineStyle: { color: '#e8eff7' } } },
        yAxis: { type: 'category', data: rows.map(item => item.name), axisTick: { show: false } },
        series: [{
          type: 'bar',
          data: rows.map(item => item.mention),
          label: { show: true, position: 'right', formatter: '{c}%' },
          itemStyle: {
            borderRadius: [0, 8, 8, 0],
            color: (params: { dataIndex: number }) => {
              const row = rows[params.dataIndex]
              return row?.is_brand
                ? new graphic.LinearGradient(0, 0, 1, 0, [{ offset: 0, color: '#2f74ff' }, { offset: 1, color: '#49d8b7' }])
                : new graphic.LinearGradient(0, 0, 1, 0, [{ offset: 0, color: '#8aa0ba' }, { offset: 1, color: '#c5d4e4' }])
            },
          },
        }],
      })
      }
    }

    const rankCompareChart = getChart(refs.competitorRank?.value ?? null)
    if (rankCompareChart && data.competitorRankRows?.length) {
      const rows = data.competitorRankRows
      rankCompareChart.setOption({
        grid: { left: 90, right: 36, top: 20, bottom: 20 },
        tooltip: {
          trigger: 'axis',
          axisPointer: { type: 'shadow' },
          formatter: (params: unknown) => {
            const list = params as Array<{ dataIndex: number }>
            const index = list?.[0]?.dataIndex ?? 0
            const row = rows[index]
            if (!row) return ''
            return `${row.name}<br/>平均排名：${row.rank}`
          },
        },
        xAxis: {
          type: 'value',
          min: 0,
          inverse: false,
          axisLabel: { formatter: '{value}' },
          splitLine: { lineStyle: { color: '#e8eff7' } },
        },
        yAxis: { type: 'category', data: rows.map(item => item.name), axisTick: { show: false } },
        series: [{
          type: 'bar',
          data: rows.map(item => item.rank),
          label: { show: true, position: 'right', formatter: '{c}' },
          itemStyle: {
            borderRadius: [0, 8, 8, 0],
            color: (params: { dataIndex: number }) => {
              const row = rows[params.dataIndex]
              return row?.is_brand
                ? new graphic.LinearGradient(0, 0, 1, 0, [{ offset: 0, color: '#2f74ff' }, { offset: 1, color: '#49d8b7' }])
                : new graphic.LinearGradient(0, 0, 1, 0, [{ offset: 0, color: '#94a3b8' }, { offset: 1, color: '#cbd5e1' }])
            },
          },
        }],
      })
    }

    const sourceStructureChart = getChart(refs.sourceStructure?.value ?? null)
    if (sourceStructureChart) {
      const categoryKeys = Object.keys(data.sourceCategoryLabels)
      const rows = data.sourceStructureRows
      const legendLabels = Object.values(data.sourceCategoryLabels)
      const compactStructure = rows.length <= 2
      const formatStructureTooltip = (params: unknown) => {
        const items = Array.isArray(params)
          ? params as Array<{ name: string; marker: string; seriesName: string; value: number; dataIndex?: number }>
          : [params as { name: string; marker: string; seriesName: string; value: number; dataIndex?: number }]
        const rowIndex = items[0]?.dataIndex ?? rows.findIndex(row => (
          (platformLabelMap[row.platform] || row.platform) === items[0]?.name
        ))
        const row = rowIndex >= 0 ? rows[rowIndex] : undefined
        const name = row
          ? (platformLabelMap[row.platform] || row.platform)
          : (items[0]?.name || '')
        if (!row?.total) return `${name}<br/>暂无含露出词的信源引用`
        const segments = compactStructure
          ? categoryKeys
            .map(type => ({
              seriesName: data.sourceCategoryLabels[type],
              value: row.categories.find(item => item.type === type)?.value || 0,
            }))
            .filter(item => item.value > 0)
          : items.filter(item => item.seriesName !== '暂无引用' && item.value > 0)
        return `${name}<br/>${segments
          .map(item => `${'marker' in item && item.marker ? item.marker : '● '}${item.seriesName}：${item.value}%`)
          .join('<br/>')}`
      }
      sourceStructureChart.setOption({
        grid: {
          left: 88,
          right: 46,
          top: compactStructure ? 20 : 18,
          bottom: compactStructure ? 28 : 34,
        },
        tooltip: {
          trigger: compactStructure ? 'item' : 'axis',
          ...(compactStructure ? {} : { axisPointer: { type: 'shadow' } }),
          formatter: formatStructureTooltip,
        },
        legend: { bottom: 0, itemWidth: 22, itemHeight: 5, textStyle: { color: '#526b89' }, data: legendLabels },
        xAxis: { type: 'value', max: 100, show: false },
        yAxis: {
          type: 'category',
          data: rows.map(item => platformLabelMap[item.platform] || item.platform),
          axisTick: { show: false },
          axisLine: { show: false },
          axisLabel: { color: '#55708f', fontWeight: 700 },
        },
        series: [
          {
            name: '暂无引用',
            type: 'bar',
            stack: 'source',
            barWidth: 16,
            data: rows.map(row => (row.total ?? 0) > 0 ? 0 : 100),
            itemStyle: { color: '#e8edf3', borderRadius: [0, 8, 8, 0] },
          },
          ...categoryKeys.map((type, index) => ({
            name: data.sourceCategoryLabels[type],
            type: 'bar',
            stack: 'source',
            barWidth: 16,
            data: rows.map(row => {
              if ((row.total ?? 0) === 0) return 0
              return row.categories.find(item => item.type === type)?.value || 0
            }),
            itemStyle: {
              color: sourceCategoryColor(type),
              borderRadius: index === categoryKeys.length - 1 ? [0, 8, 8, 0] : 0,
            },
          })),
        ],
      }, { notMerge: true })
    }

    const sourceTrendChart = getChart(refs.sourceTrend?.value ?? null)
    if (sourceTrendChart) {
      sourceTrendChart.setOption({
        color: ['#2f74ea'],
        grid: { left: 34, right: 18, top: 26, bottom: 28 },
        tooltip: { trigger: 'axis' },
        xAxis: {
          type: 'category',
          data: data.sourceTrendRows.map(item => item.label),
          axisTick: { show: false },
          axisLine: { show: false },
          axisLabel: { color: '#6d84a1' },
        },
        yAxis: { type: 'value', show: false },
        series: [{
          type: 'line',
          smooth: true,
          symbolSize: 8,
          data: data.sourceTrendRows.map(item => item.value),
          label: { show: true, position: 'top', color: '#174078', fontWeight: 700 },
          lineStyle: { width: 4 },
          areaStyle: {
            color: new graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: 'rgba(47,116,234,.23)' },
              { offset: 1, color: 'rgba(47,116,234,0)' },
            ]),
          },
        }],
      })
    }
  }

  function disposeCharts() {
    chartInstances.forEach(instance => instance.dispose())
    chartInstances.length = 0
  }

  onUnmounted(disposeCharts)

  return { chartsReady, renderCharts, disposeCharts }
}
