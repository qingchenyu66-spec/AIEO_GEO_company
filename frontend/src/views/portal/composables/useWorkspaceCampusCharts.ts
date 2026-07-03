import { nextTick, onUnmounted, ref, watch, type Ref } from 'vue'
import type { ECharts } from 'echarts/core'

export type WorkspaceCampusChartData = {
  trendLabels: string[]
  trendValues: number[]
  intentRows: Array<{ name: string; value: number }>
  intentTotal: number
  mentionRows: Array<{ name: string; value: number }>
  mentionRate: number
  healthScore: number | null
  rankGaugeScore: number
  avgBrandRank: number | null
  top3Rate: number
  platformRankLabels: string[]
  platformRankValues: number[]
  platformRankSamples: number[]
}

type ChartRefs = {
  trend: Ref<HTMLDivElement | null>
  intent: Ref<HTMLDivElement | null>
  mention: Ref<HTMLDivElement | null>
  healthGauge: Ref<HTMLDivElement | null>
  rankGauge: Ref<HTMLDivElement | null>
  top3Gauge: Ref<HTMLDivElement | null>
  platformRank: Ref<HTMLDivElement | null>
}

type EchartsRuntime = {
  init: typeof import('echarts/core').init
  getInstanceByDom: typeof import('echarts/core').getInstanceByDom
  graphic: typeof import('echarts/core').graphic
}

let echartsRuntime: EchartsRuntime | null = null
let echartsLoadPromise: Promise<EchartsRuntime> | null = null

async function loadEchartsRuntime(): Promise<EchartsRuntime> {
  if (echartsRuntime) return echartsRuntime
  if (!echartsLoadPromise) {
    echartsLoadPromise = (async () => {
      const [core, charts, components, renderers] = await Promise.all([
        import('echarts/core'),
        import('echarts/charts'),
        import('echarts/components'),
        import('echarts/renderers'),
      ])
      core.use([
        charts.BarChart,
        charts.LineChart,
        charts.GaugeChart,
        charts.PieChart,
        components.GridComponent,
        components.LegendComponent,
        components.TooltipComponent,
        renderers.CanvasRenderer,
      ])
      echartsRuntime = {
        init: core.init,
        getInstanceByDom: core.getInstanceByDom,
        graphic: core.graphic,
      }
      return echartsRuntime
    })()
  }
  return echartsLoadPromise
}

function campusGaugeOption(
  value: number,
  detailText: string,
  colors: [string, string],
  max = 100,
) {
  return {
    animationDuration: 1200,
    animationEasing: 'cubicOut' as const,
    series: [{
      type: 'gauge',
      min: 0,
      max,
      radius: '92%',
      startAngle: 220,
      endAngle: -40,
      progress: { show: true, width: 10, roundCap: true },
      axisLine: {
        lineStyle: {
          width: 10,
          color: [[1, '#e5e7eb']],
        },
      },
      axisTick: { show: false },
      splitLine: { show: false },
      axisLabel: { show: false },
      pointer: { show: false },
      anchor: { show: false },
      itemStyle: {
        color: {
          type: 'linear',
          x: 0,
          y: 0,
          x2: 1,
          y2: 0,
          colorStops: [
            { offset: 0, color: colors[0] },
            { offset: 1, color: colors[1] },
          ],
        },
      },
      detail: {
        valueAnimation: true,
        formatter: detailText,
        fontSize: 20,
        fontWeight: 800,
        color: colors[0],
        offsetCenter: [0, '8%'],
      },
      data: [{ value: Math.max(0, Math.min(max, value)) }],
    }],
  }
}

export function useWorkspaceCampusCharts(refs: ChartRefs) {
  const chartInstances: ECharts[] = []
  const chartsReady = ref(false)
  let resizeObserver: ResizeObserver | null = null

  function getChart(el: HTMLDivElement | null) {
    if (!el || !echartsRuntime) return null
    const current = echartsRuntime.getInstanceByDom(el)
    if (current) return current
    const instance = echartsRuntime.init(el)
    chartInstances.push(instance)
    return instance
  }

  function resizeCharts() {
    chartInstances.forEach(instance => instance.resize())
  }

  async function renderCharts(data: WorkspaceCampusChartData) {
    await loadEchartsRuntime()
    chartsReady.value = true
    await nextTick()

    const { graphic } = echartsRuntime!

    const trendChart = getChart(refs.trend.value)
    if (trendChart) {
      if (data.trendLabels.length) {
        trendChart.setOption({
          animationDuration: 1000,
          animationEasing: 'cubicOut' as const,
          color: ['#2d6cdf'],
          grid: { left: 38, right: 18, top: 18, bottom: 24 },
          tooltip: {
            trigger: 'axis',
            valueFormatter: (value: number) => `${value}%`,
            axisPointer: {
              type: 'line',
              lineStyle: { color: '#7ca7f8', width: 1 },
            },
          },
          xAxis: {
            type: 'category',
            data: data.trendLabels,
            boundaryGap: false,
            axisTick: { show: false },
            axisLine: { lineStyle: { color: '#dce7f4' } },
            axisLabel: { color: '#6f8198', fontSize: 11 },
          },
          yAxis: {
            type: 'value',
            max: 100,
            axisLine: { show: false },
            axisTick: { show: false },
            axisLabel: { formatter: '{value}%', color: '#9aa9bc', fontSize: 11 },
            splitLine: { lineStyle: { color: '#edf3f9' } },
          },
          series: [{
            type: 'line',
            data: data.trendValues,
            smooth: true,
            symbol: 'circle',
            symbolSize: 7,
            showSymbol: true,
            lineStyle: {
              width: 3,
              color: new graphic.LinearGradient(0, 0, 1, 0, [
                { offset: 0, color: '#2d6cdf' },
                { offset: 1, color: '#14a7c7' },
              ]),
            },
            itemStyle: {
              color: '#2d6cdf',
              borderWidth: 3,
              borderColor: '#ffffff',
            },
            areaStyle: {
              color: new graphic.LinearGradient(0, 0, 0, 1, [
                { offset: 0, color: 'rgba(45, 108, 223, .26)' },
                { offset: .62, color: 'rgba(20, 167, 199, .12)' },
                { offset: 1, color: 'rgba(45, 108, 223, 0)' },
              ]),
            },
            animationDelay: (idx: number) => idx * 60,
          }],
        }, true)
      } else {
        trendChart.clear()
      }
    }

    const intentChart = getChart(refs.intent.value)
    if (intentChart) {
      if (data.intentTotal > 0) {
        intentChart.setOption({
          animationDuration: 1200,
          animationEasing: 'elasticOut' as const,
          color: ['#14b8a6', '#3b82f6'],
          tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
          legend: {
            bottom: 0,
            itemWidth: 10,
            itemHeight: 10,
            textStyle: { color: '#6b7280', fontSize: 11 },
          },
          series: [{
            type: 'pie',
            radius: ['48%', '72%'],
            center: ['50%', '44%'],
            data: data.intentRows,
            label: { show: false },
            emphasis: {
              scale: true,
              scaleSize: 6,
            },
          }],
          graphic: [{
            type: 'text',
            left: 'center',
            top: '36%',
            style: {
              text: `${data.intentTotal}\n鏍锋湰`,
              textAlign: 'center',
              fill: '#1f2937',
              fontSize: 14,
              fontWeight: 700,
              lineHeight: 20,
            },
          }],
        }, true)
      } else {
        intentChart.clear()
      }
    }

    const mentionChart = getChart(refs.mention.value)
    if (mentionChart) {
      if (data.mentionRows.some(row => row.value > 0)) {
        mentionChart.setOption({
          animationDuration: 1200,
          animationEasing: 'elasticOut' as const,
          color: ['#14b8a6', '#ef4444'],
          tooltip: { trigger: 'item', formatter: '{b}: {d}%' },
          legend: {
            bottom: 0,
            itemWidth: 10,
            itemHeight: 10,
            textStyle: { color: '#6b7280', fontSize: 11 },
          },
          series: [{
            type: 'pie',
            radius: ['52%', '76%'],
            center: ['50%', '44%'],
            data: data.mentionRows,
            label: { show: false },
            emphasis: { scale: true, scaleSize: 6 },
          }],
          graphic: [{
            type: 'text',
            left: 'center',
            top: '36%',
            style: {
              text: `${data.mentionRate}%\n已提及`,
              textAlign: 'center',
              fill: '#14b8a6',
              fontSize: 18,
              fontWeight: 800,
              lineHeight: 24,
            },
          }],
        }, true)
      } else {
        mentionChart.clear()
      }
    }

    const healthChart = getChart(refs.healthGauge.value)
    if (healthChart) {
      healthChart.setOption(
        campusGaugeOption(
          data.healthScore ?? 0,
          data.healthScore != null ? `${data.healthScore}` : '-',
          ['#67e8f9', '#38bdf8'],
        ),
        true,
      )
    }

    const rankChart = getChart(refs.rankGauge.value)
    if (rankChart) {
      rankChart.setOption(
        campusGaugeOption(
          data.rankGaugeScore,
          data.avgBrandRank != null ? `${data.avgBrandRank}` : '-',
          ['#2563eb', '#60a5fa'],
        ),
        true,
      )
    }

    const top3Chart = getChart(refs.top3Gauge.value)
    if (top3Chart) {
      top3Chart.setOption(
        campusGaugeOption(
          data.top3Rate,
          `${data.top3Rate}%`,
          ['#7c3aed', '#a78bfa'],
        ),
        true,
      )
    }

    const platformChart = getChart(refs.platformRank.value)
    if (platformChart) {
      if (data.platformRankLabels.length) {
        const rows = [...data.platformRankLabels].reverse()
        const values = [...data.platformRankValues].reverse()
        const samples = [...data.platformRankSamples].reverse()
        const hasManyRows = rows.length > 6
        const formatPlatformLabel = (value: number, sampleCount: number) => {
          if (sampleCount <= 0) return '待返回'
          return `${value}%`
        }
        platformChart.setOption({
          animationDuration: 1000,
          animationEasing: 'cubicOut' as const,
          grid: { left: 8, right: 58, top: 6, bottom: 6 },
          tooltip: {
            trigger: 'axis',
            axisPointer: { type: 'shadow' },
            formatter: (params: unknown) => {
              const item = (params as Array<{ name: string; value: number; dataIndex: number }>)?.[0]
              if (!item) return ''
              const sampleCount = samples[item.dataIndex] ?? 0
              if (sampleCount <= 0) return `${item.name}<br/>暂无返回样本`
              return `${item.name}<br/>品牌露出率：${item.value}%<br/>样本数：${sampleCount}`
            },
          },
          xAxis: {
            type: 'value',
            max: 100,
            show: false,
          },
          yAxis: {
            type: 'category',
            data: rows,
            axisTick: { show: false },
            axisLine: { show: false },
            axisLabel: { color: '#52657d', fontSize: hasManyRows ? 11 : 12 },
          },
          series: [{
            type: 'bar',
            data: values,
            barWidth: hasManyRows ? 9 : 12,
            label: {
              show: true,
              position: 'right',
              formatter: (params: { value: number; dataIndex: number }) => (
                formatPlatformLabel(params.value, samples[params.dataIndex] ?? 0)
              ),
              color: (params: { value: number; dataIndex: number }) => {
                const sampleCount = samples[params.dataIndex] ?? 0
                if (sampleCount <= 0) return '#94a3b8'
                return params.value > 0 ? '#0f8d7f' : '#c2410c'
              },
              fontWeight: 700,
              fontSize: 11,
            },
            itemStyle: {
              borderRadius: [0, 6, 6, 0],
              color: (params: { value: number; dataIndex: number }) => {
                const sampleCount = samples[params.dataIndex] ?? 0
                if (sampleCount <= 0) return '#d9e2ef'
                if (params.value <= 0) {
                  return new graphic.LinearGradient(0, 0, 1, 0, [
                    { offset: 0, color: '#f5d0c8' },
                    { offset: 1, color: '#f0b6a8' },
                  ])
                }
                return new graphic.LinearGradient(0, 0, 1, 0, [
                  { offset: 0, color: '#2d6cdf' },
                  { offset: 1, color: '#35d39b' },
                ])
              },
            },
            animationDelay: (idx: number) => idx * 80,
          }],
        }, true)
      } else {
        platformChart.clear()
      }
    }

    resizeCharts()
  }

  let resizeBound = false

  function bindResize() {
    if (resizeBound || typeof ResizeObserver === 'undefined') return
    resizeBound = true
    resizeObserver = new ResizeObserver(() => resizeCharts())
    Object.values(refs).forEach(refItem => {
      if (refItem.value) resizeObserver?.observe(refItem.value)
    })
  }

  function disposeCharts() {
    resizeObserver?.disconnect()
    resizeObserver = null
    resizeBound = false
    chartInstances.forEach(instance => instance.dispose())
    chartInstances.length = 0
  }

  onUnmounted(disposeCharts)

  return { chartsReady, renderCharts, disposeCharts, bindResize, resizeCharts }
}

export function watchWorkspaceCampusCharts(
  data: Ref<WorkspaceCampusChartData | null>,
  render: (payload: WorkspaceCampusChartData) => Promise<void>,
  bindResize: () => void,
) {
  watch(
    data,
    async (payload) => {
      if (!payload) return
      await render(payload)
      bindResize()
    },
    { deep: true, flush: 'post' },
  )
}
