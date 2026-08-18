import { nextTick, onUnmounted, type Ref } from 'vue'
import type { ECharts } from 'echarts/core'
import type { SentimentKeywordItem } from '../services/analytics'
import { loadEchartsRuntime } from '../utils/echartsLoader'

type WordCloudPolarity = 'positive' | 'negative'

const POSITIVE_COLORS = ['#36cfc9', '#58ddb0', '#5b8ff9', '#49d8b7', '#73d13d', '#40a9ff']
const NEGATIVE_COLORS = ['#ff7875', '#ff9c6e', '#ffc069', '#ff6b7d', '#f759ab', '#ffa940']
// 2026-08-04 - 长中文短语 + 字号过大易叠字，收词量与字号区间（40）
const MAX_RENDER_WORDS = 40

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

function pickColor(polarity: WordCloudPolarity, seed: string) {
  const palette = polarity === 'positive' ? POSITIVE_COLORS : NEGATIVE_COLORS
  let hash = 0
  for (let i = 0; i < seed.length; i += 1) hash = (hash * 31 + seed.charCodeAt(i)) >>> 0
  return palette[hash % palette.length]
}

/** 长短语降权，避免占满画布挤掉短评。 */
function layoutValue(text: string, count: number) {
  const len = Math.max(1, text.replace(/\s/g, '').length)
  const penalty = Math.max(1, len / 6)
  return Math.max(1, Math.round((count * 10) / penalty))
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

    // 同频优先更短，利于排版
    const ranked = [...items].sort((a, b) => {
      if (b.count !== a.count) return b.count - a.count
      return a.text.length - b.text.length
    })

    const data = ranked.slice(0, MAX_RENDER_WORDS).map(item => ({
      name: item.text,
      value: layoutValue(item.text, item.count),
      rawCount: item.count,
      subtask_id: item.subtask_id,
      task_id: item.task_id,
      textStyle: {
        color: pickColor(polarity, item.text),
      },
    }))

    chart.setOption({
      tooltip: {
        show: true,
        formatter: (params: { name?: string; data?: { rawCount?: number; value?: number } }) => (
          `${params.name || ''}<br/>出现 ${params.data?.rawCount ?? params.data?.value ?? 0} 次 · 点击查看快照`
        ),
      },
      series: [{
        type: 'wordCloud',
        shape: 'circle',
        left: 'center',
        top: 'center',
        width: '90%',
        height: '90%',
        // 2026-08-04 - 缩小字号差、加大网格，减轻重叠与出界
        sizeRange: [13, 32],
        rotationRange: [0, 0],
        gridSize: 14,
        drawOutOfBound: false,
        layoutAnimation: false,
        textStyle: {
          fontFamily: 'PingFang SC, Microsoft YaHei, sans-serif',
          fontWeight: 600,
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
          count: Number(data?.rawCount || data?.value || data?.count || 0),
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
