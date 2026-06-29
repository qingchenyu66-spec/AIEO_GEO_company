import { computed, onMounted, reactive, ref, watch } from 'vue'
import { withRetry } from '../../../composables/useRetry'
import { notifyOperationError } from '../../../utils/requestError'
import { getBrandAsset, type BrandAsset, type BrandCompetitor, type BrandKeywordGroup } from '../../../services/brand'
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
} from '../../../services/monitor'
import {
  monitorModeLabelMap,
  monitorStatusLabelMap,
  platformLabelMap,
  sentimentLabelMap,
} from '../portalMaps'

export type MonitorViewMode = 'list' | 'matrix'

function promptBelongsToGroup(prompt: string, group: BrandKeywordGroup) {
  const text = (prompt || '').trim()
  const keyword = (group.monitor_keyword || '').trim()
  if (keyword && text.includes(keyword)) return true
  return (group.exposure_terms || []).some(term => {
    const token = (term || '').trim()
    return token && text.includes(token)
  })
}

const WEEKDAY_LABELS = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']

function scheduleSourceLabel(source: MonitorTask['schedule_source']) {
  if (source === 'run') return ''
  if (source === 'inferred') return '（按配置时刻推断）'
  if (source === 'created_at') return '（按创建时间）'
  return ''
}

function formatMonitorGroupLabel(group: BrandKeywordGroup) {
  const keyword = (group.monitor_keyword || '').trim()
  const exposure = (group.exposure_terms || []).map(term => term.trim()).filter(Boolean)
  if (!exposure.length) return keyword
  return `${keyword}（露出：${exposure.join('、')}）`
}

function defaultMatrixDateRange() {
  const end = new Date()
  const start = new Date()
  start.setDate(start.getDate() - 7)
  return {
    startDate: start.toISOString().slice(0, 10),
    endDate: end.toISOString().slice(0, 10),
  }
}

export function useMonitorRealtime(tenantId: number | null = null) {
  const monitorTasks = ref<MonitorTask[]>([])
  const monitorDetail = ref<{ task: MonitorTask; subtasks: MonitorSubtask[] } | null>(null)
  const loadingMonitor = ref(false)
  const brandAsset = ref<BrandAsset | null>(null)
  const brandCompetitors = ref<BrandCompetitor[]>([])
  const monitorSummary = ref<MonitorSummary | null>(null)
  const viewMode = ref<MonitorViewMode>('list')
  const rankingMatrix = ref<RankingMatrix | null>(null)
  const loadingMatrix = ref(false)
  const loadingMatrixDetail = ref(false)
  const selectedMatrixCell = ref<{
    taskId: string
    platform: string | null
    snapshotAt: string | null
    scheduleLabel: string | null
    prompt: string
    cell: RankingMatrixCell
  } | null>(null)
  const selectedMatrixSubtask = ref<MonitorSubtask | null>(null)

  const defaultDates = defaultMatrixDateRange()
  const filters = reactive({
    platform: 'all',
    status: 'all',
    monitorGroup: '',
  })
  const matrixFilters = reactive({
    platform: '',
    startDate: defaultDates.startDate,
    endDate: defaultDates.endDate,
    monitorGroup: '',
  })

  const monitorGroupOptions = computed(() => {
    const groups = brandAsset.value?.keyword_groups?.length
      ? brandAsset.value.keyword_groups
      : (rankingMatrix.value?.keyword_group_options || []).map(item => ({
          id: null,
          monitor_keyword: item.monitor_keyword,
          exposure_terms: item.exposure_terms,
          sort_order: 0,
          status: true,
        }))
    return groups
      .filter(group => group.status !== false && (group.monitor_keyword || '').trim())
      .sort((left, right) => (left.sort_order ?? 0) - (right.sort_order ?? 0))
  })

  const monitorResultPlatformOptions = computed(() => {
    const rows = monitorDetail.value?.subtasks || []
    return [...new Set(rows.map(item => item.platform).filter(Boolean))]
  })

  const monitorResultStatusOptions = computed(() => {
    const rows = monitorDetail.value?.subtasks || []
    return [...new Set(rows.map(item => item.status).filter(Boolean))]
  })

  const filteredMonitorSubtasks = computed(() => {
    const selectedGroup = filters.monitorGroup.trim()
    const selectedKeywordGroup = monitorGroupOptions.value.find(
      group => group.monitor_keyword === selectedGroup,
    )
    return (monitorDetail.value?.subtasks || []).filter(item => {
      const platformMatched = filters.platform === 'all' || item.platform === filters.platform
      const statusMatched = filters.status === 'all' || item.status === filters.status
      const groupMatched = !selectedKeywordGroup || promptBelongsToGroup(item.prompt || '', selectedKeywordGroup)
      return platformMatched && statusMatched && groupMatched
    })
  })

  const matrixPlatformOptions = computed(() => {
    const purchased = brandAsset.value?.monitored_platforms?.length
      ? brandAsset.value.monitored_platforms
      : rankingMatrix.value?.purchased_platforms || []
    return purchased.filter(Boolean)
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
          const leftKey = left.keyword_group || left.monitor_keywords || ''
          const rightKey = right.keyword_group || right.monitor_keywords || ''
          return leftKey.localeCompare(rightKey, 'zh-CN')
        }),
      }))
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
    const codes = purchasedCodes.length ? purchasedCodes : known.map(item => item.platform)
    return codes.map((code, index) => {
      const row = known.find(item => item.platform === code)
      return {
        code,
        name: platformLabelMap[code] || code,
        rate: row?.mention_rate ?? 0,
        total: row?.total ?? 0,
        status: row?.completed ? '已返回' : index < 5 ? '监测中' : '待接入',
      }
    })
  })

  function formatRank(value: number | null | undefined) {
    if (value === null || value === undefined) return '-'
    return Number.isInteger(value) ? String(value) : value.toFixed(1)
  }

  function formatExposureLabel(mentioned?: boolean) {
    return mentioned ? '已提及' : '未提及'
  }

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

  function taskPromptCount(task: MonitorTask) {
    return task.prompts?.length || 0
  }

  function taskPlatformCount(task: MonitorTask) {
    return task.platforms?.length || 0
  }

  async function loadBrandAssetData() {
    try {
      const response = await withRetry(() => getBrandAsset(tenantId))
      brandAsset.value = response.asset
      brandCompetitors.value = response.competitors
    } catch (error: unknown) {
      notifyOperationError(error, '品牌资产加载失败')
    }
  }

  async function loadMonitorTasks() {
    loadingMonitor.value = true
    try {
      const [, tasks, summary] = await Promise.all([
        loadBrandAssetData(),
        withRetry(() => getMonitorTasks()),
        withRetry(() => getMonitorSummary()).catch(() => null),
      ])
      monitorTasks.value = tasks
      if (summary) monitorSummary.value = summary
      const firstTaskId = !monitorDetail.value ? monitorTasks.value[0]?.task_id : ''
      if (firstTaskId) {
        window.setTimeout(() => {
          if (!monitorDetail.value) selectMonitorTask(firstTaskId)
        }, 40)
      }
    } catch (error: unknown) {
      notifyOperationError(error, '检测任务加载失败')
    } finally {
      loadingMonitor.value = false
    }
  }

  async function loadRankingMatrix() {
    loadingMatrix.value = true
    selectedMatrixCell.value = null
    selectedMatrixSubtask.value = null
    try {
      rankingMatrix.value = await withRetry(() => getRankingMatrix({
        platform: matrixFilters.platform.trim() || undefined,
        start_date: matrixFilters.startDate || undefined,
        end_date: matrixFilters.endDate || undefined,
        monitor_group: matrixFilters.monitorGroup.trim() || undefined,
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
      selectedMatrixSubtask.value = null
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
    selectedMatrixSubtask.value = null
    loadingMatrixDetail.value = true
    try {
      selectedMatrixSubtask.value = await withRetry(() => getMonitorSubtask(cell.subtask_id))
    } catch (error: unknown) {
      notifyOperationError(error, '子任务详情加载失败')
    } finally {
      loadingMatrixDetail.value = false
    }
  }

  function resetMatrixFilters() {
    const defaults = defaultMatrixDateRange()
    matrixFilters.startDate = defaults.startDate
    matrixFilters.endDate = defaults.endDate
    matrixFilters.monitorGroup = ''
    matrixFilters.platform = ''
  }

  function clearMatrixCellSelection() {
    selectedMatrixCell.value = null
    selectedMatrixSubtask.value = null
  }

  watch(viewMode, mode => {
    if (mode === 'matrix' && !rankingMatrix.value && !loadingMatrix.value) {
      void loadRankingMatrix()
    }
  })

  onMounted(loadMonitorTasks)

  return {
    monitorTasks,
    monitorDetail,
    loadingMonitor,
    filters,
    matrixFilters,
    brandAsset,
    brandCompetitors,
    monitorGroupOptions,
    formatMonitorGroupLabel,
    groupedMonitorTasks,
    schedulePlanDisplay,
    scheduleSourceLabel,
    viewMode,
    rankingMatrix,
    loadingMatrix,
    loadingMatrixDetail,
    selectedMatrixCell,
    selectedMatrixSubtask,
    loadMonitorTasks,
    loadRankingMatrix,
    selectMonitorTask,
    switchViewMode,
    selectMatrixCell,
    clearMatrixCellSelection,
    resetMatrixFilters,
    formatRank,
    formatExposureLabel,
    formatTaskTime,
    taskPromptCount,
    taskPlatformCount,
    filteredMonitorSubtasks,
    monitorResultPlatformOptions,
    monitorResultStatusOptions,
    matrixPlatformOptions,
    platformCoverage,
    platformLabelMap,
    monitorStatusLabelMap,
    monitorModeLabelMap,
    sentimentLabelMap,
  }
}
