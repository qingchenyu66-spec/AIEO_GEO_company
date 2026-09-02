import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useAuthStore } from '../../../stores/auth'
import {
  cancelLeadDiagnosis,
  createLeadDiagnosis,
  finalizeLeadDiagnosisEarly,
  downloadLeadDiagnosisExport,
  fetchLeadDiagnosisPreviewHtml,
  getLeadDiagnosisDetail,
  getLeadDiagnosisList,
  LEAD_STATUS_LABELS,
  refreshLeadDiagnosis,
  reviseLeadDiagnosisConfig,
  submitLeadDiagnosisRun,
  type LeadDiagnosisDetail,
  type LeadDiagnosisItem,
  type LeadDiagnosisRun,
  type LeadDiagnosisStatus,
} from '../../../services/leadDiagnosis'
import {
  getApproval,
  isDuplicateMergedApproval,
  isPendingApproval,
  isResubmittedApproval,
  pendingApprovalMessage,
  resubmitApproval,
} from '../../../services/approvals'
import { notifyOperationError } from '../../../utils/requestError'
import { injectReportPreviewBase } from '../../../utils/reportPreviewHtml'
import { platformLabelMap } from '../portalMaps'
import { supportedPlatforms } from '../platformMeta'
import { formatDateTime } from '../portalUtils'
import { regionOptions, selectableRegionOptions, regionLabels } from '../regionOptions'

export function formatLeadCreator(
  creator?: { display_name?: string | null; username?: string | null } | null,
) {
  if (!creator?.display_name) return '—'
  const name = creator.display_name.trim()
  const username = (creator.username || '').trim()
  if (username && username !== name) return `${name}（${username}）`
  return name
}

export function isPlaceholderLeadPrompt(text: string) {
  const value = text.trim()
  return value.startsWith('例如：') || value.startsWith('例如:') || /xxx/i.test(value)
}

export function isLeadScheduleSlotDue(day: string, slot: string) {
  const [year, month, dayNum] = day.split('-').map(part => Number.parseInt(part, 10))
  const [hour, minute] = slot.split(':').map(part => Number.parseInt(part, 10))
  const scheduled = new Date(year, month - 1, dayNum, hour, minute, 0, 0)
  return scheduled.getTime() <= Date.now()
}

export const PROMPT_TEMPLATES = [
  // 2026-08-13 - 问法模板标明品牌/非品牌，避免全品牌词导致主 KPI 暂无
  // 2026-08-21 - 非品牌=行业+推荐/靠谱/哪家好，不硬拼「公司」（蛋白粉≠蛋白粉公司）
  { label: '非品牌·推荐', lane: 'nonbrand' as const, value: '例如：蛋白粉推荐' },
  { label: '非品牌·靠谱', lane: 'nonbrand' as const, value: '例如：蛋白粉哪家靠谱' },
  { label: '非品牌·哪家好', lane: 'nonbrand' as const, value: '例如：蛋白粉哪家好' },
  // 2026-08-17 - 品牌防守改为「公司介绍/怎么样」，贴近真实检索问法
  { label: '品牌·介绍', lane: 'brand' as const, value: '例如：XXX公司介绍' },
  { label: '品牌·评价', lane: 'brand' as const, value: '例如：XXX公司怎么样' },
]

/** 非品牌问法主题：优先行业，其次产品焦点；不自动加「公司」。 */
export function nonbrandTopicLabel(industry: string, productFocus: string): string {
  return String(industry || '').trim() || String(productFocus || '').trim() || '相关品类'
}

export function buildNonbrandPromptSet(topic: string): [string, string, string] {
  const t = String(topic || '').trim() || '相关品类'
  return [`${t}推荐`, `${t}哪家靠谱`, `${t}哪家好`]
}

/** 本地粗判：问法是否含品牌名（与报告 is_brand_query 同思路）。 */
export function promptLooksBrand(prompt: string, brand: string): boolean {
  const text = String(prompt || '')
  const b = String(brand || '').trim()
  if (!text || !b) return false
  if (text.toLowerCase().includes(b.toLowerCase())) return true
  // 剥常见公司后缀后再判
  for (const suffix of ['股份有限公司', '控股集团有限公司', '集团有限公司', '有限公司', '控股集团', '集团', '公司']) {
    if (b.endsWith(suffix) && b.length > suffix.length + 1) {
      const short = b.slice(0, -suffix.length).trim()
      if (short && text.includes(short)) return true
    }
  }
  return false
}

export const SCHEDULE_SLOTS = ['09:30', '14:30', '20:30']
export const SCHEDULE_DAYS = 3
export const SCHEDULE_DAYS_SUGGEST_MIN = 3
export const SCHEDULE_DAYS_SUGGEST_MAX = 7
export const SCHEDULE_DAYS_MIN = 1
export const SCHEDULE_DAYS_MAX = 30
export const SCHEDULE_TOTAL = SCHEDULE_DAYS * SCHEDULE_SLOTS.length

export function clampScheduleDays(value: number | null | undefined) {
  const n = Number(value)
  if (!Number.isFinite(n)) return SCHEDULE_DAYS
  return Math.min(SCHEDULE_DAYS_MAX, Math.max(SCHEDULE_DAYS_MIN, Math.round(n)))
}

export function scheduleTotalForDays(days: number) {
  return clampScheduleDays(days) * SCHEDULE_SLOTS.length
}

export function buildLeadScheduleDatetimesFromDetail(row: {
  schedule_datetimes?: string[]
  schedule_plan?: Array<{ day: string; slot: string }>
  diagnosis_date: string
  schedule_days?: number
  schedule_times?: string[]
}): string[] {
  if (row.schedule_datetimes?.length) {
    return [...row.schedule_datetimes]
  }
  if (row.schedule_plan?.length) {
    return row.schedule_plan.map(entry => `${entry.day}T${entry.slot}`)
  }
  const slots = row.schedule_times?.length ? row.schedule_times : SCHEDULE_SLOTS
  const days = row.schedule_days ?? SCHEDULE_DAYS
  const out: string[] = []
  for (let dayOffset = 0; dayOffset < days; dayOffset += 1) {
    const dayDate = addDays(row.diagnosis_date, dayOffset)
    for (const slot of slots) {
      out.push(`${dayDate}T${slot}`)
    }
  }
  return out
}

/** 审批单 body：自定义时间点 > 天数×默认时段。 */
export function buildApprovalScheduleDatetimes(body: Record<string, unknown>): string[] {
  const ctx = (body.lead_context && typeof body.lead_context === 'object')
    ? body.lead_context as Record<string, unknown>
    : {}
  if (Array.isArray(ctx.schedule_datetimes) && ctx.schedule_datetimes.length) {
    return ctx.schedule_datetimes.map(item => normalizeScheduleDatetimeValue(String(item)))
  }
  const diagnosisDate = String(body.diagnosis_date || new Date().toISOString().slice(0, 10))
  return buildLeadScheduleDatetimesFromDetail({
    diagnosis_date: diagnosisDate,
    schedule_days: Number(body.schedule_days || 3),
  })
}

export function formatApprovalScheduleDisplay(body: Record<string, unknown>): string {
  const slots = buildApprovalScheduleDatetimes(body)
  if (!slots.length) return '—'
  return slots.map(formatScheduleDatetimeLabel).join('、')
}

export function formatScheduleDatetimeLabel(value: string) {
  return String(value || '').trim().replace('T', ' ')
}

export type LeadConfigScheduleSlot = { value: string; locked: boolean }

export function normalizeScheduleDatetimeValue(value: string): string {
  let text = String(value || '').trim()
  if (text.includes(' · ')) text = text.split(' · ', 1)[0].trim()
  return text.replace(' ', 'T').slice(0, 16)
}

export function parseScheduleDatetimeMs(value: string): number | null {
  const normalized = normalizeScheduleDatetimeValue(value)
  if (!normalized) return null
  const dt = new Date(normalized)
  return Number.isNaN(dt.getTime()) ? null : dt.getTime()
}

export function formatDatetimeLocalInput(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  const h = String(d.getHours()).padStart(2, '0')
  const min = String(d.getMinutes()).padStart(2, '0')
  return `${y}-${m}-${day}T${h}:${min}`
}

export function scheduleKeyToDatetimeValue(scheduleKey: string): string {
  const text = String(scheduleKey || '').trim().split('-rg')[0]
  const matched = text.match(/^(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})$/)
  if (!matched) return ''
  return `${matched[1]}-${matched[2]}-${matched[3]}T${matched[4]}:${matched[5]}`
}

export function buildLeadScheduleSlotsForEdit(row: LeadDiagnosisDetail): LeadConfigScheduleSlot[] {
  const now = Date.now()
  const seen = new Set<string>()
  const items: LeadConfigScheduleSlot[] = []

  const findRun = (normalized: string) => (row.runs || []).find((run) => (
    normalizeScheduleDatetimeValue(run.schedule_label || '') === normalized
    || scheduleKeyToDatetimeValue(run.schedule_key || '') === normalized
  ))

  const isLocked = (normalized: string): boolean => {
    const ms = parseScheduleDatetimeMs(normalized)
    const run = findRun(normalized)
    if (run && ['completed', 'submitted', 'failed', 'skipped'].includes(run.status)) return true
    if (ms != null && ms <= now) return true
    return false
  }

  const add = (raw: string) => {
    const normalized = normalizeScheduleDatetimeValue(raw)
    if (!normalized || seen.has(normalized)) return
    seen.add(normalized)
    items.push({ value: normalized, locked: isLocked(normalized) })
  }

  for (const run of row.runs || []) {
    if (run.schedule_label) add(run.schedule_label)
  }
  for (const dt of buildLeadScheduleDatetimesFromDetail(row)) {
    add(dt)
  }

  items.sort((a, b) => (parseScheduleDatetimeMs(a.value) ?? 0) - (parseScheduleDatetimeMs(b.value) ?? 0))
  return items
}

export function nextDefaultScheduleDatetime(existing: string[], baseDate?: string) {
  const now = new Date()
  now.setSeconds(0, 0)
  const floor = formatDatetimeLocalInput(now)
  const base = baseDate || floor.slice(0, 10)
  const last = existing.length ? existing[existing.length - 1] : `${base}T09:30`
  const dt = new Date(last.replace('T', ' '))
  if (Number.isNaN(dt.getTime())) return floor
  dt.setHours(dt.getHours() + 4)
  dt.setSeconds(0, 0)
  const candidate = formatDatetimeLocalInput(dt)
  return candidate < floor ? floor : candidate
}

function addDays(isoDate: string, days: number): string {
  const [year, month, day] = isoDate.split('-').map(part => Number.parseInt(part, 10))
  const date = new Date(year, month - 1, day + days)
  const y = date.getFullYear()
  const m = String(date.getMonth() + 1).padStart(2, '0')
  const d = String(date.getDate()).padStart(2, '0')
  return `${y}-${m}-${d}`
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
  const exportingFormat = ref<'html' | null>(null)
  const exportProgress = ref('')
  const detailLoading = ref(false)
  const loadError = ref('')
  const records = ref<LeadDiagnosisItem[]>([])
  const selectedId = ref<number | null>(null)
  const detail = ref<LeadDiagnosisDetail | null>(null)
  const keywordFilter = ref('')
  const statusFilter = ref<'' | LeadDiagnosisStatus>('')
  const showCreatePanel = ref(false)
  const resubmitApprovalId = ref<number | null>(null)
  const createStep = ref(1)
  const detailTab = ref<DetailTab>('progress')
  const submittingSlotKey = ref<string | null>(null)
  const previewHtmlLoading = ref(false)
  const previewHtmlUrl = ref<string | null>(null)
  const previewHtmlBlobById = new Map<number, string>()
  let pollTimer: ReturnType<typeof setInterval> | null = null
  let detailSeq = 0
  let previewSeq = 0

  function revokePreviewHtmlBlob(exceptId?: number | null) {
    for (const [id, url] of previewHtmlBlobById.entries()) {
      if (exceptId != null && id === exceptId) continue
      URL.revokeObjectURL(url)
      previewHtmlBlobById.delete(id)
    }
    if (exceptId == null) previewHtmlUrl.value = null
  }

  async function loadPreviewHtml(leadId: number) {
    const cached = previewHtmlBlobById.get(leadId)
    if (cached) {
      previewHtmlUrl.value = cached
      previewHtmlLoading.value = false
      return
    }
    const seq = ++previewSeq
    previewHtmlLoading.value = true
    try {
      const html = injectReportPreviewBase(await fetchLeadDiagnosisPreviewHtml(leadId))
      if (seq !== previewSeq || selectedId.value !== leadId) return
      const url = URL.createObjectURL(new Blob([html], { type: 'text/html;charset=utf-8' }))
      previewHtmlBlobById.set(leadId, url)
      previewHtmlUrl.value = url
    } catch (error: unknown) {
      if (seq !== previewSeq) return
      previewHtmlUrl.value = null
      notifyOperationError(error, '诊断驾驶舱预览加载失败')
    } finally {
      if (seq === previewSeq) previewHtmlLoading.value = false
    }
  }

  const createForm = ref({
    brand_name: '',
    brand_aliases: '',
    website_url: '',
    industry: '',
    product_focus: '',
    prompts: ['', '', '', '', ''],
    competitors: '',
    platforms: [] as string[],
    region_codes: [] as string[],
    contact_note: '',
    schedule_days: SCHEDULE_DAYS,
    start_immediately: true,
  })

  const createScheduleTotal = computed(() => scheduleTotalForDays(createForm.value.schedule_days))

  // 2026-08-04 - 诊断平台与职位「平台范围」同口径；空白名单则无可勾选项
  const diagnosisPlatformOptions = computed(() => {
    const raw = auth.session?.allowed_monitor_platforms
    const allow = new Set(
      Array.isArray(raw) ? raw.map(code => String(code || '').trim()).filter(Boolean) : [],
    )
    if (!allow.size) return []
    return supportedPlatforms.filter(item => allow.has(item.code))
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
  // 2026-08-11 - 无企业地区编辑权仍可选诊断地区 - 与 platform.audit.regions 对齐
  const canEditRegions = computed(() => auth.allowedMenus.some(
    menu => menu.menu_code === 'platform.audit.regions' && menu.can_update,
  ))
  const isSales = computed(() => auth.session?.identity?.position_code === 'PLATFORM_SALES')
  const canReviseConfig = computed(() => (
    !isSales.value
    && canExport.value
    && (detail.value?.status === 'pending' || detail.value?.status === 'collecting')
  ))
  const configEditing = ref(false)
  const configSaving = ref(false)
  const configEditScheduleSlots = ref<LeadConfigScheduleSlot[]>([])
  const scheduleDatetimeMinLocal = computed(() => {
    const d = new Date()
    d.setSeconds(0, 0)
    return formatDatetimeLocalInput(d)
  })
  const configEditForm = ref({
    brand_aliases_text: '',
    website_url: '',
    industry: '',
    product_focus: '',
    purchase_scenario: '',
    competitorsText: '',
    contact_note: '',
  })

  const configScheduleDisplaySlots = computed(() => {
    const row = detail.value
    if (!row) return [] as string[]
    return buildLeadScheduleSlotsForEdit(row).map(slot => formatScheduleDatetimeLabel(slot.value))
  })

  function fillConfigEditForm() {
    const row = detail.value
    if (!row) return
    configEditForm.value = {
      brand_aliases_text: (row.brand_aliases || []).join('、'),
      website_url: row.lead_context?.website_url || '',
      industry: row.lead_context?.industry || '',
      product_focus: row.lead_context?.product_focus || '',
      purchase_scenario: row.lead_context?.purchase_scenario || '',
      competitorsText: (row.competitors || []).join('、'),
      contact_note: row.contact_note || '',
    }
    configEditScheduleSlots.value = buildLeadScheduleSlotsForEdit(row)
  }

  function openConfigEdit() {
    fillConfigEditForm()
    configEditing.value = true
    detailTab.value = 'config'
  }

  function cancelConfigEdit() {
    configEditing.value = false
  }

  function addConfigScheduleSlot() {
    const list = configEditScheduleSlots.value
    const values = list.map(item => item.value)
    configEditScheduleSlots.value = [
      ...list,
      { value: nextDefaultScheduleDatetime(values, detail.value?.diagnosis_date), locked: false },
    ]
  }

  function removeConfigScheduleSlot(index: number) {
    const list = [...configEditScheduleSlots.value]
    const item = list[index]
    if (!item) return
    if (item.locked) {
      ElMessage.warning('已执行或已过的时间点不可删除')
      return
    }
    const editableCount = list.filter(slot => !slot.locked).length
    if (editableCount <= 1) {
      ElMessage.warning('至少保留一个可修改的未来时间点')
      return
    }
    list.splice(index, 1)
    configEditScheduleSlots.value = list
  }

  async function saveConfigRevise() {
    if (!selectedId.value || configSaving.value) return
    const form = configEditForm.value
    const scheduleDatetimes = configEditScheduleSlots.value.map(item => item.value.trim()).filter(Boolean)
    if (!scheduleDatetimes.length) {
      ElMessage.warning('请至少添加一个抓取时间点')
      return
    }
    const now = Date.now()
    for (const slot of configEditScheduleSlots.value) {
      if (slot.locked) continue
      const ms = parseScheduleDatetimeMs(slot.value)
      if (ms != null && ms < now) {
        ElMessage.warning('抓取时间点不能早于当前时间')
        return
      }
    }
    const hasFuture = configEditScheduleSlots.value.some((slot) => {
      const ms = parseScheduleDatetimeMs(slot.value)
      return ms != null && ms >= now
    })
    if (!hasFuture) {
      ElMessage.warning('请至少保留一个当前或未来的时间点')
      return
    }
    configSaving.value = true
    try {
      const updated = await reviseLeadDiagnosisConfig(selectedId.value, {
        brand_aliases: form.brand_aliases_text.split(/[,，、]/).map(s => s.trim()).filter(Boolean),
        lead_context: {
          website_url: form.website_url.trim(),
          industry: form.industry.trim(),
          product_focus: form.product_focus.trim(),
          purchase_scenario: form.purchase_scenario.trim(),
        },
        competitors: form.competitorsText.split(/[,，、]/).map(s => s.trim()).filter(Boolean),
        schedule_datetimes: scheduleDatetimes,
        contact_note: form.contact_note.trim() || null,
      })
      detail.value = updated
      const idx = records.value.findIndex(item => item.id === updated.id)
      if (idx >= 0) {
        records.value[idx] = { ...records.value[idx], ...updated }
      }
      configEditing.value = false
      ElMessage.success('任务配置已保存，后续抓取将按新配置执行')
    } catch (error: unknown) {
      notifyOperationError(error, '保存任务配置失败')
    } finally {
      configSaving.value = false
    }
  }

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
    return regionLabels(code ? [code] : [])
  }

  const filledPromptCount = computed(() => (
    createForm.value.prompts.map(item => item.trim()).filter(Boolean).length
  ))

  // 2026-08-13 - 问法质量条：非品牌/品牌计数，避免全品牌词
  const promptQuality = computed(() => {
    const brand = createForm.value.brand_name.trim()
    let brandN = 0
    let nonbrandN = 0
    for (const raw of createForm.value.prompts) {
      const p = raw.trim()
      if (!p) continue
      if (promptLooksBrand(p, brand)) brandN += 1
      else nonbrandN += 1
    }
    return { brandN, nonbrandN, total: brandN + nonbrandN }
  })

  const scheduleTimeline = computed(() => {
    const item = detail.value
    if (!item) return []
    const runMap = new Map((item.runs || []).map(run => [run.schedule_key, run]))

    if (item.schedule_plan?.length) {
      const dayOrder = [...new Set(item.schedule_plan.map(entry => entry.day))]
      const dayIndexMap = new Map(dayOrder.map((day, index) => [day, index + 1]))
      return item.schedule_plan.map((entry, index) => ({
        index: index + 1,
        day: entry.day,
        dayOffset: dayIndexMap.get(entry.day) ?? 1,
        slot: entry.slot,
        schedule_key: entry.schedule_key,
        label: entry.schedule_label,
        run: runMap.get(entry.schedule_key),
        state: runMap.get(entry.schedule_key)?.status || 'waiting',
      }))
    }

    const slots = item.schedule_times?.length ? item.schedule_times : SCHEDULE_SLOTS
    const days = item.schedule_days ?? SCHEDULE_DAYS
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

  const schedulePlanSummary = computed(() => {
    const item = detail.value
    if (!item) return ''
    const calendarDays = item.schedule_calendar_days ?? item.schedule_days ?? SCHEDULE_DAYS
    const total = item.schedule_total_count ?? SCHEDULE_TOTAL
    const slotCount = item.schedule_times?.length || SCHEDULE_SLOTS.length
    const endDate = item.plan_end_date
    if (endDate && endDate !== item.diagnosis_date) {
      return `共 ${total} 次抓取，跨 ${calendarDays} 个自然日（${item.diagnosis_date} 至 ${endDate}）；创建当日已过的时段自动跳过并顺延。`
    }
    return `连续 ${calendarDays} 天、每天 ${slotCount} 个时段各抓一轮，共 ${total} 次全部完成后自动汇总结论。`
  })

  const progressPercent = computed(() => {
    if (!detail.value) return 0
    const total = detail.value.schedule_total_count ?? SCHEDULE_TOTAL
    if (!total) return 0
    // 2026-08-21 - 计划外完成档曾把进度打到 133% - 前端再封顶一次
    return Math.min(100, Math.round((detail.value.completed_run_count / total) * 100))
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
    }, 10000) // 2026-08-07 - 20s 太慢，多轮抓完仍像只完成一轮
  }

  async function refreshSilently(id: number) {
    if (selectedId.value !== id) return
    try {
      const latest = await refreshLeadDiagnosis(id)
      if (selectedId.value !== id) return
      detail.value = latest
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
    const seq = ++detailSeq
    configEditing.value = false
    selectedId.value = id
    detailTab.value = 'progress'
    detailLoading.value = true
    previewHtmlUrl.value = previewHtmlBlobById.get(id) || null
    try {
      const latest = await getLeadDiagnosisDetail(id)
      if (seq !== detailSeq || selectedId.value !== id) return
      detail.value = latest
      if (detail.value.status === 'ready') detailTab.value = 'report'
      startPollingIfNeeded()
    } catch (error: unknown) {
      if (seq !== detailSeq) return
      notifyOperationError(error, '加载诊断详情失败')
    } finally {
      if (seq === detailSeq) detailLoading.value = false
    }
  }

  watch(
    [selectedId, detailTab, () => detail.value?.status],
    ([id, tab, status]) => {
      if (id && tab === 'report' && status === 'ready') {
        void loadPreviewHtml(id)
      }
    },
  )

  function prefillCreateFormFromBody(body: Record<string, unknown>) {
    const leadContext = (body.lead_context || {}) as Record<string, unknown>
    const prompts = Array.isArray(body.prompts) ? body.prompts.map(item => String(item || '')) : []
    while (prompts.length < 5) prompts.push('')
    createForm.value = {
      brand_name: String(body.brand_name || ''),
      brand_aliases: Array.isArray(body.brand_aliases) ? body.brand_aliases.join('、') : '',
      website_url: String(leadContext.website_url || ''),
      industry: String(leadContext.industry || ''),
      product_focus: String(leadContext.product_focus || ''),
      prompts: prompts.slice(0, 5),
      competitors: Array.isArray(body.competitors) ? body.competitors.join('、') : '',
      platforms: Array.isArray(body.platforms) ? [...body.platforms as string[]] : [],
      region_codes: Array.isArray(body.region_codes) ? [...body.region_codes as string[]] : [],
      contact_note: String(body.contact_note || ''),
      schedule_days: clampScheduleDays(Number(body.schedule_days || SCHEDULE_DAYS)),
      start_immediately: body.start_immediately !== false,
    }
    createStep.value = 1
    showCreatePanel.value = true
  }

  async function loadResubmitDraftFromRoute() {
    const raw = route.query.resubmit_approval_id
    const id = Number(Array.isArray(raw) ? raw[0] : raw)
    if (!Number.isFinite(id) || id <= 0) return
    try {
      const row = await getApproval(id)
      if (row.status !== 'rejected' || row.operation_key !== 'lead_diagnosis.create') {
        ElMessage.warning('该审批单不可在此处修改')
        return
      }
      resubmitApprovalId.value = id
      const body = (row.lead_adopted_body || row.payload?.body || {}) as Record<string, unknown>
      prefillCreateFormFromBody(body)
      if (row.review_comment) {
        ElMessage.warning(`上次驳回：${row.review_comment}`)
      }
    } catch (error: unknown) {
      notifyOperationError(error, '加载驳回单失败')
    }
  }

  function openCreatePanel() {
    createStep.value = 1
    createForm.value = {
      brand_name: '',
      brand_aliases: '',
      website_url: '',
      industry: '',
      product_focus: '',
      prompts: ['', '', '', '', ''],
      competitors: '',
      platforms: [],
      region_codes: [],
      contact_note: '',
      schedule_days: SCHEDULE_DAYS,
      start_immediately: true,
    }
    showCreatePanel.value = true
  }

  function closeCreatePanel() {
    showCreatePanel.value = false
    createStep.value = 1
    resubmitApprovalId.value = null
  }

  function toggleCreatePlatform(code: string) {
    if (!diagnosisPlatformOptions.value.some(item => item.code === code)) return
    const list = createForm.value.platforms
    const idx = list.indexOf(code)
    if (idx >= 0) list.splice(idx, 1)
    else list.push(code)
  }

  function brandAsCompanyLabel(brand: string) {
    const text = String(brand || '').trim()
    if (!text) return 'XXX公司'
    // 已以「公司」结尾则不再叠字（有限公司公司介绍）
    return text.endsWith('公司') ? text : `${text}公司`
  }

  function applyPromptTemplate(index: number) {
    if (index >= createForm.value.prompts.length) return
    const brand = createForm.value.brand_name.trim() || 'XXX'
    const tpl = PROMPT_TEMPLATES[index]
    // 2026-08-21 - 非品牌按钮按表单「行业」即时拼，避免写死示例行业
    if (tpl.lane === 'nonbrand') {
      const topic = nonbrandTopicLabel(createForm.value.industry, createForm.value.product_focus)
      const [p0, p1, p2] = buildNonbrandPromptSet(topic)
      createForm.value.prompts[index] = [p0, p1, p2][index] || p0
      return
    }
    let text = tpl.value.replace(/^例如：/, '')
    // 2026-08-17 - 「XXX公司介绍」优先整词替换，避免品牌名已含「公司」时叠字
    if (text.includes('XXX公司')) {
      text = text.replace(/XXX公司/g, brandAsCompanyLabel(brand))
    } else {
      text = text.replace(/XXX/g, brand)
    }
    createForm.value.prompts[index] = text
  }

  function generateBalancedPrompts() {
    const brand = createForm.value.brand_name.trim()
    if (!brand) {
      ElMessage.warning('请先填写品牌名称')
      return
    }
    if (!createForm.value.industry.trim() && !createForm.value.product_focus.trim()) {
      ElMessage.warning('请先填写行业（或产品焦点），再一键生成非品牌问法')
      return
    }
    // 2026-08-21 - 行业优先：蛋白粉推荐 / 蛋白粉哪家靠谱 / 蛋白粉哪家好；不硬加「公司」
    const topic = nonbrandTopicLabel(createForm.value.industry, createForm.value.product_focus)
    const [p0, p1, p2] = buildNonbrandPromptSet(topic)
    const company = brandAsCompanyLabel(brand)
    createForm.value.prompts = [p0, p1, p2, `${company}介绍`, `${company}怎么样`]
    ElMessage.success('已生成 3 条非品牌 + 2 条品牌问法，可再编辑')
  }

  function nextCreateStep() {
    if (createStep.value === 1) {
      if (!createForm.value.brand_name.trim()) {
        ElMessage.warning('请填写品牌名称')
        return
      }
      if (!diagnosisPlatformOptions.value.length) {
        ElMessage.warning('当前职位未配置可诊断平台，请联系管理员')
        return
      }
      // 去掉白名单外残留勾选
      createForm.value.platforms = createForm.value.platforms.filter(code =>
        diagnosisPlatformOptions.value.some(item => item.code === code),
      )
      if (!createForm.value.platforms.length) {
        ElMessage.warning('请至少勾选一个诊断平台')
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
    const platforms = createForm.value.platforms.filter(code =>
      diagnosisPlatformOptions.value.some(item => item.code === code),
    )
    if (!brand) {
      ElMessage.warning('请填写品牌名称')
      createStep.value = 1
      return
    }
    if (!diagnosisPlatformOptions.value.length) {
      ElMessage.warning('当前职位未配置可诊断平台，请联系管理员')
      createStep.value = 1
      return
    }
    if (!platforms.length) {
      ElMessage.warning('请至少勾选一个诊断平台')
      createStep.value = 1
      return
    }
    if (!prompts.length) {
      ElMessage.warning('请至少填写一个检测问题')
      return
    }
    if (prompts.some(isPlaceholderLeadPrompt)) {
      ElMessage.warning('请填写真实检测问题，不要使用「例如：」模板或 XXX 占位')
      createStep.value = 2
      return
    }
    const q = promptQuality.value
    if (q.nonbrandN < 1) {
      const ok = window.confirm(
        '当前 5 条问法中非品牌词为 0，提交后将无法计算获客主 KPI（仅能看品牌防守）。确定仍要提交？',
      )
      if (!ok) return
    } else if (q.nonbrandN < 3 || q.brandN < 2) {
      ElMessage.warning(`建议至少 3 条非品牌 + 2 条品牌（当前非品牌 ${q.nonbrandN} / 品牌 ${q.brandN}）`)
    }
    saving.value = true
    try {
      const competitors = createForm.value.competitors
        .split(/[,，、]/)
        .map(item => item.trim())
        .filter(Boolean)
      const brand_aliases = createForm.value.brand_aliases
        .split(/[,，、;/|]+/)
        .map(item => item.trim())
        .filter(Boolean)
      const days = clampScheduleDays(createForm.value.schedule_days)
      // 2026-08-13 - 官网/行业/产品走 lead_context，contact_note 仅销售备注
      const lead_context = {
        website_url: createForm.value.website_url.trim(),
        industry: createForm.value.industry.trim(),
        product_focus: createForm.value.product_focus.trim(),
        purchase_scenario: '',
        source: 'lead_diagnosis_create',
      }
      if (!lead_context.website_url) {
        ElMessage.info('未填官网：信源与行动建议质量可能下降')
      }
      const submitBody = {
        brand_name: brand,
        prompts,
        competitors,
        brand_aliases: brand_aliases.length ? brand_aliases : undefined,
        platforms,
        region_codes: canEditRegions.value ? [...createForm.value.region_codes] : [],
        contact_note: createForm.value.contact_note.trim() || undefined,
        lead_context,
        schedule_days: days,
        start_immediately: createForm.value.start_immediately,
      }
      if (resubmitApprovalId.value) {
        const updated = await resubmitApproval(resubmitApprovalId.value, { body: submitBody as Record<string, unknown> })
        closeCreatePanel()
        const msg = pendingApprovalMessage(updated, '已重新提交，等待运营或管理员审核')
        ElMessage.success(msg)
        await loadRecords()
        return
      }
      const created = await createLeadDiagnosis(submitBody)
      closeCreatePanel()
      // 2026-07-30 - 销售新建进审批后仍用审批单 id 拉详情 404 - 待审态只提示，不 selectRecord
      if (isPendingApproval(created)) {
        const msg = pendingApprovalMessage(created, '已提交审批，等待运营或管理员审核通过后生效')
        if (isDuplicateMergedApproval(created)) ElMessage.warning(msg)
        else if (isResubmittedApproval(created)) ElMessage.success(msg)
        else ElMessage.info(msg)
        await loadRecords()
        return
      }
      ElMessage.success(`诊断任务已创建，系统将连续 ${days} 天共 ${scheduleTotalForDays(days)} 次自动抓取`)
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
      await submitLeadDiagnosisRun(selectedId.value, { force: true })
      ElMessage.success('已提交抓取任务')
      await handleRefresh()
    } catch (error: unknown) {
      notifyOperationError(error, '提交抓取失败')
    }
  }

  async function handleCancel() {
    if (!selectedId.value || !canCreate.value || !detail.value) return
    if (detail.value.status !== 'pending' && detail.value.status !== 'collecting') return
    try {
      await ElMessageBox.confirm(
        '取消后本任务将停止后续抓取，已完成场次保留。确认取消？',
        '取消诊断任务',
        { type: 'warning', confirmButtonText: '确认取消', cancelButtonText: '返回' },
      )
      const latest = await cancelLeadDiagnosis(selectedId.value)
      detail.value = latest
      await loadRecords({ silent: true })
      stopPolling()
      ElMessage.success('已取消，后续场次不再抓取')
    } catch (error: unknown) {
      if (error === 'cancel') return
      notifyOperationError(error, '取消失败')
    }
  }

  async function handleFinalizeEarly() {
    if (!selectedId.value || !canCreate.value || !detail.value) return
    if (detail.value.status !== 'pending' && detail.value.status !== 'collecting') return
    const completed = (detail.value.runs || []).filter(run => run.status === 'completed').length
    if (!completed) {
      ElMessage.warning('至少完成一场抓取后才能提前生成报告')
      return
    }
    // 2026-08-11 - 提前收官勿与取消混淆 - 仅拦 submitted，pending 场次本就是要跳过的
    if ((detail.value.runs || []).some(run => run.status === 'submitted')) {
      ElMessage.warning('尚有场次正在抓取，请等当前场次结束后再提前收官')
      return
    }
    try {
      await ElMessageBox.confirm(
        `将跳过剩余未执行场次，仅用已完成的 ${completed} 场数据汇总生成报告。确认提前结束？`,
        '提前结束并生成报告',
        { type: 'warning', confirmButtonText: '确认收官', cancelButtonText: '返回' },
      )
      const latest = await finalizeLeadDiagnosisEarly(selectedId.value)
      detail.value = latest
      await loadRecords({ silent: true })
      stopPolling()
      ElMessage.success('已提前收官，可下载报告')
    } catch (error: unknown) {
      if (error === 'cancel') return
      notifyOperationError(error, '提前收官失败')
    }
  }

  const activeInflightRunCount = computed(() => (
    (detail.value?.runs || []).filter(run => run.status === 'submitted' || run.status === 'pending').length
  ))

  function canRunScheduleSlot(state: string, entry?: { day: string; slot: string }) {
    if (state === 'completed' || state === 'skipped') return false
    if (state === 'submitted' || state === 'pending') return false
    if (activeInflightRunCount.value >= 2) return false
    if (entry && !isLeadScheduleSlotDue(entry.day, entry.slot)) return false
    return true
  }

  async function handleRunSlot(scheduleKey: string, slotLabel: string) {
    if (!selectedId.value || !canCreate.value) return
    if (submittingSlotKey.value) return
    submittingSlotKey.value = scheduleKey
    try {
      await submitLeadDiagnosisRun(selectedId.value, { force: true, scheduleKey })
      ElMessage.success(`已提交：${slotLabel}`)
      await handleRefresh()
    } catch (error: unknown) {
      notifyOperationError(error, '提交抓取失败')
    } finally {
      submittingSlotKey.value = null
    }
  }

  async function handleExport(format: 'html' = 'html') {
    if (!selectedId.value || detail.value?.status !== 'ready') return
    exporting.value = true
    exportingFormat.value = format
    exportProgress.value = '内容写入中…'
    try {
      const filename = await downloadLeadDiagnosisExport(selectedId.value, format, (label) => {
        exportProgress.value = label
      })
      ElMessage.success(`HTML 已下载：${filename}`)
    } catch (error: unknown) {
      notifyOperationError(error, '导出 HTML 失败')
    } finally {
      exporting.value = false
      exportingFormat.value = null
      exportProgress.value = ''
    }
  }

  const route = useRoute()

  // 2026-08-31 - H5 订单抽屉「链诊断」带 lead_id 跳转后自动选中
  async function loadRecordsAndMaybeSelect(options?: { silent?: boolean }) {
    await loadRecords(options)
    await loadResubmitDraftFromRoute()
    const raw = route.query.lead_id
    const id = Number(Array.isArray(raw) ? raw[0] : raw)
    if (Number.isFinite(id) && id > 0) {
      void selectRecord(id)
    }
  }

  watch(
    () => route.query.resubmit_approval_id,
    () => {
      void loadResubmitDraftFromRoute()
    },
  )

  watch(
    () => route.query.lead_id,
    (raw) => {
      const id = Number(Array.isArray(raw) ? raw[0] : raw)
      if (Number.isFinite(id) && id > 0 && selectedId.value !== id) {
        void selectRecord(id)
      }
    },
  )

  onMounted(() => {
    void loadRecordsAndMaybeSelect()
  })
  onUnmounted(() => {
    stopPolling()
    revokePreviewHtmlBlob()
  })

  return {
    loading,
    saving,
    exporting,
    exportingFormat,
    exportProgress,
    detailLoading,
    previewHtmlLoading,
    previewHtmlUrl,
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
    createScheduleTotal,
    promptQuality,
    generateBalancedPrompts,
    applyPromptTemplate,
    pageMenuName,
    canCreate,
    canExport,
    canEditRegions,
    canReviseConfig,
    configEditing,
    configSaving,
    configEditForm,
    configEditScheduleSlots,
    configScheduleDisplaySlots,
    scheduleDatetimeMinLocal,
    openConfigEdit,
    cancelConfigEdit,
    saveConfigRevise,
    addConfigScheduleSlot,
    removeConfigScheduleSlot,
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
    selectableRegionOptions,
    regionLabels,
    regionLabel,
    diagnosisPlatformOptions,
    promptTemplates: PROMPT_TEMPLATES,
    scheduleSlots: SCHEDULE_SLOTS,
    scheduleDays: SCHEDULE_DAYS,
    scheduleDaysMin: SCHEDULE_DAYS_MIN,
    scheduleDaysMax: SCHEDULE_DAYS_MAX,
    scheduleDaysSuggestMin: SCHEDULE_DAYS_SUGGEST_MIN,
    scheduleDaysSuggestMax: SCHEDULE_DAYS_SUGGEST_MAX,
    scheduleTotal: SCHEDULE_TOTAL,
    clampScheduleDays,
    scheduleTotalForDays,
    runStatusLabels: RUN_STATUS_LABELS,
    statusLabels: LEAD_STATUS_LABELS,
    platformLabelMap,
    formatDateTime,
    formatLeadCreator,
    filledPromptCount,
    scheduleTimeline,
    schedulePlanSummary,
    progressPercent,
    activeInflightRunCount,
    isLeadScheduleSlotDue,
    healthTone,
    loadRecords,
    selectRecord,
    openCreatePanel,
    closeCreatePanel,
    toggleCreatePlatform,
    nextCreateStep,
    submitCreate,
    handleRefresh,
    handleForceRun,
    handleCancel,
    handleFinalizeEarly,
    handleRunSlot,
    canRunScheduleSlot,
    submittingSlotKey,
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
