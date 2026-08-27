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
  /** 闭区间 YYYY-MM-DD；period 模式按此裁行，避免宽窗/脏缓存把区间外日子算进 KPI */
  startDate: string
  endDate: string
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
  const retiredSuffix = column.retired ? '（已下线）' : ''
  if (monitorKeyword) return `${monitorKeyword}${retiredSuffix}`
  const group = (column.group_name || '').trim()
  if (group) return `${group}${retiredSuffix}`
  const prompt = (column.prompt || '').trim()
  if (prompt) {
    const base = prompt.length > 12 ? `${prompt.slice(0, 12)}…` : prompt
    return `${base}${retiredSuffix}`
  }
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

/** 闭区间枚举 YYYY-MM-DD；过长则截断，避免年视图热力炸表 */
export function enumerateDateKeys(startDate: string, endDate: string, maxDays = 62): string[] {
  const start = (startDate || '').trim().slice(0, 10)
  const end = (endDate || '').trim().slice(0, 10)
  if (!/^\d{4}-\d{2}-\d{2}$/.test(start) || !/^\d{4}-\d{2}-\d{2}$/.test(end) || start > end) {
    return []
  }
  const out: string[] = []
  const cursor = new Date(`${start}T00:00:00`)
  const last = new Date(`${end}T00:00:00`)
  while (cursor <= last && out.length < maxDays) {
    const y = cursor.getFullYear()
    const m = String(cursor.getMonth() + 1).padStart(2, '0')
    const d = String(cursor.getDate()).padStart(2, '0')
    out.push(`${y}-${m}-${d}`)
    cursor.setDate(cursor.getDate() + 1)
  }
  return out
}

/** 热力 x 轴：有筛选区间则铺满，否则仅有样本日。渲染与点击必须共用，否则 xIndex 会错位。 */
export function matrixHeatDayKeys(
  rows: RankingMatrixRow[],
  range?: { startDate?: string; endDate?: string },
) {
  const dataDays = matrixDayKeys(rows).map(key => key.slice(0, 10))
  const ranged = enumerateDateKeys(range?.startDate || '', range?.endDate || '')
  return ranged.length ? ranged : dataDays
}

function platformCodeFamily(code: string) {
  return code.replace(/_mobile$/i, '').trim().toLowerCase()
}

/** 2026-07-28 - 热力按词组平台裁列 - 未配置该平台的词不展示 */
export function columnVisibleOnPlatform(column: RankingMatrixColumn, platform: string) {
  const plats = (column.platforms || []).map(item => String(item || '').trim()).filter(Boolean)
  if (!plats.length) return true
  const target = String(platform || '').trim()
  if (!target) return true
  if (plats.includes(target)) return true
  const family = platformCodeFamily(target)
  return plats.some(code => platformCodeFamily(code) === family)
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
  const inRange = dayKeys.filter(key => {
    const day = key.slice(0, 10)
    return (!start || day >= start) && (!end || day <= end)
  })
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
      startDate: start,
      endDate: end,
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
    startDate: start,
    endDate: end,
  }
}

function rowsInRankScope(rows: RankingMatrixRow[], scope: MatrixRankScope) {
  const sorted = sortMatrixRowsAsc(rows)
  if (scope.mode === 'day' && scope.dayKey) {
    return sorted.filter(row => rowDayKey(row).slice(0, 10) === scope.dayKey.slice(0, 10))
  }
  const start = (scope.startDate || '').trim()
  const end = (scope.endDate || '').trim()
  if (!start && !end) return sorted
  return sorted.filter(row => {
    const day = rowDayKey(row).slice(0, 10)
    if (!day) return false
    if (start && day < start) return false
    if (end && day > end) return false
    return true
  })
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

function cellMonitoringSnapshots(cell: RankingMatrixCell | undefined): Array<Pick<RankingMatrixCell, 'mention_position' | 'brand_mentioned'>> {
  if (!cell) return []
  if (cell.snapshots?.length) {
    return cell.snapshots.map(snapshot => ({
      mention_position: snapshot.mention_position,
      brand_mentioned: snapshot.brand_mentioned,
    }))
  }
  return [{
    mention_position: cell.mention_position,
    brand_mentioned: cell.brand_mentioned,
  }]
}

/** 单格内每次监测是否进 Top3（有 snapshots 按轮次，否则按当日聚合 1 次）。 */
function countTop3SessionsInCell(cell: RankingMatrixCell | undefined) {
  return cellMonitoringSnapshots(cell).filter(
    snapshot => rankCountsAsTopThree(snapshot.mention_position),
  ).length
}

function countTop3SessionsInSlice(slice: MatrixPlatformSlice, scope: MatrixRankScope) {
  let total = 0
  for (const row of rowsInRankScope(slice.rows, scope)) {
    for (const column of slice.columns) {
      total += countTop3SessionsInCell(resolveColumnCell(row, column))
    }
  }
  return total
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

/** 与监测页「提及率」同口径：区间内被提及的监测次数 / 总监测次数。 */
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

export function rowMatchesColumn(row: RankingMatrixRow, column: RankingMatrixColumn) {
  const prompt = (column.prompt || '').trim()
  const monitorKeyword = (column.monitor_keyword || '').trim()
  const groupName = (column.group_name || '').trim()
  // 先认格子 key：有该监测词样本即可（含未提及 / 无位次）
  if (prompt && row.cells[prompt]) return true
  if (monitorKeyword && row.cells[monitorKeyword]) return true
  const rowGroup = (row.keyword_group || '').trim()
  if (!rowGroup) return false
  // 2026-07-31 - 「家用新风…」.includes(「新风…」) 误匹配，短词热力全变 — 且点不开
  // 已弃用双向 includes；词组行只允许精确等于 prompt / monitor_keyword / group_name
  if (prompt && rowGroup === prompt) return true
  if (monitorKeyword && rowGroup === monitorKeyword) return true
  if (groupName && rowGroup === groupName) return true
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
  const targetDay = (dayKey || matrixDayKeys(sorted).at(-1) || '').slice(0, 10)
  const pool = targetDay
    ? sorted.filter(row => rowDayKey(row).slice(0, 10) === targetDay)
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
  const snapCell = (ranks: Array<number | null>): RankingMatrixCell => ({
    subtask_id: 's',
    mention_position: ranks.length ? ranks.reduce((a, b) => a! + (b || 0), 0)! / ranks.filter(r => r != null).length : null,
    brand_mentioned: ranks.some(r => r != null),
    status: 'completed',
    page_screenshot: null,
    sentiment: null,
    updated_at: null,
    snapshots: ranks.map((rank, index) => ({
      subtask_id: `s-${index}`,
      mention_position: rank,
      brand_mentioned: rank != null,
      updated_at: null,
      status: 'completed',
      page_screenshot: null,
      sentiment: null,
    })),
  })
  const kpiSlice: MatrixPlatformSlice = {
    platform: 'doubao',
    columns: [{ prompt: 'p1', group_name: null, monitor_keyword: null }],
    rows: [{
      task_id: 't1',
      platform: 'doubao',
      day_key: '2026-06-01',
      schedule_window_key: '2026-06-01',
      schedule_label: '06-01',
      snapshot_at: '2026-06-01',
      cells: { p1: snapCell([1, 2, 8]) },
    }],
  }
  console.assert(matrixPlatformKpi(kpiSlice, buildMatrixRankScope(kpiSlice.rows, '2026-06-01', '2026-06-01')).top3 === 2)
  // 2026-07-28 - 热力铺满轴后点击 xIndex 错位 - 断言区间轴与稀疏轴不同，且 index0=区间首日
  const heatDays = matrixHeatDayKeys(kpiSlice.rows, { startDate: '2026-06-01', endDate: '2026-06-03' })
  console.assert(heatDays.length === 3 && heatDays[0] === '2026-06-01')
  console.assert(matrixDayKeys(kpiSlice.rows).length === 1)
  console.assert(matrixHeatDayKeys(kpiSlice.rows)[0] === '2026-06-01')
  const heatOpt = buildMatrixHeatOption(kpiSlice, { startDate: '2026-06-01', endDate: '2026-06-03' })
  const heatData = (heatOpt.series as Array<{ data: MatrixHeatDataItem[] }>)[0]?.data || []
  console.assert(heatData.length === 3 && heatData[0]?.dayKey === '2026-06-01' && heatData[0]?.prompt === 'p1')
  console.assert(heatData[0]?.value[2] > 0)
  console.assert(heatData[1]?.value[2] === -1)
  // 2026-07-31 - 嵌套词名 includes 误匹配：短词不得落到「家用短词」行上
  {
    const nestedCol = { prompt: '新风系统品牌推荐', group_name: null, monitor_keyword: '新风系统品牌推荐' }
    const homeCol = { prompt: '家用新风系统品牌推荐', group_name: null, monitor_keyword: '家用新风系统品牌推荐' }
    const cell = (mp: number | null): RankingMatrixCell => ({
      subtask_id: 'x',
      mention_position: mp,
      status: 'completed',
      page_screenshot: null,
      sentiment: null,
      updated_at: null,
    })
    const nestedRows: RankingMatrixRow[] = [
      {
        task_id: 't1',
        platform: 'doubao',
        day_key: '2026-07-27',
        schedule_window_key: '2026-07-27',
        schedule_label: '07-27',
        snapshot_at: '2026-07-27',
        keyword_group: '新风系统品牌推荐',
        cells: { 新风系统品牌推荐: cell(2.7) },
      },
      {
        task_id: 't2',
        platform: 'doubao',
        day_key: '2026-07-27',
        schedule_window_key: '2026-07-27',
        schedule_label: '07-27',
        snapshot_at: '2026-07-27',
        keyword_group: '家用新风系统品牌推荐',
        cells: { 家用新风系统品牌推荐: cell(1.7) },
      },
    ]
    console.assert(resolveColumnRank(nestedRows, nestedCol, '2026-07-27') === 2.7)
    console.assert(resolveColumnRank(nestedRows, homeCol, '2026-07-27') === 1.7)
    console.assert(!!resolveColumnCell(resolveColumnRow(nestedRows, nestedCol, '2026-07-27'), nestedCol))
  }
  const heatAxis = (heatOpt.xAxis as { data?: string[]; axisLabel?: { interval?: number } }).data || []
  console.assert(heatAxis.length === 3 && heatAxis[0] === '06-01' && heatAxis[1] === '06-02' && heatAxis[2] === '06-03')
  console.assert((heatOpt.xAxis as { axisLabel?: { interval?: number } }).axisLabel?.interval === 0)
  const periodKpis = matrixScopedPeriodKpis(
    kpiSlice,
    buildMatrixRankScope(kpiSlice.rows, '2026-06-01', '2026-06-01'),
  )
  console.assert(periodKpis.top3Rate === 66.7)
  console.assert(periodKpis.mentionRate === 100)
  console.assert(periodKpis.avgRank === 3.7)
  console.assert(periodKpis.sampleCount === 3)
  console.assert(periodKpis.latestDay === '2026-06-01')
  // period 必须按 start/end 裁行：宽窗矩阵里多一天不得计入近 1 日 KPI
  const wideRows: RankingMatrixRow[] = [
    ...kpiSlice.rows,
    {
      task_id: 't2',
      platform: 'doubao',
      day_key: '2026-06-10',
      schedule_window_key: '2026-06-10',
      schedule_label: '06-10',
      snapshot_at: '2026-06-10',
      cells: { p1: snapCell([1, 1, 1]) },
    },
  ]
  const clipped = matrixScopedPeriodKpis(
    { columns: kpiSlice.columns, rows: wideRows },
    buildMatrixRankScope(wideRows, '2026-06-01', '2026-06-01'),
  )
  console.assert(clipped.sampleCount === 3)
  console.assert(clipped.latestDay === '2026-06-01')
}

export function sliceMatrixByPlatform(matrix: RankingMatrix, platform: string): MatrixPlatformSlice {
  const rows = sortMatrixRowsAsc(
    matrix.rows.filter(row => (matrix.all_platforms ? row.platform === platform : true)),
  )
  const columns = matrix.columns.filter(column => columnVisibleOnPlatform(column, platform))
  return {
    columns,
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
    top3: countTop3SessionsInSlice(slice, scope),
    none: ranks.filter(rank => rank == null).length,
    avg: valid.length
      ? (valid.reduce((sum, rank) => sum + rank, 0) / valid.length).toFixed(1)
      : '—',
  }
}

/** 区间 KPI：成功样本分母；提及/Top3/均排与日表、monitor_sample_metrics 同向。 */
export type MatrixScopedPeriodKpis = {
  latestDay: string
  dayCount: number
  sampleCount: number
  mentionedCount: number
  avgRank: number | null
  mentionRate: number | null
  top3Rate: number | null
  scopeLabel: string
}

export function matrixScopedPeriodKpis(
  matrix: Pick<RankingMatrix, 'columns' | 'rows'>,
  scope: MatrixRankScope,
): MatrixScopedPeriodKpis {
  let sampleCount = 0
  let mentionedCount = 0
  let top3Count = 0
  let rankSum = 0
  const days = new Set<string>()

  for (const row of rowsInRankScope(matrix.rows, scope)) {
    const day = rowDayKey(row)
    if (day) days.add(day.slice(0, 10))
    for (const column of matrix.columns) {
      const cell = resolveColumnCell(row, column)
      if (!cell) continue
      if (cell.snapshots?.length) {
        for (const snap of cell.snapshots) {
          sampleCount += 1
          const rank = snap.mention_position
          if (rank == null || !Number.isFinite(Number(rank))) continue
          mentionedCount += 1
          rankSum += Number(rank)
          if (rankCountsAsTopThree(rank)) top3Count += 1
        }
        continue
      }
      const n = Math.max(0, Number(cell.sample_count) || 0)
      if (n <= 0) continue
      sampleCount += n
      // ponytail: 无 snapshots 仅单样本格按聚合位次计；多样本不臆造拆分
      if (n === 1 && cell.mention_position != null && Number.isFinite(Number(cell.mention_position))) {
        mentionedCount += 1
        rankSum += Number(cell.mention_position)
        if (rankCountsAsTopThree(cell.mention_position)) top3Count += 1
      }
    }
  }

  const dayKeys = [...days].sort()
  return {
    latestDay: dayKeys.at(-1) || '',
    dayCount: dayKeys.length,
    sampleCount,
    mentionedCount,
    avgRank: mentionedCount ? Math.round((rankSum / mentionedCount) * 10) / 10 : null,
    mentionRate: sampleCount ? Math.round((mentionedCount / sampleCount) * 1000) / 10 : null,
    top3Rate: sampleCount ? Math.round((top3Count / sampleCount) * 1000) / 10 : null,
    scopeLabel: scope.label,
  }
}

/** Top3 露出率：位次∈[1,3] 的监测次数 / 成功样本次数（与日表 top3_count/completed 同向）。 */
export function matrixScopedTop3Rate(
  matrix: Pick<RankingMatrix, 'columns' | 'rows'>,
  scope: MatrixRankScope,
): number | null {
  return matrixScopedPeriodKpis(matrix, scope).top3Rate
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
const HEAT_ROW_PITCH = 28
// 2026-07-30 - 热力横轴全量日期+旋转 - 略加底边留给 axisLabel
const HEAT_CHART_PAD = 88
const HEAT_CHART_MIN = 360

export function matrixBarChartHeight(itemCount: number) {
  const count = Math.max(itemCount, 1)
  // 不封顶：词多时由 .matrix-chart-wrap 纵向滚动，保证 35 词都能展开看到
  return Math.max(BAR_CHART_MIN, count * BAR_ROW_PITCH + BAR_CHART_PAD)
}

/** 热力图 Y 轴是监测词，高度必须按词数算；超出由外层 wrap 滚动，避免把词挤没。 */
export function matrixHeatChartHeight(keywordCount: number) {
  const count = Math.max(keywordCount, 1)
  return Math.max(HEAT_CHART_MIN, count * HEAT_ROW_PITCH + HEAT_CHART_PAD)
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
      // ponytail: axis 悬停默认会 triggerEmphasis；ECharts 下 label 易在 emphasis 态消失
      axisPointer: { type: 'shadow', triggerEmphasis: false },
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
      // ponytail: ECharts bar/heatmap 悬停进 emphasis 后常丢掉自定义 label（含 formatter），直接禁用
      emphasis: { disabled: true },
    }],
    },
  }
}

/** 热力点：value 供 ECharts，dayKey/prompt 供点击开抽屉（勿再靠 xIndex 反查稀疏轴） */
export type MatrixHeatDataItem = {
  value: [number, number, number]
  dayKey: string
  prompt: string
}

export function heatPointRank(data: MatrixHeatDataItem | [number, number, number] | undefined) {
  if (!data) return -1
  if (Array.isArray(data)) return data[2]
  return data.value?.[2] ?? -1
}

/** 热力横轴日期：只用 dayKey，去掉后端「N次均值」后缀；轴上用 MM-DD 减挤。 */
function heatAxisDateLabel(dayKey: string): string {
  const iso = String(dayKey || '').slice(0, 10)
  if (/^\d{4}-\d{2}-\d{2}$/.test(iso)) return iso.slice(5)
  return iso || '—'
}

function heatTooltipDateLabel(dayKey: string): string {
  const iso = String(dayKey || '').slice(0, 10)
  return /^\d{4}-\d{2}-\d{2}$/.test(iso) ? iso : (iso || '—')
}

export function buildMatrixHeatOption(
  slice: MatrixPlatformSlice,
  range?: { startDate?: string; endDate?: string },
) {
  // 2026-07-28 - 切「月」无体感 - 按筛选区间铺满日期轴，无样本日显示 —
  // 2026-07-28 - 悬停未提及但点击开出别日排名 - 点击须用同一 matrixHeatDayKeys，勿再用稀疏 matrixDayKeys
  const dayKeys = matrixHeatDayKeys(slice.rows, range)
  // 2026-07-30 - 热力横轴「3次均值」挤掉隔日标签 - 轴只用 MM-DD、interval:0、按天数旋转字号
  const axisDates = dayKeys.map(heatAxisDateLabel)
  const tipDates = dayKeys.map(heatTooltipDateLabel)
  const dayCount = dayKeys.length
  const axisRotate = dayCount > 7 ? 48 : dayCount > 4 ? 36 : 0
  const axisFontSize = dayCount > 10 ? 10 : dayCount > 6 ? 11 : 12
  const keywords = slice.columns.map(labelMatrixPrompt)
  const data: MatrixHeatDataItem[] = []
  dayKeys.forEach((dayKey, xIndex) => {
    slice.columns.forEach((column, yIndex) => {
      const value = resolveColumnRank(slice.rows, column, dayKey)
      data.push({
        value: [xIndex, yIndex, value == null ? -1 : value],
        dayKey,
        prompt: column.prompt,
      })
    })
  })

  return {
    grid: {
      left: 12,
      right: 48,
      top: 12,
      bottom: axisRotate ? 8 : 12,
      containLabel: true,
    },
    tooltip: {
      backgroundColor: 'rgba(21,48,82,.92)',
      borderWidth: 0,
      textStyle: { color: '#fff', fontSize: 12 },
      formatter: (params: { data: MatrixHeatDataItem }) => {
        const [xIndex, yIndex, value] = params.data.value
        return `<b>${keywords[yIndex] || '—'}</b><br/>${tipDates[xIndex] || '—'} · ${value < 0 ? '未提及' : formatRank(value)}`
      },
    },
    xAxis: {
      type: 'category',
      data: axisDates,
      axisLine: { lineStyle: { color: '#e8f0f8' } },
      axisTick: { show: false },
      axisLabel: {
        show: true,
        interval: 0,
        hideOverlap: false,
        rotate: axisRotate,
        color: '#58708f',
        fontSize: axisFontSize,
        fontWeight: 700,
        margin: axisRotate ? 14 : 10,
      },
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
        formatter: (params: { data: MatrixHeatDataItem }) => (
          heatPointRank(params.data) < 0 ? '—' : formatRank(heatPointRank(params.data))
        ),
        fontSize: 12,
        fontWeight: 800,
        color: (params: { data: MatrixHeatDataItem }) => {
          const value = heatPointRank(params.data)
          if (value < 0) return '#8aa0ba'
          if (value === 1) return '#fff'
          if (value <= 3) return '#0a5c42'
          return '#9a6200'
        },
      },
      itemStyle: { borderRadius: 8, borderColor: '#fff', borderWidth: 3 },
      // ponytail: 热力悬停 emphasis 会清掉格子数字；禁用后 tooltip 仍可用
      emphasis: { disabled: true },
    }],
  }
}

export function matrixChartHeight(chartType: MatrixChartType, slice: MatrixPlatformSlice) {
  if (chartType === 'bar') {
    return matrixBarChartHeight(slice.columns.length)
  }
  return matrixHeatChartHeight(slice.columns.length)
}
