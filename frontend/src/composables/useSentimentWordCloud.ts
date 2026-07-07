import { nextTick, onUnmounted, type Ref } from 'vue'
import type { ECharts } from 'echarts/core'
import type { SentimentKeywordItem } from '../services/analytics'
import { loadEchartsRuntime } from '../utils/echartsLoader'

type WordCloudPolarity = 'positive' | 'negative'

const POSITIVE_COLORS = ['#36cfc9', '#58ddb0', '#5b8ff9', '#49d8b7', '#73d13d', '#40a9ff']
const NEGATIVE_COLORS = ['#ff7875', '#ff9c6e', '#ffc069', '#ff6b7d', '#f759ab', '#ffa940']
const MAX_RENDER_WORDS = 50

type EchartsRuntime = Awaited<ReturnType<typeof loadEchartsRuntime>>

let echartsRuntime: EchartsRuntime | null = null
let echartsRuntimePromise: Promise<EchartsRuntime> | null = null

async function ensureWordCloudRuntime(): Promise<EchartsRuntime> {
  if (echartsRuntime) return echartsRuntime
  if (!echartsRuntimePromise) {
    echartsRuntimePromise = loadEchartsRuntime('wordcloud').then(runtime => {
      echartsRuntime = runtime
      return runtime
    })
  }
  return echartsRuntimePromise
}

export function preloadSentimentWordCloudRuntime() {
  void ensureWordCloudRuntime()
}

function pickColor(polarity: WordCloudPolarity) {
  const palette = polarity === 'positive' ? POSITIVE_COLORS : NEGATIVE_COLORS
  return palette[Math.floor(Math.random() * palette.length)]
}

export function useSentimentWordCloud(
  chartRef: Ref<HTMLDivElement | null>,
  onWordClick?: (item: SentimentKeywordItem) => void,
) {
  let chartInstance: ECharts | null = null

  function getChart() {
    if (!chartRef.value || !echartsRuntime) return null
    const existing = echartsRuntime.getInstanceByDom(chartRef.value)
    if (existing) {
      chartInstance = existing
      return existing
    }
    chartInstance = echartsRuntime.init(chartRef.value)
    return chartInstance
  }

  async function render(items: SentimentKeywordItem[], polarity: WordCloudPolarity) {
    await ensureWordCloudRuntime()
    await nextTick()
    const chart = getChart()
    if (!chart) return

    if (!items.length) {
      chart.clear()
      return
    }

    const data = items.slice(0, MAX_RENDER_WORDS).map(item => ({
      name: item.text,
      value: item.count,
      subtask_id: item.subtask_id,
      task_id: item.task_id,
    }))

    chart.setOption({
      tooltip: {
        show: true,
        formatter: (params: { name?: string; value?: number }) => (
          `${params.name || ''}<br/>出现 ${params.value ?? 0} 次 · 点击查看快照`
        ),
      },
      series: [{
        type: 'wordCloud',
        shape: 'circle',
        left: 'center',
        top: 'center',
        width: '96%',
        height: '96%',
        sizeRange: [14, 54],
        rotationRange: [0, 0],
        gridSize: 10,
        drawOutOfBound: false,
        textStyle: {
          fontFamily: 'PingFang SC, Microsoft YaHei, sans-serif',
          fontWeight: 600,
          color: () => pickColor(polarity),
        },
        emphasis: {
          focus: 'self',
          textStyle: {
            shadowBlur: 8,
            shadowColor: polarity === 'positive' ? 'rgba(54,207,201,.45)' : 'rgba(255,107,125,.45)',
          },
        },
        data,
      }],
    }, { notMerge: true, lazyUpdate: true })

    chart.off('click')
    if (onWordClick) {
      chart.on('click', (params: unknown) => {
        const data = (params as { data?: Record<string, unknown> }).data
        const subtaskId = String(data?.subtask_id || '')
        if (!subtaskId) return
        onWordClick({
          text: String(data?.text || data?.name || ''),
          count: Number(data?.value || data?.count || 0),
          subtask_id: subtaskId,
          task_id: String(data?.task_id || ''),
        })
      })
    }
  }

  function resize() {
    chartInstance?.resize()
  }

  function dispose() {
    chartInstance?.dispose()
    chartInstance = null
  }

  onUnmounted(dispose)

  return { render, resize, dispose }
}
