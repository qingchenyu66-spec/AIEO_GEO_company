<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { EyeOff, RefreshCw, Upload } from '@lucide/vue'
import '../../../styles/snapshot-backfill.css'
import SnapshotBackfillDialog from '../components/SnapshotBackfillDialog.vue'
import SnapshotBackfillDetailDrawer from '../components/SnapshotBackfillDetailDrawer.vue'
import {
  dismissSnapshotBackfill,
  getSnapshotBackfillMatrix,
  undismissSnapshotBackfill,
  type SnapshotBackfillMatrixCell,
  type SnapshotBackfillMatrixPlatform,
  type SnapshotBackfillMatrixSlot,
  type SnapshotBackfillPendingItem,
} from '../../../services/snapshotBackfill'
import { getMonitorSubtask, type MonitorSubtask } from '../../../services/monitor'
import { getTenants, type TenantInfo } from '../../../services/management'
import {
  getBrandAsset,
  formatKeywordGroupDetailHint,
  keywordGroupDisplayName,
  keywordGroupMonitorKeywords,
  keywordGroupSelectValue,
  platformSelectionCodes,
  type BrandKeywordGroup,
} from '../../../services/brand'
import { useAuthStore } from '../../../stores/auth'
import { notifyOperationError } from '../../../utils/requestError'
import { withRetry } from '../../../composables/useRetry'
import { mergeSnapshotBackfillItem } from '../snapshotBackfillDisplay'
import { emitMonitorRefresh } from '../../../utils/monitorRefresh'
import { platformLabelMap, supportedPlatforms } from '../portalMaps'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const backfillMenu = computed(() => auth.allowedMenus.find(menu => menu.menu_code === 'platform.snapshot_backfill'))
const canViewBackfill = computed(() => Boolean(backfillMenu.value?.can_export))
const canSubmitBackfill = computed(() => Boolean(backfillMenu.value?.can_update))

const FILTER_DEBOUNCE_MS = 350

const loading = ref(false)
const tenants = ref<TenantInfo[]>([])
const backfillVisible = ref(false)
const backfillTarget = ref<MonitorSubtask | null>(null)
const detailVisible = ref(false)
const detailLoading = ref(false)
const detailItem = ref<SnapshotBackfillPendingItem | null>(null)
const detailSubtask = ref<MonitorSubtask | null>(null)

const tenantFilter = ref<number | ''>('')
const filterDateFrom = ref('')
const filterDateTo = ref('')
const sourceFilter = ref<'' | 'tenant_monitor' | 'lead_diagnosis'>('')
const platformFilter = ref('')
const keywordGroupFilter = ref('')
const keywordFilter = ref('')
const keywordGroupOptions = ref<BrandKeywordGroup[]>([])
const tenantMonitoredPlatforms = ref<string[]>([])
const todoOnly = ref(true)

const platforms = ref<SnapshotBackfillMatrixPlatform[]>([])
const dates = ref<string[]>([])
const words = ref<string[]>([])
const cells = ref<SnapshotBackfillMatrixCell[]>([])
const activePlatform = ref('')
const cellDrawerVisible = ref(false)
const cellDrawer = ref<SnapshotBackfillMatrixCell | null>(null)

let listRequestSeq = 0
let listAbortController: AbortController | null = null
let filterDebounceTimer: ReturnType<typeof setTimeout> | null = null
let filterBootstrapping = false

function defaultDateRange() {
  const end = new Date()
  const start = new Date()
  start.setDate(end.getDate() - 6)
  const fmt = (d: Date) => {
    const y = d.getFullYear()
    const m = String(d.getMonth() + 1).padStart(2, '0')
    const day = String(d.getDate()).padStart(2, '0')
    return `${y}-${m}-${day}`
  }
  return { from: fmt(start), to: fmt(end) }
}

const platformFilterOptions = computed(() => {
  if (tenantFilter.value === '') return supportedPlatforms
  const codes = new Set<string>()
  for (const group of keywordGroupOptions.value) {
    for (const code of platformSelectionCodes(group.platforms)) {
      if (code) codes.add(code)
    }
  }
  if (!codes.size) {
    for (const code of tenantMonitoredPlatforms.value) {
      if (code) codes.add(code)
    }
  }
  if (!codes.size) return supportedPlatforms
  return supportedPlatforms.filter(platform => codes.has(platform.code))
})

/** 企业配置已购平台（词组∪monitored）；空=未配置，不过滤以免误伤旧数据 */
const configuredPlatformAllow = computed(() => {
  if (tenantFilter.value === '') return null
  const codes = new Set<string>()
  for (const group of keywordGroupOptions.value) {
    for (const code of platformSelectionCodes(group.platforms)) {
      if (code) codes.add(code)
    }
  }
  for (const code of tenantMonitoredPlatforms.value) {
    if (code) codes.add(code)
  }
  return codes.size ? codes : null
})

function platformInConfiguredAllow(code: string, allow: Set<string> | null) {
  // 2026-07-28 - 补录侧栏历史移动端仍出现 - 只认配置精确码，不成对放宽
  if (!allow) return true
  const text = String(code || '').trim()
  return Boolean(text) && allow.has(text)
}

const monitorKeywordOptions = computed(() => {
  const seen = new Set<string>()
  const options: string[] = []
  for (const group of keywordGroupOptions.value) {
    for (const keyword of keywordGroupMonitorKeywords(group)) {
      if (seen.has(keyword)) continue
      seen.add(keyword)
      options.push(keyword)
    }
  }
  return options.sort((left, right) => left.localeCompare(right, 'zh-CN'))
})

const visiblePlatforms = computed(() => (
  todoOnly.value ? platforms.value.filter(p => p.todo > 0) : platforms.value
))

const activePlatformMeta = computed(() => (
  platforms.value.find(p => p.id === activePlatform.value) || null
))

const visibleWords = computed(() => {
  if (!todoOnly.value) return words.value
  const set = new Set(
    cells.value
      .filter(c => c.platform === activePlatform.value && c.has_todo)
      .map(c => c.word),
  )
  const list = words.value.filter(w => set.has(w))
  return list.length ? list : words.value
})

const cellMap = computed(() => {
  const map = new Map<string, SnapshotBackfillMatrixCell>()
  for (const cell of cells.value) {
    if (cell.platform !== activePlatform.value) continue
    map.set(`${cell.word}||${cell.date}`, cell)
  }
  return map
})

function shortDate(iso: string) {
  return iso.length >= 10 ? iso.slice(5) : iso
}

function rankClass(rank: number | null | undefined) {
  if (rank == null) return 'rank-none'
  if (rank <= 3) return 'rank-good'
  return 'rank-mid'
}

function rankText(rank: number | null | undefined) {
  return rank == null ? '—' : String(rank)
}

function getCell(word: string, date: string) {
  return cellMap.value.get(`${word}||${date}`) || null
}

function isTenantInService(tenant: TenantInfo) {
  if (!tenant.status) return false
  if (tenant.stop_reason === 'manual' || tenant.stop_reason === 'canceled') return false
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  if (tenant.service_start_date) {
    const startDate = new Date(`${tenant.service_start_date} 00:00:00`)
    if (startDate.getTime() > today.getTime()) return false
  }
  if (tenant.service_end_date) {
    const endDate = new Date(`${tenant.service_end_date} 23:59:59`)
    if (endDate.getTime() < today.getTime()) return false
  }
  return true
}

async function loadTenants() {
  try {
    const rows = await withRetry(() => getTenants())
    tenants.value = rows.filter(isTenantInService)
  } catch {
    tenants.value = []
  }
  if (
    tenantFilter.value !== ''
    && !tenants.value.some(tenant => tenant.id === tenantFilter.value)
  ) {
    tenantFilter.value = tenants.value[0]?.id ?? ''
  }
}

async function loadTenantKeywordGroups() {
  keywordGroupFilter.value = ''
  keywordFilter.value = ''
  tenantMonitoredPlatforms.value = []
  if (tenantFilter.value === '') {
    keywordGroupOptions.value = []
    return
  }
  try {
    const asset = await getBrandAsset(Number(tenantFilter.value))
    tenantMonitoredPlatforms.value = [...(asset.asset?.monitored_platforms || [])]
    keywordGroupOptions.value = (asset.asset?.keyword_groups || []).filter(
      (group: BrandKeywordGroup) => group.status && (group.monitor_keyword || (group.monitor_keywords || []).length),
    )
  } catch {
    keywordGroupOptions.value = []
    tenantMonitoredPlatforms.value = []
  }
}

function ensureActivePlatform() {
  const list = todoOnly.value ? visiblePlatforms.value : platforms.value
  if (!list.length) {
    activePlatform.value = platforms.value[0]?.id || ''
    return
  }
  if (!list.some(p => p.id === activePlatform.value)) {
    activePlatform.value = list[0].id
  }
}

async function loadMatrix(options?: { quiet?: boolean }) {
  listAbortController?.abort()
  const controller = new AbortController()
  listAbortController = controller
  const seq = ++listRequestSeq
  const quiet = Boolean(options?.quiet)
  if (!quiet) loading.value = true
  try {
    const result = await getSnapshotBackfillMatrix({
      tenant_id: tenantFilter.value === '' ? null : Number(tenantFilter.value),
      date_from: filterDateFrom.value || undefined,
      date_to: filterDateTo.value || undefined,
      source: sourceFilter.value || undefined,
      platform: platformFilter.value || undefined,
      keyword: keywordFilter.value.trim() || undefined,
      keyword_group: keywordGroupFilter.value || undefined,
    }, { signal: controller.signal })
    if (seq !== listRequestSeq) return
    // 2026-07-28 - 全平台对比露出历史/未购 - 侧栏与格子只留配置平台
    const allow = configuredPlatformAllow.value
    const nextCells = (result.cells || []).filter(cell => platformInConfiguredAllow(cell.platform, allow))
    const nextPlatforms = (result.platforms || []).filter(p => platformInConfiguredAllow(p.id, allow))
    const liveWords = new Set(nextCells.map(cell => cell.word))
    platforms.value = nextPlatforms
    dates.value = result.dates || []
    words.value = (result.words || []).filter(word => !liveWords.size || liveWords.has(word))
    cells.value = nextCells
    if (result.date_from && !filterDateFrom.value) filterDateFrom.value = result.date_from
    if (result.date_to && !filterDateTo.value) filterDateTo.value = result.date_to
    ensureActivePlatform()
  } catch (error: unknown) {
    if (error instanceof DOMException && error.name === 'AbortError') return
    if ((error as { code?: string })?.code === 'ERR_CANCELED') return
    notifyOperationError(error, '加载补录矩阵失败')
  } finally {
    if (seq === listRequestSeq && !quiet) loading.value = false
  }
}

function scheduleLoadMatrix() {
  if (!canViewBackfill.value) return
  if (filterDebounceTimer) clearTimeout(filterDebounceTimer)
  filterDebounceTimer = setTimeout(() => {
    filterDebounceTimer = null
    void loadMatrix()
  }, FILTER_DEBOUNCE_MS)
}

function selectPlatform(id: string) {
  activePlatform.value = id
  if (todoOnly.value) {
    const p = platforms.value.find(x => x.id === id)
    if (p && p.todo === 0) {
      const first = visiblePlatforms.value[0]
      if (first) activePlatform.value = first.id
    }
  }
}

function openCell(word: string, date: string) {
  const cell = getCell(word, date)
  if (!cell) return
  cellDrawer.value = cell
  cellDrawerVisible.value = true
}

function closeCellDrawer() {
  cellDrawerVisible.value = false
  cellDrawer.value = null
}

function averageRanks(ranks: number[]) {
  if (!ranks.length) return null
  const total = ranks.reduce((sum, value) => sum + value, 0)
  return Math.round((total / ranks.length) * 10) / 10
}

function cellHasTodo(ranks: number[], sampleCount: number) {
  // 2026-07-28 - 红点口径：日均位次>3 或有场次但算不出均值；≤3 不标（含刚好=3）
  if (sampleCount <= 0) return false
  if (!ranks.length) return true
  const avg = averageRanks(ranks)
  return avg == null ? true : avg > 3
}

function recomputeCell(cell: SnapshotBackfillMatrixCell): SnapshotBackfillMatrixCell {
  const ranks: number[] = []
  let failCount = 0
  for (const slot of cell.slots) {
    if (slot.mention_position != null && Number.isFinite(Number(slot.mention_position))) {
      ranks.push(Number(slot.mention_position))
    }
    if (slot.needs_backfill && !slot.has_answer) failCount += 1
  }
  return {
    ...cell,
    rank: averageRanks(ranks),
    fail_count: failCount,
    sample_count: cell.slots.length,
    rank_sample_count: ranks.length,
    has_todo: cellHasTodo(ranks, cell.slots.length),
  }
}

function refreshPlatformStats(platformId: string) {
  const platCells = cells.value.filter(cell => cell.platform === platformId)
  const idx = platforms.value.findIndex(p => p.id === platformId)
  if (idx < 0) return
  const avgs = platCells
    .map(cell => cell.rank)
    .filter((rank): rank is number => rank != null && Number.isFinite(rank))
  platforms.value[idx] = {
    ...platforms.value[idx],
    todo: platCells.filter(cell => cell.has_todo).length,
    fail: platCells.reduce((sum, cell) => sum + (cell.fail_count || 0), 0),
    avg: averageRanks(avgs),
  }
}

/** 补录/忽略后只改本地场次，不整表重拉 */
function patchSlotLocally(
  subtaskId: string,
  patch: Partial<SnapshotBackfillMatrixSlot>,
) {
  let touchedPlatform = ''
  cells.value = cells.value.map((cell) => {
    const idx = cell.slots.findIndex(slot => slot.subtask_id === subtaskId)
    if (idx < 0) return cell
    touchedPlatform = cell.platform
    const slots = cell.slots.slice()
    slots[idx] = { ...slots[idx], ...patch }
    return recomputeCell({ ...cell, slots })
  })
  if (touchedPlatform) refreshPlatformStats(touchedPlatform)
  if (cellDrawer.value) {
    const refreshed = getCell(cellDrawer.value.word, cellDrawer.value.date)
    if (refreshed) cellDrawer.value = refreshed
  }
}

function slotToItem(slot: SnapshotBackfillMatrixSlot): SnapshotBackfillPendingItem {
  return {
    subtask_id: slot.subtask_id,
    task_id: slot.task_id || '',
    tenant_id: slot.tenant_id ?? null,
    tenant_name: slot.tenant_name ?? null,
    platform: slot.platform || activePlatform.value,
    prompt: slot.prompt || cellDrawer.value?.word || '',
    error_message: slot.error_message ?? null,
    source: (slot.source as SnapshotBackfillPendingItem['source']) || 'tenant_monitor',
    monitor_keywords: slot.monitor_keywords ?? null,
    task_status: slot.status ?? null,
    updated_at: slot.updated_at ?? null,
    needs_backfill: slot.needs_backfill,
    has_answer: slot.has_answer,
    status: slot.status ?? null,
    mention_position: slot.mention_position ?? null,
    keyword_group: slot.keyword_group ?? null,
    brand_name: slot.brand_name ?? null,
    schedule_label: slot.schedule_label ?? null,
    schedule_window_key: slot.schedule_window_key ?? null,
  }
}

async function loadSubtask(subtaskId: string) {
  return getMonitorSubtask(subtaskId, { include_ops: true })
}

async function openDetail(item: SnapshotBackfillPendingItem) {
  detailItem.value = item
  detailVisible.value = true
  detailLoading.value = true
  detailSubtask.value = null
  try {
    detailSubtask.value = await loadSubtask(item.subtask_id)
    detailItem.value = mergeSnapshotBackfillItem(item, detailSubtask.value)
  } catch (error: unknown) {
    notifyOperationError(error, '加载快照详情失败')
    detailVisible.value = false
  } finally {
    detailLoading.value = false
  }
}

async function openDetailById(subtaskId: string, item: SnapshotBackfillPendingItem | null = null) {
  if (item) {
    await openDetail(item)
    return
  }
  detailItem.value = {
    subtask_id: subtaskId,
    task_id: '',
    tenant_id: null,
    tenant_name: null,
    platform: '',
    prompt: '',
    error_message: null,
    source: 'tenant_monitor',
    monitor_keywords: null,
    task_status: null,
    updated_at: null,
  }
  detailVisible.value = true
  detailLoading.value = true
  detailSubtask.value = null
  try {
    detailSubtask.value = await loadSubtask(subtaskId)
    detailItem.value = mergeSnapshotBackfillItem(detailItem.value, detailSubtask.value)
  } catch (error: unknown) {
    notifyOperationError(error, '未找到该子任务')
    detailVisible.value = false
  } finally {
    detailLoading.value = false
  }
}

function openBackfillFromDetail() {
  if (!canSubmitBackfill.value || !detailSubtask.value) return
  backfillTarget.value = detailSubtask.value
  backfillVisible.value = true
}

async function openBackfillFromSlot(slot: SnapshotBackfillMatrixSlot) {
  if (!canSubmitBackfill.value) return
  try {
    backfillTarget.value = await loadSubtask(slot.subtask_id)
    backfillVisible.value = true
  } catch (error: unknown) {
    notifyOperationError(error, '加载子任务失败')
  }
}

function isFailurePending(slot: SnapshotBackfillMatrixSlot) {
  return Boolean(slot.needs_backfill) && !slot.has_answer
}

async function dismissSlot(slot: SnapshotBackfillMatrixSlot) {
  if (!canSubmitBackfill.value || !slot.needs_backfill) return
  try {
    if (isFailurePending(slot)) {
      await ElMessageBox.confirm(
        '当前无有效回答，忽略后将不再提醒补录，客户侧仍按未抓取/失败统计（不会补出排名）。确认忽略？',
        '忽略待补录',
        { type: 'warning', confirmButtonText: '确认忽略', cancelButtonText: '取消' },
      )
    }
    await dismissSnapshotBackfill(slot.subtask_id)
    // 2026-07-28 - 忽略只消提醒 - 保留场次排名/快照，本地清 needs_backfill，勿 removeSlot
    patchSlotLocally(slot.subtask_id, {
      needs_backfill: false,
      backfill_dismissed: true,
    })
    ElMessage.success('已忽略，不再提醒')
    emitMonitorRefresh({ tenantId: tenantFilter.value === '' ? null : Number(tenantFilter.value) })
  } catch (error: unknown) {
    if (error === 'cancel') return
    notifyOperationError(error, '忽略失败')
  }
}

async function undismissFromDetail() {
  const subtaskId = detailItem.value?.subtask_id || detailSubtask.value?.subtask_id
  if (!canSubmitBackfill.value || !subtaskId) return
  try {
    const result = await undismissSnapshotBackfill(subtaskId)
    ElMessage.success(result.item.needs_backfill ? '已取消忽略，已重新纳入待补录' : '已取消忽略')
    // 取消忽略需重新进矩阵桶，安静重拉一次即可
    await loadMatrix({ quiet: true })
    emitMonitorRefresh({ tenantId: tenantFilter.value === '' ? null : Number(tenantFilter.value) })
    await openDetailById(subtaskId, result.item)
  } catch (error: unknown) {
    notifyOperationError(error, '取消忽略失败')
  }
}

async function handleSuccess(updatedSubtask?: MonitorSubtask) {
  const activeId = updatedSubtask?.subtask_id || detailItem.value?.subtask_id
  if (updatedSubtask?.subtask_id) {
    patchSlotLocally(updatedSubtask.subtask_id, {
      mention_position: updatedSubtask.mention_position ?? null,
      needs_backfill: updatedSubtask.needs_backfill ?? false,
      has_answer: Boolean(updatedSubtask.answer_content),
      status: updatedSubtask.status ?? null,
      error_message: updatedSubtask.error_message ?? null,
    })
  } else {
    await loadMatrix({ quiet: true })
  }
  emitMonitorRefresh({ tenantId: tenantFilter.value === '' ? null : Number(tenantFilter.value) })

  if (detailVisible.value && activeId) {
    if (updatedSubtask?.subtask_id === activeId) {
      detailSubtask.value = updatedSubtask
      const baseItem = detailItem.value || backfillItemFromSubtask(updatedSubtask)
      detailItem.value = mergeSnapshotBackfillItem(baseItem, updatedSubtask)
    } else {
      await openDetailById(activeId, detailItem.value)
    }
  }

  ElMessage.success('快照补录已保存')
  clearDeepLink()
}

function backfillItemFromSubtask(subtask: MonitorSubtask): SnapshotBackfillPendingItem {
  return {
    subtask_id: subtask.subtask_id,
    task_id: subtask.task_id || '',
    tenant_id: subtask.tenant_id ?? null,
    tenant_name: subtask.tenant_name ?? null,
    platform: subtask.platform,
    prompt: subtask.prompt,
    error_message: subtask.error_message ?? null,
    source: (subtask.source as SnapshotBackfillPendingItem['source']) || 'tenant_monitor',
    monitor_keywords: subtask.monitor_keywords ?? null,
    task_status: subtask.status ?? null,
    updated_at: subtask.updated_at ?? null,
    mention_position: subtask.mention_position ?? null,
    has_answer: Boolean(subtask.answer_content),
    needs_backfill: subtask.needs_backfill ?? false,
    backfill_dismissed: subtask.backfill_dismissed ?? false,
    status: subtask.status ?? null,
  }
}

function clearDeepLink() {
  const nextQuery = { ...route.query }
  delete nextQuery.subtask_id
  delete nextQuery.backfill
  void router.replace({ query: nextQuery })
}

function resetFilters() {
  const range = defaultDateRange()
  tenantFilter.value = tenants.value[0]?.id ?? ''
  filterDateFrom.value = range.from
  filterDateTo.value = range.to
  sourceFilter.value = ''
  platformFilter.value = ''
  keywordGroupFilter.value = ''
  keywordFilter.value = ''
  keywordGroupOptions.value = []
  tenantMonitoredPlatforms.value = []
  todoOnly.value = true
  void loadTenantKeywordGroups().then(() => loadMatrix())
}

async function openFromQuery() {
  const subtaskId = String(route.query.subtask_id || '').trim()
  if (!subtaskId) return
  const wantBackfill = String(route.query.backfill || '') === '1'
  await openDetailById(subtaskId)
  if (wantBackfill && canSubmitBackfill.value && detailSubtask.value) {
    openBackfillFromDetail()
  }
}

function slotStatusLabel(slot: SnapshotBackfillMatrixSlot) {
  if (slot.needs_backfill && !slot.has_answer) return '失败待补'
  if (slot.needs_backfill) return '待补录'
  if (slot.has_answer) return '已有结果'
  return slot.status || '—'
}

onMounted(async () => {
  const range = defaultDateRange()
  filterDateFrom.value = range.from
  filterDateTo.value = range.to
  if (!canViewBackfill.value) {
    await loadTenants()
    return
  }
  await loadTenants()
  // 2026-07-28 - 通知 deep-link - 用企业/日期/平台打开矩阵，勿丢筛选
  const qTenant = String(route.query.tenant_id || '').trim()
  const qFrom = String(route.query.date_from || '').trim()
  const qTo = String(route.query.date_to || '').trim()
  const qPlatform = String(route.query.platform || '').trim()
  filterBootstrapping = true
  if (qTenant && tenants.value.some(t => String(t.id) === qTenant)) {
    tenantFilter.value = Number(qTenant)
  }
  if (qFrom) filterDateFrom.value = qFrom
  if (qTo) filterDateTo.value = qTo
  if (qPlatform) platformFilter.value = qPlatform
  filterBootstrapping = false
  const hasDeepLink = String(route.query.backfill || '') === '1' || Boolean(route.query.subtask_id)
  if (!hasDeepLink && !qTenant && tenantFilter.value === '' && tenants.value.length) {
    filterBootstrapping = true
    tenantFilter.value = tenants.value[0].id
    filterBootstrapping = false
  }
  await loadTenantKeywordGroups()
  await loadMatrix()
  if (hasDeepLink) await openFromQuery()
})

onUnmounted(() => {
  if (filterDebounceTimer) clearTimeout(filterDebounceTimer)
  listAbortController?.abort()
})

watch(
  () => route.query.subtask_id,
  async () => {
    if (route.query.subtask_id) await openFromQuery()
  },
)

watch(tenantFilter, () => {
  // 先拉词组/已购平台，再刷矩阵，避免侧栏过滤用到空配置
  void loadTenantKeywordGroups().then(() => {
    if (filterBootstrapping) return
    scheduleLoadMatrix()
  })
})

watch(platformFilterOptions, (options) => {
  if (!platformFilter.value) return
  if (!options.some(platform => platform.code === platformFilter.value)) {
    platformFilter.value = ''
  }
})

watch(todoOnly, () => {
  ensureActivePlatform()
})

watch(
  [filterDateFrom, filterDateTo, sourceFilter, platformFilter, keywordGroupFilter, keywordFilter],
  () => {
    if (filterBootstrapping) return
    scheduleLoadMatrix()
  },
)
</script>

<template>
  <section v-if="!canViewBackfill" class="snapshot-backfill-page snapshot-backfill-denied">
    <div class="mini-empty">
      <p>当前身份无「快照补录」查看权限（需岗位授予 can_export）。</p>
      <p>如需处理失败抓取，请联系管理员在岗位权限中开启快照补录查看与补录操作。</p>
    </div>
  </section>
  <section v-else class="snapshot-backfill-page sb-skin">
    <div class="snapshot-backfill-toolbar">
      <div class="snapshot-backfill-toolbar-inner">
        <select v-model="tenantFilter" title="企业">
          <option value="">全部企业</option>
          <option v-for="tenant in tenants" :key="tenant.id" :value="tenant.id">
            {{ tenant.name }}
          </option>
        </select>
        <input v-model="filterDateFrom" type="date" title="开始日期">
        <span class="sb-range-sep">至</span>
        <input v-model="filterDateTo" type="date" title="结束日期">
        <select v-model="sourceFilter" title="来源">
          <option value="">全部来源</option>
          <option value="tenant_monitor">GEO 监测</option>
          <option value="lead_diagnosis">售前诊断</option>
        </select>
        <select v-model="platformFilter" title="平台">
          <option value="">全部平台</option>
          <option v-for="platform in platformFilterOptions" :key="platform.code" :value="platform.code">
            {{ platform.name }}
          </option>
        </select>
        <select
          v-model="keywordGroupFilter"
          class="snapshot-backfill-group-select"
          :disabled="!keywordGroupOptions.length"
          :title="tenantFilter ? '词组' : '请先选择企业'"
        >
          <option value="">{{ tenantFilter ? '全部词组' : '先选企业' }}</option>
          <option
            v-for="(group, index) in keywordGroupOptions"
            :key="keywordGroupSelectValue(group, index)"
            :value="keywordGroupSelectValue(group, index)"
            :title="formatKeywordGroupDetailHint(group)"
          >
            {{ keywordGroupDisplayName(group, index) }}
          </option>
        </select>
        <select
          v-model="keywordFilter"
          class="snapshot-backfill-keyword-input"
          :disabled="!monitorKeywordOptions.length"
          :title="tenantFilter ? '监测词' : '请先选择企业'"
        >
          <option value="">{{ tenantFilter ? '全部监测词' : '先选企业' }}</option>
          <option v-for="keyword in monitorKeywordOptions" :key="keyword" :value="keyword">
            {{ keyword }}
          </option>
        </select>
        <label class="sb-toggle" :class="{ on: todoOnly }">
          <input v-model="todoOnly" type="checkbox">
          只看待补
        </label>
        <div class="snapshot-backfill-toolbar-actions">
          <span v-if="loading" class="snapshot-backfill-loading-dot">加载中…</span>
          <button type="button" class="filter-reset-btn tiny-btn" @click="resetFilters">重置</button>
          <button type="button" class="filter-reset-btn tiny-btn" :disabled="loading" @click="() => loadMatrix()">
            <RefreshCw :size="14" />
            刷新
          </button>
        </div>
      </div>
    </div>

    <div class="sb-layout">
      <section class="sb-panel sb-main">
        <div class="sb-main-head">
          <div class="sb-platform-title">
            <div class="sb-platform-logo">
              {{ (activePlatformMeta?.name || activePlatform || '—').slice(0, 1) }}
            </div>
            <div>
              <h2>{{ activePlatformMeta?.name || platformLabelMap[activePlatform] || activePlatform || '—' }}</h2>
              <p>{{ todoOnly ? '只看待补格子' : '全量词 × 日均位' }}</p>
            </div>
          </div>
          <div class="sb-kpis">
            <div class="sb-kpi primary">
              <strong>{{ activePlatformMeta?.todo ?? 0 }}</strong>
              <span>待补录</span>
            </div>
            <div class="sb-kpi">
              <strong>{{ activePlatformMeta?.fail ?? 0 }}</strong>
              <span>失败未忽略</span>
            </div>
            <div class="sb-kpi secondary">
              <strong>{{ activePlatformMeta?.avg ?? '—' }}</strong>
              <span>均位</span>
            </div>
          </div>
        </div>

        <div v-if="loading" class="mini-empty">加载中…</div>
        <div v-else-if="!visibleWords.length || !dates.length" class="mini-empty snapshot-backfill-empty">
          当前筛选下没有矩阵数据
        </div>
        <template v-else>
          <div class="sb-matrix-wrap">
            <table class="sb-matrix">
              <thead>
                <tr>
                  <th>监测词 \\ 日期</th>
                  <th v-for="d in dates" :key="d">{{ shortDate(d) }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="word in visibleWords" :key="word">
                  <th :title="word">{{ word }}</th>
                  <td v-for="d in dates" :key="`${word}-${d}`">
                    <button
                      v-if="getCell(word, d)"
                      type="button"
                      class="sb-cell"
                      :class="[
                        rankClass(getCell(word, d)?.rank),
                        { 'has-todo': getCell(word, d)?.has_todo },
                      ]"
                      @click="openCell(word, d)"
                    >
                      <span>{{ rankText(getCell(word, d)?.rank) }}</span>
                      <small>{{ getCell(word, d)?.sample_count || 0 }}次</small>
                    </button>
                    <span v-else class="sb-cell rank-none is-empty">—</span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <div class="sb-legend">
            <span><i class="sb-swatch" style="background:#e6f7ef" />1–3</span>
            <span><i class="sb-swatch" style="background:#fff3d9" />4+</span>
            <span><i class="sb-swatch" style="background:#eef1f4" />无位次</span>
            <span>
              <i class="sb-swatch" style="background:#fde8e2;outline:2px solid #e4572e;outline-offset:1px" />
              暖色+红点 = 待补
            </span>
          </div>
        </template>
      </section>

      <aside class="sb-panel sb-side">
        <h3>全平台对比</h3>
        <div class="sb-plat-list">
          <button
            v-for="p in platforms"
            :key="p.id"
            type="button"
            class="sb-plat-card"
            :class="{ active: p.id === activePlatform, dim: todoOnly && p.todo <= 0 }"
            @click="selectPlatform(p.id)"
          >
            <div class="row1">
              <span class="name">{{ p.name }}</span>
              <span class="meta">{{ words.length }}词</span>
            </div>
            <div class="stats">
              <div class="hi"><strong>{{ p.todo }}</strong><span>待补</span></div>
              <div><strong>{{ p.fail }}</strong><span>失败</span></div>
              <div><strong>{{ p.avg ?? '—' }}</strong><span>均位</span></div>
            </div>
          </button>
        </div>
      </aside>
    </div>

    <div v-if="cellDrawerVisible && cellDrawer" class="sb-drawer" @click.self="closeCellDrawer">
      <div class="sb-drawer-panel">
        <h3>格子待办</h3>
        <div class="sub">
          {{ activePlatformMeta?.name || activePlatform }} · {{ cellDrawer.word }} · {{ cellDrawer.date }}
          · 均位 {{ rankText(cellDrawer.rank) }}
        </div>
        <div
          v-for="slot in cellDrawer.slots"
          :key="slot.subtask_id"
          class="sb-todo-item"
        >
          <div class="t">{{ slot.schedule_label || slot.schedule_window_key || '场次' }} · {{ slotStatusLabel(slot) }}</div>
          <div class="d">
            位次 {{ rankText(slot.mention_position) }}
            <template v-if="slot.error_message"> · {{ slot.error_message }}</template>
          </div>
          <div class="sb-todo-actions">
            <button type="button" class="sb-btn ghost" @click="openDetail(slotToItem(slot))">详情</button>
            <button
              v-if="canSubmitBackfill"
              type="button"
              class="sb-btn"
              @click="openBackfillFromSlot(slot)"
            >
              <Upload :size="14" />
              补录
            </button>
            <button
              v-if="canSubmitBackfill && slot.needs_backfill"
              type="button"
              class="sb-btn ghost"
              @click="dismissSlot(slot)"
            >
              <EyeOff :size="14" />
              忽略
            </button>
          </div>
        </div>
        <button type="button" class="sb-btn ghost" @click="closeCellDrawer">关闭</button>
      </div>
    </div>

    <SnapshotBackfillDetailDrawer
      v-model:visible="detailVisible"
      :loading="detailLoading"
      :item="detailItem"
      :subtask="detailSubtask"
      :can-submit="canSubmitBackfill"
      @backfill="openBackfillFromDetail"
      @undismiss="undismissFromDetail"
    />

    <SnapshotBackfillDialog
      v-model:visible="backfillVisible"
      :subtask="backfillTarget"
      @success="handleSuccess"
    />
  </section>
</template>
