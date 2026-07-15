import type { ECharts } from 'echarts/core'

/** 与后端 report_competitor_visuals 回落色板对齐（品牌蓝 + 按名哈希） */
export const BRAND_LINE_COLOR = '#0057D9'
export const ENTITY_LINE_COLORS = [
  '#F28E2B', '#009E73', '#C43C92', '#7C3AED', '#008C95',
  '#D55E00', '#0072B2', '#CC79A7', '#6B8E23', '#A65E2E',
]
export const MAX_TREND_ENTITIES = 8

export function shortScheduleLabel(label: unknown) {
  const text = String(label || '')
  const match = text.match(/(\d{4})-(\d{2})-(\d{2})\s+(\d{2}:\d{2})/)
  if (match) return `${match[2]}-${match[3]} ${match[4]}`
  return text.length > 14 ? `${text.slice(0, 12)}…` : text || '—'
}

export function rankToneClass(rank: unknown) {
  if (rank === null || rank === undefined || rank === '' || rank === '—') return ''
  const value = Number(rank)
  if (Number.isNaN(value)) return ''
  if (value <= 3) return 'is-top'
  if (value <= 5) return 'is-mid'
  return 'is-low'
}

function entityColor(name: string, brandName: string, index: number) {
  if (namesMatch(name, brandName)) return BRAND_LINE_COLOR
  return ENTITY_LINE_COLORS[index % ENTITY_LINE_COLORS.length]
}

export function renderEntityRankTrendChart(
  chart: ECharts,
  rows: Array<Record<string, unknown>>,
  brandName: string,
  trackedEntities: string[],
) {
  const labels = rows.map(row => shortScheduleLabel(row.schedule_label))
  const entities = trackedEntities.length
    ? trackedEntities
    : Object.keys((rows[0]?.entities as Record<string, unknown> | undefined) || {})

  const series = entities.slice(0, MAX_TREND_ENTITIES).map((name, index) => {
    const color = entityColor(name, brandName, index)
    return {
      name,
      type: 'line' as const,
      smooth: true,
      connectNulls: false,
      symbolSize: 7,
      lineStyle: { width: namesMatch(name, brandName) ? 3 : 2, color },
      itemStyle: { color },
      label: { show: true, formatter: (params: { value: [number, number] }) => (params.value[1] ?? '').toString() },
      data: rows.map(row => {
        const entitiesMap = (row.entities as Record<string, unknown> | undefined) || {}
        const value = entitiesMap[name]
        if (value == null && namesMatch(name, brandName)) return row.avg_rank == null ? null : Number(row.avg_rank)
        return value == null || value === '' ? null : Number(value)
      }),
    }
  })

  chart.setOption({
    tooltip: { trigger: 'axis' },
    legend: { top: 0, textStyle: { color: '#58708f', fontSize: 11 } },
    grid: { left: 48, right: 24, top: 36, bottom: 48 },
    xAxis: {
      type: 'category',
      data: labels,
      axisLabel: { color: '#58708f', rotate: labels.length > 6 ? 35 : 0 },
    },
    yAxis: {
      type: 'value',
      inverse: true,
      min: 1,
      axisLabel: { color: '#58708f' },
      splitLine: { lineStyle: { color: '#eef4fb' } },
    },
    series,
  }, true)
  chart.resize()
}

export function renderMentionRateBarChart(
  chart: ECharts,
  rows: Array<Record<string, unknown>>,
  brandName = '',
) {
  const sorted = [...rows].sort((a, b) => Number(b.mention_rate || 0) - Number(a.mention_rate || 0)).slice(0, 12)
  chart.setOption({
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: 100, right: 24, top: 16, bottom: 24 },
    xAxis: {
      type: 'value',
      max: 100,
      axisLabel: { formatter: '{value}%' },
      splitLine: { lineStyle: { color: '#eef4fb' } },
    },
    yAxis: {
      type: 'category',
      data: sorted.map(row => String(row.name || '—')),
      inverse: true,
      axisLabel: { width: 90, overflow: 'truncate' },
    },
    series: [{
      type: 'bar',
      data: sorted.map((row, index) => ({
        value: Number(row.mention_rate || 0),
        itemStyle: {
          color: entityColor(String(row.name || ''), brandName || String(sorted.find(r => r.is_brand)?.name || ''), index),
        },
      })),
      label: { show: true, position: 'right', formatter: '{c}%' },
    }],
  }, true)
  chart.resize()
}

function namesMatch(left: string, right: string) {
  const a = left.trim().toLowerCase().replace(/\s+/g, '')
  const b = right.trim().toLowerCase().replace(/\s+/g, '')
  if (!a || !b) return false
  if (a === b) return true
  const [shorter, longer] = a.length <= b.length ? [a, b] : [b, a]
  return shorter.length >= 3 && longer.includes(shorter)
}

export function splitNarrativeParagraphs(text: unknown): string[] {
  const raw = String(text || '').trim()
  if (!raw) return []
  const numbered = raw.split(/(?=\d+\.\s)/).map(item => item.trim()).filter(Boolean)
  if (numbered.length > 1) return numbered
  if ((raw.match(/；/g) || []).length >= 2) {
    return raw.split('；').map(item => {
      const cleaned = item.trim()
      return cleaned.endsWith('。') ? cleaned : `${cleaned}。`
    }).filter(Boolean)
  }
  return [raw]
}
