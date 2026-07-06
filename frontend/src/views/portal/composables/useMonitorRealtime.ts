import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { withRetry } from '../../../composables/useRetry'
import { notifyOperationError } from '../../../utils/requestError'
import { onMonitorRefresh } from '../../../utils/monitorRefresh'
import {
  customerDisplayPeriodLabel,
  customerDisplayDateRange,
  monitorTaskBeforeToday,
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

export type MonitorViewMode = 'list' | 'matrix'
export type RealtimeDatePreset = 'yesterday' | '7d' | '30d' | 'custom'

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

function promptMatchesScopeFilters(
  prompt: string,
  groups: BrandKeywordGroup[],
  scope: { keywordGroup: string; monitorKeyword: string; exposureTerm: string },
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
  if (exposureFilter && !(prompt || '').includes(exposureFilter)) return false
  return true
}

function taskMatchesScopeFilters(
  task: MonitorTask,
  groups: BrandKeywordGroup[],
  scope: { keywordGroup: string; monitorKeyword: string; exposureTerm: string },
) {
  if (!scope.keywordGroup.trim() && !scope.monitorKeyword.trim() && !scope.exposureTerm.trim()) return true
  const prompts = task.prompts || []
  return prompts.some(prompt => promptMatchesScopeFilters(prompt, groups, scope))
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

export function useMonitorRealtime(externalTenantId: number | null = null) {
  const route = useRoute()
  const router = useRouter()
  const auth = useAuthStore()
  const tenantId = computed(() => {
    if (auth.session?.identity?.identity_type === 'CUSTOMER') return null
    if (externalTenantId != null) return externalTenantId
    const raw = route.query.tenant_id
    const text = Array.isArray(raw) ? raw[0] : raw
    const parsed = Number(text)
    return Number.isFinite(parsed) ? parsed : null
  })
  const isCustomerView = computed(() => auth.session?.identity?.identity_type === 'CUSTOMER')
  const customerPeriodLabel = computed(() => customerDisplayPeriodLabel())
  const monitorTasks = ref<MonitorTask[]>([])
  const monitorDetail = ref<{ task: MonitorTask; subtasks: MonitorSubtask[] } | null>(null)
  const loadingMonitor = ref(false)
  const brandAsset = ref<BrandAsset | null>(null)
  const brandCompetitors = ref<BrandCompetitor[]>([])
  const monitorSummary = ref<MonitorSummary | null>(null)
  const viewMode = ref<MonitorViewMode>('matrix')
  const rankingMatrix = ref<RankingMatrix | null>(null)
  const loadingMatrix = ref(false)
  const datePreset = ref<RealtimeDatePreset>(
    auth.session?.identity?.identity_type === 'CUSTOMER' ? '7d' : '7d',
  )
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
      )
      return platformMatched && statusMatched && exactMatched && scopeMatched
    })
  })

  const rankingMatrixView = computed(() => {
    if (!rankingMatrix.value) return null
    const exactPrompt = filters.exactPrompt.trim()
    if (!exactPrompt) return rankingMatrix.value
    const columns = rankingMatrix.value.columns.filter(col => (col.prompt || '').trim() === exactPrompt)
    if (!columns.length) return { ...rankingMatrix.value, columns: [], rows: [] }
    const rows = rankingMatrix.value.rows.filter(row => columns.some(col => row.cells[col.prompt]))
    return { ...rankingMatrix.value, columns, rows }
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
    const latestGroup = groupedMonitorTasks.value[0]
    const latestTask = latestGroup?.tasks[0]
    const latestMatrixRow = rankingMatrix.value?.rows[0]
    const completed = latestTask?.completed_items ?? monitorSummary.value?.completed_count ?? 0
    const total = latestTask?.total_items ?? monitorSummary.value?.subtask_count ?? 0
    const pendingPlatforms = platformCoverage.value.filter(item => item.status !== '已返回').length
    return {
      brandName: brandAsset.value?.brand_name || rankingMatrix.value?.brand_name || '未配置品牌',
      companyName: brandAsset.value?.company_full_name || '',
      latestSchedule: displayScheduleLabel(
        latestGroup?.schedule_label
        || latestMatrixRow?.schedule_label
        || latestMatrixRow?.snapshot_at,
        isCustomerView.value ? '暂无批次' : '暂无轮次',
      ),
      completed,
      total,
      avgRank: monitorSummary.value?.avg_rank ?? null,
      mentionRate: monitorSummary.value?.mention_rate ?? null,
      pendingPlatforms,
      taskCount: monitorTasks.value.length,
      scheduleRoundCount: rankingMatrix.value?.schedule_round_count ?? groupedMonitorTasks.value.length,
    }
  })

  const latestMatrixWindowKey = computed(() => rankingMatrix.value?.rows[0]?.schedule_window_key || '')

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
      const range = defaultDateRange(Number(days))
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

  async function loadMonitorTasks() {
    loadingMonitor.value = true
    const taskIdFromQuery = String(route.query.task_id || '').trim()
    const subtaskIdFromQuery = String(route.query.subtask_id || '').trim()
    try {
      const [, tasks, summary] = await Promise.all([
        loadBrandAssetData(),
        withRetry(() => getMonitorTasks()),
        withRetry(() => getMonitorSummary()).catch(() => null),
      ])
      monitorTasks.value = isCustomerView.value
        ? tasks.filter(task => monitorTaskBeforeToday(task))
        : tasks
      if (summary) monitorSummary.value = summary
      applyInsightsQuery()
      if (taskIdFromQuery) {
        await selectMonitorTask(taskIdFromQuery)
      } else if (!monitorDetail.value && monitorTasks.value[0]?.task_id) {
        await selectMonitorTask(monitorTasks.value[0].task_id)
      }
      if (subtaskIdFromQuery) {
        viewMode.value = 'matrix'
        await loadRankingMatrix()
        await openSubtaskById(taskIdFromQuery || monitorDetail.value?.task.task_id || '', subtaskIdFromQuery)
        clearDeepLinkQuery()
      }
    } catch (error: unknown) {
      notifyOperationError(error, '检测任务加载失败')
    } finally {
      loadingMonitor.value = false
    }
  }

  async function loadRankingMatrix() {
    loadingMatrix.value = true
    if (!detailVisible.value) {
      selectedMatrixCell.value = null
    }
    try {
      rankingMatrix.value = await withRetry(() => getRankingMatrix({
        platform: filters.platform.trim() || undefined,
        start_date: filters.startDate || undefined,
        end_date: filters.endDate || undefined,
        keyword_group: filters.keywordGroup.trim() || undefined,
        monitor_keyword: filters.monitorKeyword.trim() || undefined,
        exposure_term: filters.exposureTerm.trim() || undefined,
      }))
    } catch (error: unknown) {
      notifyOperationError(error, '排名矩阵加载失败')
    } finally {
      loadingMatrix.value = false
    }
  }

  async function selectMonitorTask(taskId: string) {
    loadingMonitor.value = true
    try {
      monitorDetail.value = await withRetry(() => getMonitorTaskDetail(taskId))
    } catch (error: unknown) {
      notifyOperationError(error, '任务详情加载失败')
    } finally {
      loadingMonitor.value = false
    }
  }

  function switchViewMode(mode: MonitorViewMode) {
    viewMode.value = mode
    if (mode === 'matrix' && !rankingMatrix.value && !loadingMatrix.value) {
      void loadRankingMatrix()
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
    try {
      detailSubtask.value = await withRetry(() => getMonitorSubtask(snapshot.subtask_id))
    } catch (error: unknown) {
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
      loadingSnapshotId.value = null
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

  function applyDatePreset(preset: RealtimeDatePreset) {
    if (isCustomerView.value) {
      datePreset.value = preset === '30d' ? '30d' : '7d'
      const range = customerDisplayDateRange(preset === '30d' ? 30 : 7)
      filters.startDate = range.startDate
      filters.endDate = range.endDate
      void loadRankingMatrix()
      return
    }
    datePreset.value = preset
    if (preset === 'custom') return
    const range = defaultDateRange(preset === '30d' ? 30 : 7)
    filters.startDate = range.startDate
    filters.endDate = range.endDate
    void loadRankingMatrix()
  }

  function onCustomDateChange() {
    if (isCustomerView.value) return
    datePreset.value = 'custom'
    void loadRankingMatrix()
  }

  function resetFilters() {
    const range = isCustomerView.value ? customerDisplayDateRange(7) : defaultDateRange(7)
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
    void loadMonitorTasks()
    if (viewMode.value === 'matrix') {
      void loadRankingMatrix()
    }
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

  const matrixDrawerSnapshots = computed(() => {
    const cell = detailContext.value?.cell
    return cell ? matrixCellSnapshots(cell) : []
  })

  const isMatrixDrawerMode = computed(() => matrixDrawerSnapshots.value.length > 0)

  onMounted(async () => {
    applyInsightsQuery()
    await loadMonitorTasks()
    if (!String(route.query.subtask_id || '').trim()) {
      await loadRankingMatrix()
    }
  })

  const stopMonitorRefresh = onMonitorRefresh(() => {
    void loadMonitorTasks()
    if (viewMode.value === 'matrix') {
      void loadRankingMatrix()
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
