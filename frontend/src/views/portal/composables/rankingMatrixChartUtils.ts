import type { EchartsRuntime } from '../../../utils/echartsLoader'
import type {
  RankingMatrix,
  RankingMatrixCell,
  RankingMatrixColumn,
  RankingMatrixRow,
} from '../../../services/monitor'
import { formatRank } from '../portalUtils'

export type MatrixChartType = 'bar' | 'heat' | 'table'
export type MatrixLayoutMode = 'single' | 'dual' | 'multi'
export type MatrixRankMode = 'day' | 'period'

export type MatrixRankScope = {
  mode: MatrixRankMode
  dayKey: string
  dayCount: number
  label: string
}

export type MatrixPlatformSlice = {
  columns: RankingMatrixColumn[]
  rows: RankingMatrixRow[]
  platform: string
}

export type MatrixKeywordDetailRow = {
  prompt: string
  label: string
  rank: number | null
  rankText: string
  deltaText: string
  deltaCls: 'delta-up' | 'delta-down' | 'delta-flat'
  pillCls: 'top1' | 'top3' | 'mid' | 'none'
  row: RankingMatrixRow | null
  cell: RankingMatrixCell | undefined
}

export function labelMatrixPrompt(column: RankingMatrixColumn) {
  const monitorKeyword = (column.monitor_keyword || '').trim()
  if (monitorKeyword) return monitorKeyword
  const group = (column.group_name || '').trim()
  if (group) return group
  const prompt = (column.prompt || '').trim()
  if (prompt) return prompt.length > 12 ? `${prompt.slice(0, 12)}…` : prompt
  return '—'
}

export function sortMatrixRowsAsc(rows: RankingMatrixRow[]) {
  return [...rows].sort((left, right) => (
    (left.day_key || left.schedule_window_key || left.snapshot_at || '').localeCompare(
      right.day_key || right.schedule_window_key || right.snapshot_at || '',
    )
  ))
}

function rowDayKey(row: RankingMatrixRow) {
  return (row.day_key || row.schedule_window_key || row.snapshot_at || '').trim()
}

export function matrixDayKeys(rows: RankingMatrixRow[]) {
  return [...new Set(rows.map(rowDayKey).filter(Boolean))].sort()
}

function averageRankValues(values: number[]) {
  if (!values.length) return null
  const total = values.reduce((sum, value) => sum + value, 0)
  return Math.round((total / values.length) * 10) / 10
}

/** 与 tooltip「约第 N 位」一致：区间/当日均值四舍五入后在 Top3 即计为进前三。 */
export function rankCountsAsTopThree(rank: number | null | undefined) {
  if (rank == null || !Number.isFinite(rank)) return false
  const rounded = Math.round(rank)
  return rounded >= 1 && rounded <= 3
}

/** 单日 = 当日排名；区间 = 所选日期范围内按天均值再汇总为区间均值。 */
export function buildMatrixRankScope(
  rows: RankingMatrixRow[],
  startDate: string,
  endDate: string,
): MatrixRankScope {
  const start = (startDate || '').trim()
  const end = (endDate || start).trim()
  const dayKeys = matrixDayKeys(rows)
  const inRange = dayKeys.filter(key => (!start || key >= start) && (!end || key <= end))
  const scopedDays = inRange.length ? inRange : dayKeys

  if (start && start === end) {
    const dayKey = scopedDays.includes(start)
      ? start
      : (scopedDays.at(-1) || start)
    return {
      mode: 'day',
      dayKey,
      dayCount: dayKey ? 1 : 0,
      label: dayKey || start,
    }
  }

  const label = start && end
    ? `${start.slice(5)} ~ ${end.slice(5)}`
    : `${scopedDays.length}天`
  return {
    mode: 'period',
    dayKey: '',
    dayCount: scopedDays.length,
    label,
  }
}

function rowsInRankScope(rows: RankingMatrixRow[], scope: MatrixRankScope) {
  const sorted = sortMatrixRowsAsc(rows)
  if (scope.mode === 'day' && scope.dayKey) {
    return sorted.filter(row => rowDayKey(row) === scope.dayKey)
  }
  return sorted
}

function ranksForColumnInScope(
  rows: RankingMatrixRow[],
  column: RankingMatrixColumn,
  scope: MatrixRankScope,
) {
  const ranks: number[] = []
  for (const row of rowsInRankScope(rows, scope)) {
    const rank = resolveColumnCell(row, column)?.mention_position
    if (rank != null) ranks.push(Number(rank))
  }
  return ranks
}

export type MatrixMentionStats = {
  mentioned: number
  total: number
  rate: number | null
}

function mentionStatsFromCell(cell: RankingMatrixCell | undefined): { mentioned: number; total: number } {
  if (!cell) return { mentioned: 0, total: 0 }
  const total = Math.max(1, cell.sample_count ?? 1)
  const mentioned = cell.rank_sample_count ?? (
    cell.brand_mentioned || cell.mention_position != null ? total : 0
  )
  return { mentioned: Math.min(mentioned, total), total }
}

/** 与监测页「露出率」同口径：区间内被提及的监测次数 / 总监测次数。 */
export function resolveScopedColumnMentionStats(
  rows: RankingMatrixRow[],
  column: RankingMatrixColumn,
  scope: MatrixRankScope,
): MatrixMentionStats {
  let mentioned = 0
  let total = 0
  for (const row of rowsInRankScope(rows, scope)) {
    const cell = resolveColumnCell(row, column)
    if (!cell) continue
    const stats = mentionStatsFromCell(cell)
    mentioned += stats.mentioned
    total += stats.total
  }
  if (!total) return { mentioned: 0, total: 0, rate: null }
  return {
    mentioned,
    total,
    rate: Math.round(mentioned / total * 1000) / 10,
  }
}

export function resolveScopedColumnRank(
  rows: RankingMatrixRow[],
  column: RankingMatrixColumn,
  scope: MatrixRankScope,
) {
  if (scope.mode === 'day') {
    return resolveColumnCell(resolveColumnRow(rows, column, scope.dayKey), column)?.mention_position ?? null
  }
  return averageRankValues(ranksForColumnInScope(rows, column, scope))
}

export function resolveScopedColumnRow(
  rows: RankingMatrixRow[],
  column: RankingMatrixColumn,
  scope: MatrixRankScope,
) {
  if (scope.mode === 'day') {
    return resolveColumnRow(rows, column, scope.dayKey)
  }
  return resolveColumnRow(rows, column, matrixDayKeys(rows).at(-1))
}

function columnGroupLabels(column: RankingMatrixColumn) {
  const labels = new Set<string>()
  for (const text of [column.monitor_keyword, column.group_name, column.prompt]) {
    const token = (text || '').trim()
    if (token) labels.add(token)
  }
  return labels
}

export function rowMatchesColumn(row: RankingMatrixRow, column: RankingMatrixColumn) {
  const rowGroup = (row.keyword_group || '').trim()
  const labels = columnGroupLabels(column)
  if (rowGroup) {
    if (labels.has(rowGroup)) return true
    for (const label of labels) {
      if (rowGroup.includes(label) || label.includes(rowGroup)) return true
    }
  }
  const prompt = (column.prompt || '').trim()
  const monitorKeyword = (column.monitor_keyword || '').trim()
  if (prompt && row.cells[prompt]) return true
  if (monitorKeyword && row.cells[monitorKeyword]) return true
  return false
}

export function resolveColumnCell(
  row: RankingMatrixRow | null | undefined,
  column: RankingMatrixColumn,
) {
  if (!row) return undefined
  for (const key of [column.prompt, column.monitor_keyword]) {
    const token = (key || '').trim()
    if (token && row.cells[token]) return row.cells[token]
  }
  return undefined
}

export function resolveColumnRow(
  rows: RankingMatrixRow[],
  column: RankingMatrixColumn,
  dayKey?: string,
) {
  const sorted = sortMatrixRowsAsc(rows)
  const targetDay = dayKey || matrixDayKeys(sorted).at(-1) || ''
  const pool = targetDay
    ? sorted.filter(row => rowDayKey(row) === targetDay)
    : sorted
  if (!pool.length) return null

  const matched = pool.filter(row => rowMatchesColumn(row, column))
  if (matched.length) return matched[matched.length - 1]

  const prompt = (column.prompt || '').trim()
  if (prompt) {
    const byPrompt = pool.filter(row => row.cells[prompt])
    if (byPrompt.length) return byPrompt[byPrompt.length - 1]
  }
  return null
}

export function resolveColumnRank(
  rows: RankingMatrixRow[],
  column: RankingMatrixColumn,
  dayKey?: string,
) {
  return resolveColumnCell(resolveColumnRow(rows, column, dayKey), column)?.mention_position ?? null
}

/** ponytail: 手测 rank scope 算法，改逻辑后可在 devtools 调用 */
export function selfCheckMatrixRankScope() {
  const cell = (mention_position: number): RankingMatrixCell => ({
    subtask_id: 'x',
    mention_position,
    status: 'completed',
    page_screenshot: null,
    sentiment: null,
    updated_at: null,
  })
  const rows: RankingMatrixRow[] = [
    {
      task_id: 't1',
      platform: 'doubao',
      day_key: '2026-06-01',
      schedule_window_key: '2026-06-01',
      schedule_label: '06-01',
      snapshot_at: '2026-06-01',
      cells: {
        p1: cell(4),
      },
    },
    {
      task_id: 't1',
      platform: 'doubao',
      day_key: '2026-06-02',
      schedule_window_key: '2026-06-02',
      schedule_label: '06-02',
      snapshot_at: '2026-06-02',
      cells: {
        p1: cell(2),
      },
    },
  ]
  const column: RankingMatrixColumn = { prompt: 'p1', group_name: null, monitor_keyword: null }
  const dayScope = buildMatrixRankScope(rows, '2026-06-02', '2026-06-02')
  const periodScope = buildMatrixRankScope(rows, '2026-06-01', '2026-06-02')
  console.assert(dayScope.mode === 'day')
  console.assert(resolveScopedColumnRank(rows, column, dayScope) === 2)
  console.assert(periodScope.mode === 'period')
  console.assert(resolveScopedColumnRank(rows, column, periodScope) === 3)
  console.assert(computeMatrixBarAxisMax([{ rank: 9 }, { rank: 10 }]) === 10)
  console.assert(computeMatrixBarAxisMax([{ rank: 12.5 }]) === 13)
  const mentionCell = (mentioned: boolean, sampleCount = 1): RankingMatrixCell => ({
    subtask_id: 'x',
    mention_position: mentioned ? 3 : null,
    brand_mentioned: mentioned,
    status: 'completed',
    page_screenshot: null,
    sentiment: null,
    updated_at: null,
    sample_count: sampleCount,
    rank_sample_count: mentioned ? sampleCount : 0,
  })
  const mentionColumn: RankingMatrixColumn = { prompt: 'p1', group_name: null, monitor_keyword: null }
  const mentionRows: RankingMatrixRow[] = [
    {
      task_id: 't1',
      platform: 'doubao',
      day_key: '2026-06-01',
      schedule_window_key: '2026-06-01',
      schedule_label: '06-01',
      snapshot_at: '2026-06-01',
      cells: { p1: mentionCell(true, 2) },
    },
    {
      task_id: 't1',
      platform: 'doubao',
      day_key: '2026-06-02',
      schedule_window_key: '2026-06-02',
      schedule_label: '06-02',
      snapshot_at: '2026-06-02',
      cells: { p1: mentionCell(false, 2) },
    },
  ]
  const mentionScope = buildMatrixRankScope(mentionRows, '2026-06-01', '2026-06-02')
  console.assert(resolveScopedColumnMentionStats(mentionRows, mentionColumn, mentionScope).rate === 50)
  console.assert(rankCountsAsTopThree(3.2) === true)
  console.assert(rankCountsAsTopThree(3.6) === false)
}

export function sliceMatrixByPlatform(matrix: RankingMatrix, platform: string): MatrixPlatformSlice {
  const rows = sortMatrixRowsAsc(
    matrix.rows.filter(row => (matrix.all_platforms ? row.platform === platform : true)),
  )
  return {
    columns: matrix.columns,
    rows,
    platform,
  }
}

export function latestMatrixRow(rows: RankingMatrixRow[]) {
  return rows.length ? rows[rows.length - 1] : null
}

export function previousMatrixRow(rows: RankingMatrixRow[]) {
  return rows.length > 1 ? rows[rows.length - 2] : null
}

export function matrixPlatformKpi(slice: MatrixPlatformSlice, scope: MatrixRankScope) {
  if (!slice.columns.length || !slice.rows.length) return { top3: 0, avg: '—', none: 0 }
  const ranks = slice.columns.map(column => resolveScopedColumnRank(slice.rows, column, scope))
  const valid = ranks.filter((rank): rank is number => rank != null)
  return {
    top3: valid.filter(rank => rankCountsAsTopThree(rank)).length,
    none: ranks.filter(rank => rank == null).length,
    avg: valid.length
      ? (valid.reduce((sum, rank) => sum + rank, 0) / valid.length).toFixed(1)
      : '—',
  }
}

function rankPillClass(rank: number | null) {
  if (rank == null) return 'none' as const
  const rounded = Math.round(rank)
  if (rounded === 1) return 'top1' as const
  if (rounded >= 2 && rounded <= 3) return 'top3' as const
  return 'mid' as const
}

function rankDeltaText(rank: number | null, prevRank: number | null) {
  if (rank == null && prevRank == null) return { text: '—', cls: 'delta-flat' as const }
  if (rank == null && prevRank != null) return { text: '↓失榜', cls: 'delta-down' as const }
  if (rank != null && prevRank == null) return { text: '↑新上榜', cls: 'delta-up' as const }
  if (rank == null || prevRank == null) return { text: '—', cls: 'delta-flat' as const }
  const diff = prevRank - rank
  if (diff > 0) return { text: `↑${diff}`, cls: 'delta-up' as const }
  if (diff < 0) return { text: `↓${Math.abs(diff)}`, cls: 'delta-down' as const }
  return { text: '—', cls: 'delta-flat' as const }
}

export function buildKeywordDetailRows(
  slice: MatrixPlatformSlice,
  formatRank: (rank: number | null | undefined) => string,
  scope: MatrixRankScope,
): MatrixKeywordDetailRow[] {
  const dayKeys = matrixDayKeys(slice.rows)
  const prevDay = scope.mode === 'day' && scope.dayKey
    ? (dayKeys.filter(key => key < scope.dayKey).at(-1) || '')
    : ''
  return slice.columns.map(column => {
    const row = resolveScopedColumnRow(slice.rows, column, scope)
    const rank = resolveScopedColumnRank(slice.rows, column, scope)
    const prevRow = prevDay ? resolveColumnRow(slice.rows, column, prevDay) : null
    const prevRank = prevRow ? resolveColumnCell(prevRow, column)?.mention_position ?? null : null
    const delta = scope.mode === 'day'
      ? rankDeltaText(rank, prevRank)
      : { text: '—', cls: 'delta-flat' as const }
    return {
      prompt: column.prompt,
      label: labelMatrixPrompt(column),
      rank,
      rankText: formatRank(rank),
      deltaText: delta.text,
      deltaCls: delta.cls,
      pillCls: rankPillClass(rank),
      row,
      cell: row ? resolveColumnCell(row, column) : undefined,
    }
  }).sort((left, right) => {
    if (left.rank == null && right.rank == null) return 0
    if (left.rank == null) return 1
    if (right.rank == null) return -1
    return left.rank - right.rank
  })
}

function rankBarStyle(
  rank: number | null | undefined,
  graphic: NonNullable<EchartsRuntime['graphic']>,
) {
  if (rank == null) return { color: '#dce5f0', labelColor: '#8aa0ba' }
  const rounded = Math.round(rank)
  if (rounded === 1) {
    return {
      color: new graphic.LinearGradient(0, 0, 1, 0, [
        { offset: 0, color: '#0a916d' },
        { offset: 1, color: '#14c78a' },
      ]),
      labelColor: '#0a5c42',
    }
  }
  if (rounded >= 2 && rounded <= 3) {
    return {
      color: new graphic.LinearGradient(0, 0, 1, 0, [
        { offset: 0, color: '#6dd4b0' },
        { offset: 1, color: '#a8e8cf' },
      ]),
      labelColor: '#0a5c42',
    }
  }
  return {
    color: new graphic.LinearGradient(0, 0, 1, 0, [
      { offset: 0, color: '#f0a830' },
      { offset: 1, color: '#ffd37a' },
    ]),
    labelColor: '#9a6200',
  }
}

const BAR_AXIS_MIN = 0.55 // ponytail: min=1 时 inverse 轴上 #1 柱宽为 0
const BAR_AXIS_FLOOR = 10

/** 横轴上限：随数据最大排名扩展，避免 #8+ 全部顶格等长。 */
export function computeMatrixBarAxisMax(items: Array<{ rank: number | null }>) {
  const ranks = items
    .map(item => item.rank)
    .filter((rank): rank is number => rank != null && rank > 0)
  const peak = ranks.length ? Math.max(...ranks) : BAR_AXIS_FLOOR
  return Math.max(BAR_AXIS_FLOOR, Math.ceil(peak))
}

function matrixBarAxisTicks(axisMax: number) {
  if (axisMax <= 6) {
    return Array.from({ length: axisMax }, (_, index) => index + 1)
  }
  const step = axisMax <= 12 ? 2 : Math.ceil(axisMax / 6)
  const ticks = new Set<number>([1, axisMax])
  for (let value = step; value < axisMax; value += step) ticks.add(value)
  return [...ticks].sort((left, right) => left - right)
}

function matrixBarRankTooltip(rank: number | null) {
  if (rank == null) return 'AI 回答中未提及品牌'
  if (Number.isInteger(rank)) return `AI 推荐列表约第 ${rank} 位`
  return `AI 推荐列表约第 ${rank} 位（多轮均值）`
}

function matrixBarMentionTooltip(stats: MatrixMentionStats) {
  if (stats.rate == null) return '品牌曝光率 —'
  return `品牌曝光率 ${stats.rate}%（${stats.mentioned}/${stats.total} 次监测提及）`
}

const BAR_ROW_PITCH = 44
const BAR_CHART_PAD = 80
const BAR_CHART_MIN = 420
const BAR_CHART_MAX = 640
const BAR_GRID_MIN_TOP = 18
const BAR_GRID_MIN_BOTTOM = 12
const BAR_AXIS_RESERVE = 24

export function matrixBarChartHeight(itemCount: number) {
  const count = Math.max(itemCount, 1)
  return Math.max(BAR_CHART_MIN, Math.min(BAR_CHART_MAX, count * BAR_ROW_PITCH + BAR_CHART_PAD))
}

export type MatrixBarLayoutHint = {
  chartHeight: number
  rowPitch: number
}

function matrixBarGridMargins(itemCount: number, chartHeight: number, rowPitch = BAR_ROW_PITCH) {
  const count = Math.max(itemCount, 1)
  const plotHeight = count * rowPitch
  const fixedBottom = BAR_GRID_MIN_BOTTOM + BAR_AXIS_RESERVE
  const budget = chartHeight - BAR_GRID_MIN_TOP - fixedBottom
  if (plotHeight >= budget) {
    return { top: BAR_GRID_MIN_TOP, bottom: fixedBottom }
  }
  const slack = budget - plotHeight
  return {
    top: BAR_GRID_MIN_TOP + slack / 2,
    bottom: fixedBottom + slack / 2,
  }
}

/** 右侧更高时：图表区略拉高、行距略增，条形块垂直居中 */
export function resolveMatrixBarLayoutHint(
  itemCount: number,
  railHeight: number,
  cardHeadHeight: number,
  wrapVerticalPad = 20,
): MatrixBarLayoutHint | undefined {
  const baseHeight = matrixBarChartHeight(itemCount)
  const railChartBudget = railHeight - cardHeadHeight - wrapVerticalPad
  if (railChartBudget <= baseHeight + 16) return undefined

  const chartHeight = Math.min(
    BAR_CHART_MAX,
    Math.round(baseHeight + (railChartBudget - baseHeight) * 0.55),
  )
  if (chartHeight <= baseHeight + 8) return undefined

  const count = Math.max(itemCount, 1)
  const plotBudget = chartHeight - BAR_GRID_MIN_TOP - BAR_GRID_MIN_BOTTOM - BAR_AXIS_RESERVE
  const rowPitch = Math.min(54, Math.max(BAR_ROW_PITCH, Math.floor(plotBudget / count)))

  return { chartHeight, rowPitch }
}

export function buildMatrixBarOption(
  slice: MatrixPlatformSlice,
  runtime: EchartsRuntime,
  scopeLabel: string,
  scope: MatrixRankScope,
  layoutHint?: MatrixBarLayoutHint,
) {
  const graphic = runtime.graphic!
  const items = slice.columns.map(column => {
    const row = resolveScopedColumnRow(slice.rows, column, scope)
    return {
      prompt: column.prompt,
      label: labelMatrixPrompt(column),
      rank: resolveScopedColumnRank(slice.rows, column, scope),
      row,
      column,
    }
  }).sort((left, right) => {
    if (left.rank == null && right.rank == null) return 0
    if (left.rank == null) return 1
    if (right.rank == null) return -1
    return left.rank - right.rank
  })

  const chartHeight = layoutHint?.chartHeight ?? matrixBarChartHeight(items.length)
  const rowPitch = layoutHint?.rowPitch ?? BAR_ROW_PITCH
  const grid = matrixBarGridMargins(items.length, chartHeight, rowPitch)
  const axisMax = computeMatrixBarAxisMax(items)
  const axisTicks = matrixBarAxisTicks(axisMax)

  return {
    height: chartHeight,
    option: {
      grid: {
        left: 12,
        right: 64,
        top: grid.top,
        bottom: grid.bottom + 8,
        containLabel: true,
      },
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(21,48,82,.92)',
      borderWidth: 0,
      textStyle: { color: '#fff', fontSize: 12 },
      formatter: (params: Array<{ dataIndex: number }>) => {
        const item = items[params[0]?.dataIndex ?? 0]
        if (!item) return ''
        const prefix = scope.mode === 'day'
          ? (scopeLabel || scope.dayKey || '当日')
          : `${scopeLabel || '区间'} 均值`
        const mention = matrixBarMentionTooltip(
          resolveScopedColumnMentionStats(slice.rows, item.column, scope),
        )
        return `<b>${item.label}</b><br/>${prefix}<br/>${matrixBarRankTooltip(item.rank)}<br/>${mention}`
      },
    },
    xAxis: {
      type: 'value',
      min: BAR_AXIS_MIN,
      max: axisMax,
      inverse: true,
      name: '推荐排名（→ 1 最佳）',
      nameLocation: 'middle',
      nameGap: 28,
      nameTextStyle: { color: '#8aa0ba', fontSize: 11, fontWeight: 600 },
      splitLine: { lineStyle: { type: 'dashed', color: '#e8f0f8' } },
      axisLabel: {
        formatter: (value: number) => {
          const rounded = Math.round(value)
          if (!axisTicks.includes(rounded)) return ''
          return String(rounded)
        },
        color: '#8aa0ba',
        fontSize: 11,
      },
      axisLine: { show: false },
      axisTick: { show: false },
    },
    yAxis: {
      type: 'category',
      data: items.map(item => item.label),
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: {
        color: '#153052',
        fontSize: 13,
        fontWeight: 700,
      },
    },
    series: [{
      type: 'bar',
      barWidth: 18,
      data: items.map(item => {
        const style = rankBarStyle(item.rank, graphic)
        const barValue = item.rank == null
          ? axisMax + 0.35
          : Math.min(item.rank, axisMax + 0.35)
        return {
          value: barValue,
          itemStyle: { color: style.color, borderRadius: [0, 8, 8, 0] },
          label: { color: style.labelColor },
          prompt: item.prompt,
          rank: item.rank,
          row: item.row,
        }
      }),
      showBackground: true,
      backgroundStyle: { color: 'rgba(232,240,248,.55)', borderRadius: [0, 8, 8, 0] },
      label: {
        show: true,
        position: 'right',
        fontWeight: 800,
        fontSize: 12,
        formatter: (params: { dataIndex: number }) => {
          const item = items[params.dataIndex]
          return item?.rank == null ? '—' : formatRank(item.rank)
        },
      },
    }],
    },
  }
}

export function buildMatrixHeatOption(slice: MatrixPlatformSlice) {
  const dayKeys = matrixDayKeys(slice.rows)
  const dates = dayKeys.map(dayKey => {
    const row = slice.rows.find(item => rowDayKey(item) === dayKey)
    return row?.schedule_label || dayKey || '—'
  })
  const keywords = slice.columns.map(labelMatrixPrompt)
  const data: Array<[number, number, number]> = []
  dayKeys.forEach((dayKey, xIndex) => {
    slice.columns.forEach((column, yIndex) => {
      const value = resolveColumnRank(slice.rows, column, dayKey)
      data.push([xIndex, yIndex, value == null ? -1 : value])
    })
  })

  return {
    grid: { left: 12, right: 48, top: 12, bottom: 12, containLabel: true },
    tooltip: {
      backgroundColor: 'rgba(21,48,82,.92)',
      borderWidth: 0,
      textStyle: { color: '#fff', fontSize: 12 },
      formatter: (params: { data: [number, number, number] }) => {
        const [xIndex, yIndex, value] = params.data
        return `<b>${keywords[yIndex] || '—'}</b><br/>${dates[xIndex] || '—'} · ${value < 0 ? '未提及' : formatRank(value)}`
      },
    },
    xAxis: {
      type: 'category',
      data: dates,
      axisLine: { lineStyle: { color: '#e8f0f8' } },
      axisTick: { show: false },
      axisLabel: { color: '#58708f', fontSize: 12, fontWeight: 700 },
    },
    yAxis: {
      type: 'category',
      data: keywords,
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: '#153052', fontSize: 12, fontWeight: 700 },
    },
    visualMap: {
      show: false,
      min: -1,
      max: 6,
      inRange: { color: ['#edf2f8', '#c8f5e2', '#6dd4b0', '#f5d78a', '#f0a830'] },
    },
    series: [{
      type: 'heatmap',
      data,
      label: {
        show: true,
        formatter: (params: { data: [number, number, number] }) => (
          params.data[2] < 0 ? '—' : formatRank(params.data[2])
        ),
        fontSize: 12,
        fontWeight: 800,
        color: (params: { data: [number, number, number] }) => {
          const value = params.data[2]
          if (value < 0) return '#8aa0ba'
          if (value === 1) return '#fff'
          if (value <= 3) return '#0a5c42'
          return '#9a6200'
        },
      },
      itemStyle: { borderRadius: 8, borderColor: '#fff', borderWidth: 3 },
    }],
  }
}

export function matrixChartHeight(chartType: MatrixChartType, slice: MatrixPlatformSlice) {
  const count = chartType === 'bar' ? slice.columns.length : slice.rows.length
  if (chartType === 'bar') {
    return matrixBarChartHeight(count)
  }
  return Math.max(BAR_CHART_MIN, Math.min(BAR_CHART_MAX, count * BAR_ROW_PITCH + BAR_CHART_PAD))
}
