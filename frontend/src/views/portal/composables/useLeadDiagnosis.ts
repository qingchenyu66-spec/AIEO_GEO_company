import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '../../../stores/auth'
import {
  createLeadDiagnosis,
  downloadLeadDiagnosisExport,
  getLeadDiagnosisDetail,
  getLeadDiagnosisList,
  LEAD_STATUS_LABELS,
  refreshLeadDiagnosis,
  submitLeadDiagnosisRun,
  type LeadDiagnosisDetail,
  type LeadDiagnosisItem,
  type LeadDiagnosisRun,
  type LeadDiagnosisStatus,
} from '../../../services/leadDiagnosis'
import { notifyOperationError } from '../../../utils/requestError'
import { platformLabelMap } from '../portalMaps'
import { formatDateTime } from '../portalUtils'
import { regionOptions } from '../regionOptions'

export const PROMPT_TEMPLATES = [
  { label: '产品推荐', value: '例如：XXX有哪些产品值得推荐？' },
  { label: '排名查询', value: '例如：XXX在同类品牌里排名怎么样？' },
  { label: '哪家更好', value: '例如：XXX和主要竞品哪家更好？' },
  { label: '选购建议', value: '例如：选择XXX需要重点关注什么？' },
  { label: '靠谱程度', value: '例如：XXX品牌靠谱吗？用户评价怎么样？' },
]

export const SCHEDULE_SLOTS = ['09:30', '14:30', '20:30']
export const SCHEDULE_DAYS = 3
export const SCHEDULE_TOTAL = SCHEDULE_DAYS * SCHEDULE_SLOTS.length

function addDays(isoDate: string, days: number): string {
  const date = new Date(`${isoDate}T00:00:00`)
  date.setDate(date.getDate() + days)
  return date.toISOString().slice(0, 10)
}

export const RUN_STATUS_LABELS: Record<string, string> = {
  pending: '待提交',
  submitted: '已提交',
  completed: '已完成',
  failed: '失败',
  skipped: '已跳过',
}

export type DetailTab = 'progress' | 'report' | 'queries' | 'sources' | 'platforms' | 'config'

export function useLeadDiagnosis() {
  const auth = useAuthStore()
  const loading = ref(false)
  const saving = ref(false)
  const exporting = ref(false)
  const detailLoading = ref(false)
  const loadError = ref('')
  const records = ref<LeadDiagnosisItem[]>([])
  const selectedId = ref<number | null>(null)
  const detail = ref<LeadDiagnosisDetail | null>(null)
  const keywordFilter = ref('')
  const statusFilter = ref<'' | LeadDiagnosisStatus>('')
  const showCreatePanel = ref(false)
  const createStep = ref(1)
  const detailTab = ref<DetailTab>('progress')
  let pollTimer: ReturnType<typeof setInterval> | null = null

  const createForm = ref({
    brand_name: '',
    prompts: ['', '', '', '', ''],
    competitors: '',
    region_code: '',
    contact_note: '',
    start_immediately: true,
  })

  const pageMenuName = computed(() => (
    auth.allowedMenus.find(menu => menu.menu_code === 'platform.lead_diagnosis')?.menu_name || '售前诊断'
  ))

  const canCreate = computed(() => auth.allowedMenus.some(
    menu => menu.menu_code === 'platform.lead_diagnosis' && menu.can_create,
  ))
  const canExport = computed(() => auth.allowedMenus.some(
    menu => menu.menu_code === 'platform.lead_diagnosis' && menu.can_export,
  ))

  const filteredRecords = computed(() => {
    const keyword = keywordFilter.value.trim().toLowerCase()
    return records.value.filter(item => {
      if (statusFilter.value && item.status !== statusFilter.value) return false
      if (!keyword) return true
      return (item.brand_name || '').toLowerCase().includes(keyword)
    })
  })

  const statsSummary = computed(() => ({
    total: records.value.length,
    collecting: records.value.filter(item => item.status === 'collecting' || item.status === 'pending').length,
    ready: records.value.filter(item => item.status === 'ready').length,
  }))

  const diagnosisResult = computed(() => detail.value?.diagnosis_result || null)
  const kpis = computed(() => (diagnosisResult.value?.kpis as Record<string, unknown> | undefined) || {})
  const diagnosisBlock = computed(() => (diagnosisResult.value?.diagnosis as Record<string, unknown> | undefined) || {})
  const platformStats = computed(() => (
    (diagnosisResult.value?.monitor_snapshot as Record<string, unknown> | undefined)?.platform_stats as Array<Record<string, unknown>> || []
  ))
  const highlights = computed(() => (
    (diagnosisResult.value?.monitor_snapshot as Record<string, unknown> | undefined)?.highlights as string[] || []
  ))
  const reportSections = computed(() => (
    (diagnosisResult.value?.report_sections as Record<string, string> | undefined) || {}
  ))
  const promptAnalytics = computed(() => (
    (diagnosisResult.value?.monitor_snapshot as Record<string, unknown> | undefined)?.prompt_analytics as Array<Record<string, unknown>> || []
  ))
  const sourceAnalysis = computed(() => (
    (diagnosisResult.value?.monitor_snapshot as Record<string, unknown> | undefined)?.source_analysis as Record<string, unknown> || {}
  ))
  const rankTrend = computed(() => (
    (diagnosisResult.value?.monitor_snapshot as Record<string, unknown> | undefined)?.rank_trend as Array<Record<string, unknown>> || []
  ))
  const trackedEntities = computed(() => (
    (diagnosisResult.value?.monitor_snapshot as Record<string, unknown> | undefined)?.tracked_entities as string[] || []
  ))
  const brandCityRankings = computed(() => (
    (diagnosisResult.value?.monitor_snapshot as Record<string, unknown> | undefined)?.brand_city_rankings as Array<Record<string, unknown>> || []
  ))
  const executiveSummary = computed(() => (
    (diagnosisResult.value?.ai_insights as Record<string, unknown> | undefined)?.executive_summary as string | undefined
  ))
  const hasReportSections = computed(() => (
    Object.values(reportSections.value).some(value => String(value || '').trim())
  ))

  function regionLabel(code: string | null | undefined) {
    if (!code) return '全部区域'
    return regionOptions.find(item => item.code === code)?.name || code
  }

  const filledPromptCount = computed(() => (
    createForm.value.prompts.map(item => item.trim()).filter(Boolean).length
  ))

  const scheduleTimeline = computed(() => {
    const item = detail.value
    if (!item) return []
    const slots = item.schedule_times?.length ? item.schedule_times : SCHEDULE_SLOTS
    const days = item.schedule_days ?? SCHEDULE_DAYS
    const runMap = new Map((item.runs || []).map(run => [run.schedule_key, run]))
    const entries: ScheduleTimelineItem[] = []
    let index = 0
    for (let dayOffset = 0; dayOffset < days; dayOffset += 1) {
      const dayDate = addDays(item.diagnosis_date, dayOffset)
      const dateKey = dayDate.replace(/-/g, '')
      for (const slot of slots) {
        index += 1
        const hm = slot.replace(':', '')
        const key = `${dateKey}-${hm}`
        const run = runMap.get(key)
        entries.push({
          index,
          day: dayDate,
          dayOffset: dayOffset + 1,
          slot,
          schedule_key: key,
          label: `${dayDate} ${slot}`,
          run,
          state: run?.status || 'waiting',
        })
      }
    }
    return entries
  })

  const progressPercent = computed(() => {
    if (!detail.value) return 0
    const total = detail.value.schedule_total_count ?? SCHEDULE_TOTAL
    return Math.round((detail.value.completed_run_count / total) * 100)
  })

  function healthTone(score: number | null | undefined) {
    if (score == null) return ''
    if (score >= 80) return 'is-good'
    if (score >= 60) return 'is-mid'
    return 'is-warn'
  }

  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer)
      pollTimer = null
    }
  }

  function startPollingIfNeeded() {
    stopPolling()
    if (!selectedId.value || detail.value?.status === 'ready' || detail.value?.status === 'failed') return
    pollTimer = setInterval(() => {
      if (selectedId.value) void refreshSilently(selectedId.value)
    }, 20000)
  }

  async function refreshSilently(id: number) {
    try {
      detail.value = await refreshLeadDiagnosis(id)
      await loadRecords({ silent: true })
      if (detail.value.status === 'ready' || detail.value.status === 'failed') stopPolling()
    } catch {
      // 轮询失败不打断用户当前查看。
    }
  }

  async function loadRecords(options?: { silent?: boolean }) {
    if (!options?.silent) {
      loading.value = true
      loadError.value = ''
    }
    try {
      records.value = await getLeadDiagnosisList()
    } catch (error: unknown) {
      loadError.value = '加载售前诊断列表失败，请确认后端服务已启动后刷新页面'
      if (!options?.silent) notifyOperationError(error, '加载售前诊断列表失败')
    } finally {
      if (!options?.silent) loading.value = false
    }
  }

  async function selectRecord(id: number) {
    selectedId.value = id
    detailTab.value = 'progress'
    detailLoading.value = true
    try {
      detail.value = await getLeadDiagnosisDetail(id)
      if (detail.value.status === 'ready') detailTab.value = 'report'
      startPollingIfNeeded()
    } catch (error: unknown) {
      notifyOperationError(error, '加载诊断详情失败')
    } finally {
      detailLoading.value = false
    }
  }

  function openCreatePanel() {
    createStep.value = 1
    createForm.value = {
      brand_name: '',
      prompts: ['', '', '', '', ''],
      competitors: '',
      region_code: '',
      contact_note: '',
      start_immediately: true,
    }
    showCreatePanel.value = true
  }

  function closeCreatePanel() {
    showCreatePanel.value = false
    createStep.value = 1
  }

  function applyPromptTemplate(index: number) {
    if (index >= createForm.value.prompts.length) return
    const brand = createForm.value.brand_name.trim() || 'XXX'
    createForm.value.prompts[index] = PROMPT_TEMPLATES[index].value.replace(/XXX/g, brand)
  }

  function nextCreateStep() {
    if (createStep.value === 1) {
      if (!createForm.value.brand_name.trim()) {
        ElMessage.warning('请填写品牌名称')
        return
      }
      createStep.value = 2
      return
    }
    void submitCreate()
  }

  async function submitCreate() {
    const brand = createForm.value.brand_name.trim()
    const prompts = createForm.value.prompts.map(item => item.trim()).filter(Boolean)
    if (!brand) {
      ElMessage.warning('请填写品牌名称')
      createStep.value = 1
      return
    }
    if (!prompts.length) {
      ElMessage.warning('请至少填写一个检测问题')
      return
    }
    saving.value = true
    try {
      const competitors = createForm.value.competitors
        .split(/[,，、]/)
        .map(item => item.trim())
        .filter(Boolean)
      const created = await createLeadDiagnosis({
        brand_name: brand,
        prompts,
        competitors,
        region_code: createForm.value.region_code.trim() || null,
        contact_note: createForm.value.contact_note.trim() || undefined,
        start_immediately: createForm.value.start_immediately,
      })
      closeCreatePanel()
      ElMessage.success('诊断任务已创建，系统将连续三天共九次自动抓取')
      await loadRecords()
      await selectRecord(created.id)
    } catch (error: unknown) {
      notifyOperationError(error, '创建诊断失败')
    } finally {
      saving.value = false
    }
  }

  async function handleRefresh() {
    if (!selectedId.value) return
    detailLoading.value = true
    try {
      detail.value = await refreshLeadDiagnosis(selectedId.value)
      await loadRecords({ silent: true })
      startPollingIfNeeded()
      ElMessage.success('进度已更新')
    } catch (error: unknown) {
      notifyOperationError(error, '刷新失败')
    } finally {
      detailLoading.value = false
    }
  }

  async function handleForceRun() {
    if (!selectedId.value || !canCreate.value) return
    try {
      await submitLeadDiagnosisRun(selectedId.value, true)
      ElMessage.success('已提交抓取任务')
      await handleRefresh()
    } catch (error: unknown) {
      notifyOperationError(error, '提交抓取失败')
    }
  }

  async function handleExport() {
    if (!selectedId.value || detail.value?.status !== 'ready') return
    exporting.value = true
    try {
      const filename = await downloadLeadDiagnosisExport(selectedId.value, 'pdf')
      ElMessage.success(`PDF 已下载：${filename}`)
    } catch (error: unknown) {
      notifyOperationError(error, '导出 PDF 失败')
    } finally {
      exporting.value = false
    }
  }

  onMounted(loadRecords)
  onUnmounted(stopPolling)

  return {
    loading,
    saving,
    exporting,
    detailLoading,
    loadError,
    records,
    selectedId,
    detail,
    keywordFilter,
    statusFilter,
    showCreatePanel,
    createStep,
    detailTab,
    createForm,
    pageMenuName,
    canCreate,
    canExport,
    filteredRecords,
    statsSummary,
    diagnosisResult,
    kpis,
    diagnosisBlock,
    platformStats,
    highlights,
    reportSections,
    promptAnalytics,
    sourceAnalysis,
    rankTrend,
    brandCityRankings,
    trackedEntities,
    executiveSummary,
    hasReportSections,
    regionOptions,
    regionLabel,
    promptTemplates: PROMPT_TEMPLATES,
    scheduleSlots: SCHEDULE_SLOTS,
    scheduleDays: SCHEDULE_DAYS,
    scheduleTotal: SCHEDULE_TOTAL,
    runStatusLabels: RUN_STATUS_LABELS,
    statusLabels: LEAD_STATUS_LABELS,
    platformLabelMap,
    formatDateTime,
    filledPromptCount,
    scheduleTimeline,
    progressPercent,
    healthTone,
    loadRecords,
    selectRecord,
    openCreatePanel,
    closeCreatePanel,
    applyPromptTemplate,
    nextCreateStep,
    submitCreate,
    handleRefresh,
    handleForceRun,
    handleExport,
  }
}

export type ScheduleTimelineItem = {
  index: number
  day: string
  dayOffset: number
  slot: string
  schedule_key: string
  label: string
  run?: LeadDiagnosisRun
  state: string
}
