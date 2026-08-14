import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { withRetry } from '../../../composables/useRetry'
import { notifyOperationError } from '../../../utils/requestError'
import { onMonitorRefresh } from '../../../utils/monitorRefresh'
import {
  customerDisplayPeriodLabel,
  customerDisplayCutoffDate,
  customerDisplayDateRange,
  monitorTaskBeforeToday,
  workspaceTrendDateRange,
  workspaceTrendPeriodLabel,
  type WorkspaceTrendPreset,
} from '../../../utils/customerMonitorDate'
import { useAuthStore } from '../../../stores/auth'
import {
  findKeywordGroupByFilter,
  findKeywordGroupBySelectValue,
  formatKeywordGroupLabel,
  formatKeywordGroupDetailHint,
  getBrandAsset,
  keywordGroupDisplayName,
  keywordGroupFilterValue,
  keywordGroupMonitorKeywords,
  keywordGroupSelectValue,
  type BrandAsset,
  type BrandCompetitor,
  type BrandKeywordGroup,
} from '../../../services/brand'
import {
  getMonitorSubtask,
  getMonitorSummary,
  getMonitorTaskDetail,
  getMonitorTasks,
  getRankingMatrix,
  type MonitorSubtask,
  type MonitorSummary,
  type MonitorTask,
  type MonitorTaskScheduleGroup,
  type RankingMatrix,
  type RankingMatrixCell,
  type RankingMatrixCellSnapshot,
  type RankingMatrixColumn,
  type RankingMatrixRow,
} from '../../../services/monitor'
import {
  monitorModeLabelMap,
  monitorStatusLabelMap,
  platformLabelMap,
  sentimentLabelMap,
} from '../portalMaps'
import { sortPlatformCodes } from '../platformOrder'
import { formatExposureLabel, formatRank, sanitizeCustomerScheduleLabel } from '../portalUtils'
import {
  buildMatrixRankScope,
  matrixScopedPeriodKpis,
  sliceMatrixByPlatform,
  type MatrixChartType,
  type MatrixLayoutMode,
} from './rankingMatrixChartUtils'
import { loadEchartsRuntime } from '../../../utils/echartsLoader'

export type MonitorViewMode = 'list' | 'matrix'
export type RealtimeDatePreset = '7d' | '30d' | 'custom'
export type MonitorDatePreset = RealtimeDatePreset | WorkspaceTrendPreset

const CUSTOMER_DATE_PRESETS: WorkspaceTrendPreset[] = ['7d', 'month', 'quarter', 'year', 'custom']

function isCustomerDatePreset(preset: MonitorDatePreset): preset is WorkspaceTrendPreset {
  return (CUSTOMER_DATE_PRESETS as string[]).includes(preset)
}

function promptBelongsToGroup(prompt: string, group: BrandKeywordGroup) {
  const text = (prompt || '').trim()
  for (const keyword of keywordGroupMonitorKeywords(group)) {
    const token = (keyword || '').trim()
    if (token && (token === text || text.includes(token))) return true
  }
  return false
}

const WEEKDAY_LABELS = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']

function scheduleSourceLabel(source: MonitorTask['schedule_source'] | RankingMatrixRow['schedule_source'] | RankingMatrixCellSnapshot['schedule_source']) {
  if (!source || source === 'daily_avg') return ''
  if (source === 'run') return ''
  if (source === 'lead_diagnosis') return '（售前诊断）'
  if (source === 'inferred') return '（推断）'
  if (source === 'created_at') return '（创建时间）'
  return ''
}

function matrixCellSnapshots(cell: RankingMatrixCell): RankingMatrixCellSnapshot[] {
  if (cell.snapshots?.length) return cell.snapshots
  return [{
    subtask_id: cell.subtask_id,
    mention_position: cell.mention_position,
    raw_mention_position: cell.raw_mention_position,
    brand_mentioned: cell.brand_mentioned,
    monitor_keyword: cell.monitor_keyword,
    prompt_intent: cell.prompt_intent,
    updated_at: cell.updated_at,
    status: cell.status,
    page_screenshot: cell.page_screenshot,
    sentiment: cell.sentiment,
  }]
}

function matrixCellTitle(cell: RankingMatrixCell | undefined) {
  if (!cell) return ''
  if ((cell.rank_sample_count || cell.sample_count || 0) > 1) {
    return `当日 ${cell.rank_sample_count || cell.sample_count} 次监测均值`
  }
  return ''
}

function formatMonitorGroupLabel(group: BrandKeywordGroup, index = group.sort_order ?? 0) {
  return formatKeywordGroupLabel(group, index)
}

function findMonitorGroupByFilter(
  filterValue: string,
  groups: BrandKeywordGroup[],
) {
  return findKeywordGroupBySelectValue(filterValue, groups) || findKeywordGroupByFilter(filterValue, groups)
}

function groupsForExposureTerm(
  exposureTerm: string,
  groups: BrandKeywordGroup[],
  asset: BrandAsset | null,
): BrandKeywordGroup[] {
  const text = exposureTerm.trim()
  if (!text) return []
  const matched = groups.filter(
    group => group.status !== false && (group.exposure_terms || []).includes(text),
  )
  if (matched.length) return matched
  if (asset) {
    const assetTerms = new Set(
      [asset.brand_short_name, asset.brand_name, ...(asset.aliases || [])]
        .map(item => (item || '').trim())
        .filter(Boolean),
    )
    if (assetTerms.has(text)) {
      return groups.filter(
        group => group.status !== false && keywordGroupMonitorKeywords(group).length > 0,
      )
    }
  }
  return []
}

function promptMatchesScopeFilters(
  prompt: string,
  groups: BrandKeywordGroup[],
  scope: { keywordGroup: string; monitorKeyword: string; exposureTerm: string },
  asset: BrandAsset | null = null,
) {
  const groupFilter = scope.keywordGroup.trim()
  const monitorFilter = scope.monitorKeyword.trim()
  const exposureFilter = scope.exposureTerm.trim()
  if (groupFilter) {
    const group = findMonitorGroupByFilter(groupFilter, groups)
    if (!group || !promptBelongsToGroup(prompt, group)) return false
  }
  if (monitorFilter) {
    const text = (prompt || '').trim()
    if (text !== monitorFilter && !text.toLowerCase().includes(monitorFilter.toLowerCase())) return false
  }
  if (exposureFilter) {
    const matchedGroups = groupsForExposureTerm(exposureFilter, groups, asset)
    if (matchedGroups.length) {
      if (!matchedGroups.some(group => promptBelongsToGroup(prompt, group))) return false
    } else if (!(prompt || '').includes(exposureFilter)) {
      return false
    }
  }
  return true
}

function taskMatchesScopeFilters(
  task: MonitorTask,
  groups: BrandKeywordGroup[],
  scope: { keywordGroup: string; monitorKeyword: string; exposureTerm: string },
  asset: BrandAsset | null = null,
) {
  if (!scope.keywordGroup.trim() && !scope.monitorKeyword.trim() && !scope.exposureTerm.trim()) return true
  const prompts = task.prompts || []
  return prompts.some(prompt => promptMatchesScopeFilters(prompt, groups, scope, asset))
}

function defaultDateRange(days = 7) {
  const end = new Date()
  const start = new Date()
  start.setDate(start.getDate() - days)
  return {
    startDate: start.toISOString().slice(0, 10),
    endDate: end.toISOString().slice(0, 10),
  }
}

function matrixCellRankClass(rank: number | null | undefined) {
  if (rank === null || rank === undefined) return 'rank-none'
  if (rank <= 1) return 'rank-top-1'
  if (rank <= 3) return 'rank-top-3'
  if (rank <= 6) return 'rank-mid'
  return 'rank-low'
}

function resolveMatrixColumnMonitorKeyword(
  column: RankingMatrixColumn,
  groups: BrandKeywordGroup[],
  options: RankingMatrix['keyword_group_options'] = [],
): string | null {
  const fromApi = (column.monitor_keyword || '').trim()
  if (fromApi) return fromApi
  if (column.group_id != null) {
    const matched = groups.find(group => group.id === column.group_id)
    if (matched) {
      const explicit = (matched.monitor_keyword || '').trim()
      if (explicit) return explicit
    }
  }
  const text = (column.prompt || '').trim()
  if (!text) return null
  let best: { score: number; keyword: string } | null = null
  for (const group of groups) {
    const explicit = (group.monitor_keyword || '').trim()
    const keywords = keywordGroupMonitorKeywords(group)
    const candidates = explicit ? [explicit, ...keywords] : keywords
    for (const keyword of candidates) {
      const token = (keyword || '').trim()
      if (!token) continue
      let score = -1
      if (text === token) score = 2000 + token.length
      else if (text.includes(token)) score = 1500 + token.length
      else if (token.includes(text)) score = 1400 + text.length
      if (score >= 0 && (!best || score > best.score)) {
        best = { score, keyword: explicit || token }
      }
    }
  }
  if (best) return best.keyword
  for (const option of options || []) {
    const keywords = option.monitor_keywords?.length
      ? option.monitor_keywords
      : [option.monitor_keyword]
    for (const keyword of keywords) {
      const token = (keyword || '').trim()
      if (token && (text === token || text.includes(token))) return token
    }
  }
  return null
}

function enrichRankingMatrixColumns(
  matrix: RankingMatrix,
  groups: BrandKeywordGroup[],
): RankingMatrix {
  return {
    ...matrix,
    columns: matrix.columns.map(column => ({
      ...column,
      monitor_keyword: (column.monitor_keyword || '').trim()
        || resolveMatrixColumnMonitorKeyword(column, groups, matrix.keyword_group_options),
    })),
  }
}

export function useMonitorRealtime(externalTenantId: number | null = null) {
  const route = useRoute()
  const router = useRouter()
  const auth = useAuthStore()
  const tenantId = computed(() => {
    if (auth.session?.identity?.identity_type === 'CUSTOMER') return null
    if (externalTenantId != null) return externalTenantId
    const previewId = Number(Array.isArray(route.query.preview_tenant_id) ? route.query.preview_tenant_id[0] : route.query.preview_tenant_id)
    if (Number.isFinite(previewId) && previewId > 0) return previewId
    const raw = route.query.tenant_id
    const text = Array.isArray(raw) ? raw[0] : raw
    const parsed = Number(text)
    return Number.isFinite(parsed) ? parsed : null
  })
  const isCustomerView = computed(() => (
    auth.session?.identity?.identity_type === 'CUSTOMER'
    || (auth.session?.identity?.identity_type === 'PLATFORM' && tenantId.value != null && Boolean(route.query.preview_tenant_id))
  ))
  const customerPeriodLabel = computed(() => customerDisplayPeriodLabel())
  const customerTrendPeriodLabel = computed(() => (
    workspaceTrendPeriodLabel(
      isCustomerDatePreset(datePreset.value) ? datePreset.value : '7d',
      filters.startDate,
      filters.endDate,
    )
  ))
  const customerTrendMaxDate = customerDisplayCutoffDate()
  const monitorTasks = ref<MonitorTask[]>([])
  const monitorDetail = ref<{ task: MonitorTask; subtasks: MonitorSubtask[] } | null>(null)
  const loadingMonitor = ref(false)
  const brandAsset = ref<BrandAsset | null>(null)
  const brandCompetitors = ref<BrandCompetitor[]>([])
  const monitorSummary = ref<MonitorSummary | null>(null)
  const viewMode = ref<MonitorViewMode>('matrix')
  const rankingMatrix = ref<RankingMatrix | null>(null)
  const loadingMatrix = ref(false)
  let matrixSeq = 0
  let matrixAbort: AbortController | null = null
  const matrixChartType = ref<MatrixChartType>('bar')

  watch(matrixChartType, (type) => {
    if (type === 'table') matrixChartType.value = 'bar'
  })
  const activeMatrixPlatform = ref('')
  const datePreset = ref<MonitorDatePreset>('7d')
  const configExpanded = ref(false)

  const detailVisible = ref(false)
  const loadingDetail = ref(false)
  const expandedSnapshotId = ref<string | null>(null)
  const loadingSnapshotId = ref<string | null>(null)
  const detailSubtask = ref<MonitorSubtask | null>(null)
  const detailContext = ref<{
    scheduleLabel: string | null
    prompt: string
    platform: string | null
    cell: RankingMatrixCell | null
  } | null>(null)

  const selectedMatrixCell = ref<{
    taskId: string
    platform: string | null
    snapshotAt: string | null
    scheduleLabel: string | null
    prompt: string
    cell: RankingMatrixCell
  } | null>(null)

  const initialDates = auth.session?.identity?.identity_type === 'CUSTOMER'
    ? customerDisplayDateRange(7)
    : defaultDateRange(7)
  const filters = reactive({
    platform: '',
    keywordGroup: '',
    monitorKeyword: '',
    exposureTerm: '',
    exactPrompt: '',
    startDate: initialDates.startDate,
    endDate: initialDates.endDate,
    scheduleWindowKey: '',
    status: 'all',
  })

  const monitorGroupOptions = computed(() => {
    const normalizeGroup = (group: BrandKeywordGroup, index: number): BrandKeywordGroup | null => {
      if (group.status === false) return null
      const keywords = keywordGroupMonitorKeywords(group)
      if (!keywords.length) return null
      return {
        ...group,
        monitor_keyword: keywords[0],
        monitor_keywords: keywords,
        sort_order: group.sort_order ?? index,
      }
    }

    const signature = (group: BrandKeywordGroup) => keywordGroupMonitorKeywords(group).join('\u0001')

    const fromAsset = (brandAsset.value?.keyword_groups || [])
      .map((group, index) => normalizeGroup(group, index))
      .filter((group): group is BrandKeywordGroup => group !== null)

    if (fromAsset.length) {
      return fromAsset.sort((left, right) => (left.sort_order ?? 0) - (right.sort_order ?? 0))
    }

    const merged = new Map<string, BrandKeywordGroup>()
    for (const [index, item] of (rankingMatrix.value?.keyword_group_options || []).entries()) {
      const group = normalizeGroup(
        {
          id: null,
          name: item.name || item.monitor_keyword,
          monitor_keyword: item.monitor_keyword,
          monitor_keywords: item.monitor_keywords?.length ? item.monitor_keywords : [item.monitor_keyword],
          exposure_terms: item.exposure_terms || [],
          sort_order: index,
          status: true,
        },
        index,
      )
      if (!group) continue
      const key = signature(group)
      if (!merged.has(key)) merged.set(key, group)
    }

    return [...merged.values()].sort((left, right) => (left.sort_order ?? 0) - (right.sort_order ?? 0))
  })

  const selectedKeywordGroup = computed(() => {
    const value = filters.keywordGroup.trim()
    if (!value) return null
    return findMonitorGroupByFilter(value, monitorGroupOptions.value)
  })

  const monitorKeywordOptions = computed(() => {
    const seen = new Set<string>()
    const keywords: string[] = []
    const add = (value: string | null | undefined) => {
      const token = (value || '').trim()
      if (!token || seen.has(token)) return
      seen.add(token)
      keywords.push(token)
    }
    const scopedGroups = selectedKeywordGroup.value
      ? [selectedKeywordGroup.value]
      : monitorGroupOptions.value
    for (const group of scopedGroups) {
      for (const keyword of keywordGroupMonitorKeywords(group)) add(keyword)
    }
    for (const column of rankingMatrix.value?.columns || []) add(column.prompt)
    return keywords.sort((left, right) => left.localeCompare(right, 'zh-CN'))
  })

  const exposureTermOptions = computed(() => {
    const seen = new Set<string>()
    const terms: string[] = []
    const add = (value: string | null | undefined) => {
      const token = (value || '').trim()
      if (!token || seen.has(token)) return
      seen.add(token)
      terms.push(token)
    }
    const scopedGroups = selectedKeywordGroup.value
      ? [selectedKeywordGroup.value]
      : monitorGroupOptions.value
    for (const group of scopedGroups) {
      for (const term of group.exposure_terms || []) add(term)
    }
    if (!selectedKeywordGroup.value) {
      const asset = brandAsset.value
      if (asset) {
        add(asset.brand_short_name)
        add(asset.brand_name)
        for (const alias of asset.aliases || []) add(alias)
      }
      for (const term of rankingMatrix.value?.exposure_term_options || []) add(term)
    }
    return terms.sort((left, right) => left.localeCompare(right, 'zh-CN'))
  })

  const filterScope = computed(() => ({
    keywordGroup: filters.keywordGroup.trim(),
    monitorKeyword: filters.monitorKeyword.trim(),
    exposureTerm: filters.exposureTerm.trim(),
  }))

  const platformOptions = computed(() => {
    const purchased = brandAsset.value?.monitored_platforms?.length
      ? brandAsset.value.monitored_platforms
      : rankingMatrix.value?.purchased_platforms || []
    return sortPlatformCodes(purchased.filter(Boolean))
  })

  const groupedMonitorTasks = computed<MonitorTaskScheduleGroup[]>(() => {
    const groups = new Map<string, MonitorTaskScheduleGroup>()
    for (const task of monitorTasks.value) {
      const windowKey = task.schedule_window_key || task.task_id
      const label = task.schedule_label || formatTaskTime(task.created_at)
      if (!groups.has(windowKey)) {
        groups.set(windowKey, {
          schedule_window_key: windowKey,
          schedule_label: label,
          tasks: [],
        })
      }
      groups.get(windowKey)!.tasks.push(task)
    }
    return [...groups.values()]
      .sort((left, right) => right.schedule_window_key.localeCompare(left.schedule_window_key))
      .map(group => ({
        ...group,
        tasks: [...group.tasks].sort((left, right) => {
          const leftKey = matchTaskKeywordGroup(left) || left.monitor_keywords || ''
          const rightKey = matchTaskKeywordGroup(right) || right.monitor_keywords || ''
          return leftKey.localeCompare(rightKey, 'zh-CN')
        }),
      }))
  })

  const scheduleRoundOptions = computed(() => {
    const map = new Map<string, string>()
    for (const group of groupedMonitorTasks.value) {
      map.set(group.schedule_window_key, group.schedule_label)
    }
    for (const row of rankingMatrix.value?.rows || []) {
      const key = row.schedule_window_key || row.task_id
      const label = row.schedule_label || row.snapshot_at || key
      if (key) map.set(key, label)
    }
    return [...map.entries()].map(([schedule_window_key, schedule_label]) => ({
      schedule_window_key,
      schedule_label: isCustomerView.value
        ? sanitizeCustomerScheduleLabel(schedule_label)
        : schedule_label,
    }))
  })

  function displayScheduleLabel(label: string | null | undefined, fallback = '暂无批次') {
    if (isCustomerView.value) return sanitizeCustomerScheduleLabel(label, fallback)
    return label?.trim() || fallback
  }

  const monitorResultPlatformOptions = computed(() => {
    const rows = monitorDetail.value?.subtasks || []
    return [...new Set(rows.map(item => item.platform).filter(Boolean))]
  })

  const monitorResultStatusOptions = computed(() => {
    const rows = monitorDetail.value?.subtasks || []
    return [...new Set(rows.map(item => item.status).filter(Boolean))]
  })

  const filteredMonitorSubtasks = computed(() => {
    const exactPrompt = filters.exactPrompt.trim()
    return (monitorDetail.value?.subtasks || []).filter(item => {
      const platformMatched = !filters.platform || item.platform === filters.platform
      const statusMatched = filters.status === 'all' || item.status === filters.status
      const exactMatched = !exactPrompt || (item.prompt || '').trim() === exactPrompt
      const scopeMatched = promptMatchesScopeFilters(
        item.prompt || '',
        monitorGroupOptions.value,
        filterScope.value,
        brandAsset.value,
      )
      return platformMatched && statusMatched && exactMatched && scopeMatched
    })
  })

  const rankingMatrixView = computed(() => {
    if (!rankingMatrix.value) return null

    const purchased = new Set(platformOptions.value)
    let matrix = rankingMatrix.value
    if (matrix.all_platforms && purchased.size) {
      const rows = matrix.rows.filter(row => !row.platform || purchased.has(row.platform))
      const roundKeys = new Set(
        rows.map(row => row.day_key || row.schedule_window_key || '').filter(Boolean),
      )
      matrix = {
        ...matrix,
        rows,
        task_count: rows.length,
        schedule_round_count: roundKeys.size || matrix.schedule_round_count,
      }
    }

    matrix = enrichRankingMatrixColumns(matrix, monitorGroupOptions.value)

    const exactPrompt = filters.exactPrompt.trim()
    if (!exactPrompt) return matrix
    const columns = matrix.columns.filter(col => (col.prompt || '').trim() === exactPrompt)
    if (!columns.length) return { ...matrix, columns: [], rows: [] }
    const rows = matrix.rows.filter(row => columns.some(col => row.cells[col.prompt]))
    return { ...matrix, columns, rows }
  })

  const filteredGroupedMonitorTasks = computed<MonitorTaskScheduleGroup[]>(() => {
    const key = filters.scheduleWindowKey.trim()
    return groupedMonitorTasks.value
      .filter(group => !key || group.schedule_window_key === key)
      .map(group => ({
        ...group,
        tasks: group.tasks.filter(task => taskMatchesScopeFilters(
          task,
          monitorGroupOptions.value,
          filterScope.value,
          brandAsset.value,
        )),
      }))
      .filter(group => group.tasks.length > 0)
  })

  const schedulePlanDisplay = computed(() => {
    const plan = rankingMatrix.value?.schedule_plan
    const asset = brandAsset.value
    const scheduleType = plan?.schedule_type || asset?.schedule_type
    const scheduleTimes = plan?.schedule_times?.length
      ? plan.schedule_times
      : (asset?.schedule_times || [])
    const typeLabels: Record<string, string> = {
      daily_times: '每天定时',
      fixed_times: '固定时刻',
      weekly: '每周指定日',
      monthly: '每月指定日',
    }
    let detail = typeLabels[scheduleType || ''] || '监测计划'
    if (scheduleType === 'weekly') {
      const weekdays = plan?.schedule_weekdays?.length
        ? plan.schedule_weekdays
        : (asset?.schedule_weekdays || [])
      if (weekdays.length) {
        detail += ` · ${weekdays.map(day => WEEKDAY_LABELS[day - 1] || day).join('、')}`
      }
    }
    if (scheduleType === 'monthly') {
      const monthDays = plan?.schedule_month_days?.length
        ? plan.schedule_month_days
        : (asset?.schedule_month_days || [])
      if (monthDays.length) {
        detail += ` · 每月 ${monthDays.join('、')} 日`
      }
    }
    if (scheduleType === 'daily_times' && !scheduleTimes.length && asset?.schedule_frequency) {
      detail += ` · 每天 ${asset.schedule_frequency} 次`
    }
    return {
      typeLabel: detail,
      times: scheduleTimes,
    }
  })

  const platformCoverage = computed(() => {
    const known = monitorSummary.value?.platform_stats || []
    const purchasedCodes = brandAsset.value?.monitored_platforms?.length ? brandAsset.value.monitored_platforms : []
    const codes = sortPlatformCodes(purchasedCodes.length ? purchasedCodes : known.map(item => item.platform))
    return codes.map(code => {
      const row = known.find(item => item.platform === code)
      return {
        code,
        name: platformLabelMap[code] || code,
        rate: row?.mention_rate ?? 0,
        total: row?.total ?? 0,
        completed: row?.completed ?? 0,
        status: row?.completed ? '已返回' : '待返回',
      }
    })
  })

  const heroMetrics = computed(() => {
    const matrix = rankingMatrixView.value
    const rankScope = matrix
      ? buildMatrixRankScope(matrix.rows, filters.startDate, filters.endDate)
      : null
    const periodKpis = matrix && rankScope ? matrixScopedPeriodKpis(matrix, rankScope) : null
    const scopeLabel = periodKpis?.scopeLabel
      || rankScope?.label
      || `${filters.startDate.slice(5)} ~ ${filters.endDate.slice(5)}`
    const fallbackLatest = rankingMatrix.value?.rows[0]
    const latestSchedule = periodKpis?.latestDay
      || displayScheduleLabel(
        fallbackLatest?.schedule_label || fallbackLatest?.snapshot_at,
        isCustomerView.value ? '暂无批次' : '暂无轮次',
      )
    return {
      brandName: brandAsset.value?.brand_name || rankingMatrix.value?.brand_name || '未配置品牌',
      companyName: brandAsset.value?.company_full_name || '',
      latestSchedule,
      dayCount: periodKpis?.dayCount ?? 0,
      sampleCount: periodKpis?.sampleCount ?? null,
      mentionedCount: periodKpis?.mentionedCount ?? null,
      noneRankCount:
        periodKpis?.sampleCount != null && periodKpis?.mentionedCount != null
          ? Math.max(0, periodKpis.sampleCount - periodKpis.mentionedCount)
          : null,
      columnCount: matrix?.columns.length ?? 0,
      avgRank: periodKpis?.avgRank ?? null,
      mentionRate: periodKpis?.mentionRate ?? null,
      top3Rate: periodKpis?.top3Rate ?? null,
      scopeLabel,
    }
  })

  const latestMatrixWindowKey = computed(() => rankingMatrix.value?.rows[0]?.schedule_window_key || '')

  const matrixLayoutMode = computed<MatrixLayoutMode>(() => {
    if (filters.platform.trim()) return 'single'
    const count = platformOptions.value.length || rankingMatrixView.value?.purchased_platforms?.length || 1
    if (count <= 1) return 'single'
    if (count === 2) return 'dual'
    return 'multi'
  })

  const matrixFilterSummary = computed(() => {
    const matrix = rankingMatrixView.value
    const groupLabel = selectedKeywordGroup.value
      ? keywordGroupFilterValue(selectedKeywordGroup.value, selectedKeywordGroup.value.sort_order ?? 0)
      : '全部'
    const platformLabel = filters.platform.trim()
      ? (platformLabelMap[filters.platform] || filters.platform)
      : `${platformOptions.value.length} 平台 · 当前 ${platformLabelMap[activeMatrixPlatform.value] || activeMatrixPlatform.value || '—'}`
    const dayCount = matrix
      ? new Set(matrix.rows.map(row => row.day_key || row.schedule_window_key || '').filter(Boolean)).size
      : 0
    return {
      date: `${filters.startDate.slice(5)} ~ ${filters.endDate.slice(5)}`,
      platform: platformLabel,
      group: groupLabel,
      monitorKeyword: filters.monitorKeyword.trim() || '全部',
      exposureTerm: filters.exposureTerm.trim() || '全部',
      columnCount: matrix?.columns.length ?? 0,
      dayCount,
    }
  })

  function pickDefaultMatrixPlatform(matrix: RankingMatrix) {
    const purchased = platformOptions.value.length
      ? platformOptions.value
      : (matrix.purchased_platforms || [])
    const rowPlatforms = new Set(
      matrix.rows.map(row => row.platform).filter(Boolean) as string[],
    )
    const withRows = matrix.all_platforms
      ? purchased.filter(code => rowPlatforms.has(code))
      : purchased
    const list = withRows.length ? withRows : purchased
    for (const code of list) {
      const slice = sliceMatrixByPlatform(matrix, code)
      if (slice.columns.length && slice.rows.length) return code
    }
    return list[0] || matrix.platform || ''
  }

  function ensureActiveMatrixPlatform() {
    const matrix = rankingMatrixView.value
    if (!matrix) return
    if (filters.platform.trim()) {
      activeMatrixPlatform.value = filters.platform.trim()
      return
    }
    const current = activeMatrixPlatform.value.trim()
    const purchased = platformOptions.value.length
      ? platformOptions.value
      : (matrix.purchased_platforms || [])
    const rowPlatforms = new Set(
      matrix.rows.map(row => row.platform).filter(Boolean) as string[],
    )
    const withRows = matrix.all_platforms
      ? purchased.filter(code => rowPlatforms.has(code))
      : purchased
    const list = withRows.length ? withRows : purchased
    if (!current || !list.includes(current)) {
      activeMatrixPlatform.value = pickDefaultMatrixPlatform(matrix)
    }
  }

  function openMatrixChartCell(payload: {
    row: RankingMatrixRow
    prompt: string
    cell: RankingMatrixCell | undefined
  }) {
    void selectMatrixCell(
      payload.row.task_id,
      payload.row.platform,
      payload.row.snapshot_at,
      payload.row.schedule_label,
      payload.prompt,
      payload.cell,
    )
  }

  // formatRank / formatExposureLabel 见 portalUtils，与快照补录等页面共用

  function formatTaskTime(value: string | null | undefined) {
    if (!value) return '-'
    const date = new Date(value)
    if (Number.isNaN(date.getTime())) return value
    return date.toLocaleString('zh-CN', {
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    })
  }

  function formatDateTime(value: string | null | undefined) {
    if (!value) return '-'
    const date = new Date(value)
    if (Number.isNaN(date.getTime())) return value
    return date.toLocaleString('zh-CN')
  }

  function taskPromptCount(task: MonitorTask) {
    return task.prompts?.length || 0
  }

  function taskPlatformCount(task: MonitorTask) {
    return task.platforms?.length || 0
  }

  function keywordGroupLabelFromGroup(group: BrandKeywordGroup | null | undefined) {
    if (!group) return null
    return keywordGroupDisplayName(group, group.sort_order ?? 0)
  }

  function keywordGroupFromScheduleKey(task: MonitorTask) {
    const key = task.schedule_key || ''
    if (!key.includes('-kw')) return null
    const suffix = key.split('-kw').pop() || ''
    const matched = monitorGroupOptions.value.find(group => {
      if (group.id != null && String(group.id) === suffix) return true
      return String(group.sort_order ?? 0) === suffix
    })
    return keywordGroupLabelFromGroup(matched)
  }

  function matchTaskKeywordGroup(task: MonitorTask) {
    const resolved = (task.keyword_group || '').trim()
    const brandKeyword = (task.monitor_keywords || '').trim()
    if (resolved && resolved !== brandKeyword) return resolved

    const fromSchedule = keywordGroupFromScheduleKey(task)
    if (fromSchedule) return fromSchedule

    const prompts = task.prompts || []
    if (prompts.length) {
      const first = prompts[0]
      for (const group of monitorGroupOptions.value) {
        if (promptBelongsToGroup(first, group)) {
          return keywordGroupLabelFromGroup(group)
        }
      }
    }

    return resolved || null
  }

  function formatTaskTitle(task: MonitorTask) {
    return matchTaskKeywordGroup(task) || task.monitor_keywords || '未填词组'
  }

  function taskPromptPreview(task: MonitorTask, max = 40) {
    const prompt = (task.prompt_preview || task.prompts?.[0] || '').replace(/\s+/g, ' ').trim()
    if (!prompt) return ''
    return prompt.length > max ? `${prompt.slice(0, max)}…` : prompt
  }

  function answerExcerpt(content: string | null | undefined, max = 120) {
    const text = (content || '').replace(/\s+/g, ' ').trim()
    if (!text) return ''
    return text.length > max ? `${text.slice(0, max)}…` : text
  }

  function sentimentToneClass(sentiment: string | null | undefined) {
    if (sentiment === '负面') return 'tone-negative'
    if (sentiment === '正面') return 'tone-positive'
    return 'tone-neutral'
  }

  async function loadBrandAssetData() {
    try {
      const response = await withRetry(() => getBrandAsset(tenantId.value))
      brandAsset.value = response.asset
      brandCompetitors.value = response.competitors
    } catch (error: unknown) {
      notifyOperationError(error, '品牌资产加载失败')
    }
  }

  function clearDeepLinkQuery() {
    const nextQuery = { ...route.query }
    delete nextQuery.task_id
    delete nextQuery.subtask_id
    delete nextQuery.platform
    delete nextQuery.monitor_prompt
    delete nextQuery.insights_day
    delete nextQuery.date_days
    delete nextQuery.view
    router.replace({ path: route.path, query: nextQuery }).catch(() => undefined)
  }

  function applyQueryPlatform() {
    const platformFromQuery = String(route.query.platform || '').trim()
    if (platformFromQuery && platformOptions.value.includes(platformFromQuery)) {
      filters.platform = platformFromQuery
    }
  }

  function applyInsightsQuery() {
    applyQueryPlatform()
    const prompt = String(route.query.monitor_prompt || '').trim()
    filters.exactPrompt = prompt

    const day = String(route.query.insights_day || '').trim()
    const days = String(route.query.date_days || '').trim()
    if (day) {
      filters.startDate = day
      filters.endDate = day
      datePreset.value = 'custom'
    } else if (days === '7' || days === '30' || days === '90') {
      const range = isCustomerView.value
        ? customerDisplayDateRange(Number(days))
        : defaultDateRange(Number(days))
      filters.startDate = range.startDate
      filters.endDate = range.endDate
      datePreset.value = days === '7' ? '7d' : days === '90' ? 'custom' : '30d'
    }

    if (String(route.query.view || '').trim() === 'matrix') {
      viewMode.value = 'matrix'
    }
  }

  async function openDetailDrawer(
    subtask: MonitorSubtask,
    context: {
      scheduleLabel?: string | null
      prompt?: string
      platform?: string | null
      cell?: RankingMatrixCell | null
    } = {},
  ) {
    detailSubtask.value = subtask
    detailContext.value = {
      scheduleLabel: context.scheduleLabel ?? subtask.updated_at ?? null,
      prompt: context.prompt ?? subtask.prompt ?? '',
      platform: context.platform ?? subtask.platform ?? null,
      cell: context.cell ?? null,
    }
    detailVisible.value = true
  }

  async function openSubtaskById(taskId: string, subtaskId: string) {
    if (taskId) {
      await selectMonitorTask(taskId)
    }
    loadingDetail.value = true
    detailVisible.value = true
    try {
      const subtask = await withRetry(() => getMonitorSubtask(subtaskId))
      if (!subtask) throw new Error('子任务不存在')
      selectedMatrixCell.value = {
        taskId: taskId || subtask.task_id || '',
        platform: subtask.platform || null,
        snapshotAt: subtask.updated_at || null,
        scheduleLabel: subtask.updated_at || null,
        prompt: subtask.prompt || '',
        cell: {
          subtask_id: subtask.subtask_id,
          mention_position: subtask.mention_position,
          raw_mention_position: subtask.raw_mention_position,
          brand_mentioned: subtask.brand_mentioned,
          prompt_intent: subtask.prompt_intent,
          status: subtask.status,
          page_screenshot: subtask.page_screenshot,
          sentiment: subtask.sentiment,
          updated_at: subtask.updated_at || null,
        },
      }
      await openDetailDrawer(subtask, {
        scheduleLabel: formatDateTime(subtask.updated_at),
        prompt: subtask.prompt,
        platform: subtask.platform,
      })
    } catch (error: unknown) {
      notifyOperationError(error, '子任务详情加载失败')
    } finally {
      loadingDetail.value = false
    }
  }

  async function loadMonitorTasks(options: { loadTaskDetail?: boolean } = {}) {
    const loadTaskDetail = options.loadTaskDetail ?? true
    loadingMonitor.value = true
    const taskIdFromQuery = String(route.query.task_id || '').trim()
    const subtaskIdFromQuery = String(route.query.subtask_id || '').trim()
    try {
      const [, tasks] = await Promise.all([
        loadBrandAssetData(),
        withRetry(() => getMonitorTasks(tenantId.value)),
      ])
      // summary 仅作 KPI 兜底，不阻塞任务列表首屏
      void withRetry(() => getMonitorSummary(false, tenantId.value))
        .then(summary => { if (summary) monitorSummary.value = summary })
        .catch(() => null)
      monitorTasks.value = isCustomerView.value
        ? tasks.filter(task => monitorTaskBeforeToday(task))
        : tasks
      applyInsightsQuery()
      if (subtaskIdFromQuery) {
        // 深链：先开抽屉（单条 subtask），矩阵后台加载，避免卡在整页矩阵
        viewMode.value = 'matrix'
        void loadRankingMatrix()
        await openSubtaskById('', subtaskIdFromQuery)
        clearDeepLinkQuery()
      } else if (taskIdFromQuery) {
        await selectMonitorTask(taskIdFromQuery)
      } else if (
        loadTaskDetail
        && viewMode.value === 'list'
        && !monitorDetail.value
        && monitorTasks.value[0]?.task_id
      ) {
        await selectMonitorTask(monitorTasks.value[0].task_id)
      }
    } catch (error: unknown) {
      notifyOperationError(error, '检测任务加载失败')
    } finally {
      loadingMonitor.value = false
    }
  }

  async function loadRankingMatrix() {
    const seq = ++matrixSeq
    matrixAbort?.abort()
    matrixAbort = new AbortController()
    const signal = matrixAbort.signal
    const startDate = filters.startDate
    const endDate = filters.endDate
    const startMs = Date.parse(`${startDate}T00:00:00`)
    const endMs = Date.parse(`${endDate}T00:00:00`)
    const spanDays = Number.isFinite(startMs) && Number.isFinite(endMs)
      ? Math.max(1, Math.round((endMs - startMs) / 86400000) + 1)
      : 7
    loadingMatrix.value = true
    if (!detailVisible.value) {
      selectedMatrixCell.value = null
    }
    // ponytail: 保留上一份矩阵作骨架，靠 seq 防脏写；清空会让四卡闪「—」体感更慢
    try {
      // 抓请求瞬间的日期，避免快速切预设时 withRetry 读到后一次筛选
      const data = await withRetry(() => getRankingMatrix({
        platform: filters.platform.trim() || undefined,
        start_date: startDate || undefined,
        end_date: endDate || undefined,
        keyword_group: filters.keywordGroup.trim() || undefined,
        monitor_keyword: filters.monitorKeyword.trim() || undefined,
        exposure_term: filters.exposureTerm.trim() || undefined,
        // 默认 120 在「月×多平台×多词组」会被砍行，KPI 假成跟近 7 日一样
        limit_rows: Math.min(8000, Math.max(500, spanDays * 40)),
        tenant_id: tenantId.value ?? undefined,
      }, { signal }))
      if (seq !== matrixSeq) return
      rankingMatrix.value = data
      ensureActiveMatrixPlatform()
    } catch (error: unknown) {
      if (seq !== matrixSeq) return
      if (signal.aborted) return
      notifyOperationError(error, '排名矩阵加载失败')
    } finally {
      if (seq === matrixSeq) loadingMatrix.value = false
    }
  }

  let detailSeq = 0
  let snapshotDetailSeq = 0

  async function selectMonitorTask(taskId: string) {
    const seq = ++detailSeq
    loadingMonitor.value = true
    try {
      const data = await withRetry(() => getMonitorTaskDetail(taskId))
      if (seq !== detailSeq) return
      monitorDetail.value = data
    } catch (error: unknown) {
      if (seq !== detailSeq) return
      notifyOperationError(error, '任务详情加载失败')
    } finally {
      if (seq === detailSeq) loadingMonitor.value = false
    }
  }

  function switchViewMode(mode: MonitorViewMode) {
    viewMode.value = mode
  }

  /** 逐条列表懒加载：默认矩阵首屏不拉 tasks。 */
  async function ensureListViewData() {
    if (!monitorTasks.value.length) {
      await loadMonitorTasks({ loadTaskDetail: true })
      return
    }
    if (!monitorDetail.value && monitorTasks.value[0]?.task_id) {
      void selectMonitorTask(monitorTasks.value[0].task_id)
    }
  }

  async function selectMatrixCell(
    taskId: string,
    platform: string | null | undefined,
    snapshotAt: string | null,
    scheduleLabel: string | null | undefined,
    prompt: string,
    cell: RankingMatrixCell | undefined,
  ) {
    if (!cell) {
      selectedMatrixCell.value = null
      return
    }
    selectedMatrixCell.value = {
      taskId,
      platform: platform || null,
      snapshotAt,
      scheduleLabel: scheduleLabel || snapshotAt,
      prompt,
      cell,
    }
    detailContext.value = {
      scheduleLabel: scheduleLabel || snapshotAt,
      prompt,
      platform: platform || null,
      cell,
    }
    expandedSnapshotId.value = null
    detailSubtask.value = null
    loadingSnapshotId.value = null
    detailVisible.value = true
  }

  async function toggleMatrixSnapshot(snapshot: RankingMatrixCellSnapshot) {
    if (!snapshot.subtask_id) return
    if (expandedSnapshotId.value === snapshot.subtask_id) {
      expandedSnapshotId.value = null
      detailSubtask.value = null
      return
    }
    expandedSnapshotId.value = snapshot.subtask_id
    loadingSnapshotId.value = snapshot.subtask_id
    const seq = ++snapshotDetailSeq
    try {
      const subtask = await withRetry(() => getMonitorSubtask(snapshot.subtask_id))
      if (seq !== snapshotDetailSeq) return
      if (!subtask) throw new Error('missing')
      detailSubtask.value = subtask
      // 2026-08-14 - 会话回填：详情落库后的有效位次写回当前快照，收起不再闪回「—」
      if (
        subtask.mention_position != null
        && Number.isFinite(Number(subtask.mention_position))
        && snapshot.mention_position == null
      ) {
        snapshot.mention_position = Number(subtask.mention_position)
      }
      if (typeof subtask.brand_mentioned === 'boolean') {
        snapshot.brand_mentioned = subtask.brand_mentioned
      }
    } catch (error: unknown) {
      if (seq !== snapshotDetailSeq) return
      if (snapshot.page_screenshot) {
        detailSubtask.value = {
          subtask_id: snapshot.subtask_id,
          platform: detailContext.value?.platform || '',
          mode: 'standard',
          prompt: detailContext.value?.prompt || '',
          status: snapshot.status || 'completed',
          page_screenshot: snapshot.page_screenshot,
          answer_content: null,
          reference_list: [],
          citation_list: [],
          recommended_questions: [],
          error_message: null,
          mention_position: snapshot.mention_position ?? null,
          mention_context: null,
          raw_mention_position: snapshot.raw_mention_position ?? null,
          sentiment: snapshot.sentiment ?? null,
          competitor_rankings: [],
          all_rankings: [],
          amount: null,
          prompt_intent: snapshot.prompt_intent,
          brand_mentioned: snapshot.brand_mentioned,
        }
      } else {
        notifyOperationError(error, '子任务详情加载失败')
        expandedSnapshotId.value = null
        detailSubtask.value = null
      }
    } finally {
      if (seq === snapshotDetailSeq) loadingSnapshotId.value = null
    }
  }

  async function openListSubtask(subtask: MonitorSubtask) {
    loadingDetail.value = true
    detailVisible.value = true
    try {
      const full = subtask.answer_content
        ? subtask
        : await withRetry(() => getMonitorSubtask(subtask.subtask_id))
      await openDetailDrawer(full, {
        scheduleLabel: monitorDetail.value?.task.schedule_label || formatDateTime(subtask.updated_at),
        prompt: subtask.prompt,
        platform: subtask.platform,
      })
    } catch (error: unknown) {
      notifyOperationError(error, '子任务详情加载失败')
    } finally {
      loadingDetail.value = false
    }
  }

  function closeDetail() {
    detailVisible.value = false
    detailSubtask.value = null
    detailContext.value = null
    selectedMatrixCell.value = null
    expandedSnapshotId.value = null
    loadingSnapshotId.value = null
  }

  function applyDatePreset(preset: MonitorDatePreset) {
    if (isCustomerView.value) {
      if (!isCustomerDatePreset(preset)) return
      // 2026-07-28 - 切月/季无体感 - 同选项再点也强制重拉；标签会显示「本月 …」
      if (preset === datePreset.value && preset !== 'custom') {
        const range = workspaceTrendDateRange(preset)
        filters.startDate = range.startDate
        filters.endDate = range.endDate
        void loadRankingMatrix()
        return
      }
      datePreset.value = preset
      if (preset === 'custom') return
      const range = workspaceTrendDateRange(preset)
      filters.startDate = range.startDate
      filters.endDate = range.endDate
      void loadRankingMatrix()
      return
    }
    if (!['7d', '30d', 'custom'].includes(preset)) return
    if (preset === datePreset.value && preset !== 'custom') {
      const range = defaultDateRange(preset === '30d' ? 30 : 7)
      filters.startDate = range.startDate
      filters.endDate = range.endDate
      void loadRankingMatrix()
      return
    }
    datePreset.value = preset as RealtimeDatePreset
    if (preset === 'custom') return
    const range = defaultDateRange(preset === '30d' ? 30 : 7)
    filters.startDate = range.startDate
    filters.endDate = range.endDate
    void loadRankingMatrix()
  }

  function onCustomDateChange() {
    if (isCustomerView.value) {
      if (filters.startDate > filters.endDate) {
        filters.startDate = filters.endDate
      }
      if (filters.endDate > customerTrendMaxDate) {
        filters.endDate = customerTrendMaxDate
      }
      if (filters.startDate > customerTrendMaxDate) {
        filters.startDate = customerTrendMaxDate
      }
      datePreset.value = 'custom'
      void loadRankingMatrix()
      return
    }
    datePreset.value = 'custom'
    void loadRankingMatrix()
  }

  function resetFilters() {
    const range = isCustomerView.value
      ? workspaceTrendDateRange('7d')
      : defaultDateRange(7)
    filters.platform = ''
    filters.keywordGroup = ''
    filters.monitorKeyword = ''
    filters.exposureTerm = ''
    filters.exactPrompt = ''
    filters.scheduleWindowKey = ''
    filters.status = 'all'
    filters.startDate = range.startDate
    filters.endDate = range.endDate
    datePreset.value = isCustomerView.value ? '7d' : '7d'
    void loadRankingMatrix()
  }

  function refreshCurrentView() {
    if (viewMode.value === 'matrix') {
      void loadRankingMatrix()
      return
    }
    void loadMonitorTasks({ loadTaskDetail: true })
  }

  function exportMatrixCsv() {
    if (!rankingMatrix.value?.rows.length) return
    const columns = rankingMatrix.value.columns
    const header = ['日期', '词组', '平台', ...columns.map(col => col.prompt)]
    const rows = rankingMatrix.value.rows.map(row => [
      row.schedule_label || row.snapshot_at || '',
      row.keyword_group || '',
      row.platform ? (platformLabelMap[row.platform] || row.platform) : '',
      ...columns.map(col => formatRank(row.cells[col.prompt]?.mention_position)),
    ])
    const csv = [header, ...rows]
      .map(line => line.map(cell => `"${String(cell || '').replace(/"/g, '""')}"`).join(','))
      .join('\n')
    const blob = new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `${heroMetrics.value.brandName}-排名矩阵-${filters.endDate}.csv`
    link.click()
    URL.revokeObjectURL(url)
  }

  function isLatestMatrixRow(row: RankingMatrix['rows'][number]) {
    const key = latestMatrixWindowKey.value
    if (!key) return false
    return (row.schedule_window_key || row.task_id) === key
  }

  watch(viewMode, mode => {
    if (mode === 'matrix' && !rankingMatrix.value && !loadingMatrix.value) {
      void loadRankingMatrix()
    }
    if (mode === 'list') {
      void ensureListViewData()
    }
  })

  watch(
    () => filters.keywordGroup,
    () => {
      if (filters.monitorKeyword && !monitorKeywordOptions.value.includes(filters.monitorKeyword)) {
        filters.monitorKeyword = ''
      }
      if (filters.exposureTerm && !exposureTermOptions.value.includes(filters.exposureTerm)) {
        filters.exposureTerm = ''
      }
    },
  )

  watch(
    () => [filters.platform, filters.keywordGroup, filters.monitorKeyword, filters.exposureTerm],
    () => {
      if (viewMode.value === 'matrix') {
        void loadRankingMatrix()
      }
    },
  )

  watch(
    () => filters.platform,
    (platform) => {
      if (platform.trim()) {
        activeMatrixPlatform.value = platform.trim()
      } else {
        ensureActiveMatrixPlatform()
      }
    },
  )

  watch(rankingMatrixView, () => {
    ensureActiveMatrixPlatform()
  }, { deep: true })

  watch(platformOptions, (list) => {
    if (filters.platform.trim() || !list.length) return
    if (!activeMatrixPlatform.value.trim()) {
      activeMatrixPlatform.value = list[0]
    }
  })

  const matrixDrawerSnapshots = computed(() => {
    const cell = detailContext.value?.cell
    return cell ? matrixCellSnapshots(cell) : []
  })

  const isMatrixDrawerMode = computed(() => matrixDrawerSnapshots.value.length > 0)

  onMounted(async () => {
    applyInsightsQuery()
    const subtaskDeepLink = String(route.query.subtask_id || '').trim()
    const taskDeepLink = String(route.query.task_id || '').trim()

    void loadEchartsRuntime('matrix')

    // 深链打开单条/任务：必须拉 tasks；矩阵可后台补
    if (subtaskDeepLink || taskDeepLink) {
      await loadMonitorTasks()
      return
    }

    if (viewMode.value === 'matrix') {
      loadingMatrix.value = true
      // ponytail: 矩阵首屏不拉 tasks；点「逐条」再 ensureListViewData。summary 后台补平台芯片。
      await Promise.all([
        loadRankingMatrix(),
        loadBrandAssetData(),
      ])
      void withRetry(() => getMonitorSummary(false, tenantId.value))
        .then(summary => { if (summary) monitorSummary.value = summary })
        .catch(() => null)
      return
    }

    await Promise.all([
      loadMonitorTasks(),
      loadRankingMatrix(),
    ])
  })

  const stopMonitorRefresh = onMonitorRefresh(() => {
    void loadRankingMatrix()
    if (viewMode.value === 'list') {
      void loadMonitorTasks({ loadTaskDetail: true })
    }
  })
  onUnmounted(stopMonitorRefresh)

  return {
    monitorTasks,
    monitorDetail,
    loadingMonitor,
    filters,
    datePreset,
    configExpanded,
    brandAsset,
    brandCompetitors,
    monitorGroupOptions,
    monitorKeywordOptions,
    exposureTermOptions,
    filterScope,
    platformOptions,
    scheduleRoundOptions,
    isCustomerView,
    customerPeriodLabel,
    customerTrendPeriodLabel,
    customerTrendMaxDate,
    displayScheduleLabel,
    formatMonitorGroupLabel,
    formatKeywordGroupDetailHint,
    keywordGroupSelectValue,
    keywordGroupDisplayName,
    keywordGroupFilterValue,
    groupedMonitorTasks,
    filteredGroupedMonitorTasks,
    schedulePlanDisplay,
    scheduleSourceLabel,
    viewMode,
    rankingMatrix,
    rankingMatrixView,
    matrixChartType,
    activeMatrixPlatform,
    matrixLayoutMode,
    matrixFilterSummary,
    loadingMatrix,
    loadingDetail,
    detailVisible,
    detailSubtask,
    detailContext,
    selectedMatrixCell,
    heroMetrics,
    platformCoverage,
    loadMonitorTasks,
    loadRankingMatrix,
    refreshCurrentView,
    selectMonitorTask,
    switchViewMode,
    selectMatrixCell,
    openMatrixChartCell,
    toggleMatrixSnapshot,
    matrixDrawerSnapshots,
    isMatrixDrawerMode,
    expandedSnapshotId,
    loadingSnapshotId,
    openListSubtask,
    closeDetail,
    applyDatePreset,
    onCustomDateChange,
    resetFilters,
    exportMatrixCsv,
    formatRank,
    formatExposureLabel,
    matrixCellTitle,
    formatTaskTime,
    formatDateTime,
    formatTaskTitle,
    taskPromptPreview,
    answerExcerpt,
    sentimentToneClass,
    matrixCellRankClass,
    isLatestMatrixRow,
    taskPromptCount,
    taskPlatformCount,
    filteredMonitorSubtasks,
    monitorResultPlatformOptions,
    monitorResultStatusOptions,
    platformLabelMap,
    monitorStatusLabelMap,
    monitorModeLabelMap,
    sentimentLabelMap,
  }
}
