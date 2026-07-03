import type { ECharts } from 'echarts/core'

export const ENTITY_LINE_COLORS = ['#ef4444', '#22c55e', '#3b82f6', '#f59e0b', '#8b5cf6']

export function shortScheduleLabel(label: unknown) {
  const text = String(label || '')
  const match = text.match(/(\d{4})-(\d{2})-(\d{2})\s+(\d{2}:\d{2})/)
  if (match) return `${match[2]}-${match[3]} ${match[4]}`
  return text.length > 14 ? `${text.slice(0, 12)}…` : text || '—'
}

export function rankToneClass(rank: unknown) {
  const value = Number(rank)
  if (Number.isNaN(value)) return ''
  if (value <= 3) return 'is-top'
  if (value <= 5) return 'is-mid'
  return 'is-low'
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

  const series = entities.slice(0, 5).map((name, index) => ({
    name,
    type: 'line' as const,
    smooth: true,
    connectNulls: false,
    symbolSize: 7,
    lineStyle: { width: namesMatch(name, brandName) ? 3 : 2, color: ENTITY_LINE_COLORS[index % ENTITY_LINE_COLORS.length] },
    itemStyle: { color: ENTITY_LINE_COLORS[index % ENTITY_LINE_COLORS.length] },
    label: { show: true, formatter: (params: { value: [number, number] }) => (params.value[1] ?? '').toString() },
    data: rows.map(row => {
      const entitiesMap = (row.entities as Record<string, unknown> | undefined) || {}
      const value = entitiesMap[name]
      if (value == null && namesMatch(name, brandName)) return row.avg_rank == null ? null : Number(row.avg_rank)
      return value == null || value === '' ? null : Number(value)
    }),
  }))

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
      data: sorted.map(row => ({
        value: Number(row.mention_rate || 0),
        itemStyle: {
          color: row.is_brand ? '#22c55e' : row.is_competitor ? '#3b82f6' : (
            Number(row.mention_rate || 0) >= 60 ? '#86efac'
              : Number(row.mention_rate || 0) >= 30 ? '#fde047' : '#fdba74'
          ),
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
  return a === b || a.includes(b) || b.includes(a)
}

export function splitNarrativeParagraphs(text: unknown): string[] {
  const raw = String(text || '').trim()
  if (!raw) return []
  const numbered = raw.split(/(?=\d+\.\s)/).map(item => item.trim()).filter(Boolean)
  if (numbered.length > 1) return numbered
  if ((raw.match(/；/g) || []).length >= 2) {
    return raw.split('；').map(item => {
      const cleaned = item.trim()
      if (!cleaned) return ''
      return /[。！？；]$/.test(cleaned) ? cleaned : `${cleaned}。`
    }).filter(Boolean)
  }
  const lines = raw.split(/\n+/).map(item => item.trim()).filter(Boolean)
  return lines.length ? lines : [raw]
}
