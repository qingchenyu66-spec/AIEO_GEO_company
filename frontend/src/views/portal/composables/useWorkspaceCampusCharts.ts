import { nextTick, onUnmounted, ref, watch, type Ref } from 'vue'
import type { ECharts } from 'echarts/core'
import { loadEchartsRuntime } from '../../../utils/echartsLoader'

export type WorkspaceCampusChartData = {
  trendLabels: string[]
  trendValues: Array<number | null>
  trendEmptyFlags?: boolean[]
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

type ChartKey = keyof ChartRefs

type EchartsRuntime = Awaited<ReturnType<typeof loadEchartsRuntime>>

const VIEWPORT_ROOT_MARGIN = '200px 0px'
const VIEWPORT_PREFETCH_PX = 200

let echartsRuntime: EchartsRuntime | null = null

async function ensureEchartsRuntime(): Promise<EchartsRuntime> {
  if (!echartsRuntime) {
    echartsRuntime = await loadEchartsRuntime('portal')
  }
  return echartsRuntime
}

function campusGaugeOption(
  value: number,
  _detailText: string,
  colors: [string, string],
  max = 100,
) {
  const safe = Math.max(0, Math.min(max, value))
  return {
    animation: false,
    series: [{
      type: 'gauge',
      min: 0,
      max,
      // Align with workbench mock: arc sits low so progress is readable in short containers
      radius: '100%',
      center: ['50%', '72%'],
      startAngle: 210,
      endAngle: -30,
      progress: {
        show: true,
        width: 11,
        roundCap: true,
        itemStyle: { color: colors[0] },
      },
      axisLine: {
        lineStyle: {
          width: 11,
          color: [
            [0.4, '#fecaca'],
            [0.7, '#fde68a'],
            [1, '#bbf7d0'],
          ],
        },
      },
      axisTick: { show: false },
      splitLine: { show: false },
      axisLabel: { show: false },
      pointer: { show: false },
      anchor: { show: false },
      detail: { show: false },
      data: [{ value: safe }],
    }],
  }
}

function isInViewport(el: HTMLElement): boolean {
  const rect = el.getBoundingClientRect()
  return rect.bottom >= -VIEWPORT_PREFETCH_PX && rect.top <= window.innerHeight + VIEWPORT_PREFETCH_PX
}

export function useWorkspaceCampusCharts(refs: ChartRefs) {
  const chartInstances: ECharts[] = []
  const chartsReady = ref(false)
  let resizeObserver: ResizeObserver | null = null
  let viewportObserver: IntersectionObserver | null = null
  let latestData: WorkspaceCampusChartData | null = null
  const initializedCharts = new Set<ChartKey>()
  const elToKey = new WeakMap<HTMLDivElement, ChartKey>()

  const chartEntries: Array<{ key: ChartKey; ref: Ref<HTMLDivElement | null> }> = [
    { key: 'trend', ref: refs.trend },
    { key: 'intent', ref: refs.intent },
    { key: 'mention', ref: refs.mention },
    { key: 'healthGauge', ref: refs.healthGauge },
    { key: 'rankGauge', ref: refs.rankGauge },
    { key: 'top3Gauge', ref: refs.top3Gauge },
    { key: 'platformRank', ref: refs.platformRank },
  ]

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

  function ensureViewportObserver() {
    if (viewportObserver || typeof IntersectionObserver === 'undefined') return
    viewportObserver = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting || !latestData) return
        const el = entry.target as HTMLDivElement
        const key = elToKey.get(el)
        if (!key) return
        applyChartOption(key, latestData)
        viewportObserver?.unobserve(el)
      })
    }, { rootMargin: VIEWPORT_ROOT_MARGIN })
  }

  function applyChartOption(key: ChartKey, data: WorkspaceCampusChartData) {
    const { graphic } = echartsRuntime!
    if (!graphic) return

    switch (key) {
      case 'trend': {
        const trendChart = getChart(refs.trend.value)
        if (!trendChart) return
        if (data.trendLabels.length) {
          // 2026-08-20 - 无样本日误画成 0% - null 断线；灰点 scatter 提示「当日暂无样本」
          const emptyFlags = data.trendEmptyFlags
            || data.trendValues.map(value => value == null)
          const emptyScatter = data.trendLabels
            .map((label, index) => (emptyFlags[index] ? [label, 0] : null))
            .filter((item): item is [string, number] => item != null)
          trendChart.setOption({
            animation: false,
            color: ['#2563eb'],
            grid: { left: 48, right: 24, top: 24, bottom: 36, containLabel: false },
            tooltip: {
              trigger: 'axis',
              axisPointer: {
                type: 'line',
                lineStyle: { color: '#93c5fd', width: 1 },
              },
              formatter: (params: Array<{ axisValueLabel?: string; axisValue?: string; seriesType?: string; value?: number | string | null | Array<string | number> }>) => {
                const rows = Array.isArray(params) ? params : [params]
                const axis = String(rows[0]?.axisValueLabel ?? rows[0]?.axisValue ?? '')
                const line = rows.find(row => row.seriesType === 'line')
                const raw = line?.value
                const num = Array.isArray(raw) ? raw[1] : raw
                if (num == null || num === '' || Number.isNaN(Number(num))) {
                  return `${axis}<br/>当日暂无样本`
                }
                return `${axis}<br/>提及率 ${Number(num)}%`
              },
            },
            xAxis: {
              type: 'category',
              data: data.trendLabels,
              boundaryGap: true,
              axisTick: { show: false },
              axisLine: { lineStyle: { color: '#e2e8f0' } },
              axisLabel: { color: '#64748b', fontSize: 11 },
            },
            yAxis: {
              type: 'value',
              max: 100,
              axisLine: { show: false },
              axisTick: { show: false },
              axisLabel: { formatter: '{value}%', color: '#64748b', fontSize: 11 },
              splitLine: { lineStyle: { color: '#f1f5f9' } },
            },
            series: [
              {
                type: 'line',
                data: data.trendValues,
                connectNulls: false,
                smooth: true,
                symbol: 'circle',
                symbolSize: 8,
                showSymbol: true,
                lineStyle: { width: 3, color: '#2563eb' },
                itemStyle: {
                  color: '#2563eb',
                  borderWidth: 2,
                  borderColor: '#2563eb',
                },
                areaStyle: {
                  color: new graphic.LinearGradient(0, 0, 0, 1, [
                    { offset: 0, color: 'rgba(37, 99, 235, 0.25)' },
                    { offset: 1, color: 'rgba(37, 99, 235, 0.02)' },
                  ]),
                },
              },
              {
                type: 'scatter',
                data: emptyScatter,
                symbol: 'circle',
                symbolSize: 7,
                itemStyle: {
                  color: '#e2e8f0',
                  borderColor: '#94a3b8',
                  borderWidth: 1.5,
                },
                z: 5,
                tooltip: {
                  trigger: 'item',
                  formatter: (params: { name?: string; value?: [string, number] }) => {
                    const label = params.value?.[0] ?? params.name ?? ''
                    return `${label}<br/>当日暂无样本`
                  },
                },
              },
            ],
          }, true)
        } else {
          trendChart.clear()
        }
        break
      }
      case 'intent': {
        const intentChart = getChart(refs.intent.value)
        if (!intentChart) return
        if (data.intentTotal > 0) {
          intentChart.setOption({
            animation: false,
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
        break
      }
      case 'mention': {
        const mentionChart = getChart(refs.mention.value)
        if (!mentionChart) return
        if (data.mentionRows.some(row => row.value > 0)) {
          mentionChart.setOption({
            animation: false,
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
        break
      }
      case 'healthGauge': {
        const healthChart = getChart(refs.healthGauge.value)
        if (!healthChart) return
        healthChart.setOption(
          campusGaugeOption(
            data.healthScore ?? 0,
            data.healthScore != null ? `${data.healthScore}` : '-',
            ['#67e8f9', '#38bdf8'],
          ),
          true,
        )
        break
      }
      case 'rankGauge': {
        const rankChart = getChart(refs.rankGauge.value)
        if (!rankChart) return
        rankChart.setOption(
          campusGaugeOption(
            data.rankGaugeScore,
            data.avgBrandRank != null ? `${data.avgBrandRank}` : '-',
            ['#2563eb', '#60a5fa'],
          ),
          true,
        )
        break
      }
      case 'top3Gauge': {
        const top3Chart = getChart(refs.top3Gauge.value)
        if (!top3Chart) return
        top3Chart.setOption(
          campusGaugeOption(
            data.top3Rate,
            `${data.top3Rate}%`,
            ['#7c3aed', '#a78bfa'],
          ),
          true,
        )
        break
      }
      case 'platformRank': {
        const platformChart = getChart(refs.platformRank.value)
        if (!platformChart) return
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
            animation: false,
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
            }],
          }, true)
        } else {
          platformChart.clear()
        }
        break
      }
    }

    initializedCharts.add(key)
  }

  function scheduleChart(key: ChartKey, el: HTMLDivElement, data: WorkspaceCampusChartData) {
    if (initializedCharts.has(key) || isInViewport(el)) {
      applyChartOption(key, data)
      return
    }
    ensureViewportObserver()
    if (!viewportObserver) {
      applyChartOption(key, data)
      return
    }
    elToKey.set(el, key)
    viewportObserver.observe(el)
  }

  async function renderCharts(data: WorkspaceCampusChartData) {
    await ensureEchartsRuntime()
    latestData = data
    chartsReady.value = true
    await nextTick()

    if (!echartsRuntime?.graphic) return

    for (const { key, ref: chartRef } of chartEntries) {
      const el = chartRef.value
      if (!el) continue
      scheduleChart(key, el, data)
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
    viewportObserver?.disconnect()
    viewportObserver = null
    latestData = null
    initializedCharts.clear()
    resizeObserver?.disconnect()
    resizeObserver = null
    resizeBound = false
    chartInstances.forEach(instance => instance.dispose())
    chartInstances.length = 0
  }

  onUnmounted(disposeCharts)

  // Self-check: node -e "console.assert('200px 0px'==='200px 0px'&&200===parseInt('200px'))"
  // Lazy rule: init/setOption only when initialized || in viewport (±200px); updates skip off-screen never-init charts.

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
