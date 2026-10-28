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
  dismissSnapshotBackfillBatch,
  type SnapshotBackfillBatchDismissSlot,
  ensureGapBackfillSubtask,
  getPendingSnapshotBackfills,
  getSnapshotBackfillMatrix,
  undismissSnapshotBackfill,
  waitForBackfillParse,
  type SnapshotBackfillMatrixCell,
  type SnapshotBackfillMatrixPlatform,
  type SnapshotBackfillMatrixSlot,
  type SnapshotBackfillListSummary,
  type SnapshotBackfillPendingItem,
} from '../../../services/snapshotBackfill'
import { getMonitorSubtask, type MonitorSubtask } from '../../../services/monitor'
import { getTenants, isTenantInService, type TenantInfo } from '../../../services/management'
import {
  getBrandAsset,
  formatKeywordGroupDetailHint,
  keywordGroupDisplayName,
  keywordGroupMonitorKeywords,
  keywordGroupSelectValue,
  platformSelectionCodes,
  type BrandKeywordGroup,
  type BrandWordGroup,
} from '../../../services/brand'
import { useAuthStore } from '../../../stores/auth'
import { notifyOperationError } from '../../../utils/requestError'
import { withRetry } from '../../../composables/useRetry'
import { mergeSnapshotBackfillItem } from '../snapshotBackfillDisplay'
import { mergeSnapshotBackfillMobilePage } from '../snapshotBackfillMobile'
import { emitMonitorRefresh } from '../../../utils/monitorRefresh'
import { platformLabelMap, supportedPlatforms } from '../portalMaps'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const backfillMenu = computed(() => auth.allowedMenus.find(menu => menu.menu_code === 'platform.snapshot_backfill'))
const canViewBackfill = computed(() => Boolean(backfillMenu.value?.can_export))
const canSubmitBackfill = computed(() => Boolean(backfillMenu.value?.can_update))

const FILTER_DEBOUNCE_MS = 350
const MOBILE_PAGE_SIZE = 24
const MOBILE_BREAKPOINT = '(max-width: 767px)'

const loading = ref(false)
const batchDismissLoading = ref(false)
const tenants = ref<TenantInfo[]>([])
const backfillVisible = ref(false)
const backfillTarget = ref<MonitorSubtask | null>(null)
const detailVisible = ref(false)
const detailLoading = ref(false)
const detailItem = ref<SnapshotBackfillPendingItem | null>(null)
const detailSubtask = ref<MonitorSubtask | null>(null)
const isMobileViewport = ref(false)
const mobileFiltersOpen = ref(false)
const mobileItems = ref<SnapshotBackfillPendingItem[]>([])
const mobileSummary = ref<SnapshotBackfillListSummary | null>(null)
const mobileLoadingMore = ref(false)

const tenantFilter = ref<number | ''>('')
const filterDateFrom = ref('')
const filterDateTo = ref('')
const sourceFilter = ref<'' | 'tenant_monitor' | 'lead_diagnosis'>('')
const purposeFilter = ref<'geo' | 'brand_word'>('geo')
const platformFilter = ref('')
const keywordGroupFilter = ref('')
const keywordFilter = ref('')
const keywordGroupOptions = ref<Array<BrandKeywordGroup | BrandWordGroup>>([])
const tenantMonitoredPlatforms = ref<string[]>([])
const todoOnly = ref(true)
// 2026-09-01 - 默认日常补录单表；打开才左右对照（词列共用）
const showBeforeCompare = ref(false)

const platforms = ref<SnapshotBackfillMatrixPlatform[]>([])
const dates = ref<string[]>([])
const words = ref<string[]>([])
const cells = ref<SnapshotBackfillMatrixCell[]>([])
const activePlatform = ref('')
const cellDrawerVisible = ref(false)
const cellDrawer = ref<SnapshotBackfillMatrixCell | null>(null)
/** 从「补录前」打开：可点开看，不可补录/忽略 */
const cellDrawerAllowBackfill = ref(true)

type ComparePaneId = 'before' | 'after'
const comparePanes: Array<{ id: ComparePaneId; label: string }> = [
  { id: 'before', label: '补录前' },
  { id: 'after', label: '补录后' },
]
let compareScrollSyncing = false

/** 2026-09-01 - 词列/补录前/补录后：纵滚全同步；左右热力横滚互相同步 */
function onCompareScroll(event: Event) {
  if (compareScrollSyncing) return
  const source = event.currentTarget
  if (!(source instanceof HTMLElement)) return
  const root = source.closest('.sb-compare')
  if (!root) return
  const sourceAxis = source.dataset.compareAxis || 'xy'
  compareScrollSyncing = true
  root.querySelectorAll<HTMLElement>('[data-compare-scroll]').forEach((el) => {
    if (el === source) return
    el.scrollTop = source.scrollTop
    if (sourceAxis === 'xy' && el.dataset.compareAxis === 'xy') {
      el.scrollLeft = source.scrollLeft
    }
  })
  requestAnimationFrame(() => {
    compareScrollSyncing = false
  })
}

let listRequestSeq = 0
let listAbortController: AbortController | null = null
// 2026-09-02 - A：关窗后后台轮询解析结果
const parsePollControllers = new Map<string, AbortController>()
let filterDebounceTimer: ReturnType<typeof setTimeout> | null = null
let filterBootstrapping = false
let mobileMediaQuery: MediaQueryList | null = null

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

/** 筛选项「全部平台」：主区按端分块竖铺热力 */
const isAllPlatformsView = computed(() => !platformFilter.value)

// visiblePlatforms / 前后 lookup / KPI 在 recomputeCell 之后定义

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

function platformDisplayName(code: string) {
  return platforms.value.find(p => p.id === code)?.name
    || platformLabelMap[code]
    || code
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
    // 2026-09-08 - 品牌词轨用品牌词组筛选
    const groups = purposeFilter.value === 'brand_word'
      ? (asset.asset?.brand_word_groups || [])
      : (asset.asset?.keyword_groups || [])
    keywordGroupOptions.value = groups.filter(
      (group: BrandKeywordGroup | BrandWordGroup) => Boolean(
        group.status && (group.monitor_keyword || (group.monitor_keywords || []).length),
      ),
    )
  } catch {
    keywordGroupOptions.value = []
    tenantMonitoredPlatforms.value = []
  }
}

function ensureActivePlatform() {
  const list = todoOnly.value ? visiblePlatforms.value : displayPlatforms.value
  if (!list.length) {
    activePlatform.value = displayPlatforms.value[0]?.id || platforms.value[0]?.id || ''
    return
  }
  if (!list.some(p => p.id === activePlatform.value)) {
    activePlatform.value = list[0].id
  }
}

async function loadMobileItems(options?: { append?: boolean; quiet?: boolean }) {
  listAbortController?.abort()
  const controller = new AbortController()
  listAbortController = controller
  const seq = ++listRequestSeq
  const append = Boolean(options?.append)
  const quiet = Boolean(options?.quiet)
  const offset = append ? mobileItems.value.length : 0
  if (append) mobileLoadingMore.value = true
  else if (!quiet) loading.value = true
  try {
    const result = await getPendingSnapshotBackfills({
      tenant_id: tenantFilter.value === '' ? null : Number(tenantFilter.value),
      date_from: filterDateFrom.value || undefined,
      date_to: filterDateTo.value || undefined,
      source: sourceFilter.value || undefined,
      platform: platformFilter.value || undefined,
      keyword: keywordFilter.value.trim() || undefined,
      keyword_group: keywordGroupFilter.value || undefined,
      purpose: purposeFilter.value,
      pending_only: todoOnly.value,
      offset,
      limit: MOBILE_PAGE_SIZE,
      include_summary: true,
    }, { signal: controller.signal })
    if (seq !== listRequestSeq) return
    if (append) {
      mobileItems.value = mergeSnapshotBackfillMobilePage(mobileItems.value, result.items)
    } else {
      mobileItems.value = result.items
    }
    mobileSummary.value = result.summary
  } catch (error: unknown) {
    if (error instanceof DOMException && error.name === 'AbortError') return
    if ((error as { code?: string })?.code === 'ERR_CANCELED') return
    notifyOperationError(error, '加载待补录任务失败')
  } finally {
    if (seq === listRequestSeq) {
      if (!quiet) loading.value = false
      mobileLoadingMore.value = false
    }
  }
}

async function loadDesktopMatrix(options?: { quiet?: boolean; skipCache?: boolean }) {
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
      purpose: purposeFilter.value,
      skip_cache: options?.skipCache || undefined,
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
    if (platformFilter.value) {
      activePlatform.value = platformFilter.value
    } else {
      ensureActivePlatform()
    }
    // 2026-08-04 - 缺口忽略后抽屉仍显示漏跑 - 矩阵重拉后同步格子待办
    syncCellDrawerFromMatrix()
    // 2026-09-02 - 刷新后矩阵仍 pending 时自动续轮，勿只靠本次提交触发
    resumePendingParsePolls()
  } catch (error: unknown) {
    if (error instanceof DOMException && error.name === 'AbortError') return
    if ((error as { code?: string })?.code === 'ERR_CANCELED') return
    notifyOperationError(error, '加载补录矩阵失败')
  } finally {
    if (seq === listRequestSeq && !quiet) loading.value = false
  }
}

async function loadMatrix(options?: { quiet?: boolean; skipCache?: boolean }) {
  if (isMobileViewport.value) {
    await loadMobileItems({ quiet: options?.quiet })
    return
  }
  await loadDesktopMatrix(options)
}

/** 扫描矩阵 pending 槽位，已在轮询的跳过，避免刷新丢续等。 */
function resumePendingParsePolls() {
  const seen = new Set<string>()
  for (const cell of cells.value) {
    for (const slot of cell.slots || []) {
      const sid = String(slot.subtask_id || '').trim()
      if (!sid || seen.has(sid)) continue
      if (String(slot.backfill_parse_status || '').toLowerCase() !== 'pending') continue
      seen.add(sid)
      if (parsePollControllers.has(sid)) continue
      // 2026-09-02 - 刷新续轮静默完成，勿连开详情/连弹成功
      void handleParseQueued({
        subtask_id: sid,
        answer_content: slot.has_answer ? '1' : '',
      } as MonitorSubtask, { silent: true })
    }
  }
}

function syncCellDrawerFromMatrix() {
  if (!cellDrawerVisible.value || !cellDrawer.value) return
  const current = cellDrawer.value
  const refreshed = getCell(current.word, current.date, current.platform)
  if (!refreshed) {
    closeCellDrawer()
    return
  }
  cellDrawer.value = refreshed
  // 2026-08-21 - 方案 A：全忽略后仍要能展开已忽略，勿因 todoOnly 关抽屉
  maybeCloseCellDrawerAfterTodoClear(refreshed)
}

function cellHasDismissedSlots(cell: SnapshotBackfillMatrixCell | null | undefined) {
  return Boolean(cell?.slots?.some(slot => slot.backfill_dismissed))
}

function maybeCloseCellDrawerAfterTodoClear(cell: SnapshotBackfillMatrixCell | null | undefined) {
  if (!todoOnly.value) return
  if (!cell) {
    closeCellDrawer()
    return
  }
  if (!cell.has_todo && !cellHasDismissedSlots(cell)) {
    closeCellDrawer()
  }
}

const showDismissedSlots = ref(false)

function slotWindowKey(slot: SnapshotBackfillMatrixSlot) {
  return String(slot.schedule_window_key || slot.schedule_label || slot.subtask_id || '').trim()
}

/** 同窗多条时抽屉/对照只留一条（与后端去重口径一致） */
function preferMatrixSlot(a: SnapshotBackfillMatrixSlot, b: SnapshotBackfillMatrixSlot) {
  const score = (slot: SnapshotBackfillMatrixSlot) => (
    (slot.backfill_dismissed ? 0 : 1) * 10000
    + (slot.is_gap ? 0 : 1) * 1000
    + (slot.has_answer && !slot.needs_backfill ? 1 : 0) * 100
    + (slot.has_before_backfill ? 1 : 0) * 10
    + (slot.mention_position != null ? 1 : 0)
  )
  return score(a) >= score(b) ? a : b
}

function dedupeDrawerSlots(slots: SnapshotBackfillMatrixSlot[]) {
  const best = new Map<string, SnapshotBackfillMatrixSlot>()
  const order: string[] = []
  let anon = 0
  for (const slot of slots) {
    let key = slotWindowKey(slot)
    if (!key) {
      key = `anon:${anon}`
      anon += 1
    }
    const prev = best.get(key)
    if (!prev) {
      best.set(key, slot)
      order.push(key)
      continue
    }
    best.set(key, preferMatrixSlot(prev, slot))
  }
  return order.map(key => best.get(key)!).filter(Boolean)
}

const drawerActiveSlots = computed(() => {
  const slots = dedupeDrawerSlots(cellDrawer.value?.slots || [])
  // 2026-08-21 - 方案 A：默认只列未忽略；已忽略靠开关展开
  return slots.filter(slot => !slot.backfill_dismissed)
})

const drawerDismissedSlots = computed(() => {
  const slots = dedupeDrawerSlots(cellDrawer.value?.slots || [])
  return slots.filter(slot => Boolean(slot.backfill_dismissed))
})


function scheduleLoadMatrix() {
  if (!canViewBackfill.value) return
  if (filterDebounceTimer) clearTimeout(filterDebounceTimer)
  filterDebounceTimer = setTimeout(() => {
    filterDebounceTimer = null
    void loadMatrix()
  }, FILTER_DEBOUNCE_MS)
}

function selectPlatform(id: string) {
  // 2026-07-30 - 全部平台分块竖铺 - 侧栏点端滚动到对应热力块；单端筛选时切该端
  if (isAllPlatformsView.value) {
    activePlatform.value = id
    document.getElementById(`sb-plat-block-${id}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    return
  }
  if (platformFilter.value !== id) {
    platformFilter.value = id
    return
  }
  activePlatform.value = id
  if (todoOnly.value) {
    const p = platforms.value.find(x => x.id === id)
    if (p && p.todo === 0) {
      const first = visiblePlatforms.value[0]
      if (first) activePlatform.value = first.id
    }
  }
}

function openCell(word: string, date: string, platform?: string, pane?: ComparePaneId) {
  // 2026-09-14 - 从「补录前」点开必须用 before 格子，否则侧栏/详情入口位次全是补录后
  const cell = pane === 'before'
    ? (getCellForPane('before', word, date, platform) || getCell(word, date, platform))
    : getCell(word, date, platform)
  if (!cell) return
  // 2026-09-01 - 补录前对照可点开看，但不允许补录/忽略
  openCellDirect(cell, pane !== 'before')
}

function openCellDirect(cell: SnapshotBackfillMatrixCell, allowBackfill = true) {
  activePlatform.value = cell.platform
  cellDrawer.value = cell
  cellDrawerAllowBackfill.value = allowBackfill
  // 2026-08-21 - 方案 A：每次打开格子默认不展开已忽略，避免误点
  showDismissedSlots.value = false
  cellDrawerVisible.value = true
}

function closeCellDrawer() {
  cellDrawerVisible.value = false
  cellDrawer.value = null
  cellDrawerAllowBackfill.value = true
  showDismissedSlots.value = false
}

function averageRanks(ranks: number[]) {
  if (!ranks.length) return null
  const total = ranks.reduce((sum, value) => sum + value, 0)
  return Math.round((total / ranks.length) * 10) / 10
}

function cellHasTodo(slots: SnapshotBackfillMatrixSlot[]) {
  // 2026-07-28 - 点开可忽略消红点 - 红点只看未忽略场次日均>3（或无均值）
  const active = slots.filter(slot => !slot.backfill_dismissed)
  if (!active.length) return false
  // 2026-08-07 - 仅算均位会漏掉「仍有漏跑/失败」- 有缺口或失败待补仍标红
  if (active.some(slot => slot.is_gap || (slot.needs_backfill && !slot.has_answer))) return true
  const ranks: number[] = []
  for (const slot of active) {
    if (slot.mention_position != null && Number.isFinite(Number(slot.mention_position))) {
      ranks.push(Number(slot.mention_position))
    }
  }
  if (!ranks.length) return true
  const avg = averageRanks(ranks)
  return avg == null ? true : avg > 3
}

function recomputeCell(cell: SnapshotBackfillMatrixCell): SnapshotBackfillMatrixCell {
  const ranks: number[] = []
  let failCount = 0
  let gapCount = 0
  for (const slot of cell.slots) {
    if (slot.is_gap && !slot.backfill_dismissed) gapCount += 1
    if (slot.mention_position != null && Number.isFinite(Number(slot.mention_position))) {
      ranks.push(Number(slot.mention_position))
    }
    if (slot.needs_backfill && !slot.has_answer && !slot.backfill_dismissed) failCount += 1
  }
  return {
    ...cell,
    rank: averageRanks(ranks),
    fail_count: failCount,
    gap_count: gapCount,
    sample_count: cell.slots.length,
    rank_sample_count: ranks.length,
    has_todo: cellHasTodo(cell.slots),
  }
}

/** 有快照的场次换成补录前位次；无快照保持现状（未补过=前后一样） */
function slotAsBefore(slot: SnapshotBackfillMatrixSlot): SnapshotBackfillMatrixSlot {
  if (!slot.has_before_backfill) return slot
  const beforeHasAnswer = Boolean(slot.before_has_answer)
  return {
    ...slot,
    mention_position: slot.before_mention_position ?? null,
    has_answer: beforeHasAnswer,
    needs_backfill: !beforeHasAnswer,
    status: slot.before_status ?? slot.status,
  }
}

function remapCellBefore(cell: SnapshotBackfillMatrixCell): SnapshotBackfillMatrixCell {
  return recomputeCell({ ...cell, slots: cell.slots.map(slotAsBefore) })
}

function buildCellLookup(list: SnapshotBackfillMatrixCell[]) {
  const map = new Map<string, SnapshotBackfillMatrixCell>()
  for (const cell of list) {
    map.set(`${cell.platform}||${cell.word}||${cell.date}`, cell)
  }
  return map
}

const afterCells = computed(() => cells.value)
const beforeCells = computed(() => cells.value.map(remapCellBefore))

const afterCellLookup = computed(() => buildCellLookup(afterCells.value))
const beforeCellLookup = computed(() => buildCellLookup(beforeCells.value))

function platformsFromCells(
  base: SnapshotBackfillMatrixPlatform[],
  list: SnapshotBackfillMatrixCell[],
): SnapshotBackfillMatrixPlatform[] {
  return base.map((p) => {
    const platCells = list.filter(cell => cell.platform === p.id)
    const avgs = platCells
      .map(cell => cell.rank)
      .filter((rank): rank is number => rank != null && Number.isFinite(rank))
    return {
      ...p,
      todo: platCells.filter(cell => cell.has_todo).length,
      fail: platCells.reduce((sum, cell) => sum + (cell.fail_count || 0), 0),
      avg: averageRanks(avgs),
    }
  })
}

/** 侧栏 / 待补过滤用补录后；左右对照行对齐也靠这套 */
const displayPlatforms = computed(() => platformsFromCells(platforms.value, afterCells.value))
const beforePlatforms = computed(() => platformsFromCells(platforms.value, beforeCells.value))

const visiblePlatforms = computed(() => (
  todoOnly.value ? displayPlatforms.value.filter(p => p.todo > 0) : displayPlatforms.value
))

const activePlatformMeta = computed(() => (
  displayPlatforms.value.find(p => p.id === activePlatform.value) || null
))

function sumPlatformKpis(list: SnapshotBackfillMatrixPlatform[]) {
  let todo = 0
  let fail = 0
  const avgs: number[] = []
  for (const p of list) {
    todo += Number(p.todo) || 0
    fail += Number(p.fail) || 0
    if (p.avg != null && Number.isFinite(Number(p.avg))) avgs.push(Number(p.avg))
  }
  return {
    todo,
    fail,
    avg: avgs.length ? Math.round((avgs.reduce((s, n) => s + n, 0) / avgs.length) * 10) / 10 : null,
  }
}

/** 头栏 KPI：日常看补录后；对照时附带补录前（与当前可见端对齐） */
const headKpisAfter = computed(() => {
  if (isAllPlatformsView.value) {
    return sumPlatformKpis(todoOnly.value ? visiblePlatforms.value : displayPlatforms.value)
  }
  return {
    todo: activePlatformMeta.value?.todo ?? 0,
    fail: activePlatformMeta.value?.fail ?? 0,
    avg: activePlatformMeta.value?.avg ?? null,
  }
})

const headKpisBefore = computed(() => {
  if (isAllPlatformsView.value) {
    const ids = new Set(
      (todoOnly.value ? visiblePlatforms.value : displayPlatforms.value).map(p => p.id),
    )
    return sumPlatformKpis(beforePlatforms.value.filter(p => ids.has(p.id)))
  }
  const meta = beforePlatforms.value.find(p => p.id === activePlatform.value)
  return {
    todo: meta?.todo ?? 0,
    fail: meta?.fail ?? 0,
    avg: meta?.avg ?? null,
  }
})

function formatKpiAvg(value: number | null | undefined) {
  return value == null || !Number.isFinite(Number(value)) ? '—' : String(value)
}

/** 运营操作始终看补录后格子 */
function getCell(word: string, date: string, platform?: string) {
  return afterCellLookup.value.get(`${platform || activePlatform.value}||${word}||${date}`) || null
}

function getCellForPane(pane: ComparePaneId, word: string, date: string, platform?: string) {
  const map = pane === 'before' ? beforeCellLookup.value : afterCellLookup.value
  return map.get(`${platform || activePlatform.value}||${word}||${date}`) || null
}

function platformMetaForPane(pane: ComparePaneId, platformId: string) {
  const list = pane === 'before' ? beforePlatforms.value : displayPlatforms.value
  return list.find(p => p.id === platformId) || null
}

const visibleWords = computed(() => {
  if (!todoOnly.value) return words.value
  const set = new Set(
    afterCells.value
      .filter(c => c.platform === activePlatform.value && c.has_todo)
      .map(c => c.word),
  )
  const list = words.value.filter(w => set.has(w))
  return list.length ? list : words.value
})

function wordsForPlatform(platformId: string) {
  // 2026-07-30 - 全部平台只见一端 - 分块矩阵按端各自出词行
  const platCells = afterCells.value.filter(c => c.platform === platformId)
  if (!platCells.length) return [] as string[]
  if (!todoOnly.value) {
    const set = new Set(platCells.map(c => c.word))
    return words.value.filter(w => set.has(w))
  }
  const set = new Set(platCells.filter(c => c.has_todo).map(c => c.word))
  return words.value.filter(w => set.has(w))
}

/** 运营口径：成功才计提及；分母含成功+失败+漏跑+已忽略（与工作台词×平台不同） */
const MENTION_RATE_SUCCESS = new Set(['completed', 'partial_completed'])

function slotIsSuccessStatus(status: string | null | undefined) {
  return MENTION_RATE_SUCCESS.has(String(status || '').trim().toLowerCase())
}

function slotMentionFlags(slot: SnapshotBackfillMatrixSlot, mode: 'after' | 'before') {
  // 2026-09-01 - 补录页提及率按运营拍板：失败/漏跑/已忽略都进分母压低率
  if (slot.is_gap) {
    return { sample: true, mentioned: false }
  }
  if (mode === 'before' && slot.has_before_backfill) {
    return {
      sample: true,
      mentioned: slotIsSuccessStatus(slot.before_status) && slot.before_mention_position != null,
    }
  }
  return {
    sample: true,
    mentioned: slotIsSuccessStatus(slot.status) && slot.mention_position != null,
  }
}

function mentionRateFromSlots(slots: SnapshotBackfillMatrixSlot[], mode: 'after' | 'before') {
  let sample = 0
  let mentioned = 0
  for (const slot of slots) {
    const flags = slotMentionFlags(slot, mode)
    if (!flags.sample) continue
    sample += 1
    if (flags.mentioned) mentioned += 1
  }
  if (!sample) return null
  return Math.round((mentioned / sample) * 1000) / 10
}

function wordPeriodMentionRate(platformId: string, word: string, mode: 'after' | 'before') {
  const slots = cells.value
    .filter(cell => cell.platform === platformId && cell.word === word)
    .flatMap(cell => cell.slots)
  return mentionRateFromSlots(slots, mode)
}

function formatMentionRate(value: number | null) {
  return value == null ? '—' : `${value}%`
}

/** 词列：对照时展示时段提及 前→后；格子悬停仍单侧 */
function formatWordPeriodMentionRate(platformId: string, word: string) {
  const after = wordPeriodMentionRate(platformId, word, 'after')
  const before = wordPeriodMentionRate(platformId, word, 'before')
  return `${formatMentionRate(before)} → ${formatMentionRate(after)}`
}

function cellHoverTitle(pane: ComparePaneId, word: string, date: string, platform?: string) {
  const raw = getCell(word, date, platform)
  const cell = getCellForPane(pane, word, date, platform)
  const slots = raw?.slots || cell?.slots || []
  // 2026-09-01 - 悬停只显示当前侧提及率，不做前→后
  const mode = pane === 'before' ? 'before' : 'after'
  return formatMentionRate(mentionRateFromSlots(slots, mode))
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

/** 补录/忽略后只改本地场次，不整表重拉；未命中返回 false（缺口格补录后需重拉矩阵） */
function patchSlotLocally(
  subtaskId: string,
  patch: Partial<SnapshotBackfillMatrixSlot>,
): boolean {
  let touchedPlatform = ''
  let touched = false
  cells.value = cells.value.map((cell) => {
    const idx = cell.slots.findIndex(slot => slot.subtask_id === subtaskId)
    if (idx < 0) return cell
    touched = true
    touchedPlatform = cell.platform
    const slots = cell.slots.slice()
    const old = slots[idx]
    let next: SnapshotBackfillMatrixSlot = { ...old, ...patch, is_gap: false }
    // 2026-09-01 - 补录后左屏跟着右屏变 - 无 before 快照时用补丁前旧值冻住
    if (
      patch.has_answer
      && !old.has_before_backfill
      && !patch.has_before_backfill
    ) {
      next = {
        ...next,
        has_before_backfill: true,
        before_mention_position: old.mention_position ?? null,
        before_has_answer: Boolean(old.has_answer),
        before_status: old.status ?? null,
      }
    }
    slots[idx] = next
    return recomputeCell({ ...cell, slots })
  })
  if (touchedPlatform) refreshPlatformStats(touchedPlatform)
  if (cellDrawer.value) {
    const refreshed = getCell(cellDrawer.value.word, cellDrawer.value.date, cellDrawer.value.platform)
    if (refreshed) cellDrawer.value = refreshed
    maybeCloseCellDrawerAfterTodoClear(refreshed)
  }
  return touched
}

/** 2026-08-04 - 缺口忽略后仍显示漏跑 - gap 槽无 subtask_id，须按 window_key 本地消掉 */
function patchGapSlotDismissedLocally(
  slot: SnapshotBackfillMatrixSlot,
  subtaskId: string,
): boolean {
  const windowKey = String(slot.schedule_window_key || '').trim()
  const prompt = String(slot.prompt || cellDrawer.value?.word || '').trim()
  const platform = String(slot.platform || activePlatform.value || '').trim()
  if (!windowKey && !subtaskId) return false
  let touchedPlatform = ''
  let touched = false
  cells.value = cells.value.map((cell) => {
    if (platform && cell.platform !== platform) return cell
    if (prompt && cell.word !== prompt) return cell
    const idx = cell.slots.findIndex((item) => {
      if (subtaskId && item.subtask_id === subtaskId) return true
      if (!windowKey) return false
      return Boolean(item.is_gap) && String(item.schedule_window_key || '').trim() === windowKey
    })
    if (idx < 0) return cell
    touched = true
    touchedPlatform = cell.platform
    const slots = cell.slots.slice()
    slots[idx] = {
      ...slots[idx],
      subtask_id: subtaskId || slots[idx].subtask_id,
      is_gap: false,
      needs_backfill: false,
      backfill_dismissed: true,
    }
    return recomputeCell({ ...cell, slots })
  })
  if (touchedPlatform) refreshPlatformStats(touchedPlatform)
  if (cellDrawer.value) {
    const refreshed = getCell(cellDrawer.value.word, cellDrawer.value.date, cellDrawer.value.platform)
    if (refreshed) cellDrawer.value = refreshed
    // 2026-08-21 - 方案 A：忽略后自动展开已忽略区，方便立刻取消忽略
    showDismissedSlots.value = true
    maybeCloseCellDrawerAfterTodoClear(refreshed)
  }
  return touched
}

function slotKey(slot: SnapshotBackfillMatrixSlot) {
  return slot.subtask_id || `gap:${slot.schedule_window_key || slot.schedule_label || ''}`
}

function slotToItem(slot: SnapshotBackfillMatrixSlot): SnapshotBackfillPendingItem {
  return {
    subtask_id: slot.subtask_id || '',
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

async function dismissMobileItem(item: SnapshotBackfillPendingItem) {
  if (!canSubmitBackfill.value || !item.subtask_id) return
  try {
    if (item.needs_backfill && !item.has_answer) {
      await ElMessageBox.confirm(
        '当前无有效回答，忽略后将不再提醒补录，客户侧仍按未抓取/失败统计（不会补出排名）。确认忽略？',
        '忽略待补录',
        { type: 'warning', confirmButtonText: '确认忽略', cancelButtonText: '取消' },
      )
    }
    await dismissSnapshotBackfill(item.subtask_id)
    mobileItems.value = mobileItems.value.filter(row => row.subtask_id !== item.subtask_id)
    ElMessage.success('已忽略，不再提醒')
    emitMonitorRefresh({ tenantId: tenantFilter.value === '' ? null : Number(tenantFilter.value) })
    await loadMobileItems({ quiet: true })
  } catch (error: unknown) {
    if (error === 'cancel') return
    notifyOperationError(error, '忽略失败')
  }
}

async function openMobileBackfill(item: SnapshotBackfillPendingItem) {
  if (!canSubmitBackfill.value || !item.subtask_id) return
  if (!statusAllowsSnapshotBackfill(item.status || item.task_status)) {
    ElMessage.warning('该场次监测尚未结束，请等抓取完成或失败后再补录')
    return
  }
  try {
    backfillTarget.value = await loadSubtask(item.subtask_id)
    backfillVisible.value = true
  } catch (error: unknown) {
    notifyOperationError(error, '加载子任务失败')
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

const TERMINAL_BACKFILL_STATUSES = new Set(['completed', 'partial_completed', 'failed', 'stopped'])

function statusAllowsSnapshotBackfill(status: string | null | undefined) {
  const value = String(status || '').trim().toLowerCase()
  // 缺口格无状态：允许走 ensureGap；真实子任务必须终态
  if (!value) return true
  return TERMINAL_BACKFILL_STATUSES.has(value)
}

async function openBackfillFromDetail() {
  if (!canSubmitBackfill.value || !cellDrawerAllowBackfill.value || !detailSubtask.value) return
  // 2026-08-11 - 监测未终态就补录会被同步盖掉
  if (!statusAllowsSnapshotBackfill(detailSubtask.value.status)) {
    ElMessage.warning('该场次监测尚未结束，请等抓取完成或失败后再补录')
    return
  }
  // 2026-08-21 - 抽屉缓存可能缺正文/截图，只改排名误判无模力结果；打开前再拉详情
  const sid = detailSubtask.value.subtask_id
  if (sid) {
    try {
      detailSubtask.value = await loadSubtask(sid)
      if (detailItem.value) {
        detailItem.value = mergeSnapshotBackfillItem(detailItem.value, detailSubtask.value)
      }
    } catch (error: unknown) {
      notifyOperationError(error, '加载子任务失败')
      return
    }
  }
  backfillTarget.value = detailSubtask.value
  backfillVisible.value = true
}

async function openBackfillFromSlot(slot: SnapshotBackfillMatrixSlot) {
  if (!canSubmitBackfill.value || !cellDrawerAllowBackfill.value) return
  if (!slot.is_gap && !statusAllowsSnapshotBackfill(slot.status)) {
    ElMessage.warning('该场次监测尚未结束，请等抓取完成或失败后再补录')
    return
  }
  try {
    if (slot.is_gap || !slot.subtask_id) {
      const tenantId = slot.tenant_id ?? (tenantFilter.value === '' ? null : Number(tenantFilter.value))
      if (!tenantId || !slot.schedule_window_key) {
        throw new Error('缺少企业或场次信息')
      }
      const result = await ensureGapBackfillSubtask({
        tenant_id: tenantId,
        platform: slot.platform || activePlatform.value,
        prompt: slot.prompt || cellDrawer.value?.word || '',
        schedule_window_key: slot.schedule_window_key,
      })
      backfillTarget.value = result.subtask
      backfillVisible.value = true
      await loadMatrix({ quiet: true, skipCache: true })
      syncCellDrawerFromMatrix()
      return
    }
    backfillTarget.value = await loadSubtask(slot.subtask_id)
    backfillVisible.value = true
  } catch (error: unknown) {
    notifyOperationError(error, '加载子任务失败')
  }
}

function isFailurePending(slot: SnapshotBackfillMatrixSlot) {
  return Boolean(slot.needs_backfill) && !slot.has_answer
}

function slotBatchDismissable(slot: SnapshotBackfillMatrixSlot, inTodoCell: boolean) {
  if (slot.backfill_dismissed) return false
  // 2026-08-28 - 一键忽略计数与后端对齐 - 红点格内全部未忽略场次
  if (todoOnly.value && inTodoCell) return Boolean(slot.is_gap || slot.subtask_id)
  return Boolean(slot.is_gap || slot.subtask_id)
}

const batchDismissableCount = computed(() => {
  let count = 0
  for (const cell of cells.value) {
    const inTodoCell = Boolean(cell.has_todo)
    if (todoOnly.value && !inTodoCell) continue
    for (const slot of cell.slots) {
      if (slotBatchDismissable(slot, inTodoCell)) count += 1
    }
  }
  return count
})

function collectBatchDismissSlots(): SnapshotBackfillBatchDismissSlot[] {
  const out: SnapshotBackfillBatchDismissSlot[] = []
  const defaultTenant = tenantFilter.value === '' ? null : Number(tenantFilter.value)
  for (const cell of cells.value) {
    const inTodoCell = Boolean(cell.has_todo)
    if (todoOnly.value && !inTodoCell) continue
    for (const slot of cell.slots) {
      if (!slotBatchDismissable(slot, inTodoCell)) continue
      out.push({
        tenant_id: slot.tenant_id ?? defaultTenant,
        platform: String(slot.platform || cell.platform),
        prompt: String(slot.prompt || cell.word),
        schedule_window_key: slot.schedule_window_key,
        subtask_id: slot.subtask_id,
        is_gap: Boolean(slot.is_gap),
      })
    }
  }
  return out
}

/** 2026-08-28 - 一键忽略要瞬间消失 - 确认后先本地消红点，后台再落库 */
function buildBatchDismissLocalKeys(slots: SnapshotBackfillBatchDismissSlot[]) {
  const defaultTenant = tenantFilter.value === '' ? null : Number(tenantFilter.value)
  const keys = new Set<string>()
  for (const slot of slots) {
    if (slot.subtask_id) {
      keys.add(`id:${slot.subtask_id}`)
      continue
    }
    const tenantId = slot.tenant_id ?? defaultTenant
    keys.add(`gap:${tenantId}:${slot.platform}:${slot.prompt}:${slot.schedule_window_key || ''}`)
  }
  return { keys, defaultTenant }
}

function patchAllBatchDismissedLocally(slots: SnapshotBackfillBatchDismissSlot[]) {
  const { keys, defaultTenant } = buildBatchDismissLocalKeys(slots)
  const touchedPlatforms = new Set<string>()
  cells.value = cells.value.map((cell) => {
    let touched = false
    const nextSlots = cell.slots.map((slot) => {
      if (slot.backfill_dismissed) return slot
      const slotKey = slot.subtask_id
        ? `id:${slot.subtask_id}`
        : `gap:${slot.tenant_id ?? defaultTenant}:${slot.platform || cell.platform}:${slot.prompt || cell.word}:${slot.schedule_window_key || ''}`
      if (!keys.has(slotKey)) return slot
      touched = true
      return {
        ...slot,
        backfill_dismissed: true,
        needs_backfill: false,
        is_gap: false,
      }
    })
    if (!touched) return cell
    touchedPlatforms.add(cell.platform)
    return recomputeCell({ ...cell, slots: nextSlots })
  })
  for (const plat of touchedPlatforms) refreshPlatformStats(plat)
  if (cellDrawer.value) {
    const refreshed = getCell(cellDrawer.value.word, cellDrawer.value.date, cellDrawer.value.platform)
    if (refreshed) cellDrawer.value = refreshed
    maybeCloseCellDrawerAfterTodoClear(refreshed)
  }
}

const BATCH_DISMISS_CHUNK = 500

async function dismissAllInFilter() {
  if (!canSubmitBackfill.value || batchDismissLoading.value) return
  const count = batchDismissableCount.value
  if (!count) {
    ElMessage.info('当前筛选下没有可忽略的待办场次')
    return
  }
  try {
    await ElMessageBox.confirm(
      `将忽略当前筛选下 ${count} 条待办场次（${todoOnly.value ? '仅红点格子' : '含全部未忽略场次'}）。`
        + '无有效回答的场次忽略后不再提醒补录，客户侧仍按未抓取/失败统计。确认继续？',
      '一键忽略',
      { type: 'warning', confirmButtonText: '确认忽略', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  batchDismissLoading.value = true
  const slots = collectBatchDismissSlots()
  if (!slots.length) {
    batchDismissLoading.value = false
    ElMessage.info('当前筛选下没有可忽略的待办场次')
    return
  }
  patchAllBatchDismissedLocally(slots)
  closeCellDrawer()
  batchDismissLoading.value = false
  ElMessage.success(`已忽略 ${slots.length} 条待办场次`)

  void (async () => {
    try {
      let totalDismissed = 0
      let truncated = false
      for (let i = 0; i < slots.length; i += BATCH_DISMISS_CHUNK) {
        const chunk = slots.slice(i, i + BATCH_DISMISS_CHUNK)
        const result = await dismissSnapshotBackfillBatch({ slots: chunk, todo_only: todoOnly.value })
        totalDismissed += result.dismissed
        truncated = truncated || Boolean(result.truncated)
      }
      emitMonitorRefresh({ tenantId: tenantFilter.value === '' ? null : Number(tenantFilter.value) })
      if (truncated || totalDismissed < slots.length) {
        await loadMatrix({ quiet: true, skipCache: true })
      }
    } catch (error: unknown) {
      notifyOperationError(error, '后台同步失败，正在刷新')
      await loadMatrix({ quiet: true, skipCache: true })
    }
  })()
}

async function dismissSlot(slot: SnapshotBackfillMatrixSlot) {
  // 2026-08-04 - 到期/漏跑缺口格不能忽略 - 先落占位子任务再走同一套 dismiss
  if (!canSubmitBackfill.value || !cellDrawerAllowBackfill.value || slot.backfill_dismissed) return
  if (!slot.is_gap && !slot.subtask_id) return
  try {
    if (isFailurePending(slot) || slot.is_gap) {
      await ElMessageBox.confirm(
        '当前无有效回答，忽略后将不再提醒补录，客户侧仍按未抓取/失败统计（不会补出排名）。确认忽略？',
        '忽略待补录',
        { type: 'warning', confirmButtonText: '确认忽略', cancelButtonText: '取消' },
      )
    }
    let subtaskId = slot.subtask_id || ''
    if (slot.is_gap || !subtaskId) {
      const tenantId = slot.tenant_id ?? (tenantFilter.value === '' ? null : Number(tenantFilter.value))
      if (!tenantId || !slot.schedule_window_key) {
        throw new Error('缺少企业或场次信息')
      }
      const ensured = await ensureGapBackfillSubtask({
        tenant_id: tenantId,
        platform: slot.platform || activePlatform.value,
        prompt: slot.prompt || cellDrawer.value?.word || '',
        schedule_window_key: slot.schedule_window_key,
      })
      subtaskId = ensured.subtask.subtask_id
    }
    await dismissSnapshotBackfill(subtaskId)
    // 2026-08-04 - 忽略 toast 后抽屉仍漏跑 - gap 无 subtask_id，先本地消槽；矩阵缓存可能仍旧
    patchGapSlotDismissedLocally(slot, subtaskId)
    ElMessage.success('已忽略，不再提醒')
    emitMonitorRefresh({ tenantId: tenantFilter.value === '' ? null : Number(tenantFilter.value) })
    void loadMatrix({ quiet: true, skipCache: true }).then(() => {
      // 后端若仍吐缺口（缓存/占位未入矩阵），再盖一次本地忽略态
      patchGapSlotDismissedLocally(slot, subtaskId)
    })
  } catch (error: unknown) {
    if (error === 'cancel') return
    notifyOperationError(error, '忽略失败')
  }
}

async function undismissSnapshot(subtaskId: string, reopenDetail = false) {
  if (!canSubmitBackfill.value || !subtaskId) return null
  const result = await undismissSnapshotBackfill(subtaskId)
  ElMessage.success(result.item.needs_backfill ? '已取消忽略，已重新纳入待补录' : '已取消忽略')
  // 取消忽略需重新进矩阵桶，安静重拉一次即可
  await loadMatrix({ quiet: true, skipCache: true })
  syncCellDrawerFromMatrix()
  emitMonitorRefresh({ tenantId: tenantFilter.value === '' ? null : Number(tenantFilter.value) })
  if (reopenDetail) {
    await openDetailById(subtaskId, result.item)
  }
  return result
}

async function undismissFromDetail() {
  const subtaskId = detailItem.value?.subtask_id || detailSubtask.value?.subtask_id
  if (!subtaskId) return
  try {
    await undismissSnapshot(subtaskId, true)
  } catch (error: unknown) {
    notifyOperationError(error, '取消忽略失败')
  }
}

// 2026-08-21 - 方案 A：格子抽屉对已忽略场次直接取消忽略，再可点补录
async function undismissFromSlot(slot: SnapshotBackfillMatrixSlot) {
  if (!canSubmitBackfill.value || !cellDrawerAllowBackfill.value) return
  const subtaskId = String(slot.subtask_id || '').trim()
  if (!subtaskId) {
    ElMessage.warning('缺少子任务，无法取消忽略')
    return
  }
  try {
    await undismissSnapshot(subtaskId, false)
  } catch (error: unknown) {
    notifyOperationError(error, '取消忽略失败')
  }
}

async function handleSuccess(updatedSubtask?: MonitorSubtask) {
  const activeId = updatedSubtask?.subtask_id || detailItem.value?.subtask_id || backfillTarget.value?.subtask_id
  let patched = false
  if (updatedSubtask?.subtask_id) {
    const patch: Partial<SnapshotBackfillMatrixSlot> = {
      mention_position: updatedSubtask.mention_position ?? null,
      has_answer: Boolean(updatedSubtask.answer_content),
      status: updatedSubtask.status ?? null,
      error_message: updatedSubtask.error_message ?? null,
      is_gap: false,
      backfill_parse_status: updatedSubtask.backfill_parse_status ?? null,
    }
    if (updatedSubtask.needs_backfill !== undefined) {
      patch.needs_backfill = updatedSubtask.needs_backfill
    }
    // 2026-09-01 - 补录成功后本地格子也能切「补录前」
    const before = updatedSubtask.before_backfill
    if (before) {
      patch.has_before_backfill = true
      patch.before_mention_position = before.mention_position ?? null
      patch.before_has_answer = Boolean(before.has_answer)
      patch.before_status = before.status ?? null
    }
    patched = patchSlotLocally(updatedSubtask.subtask_id, patch)
  }
  // 2026-08-03 - 缺口格补录后矩阵仍显示漏跑 - 本地 patch 找不到 is_gap 槽位，须重拉
  if (!patched) {
    await loadMatrix({ quiet: true, skipCache: true })
  }
  syncCellDrawerFromMatrix()
  // 仅当整格已无场次（含已忽略）才关抽屉
  if (cellDrawerVisible.value && !drawerActiveSlots.value.length && !drawerDismissedSlots.value.length) {
    closeCellDrawer()
  }
  emitMonitorRefresh({ tenantId: tenantFilter.value === '' ? null : Number(tenantFilter.value) })

  // 2026-08-07 - 从格子待办补录后待办消失、没有详情入口 - 自动打开详情方便看快照
  if (updatedSubtask?.subtask_id) {
    const baseItem = detailItem.value?.subtask_id === updatedSubtask.subtask_id
      ? detailItem.value
      : backfillItemFromSubtask(updatedSubtask)
    await openDetail(mergeSnapshotBackfillItem(baseItem, updatedSubtask))
  } else if (detailVisible.value && activeId) {
    await openDetailById(activeId, detailItem.value)
  }

  ElMessage.success('快照补录已保存')
  clearDeepLink()
}

/** 后台解析完成：只 patch/刷矩阵；silent=刷新续轮，勿开详情、勿连弹成功。 */
async function applyBackgroundParseDone(
  updatedSubtask: MonitorSubtask,
  options?: { silent?: boolean },
) {
  const silent = Boolean(options?.silent)
  let patched = false
  const patch: Partial<SnapshotBackfillMatrixSlot> = {
    mention_position: updatedSubtask.mention_position ?? null,
    has_answer: Boolean(updatedSubtask.answer_content),
    status: updatedSubtask.status ?? null,
    error_message: updatedSubtask.error_message ?? null,
    is_gap: false,
    backfill_parse_status: updatedSubtask.backfill_parse_status ?? 'ok',
  }
  if (updatedSubtask.needs_backfill !== undefined) {
    patch.needs_backfill = updatedSubtask.needs_backfill
  }
  const before = updatedSubtask.before_backfill
  if (before) {
    patch.has_before_backfill = true
    patch.before_mention_position = before.mention_position ?? null
    patch.before_has_answer = Boolean(before.has_answer)
    patch.before_status = before.status ?? null
  }
  patched = patchSlotLocally(updatedSubtask.subtask_id, patch)
  if (!patched) {
    await loadMatrix({ quiet: true, skipCache: true })
  }
  syncCellDrawerFromMatrix()
  emitMonitorRefresh({ tenantId: tenantFilter.value === '' ? null : Number(tenantFilter.value) })
  // 2026-09-02 - 主动提交轻提示；续轮静默。两侧都不自动开详情
  if (!silent) {
    ElMessage.success('快照补录已保存')
  }
}

/** 2026-09-02 - A：慢路径入队后关窗，本地标「解析中」并后台轮询刷新 */
async function handleParseQueued(subtask: MonitorSubtask, options?: { silent?: boolean }) {
  if (!subtask?.subtask_id) return
  const sid = subtask.subtask_id
  const silent = Boolean(options?.silent)
  patchSlotLocally(sid, {
    is_gap: false,
    backfill_parse_status: 'pending',
    needs_backfill: true,
    has_answer: Boolean(subtask.answer_content),
  })
  syncCellDrawerFromMatrix()
  parsePollControllers.get(sid)?.abort()
  const controller = new AbortController()
  parsePollControllers.set(sid, controller)
  const releaseController = () => {
    if (parsePollControllers.get(sid) === controller) {
      parsePollControllers.delete(sid)
    }
  }
  try {
    const done = await waitForBackfillParse(sid, { signal: controller.signal })
    if (controller.signal.aborted) return
    await applyBackgroundParseDone(done, { silent })
  } catch (error: unknown) {
    if (controller.signal.aborted) return
    // 2026-09-02 - 先释放 controller 再 loadMatrix，避免 resume 因 Map 占用而跳过导致停轮假死
    releaseController()
    try {
      const detail = await getMonitorSubtask(sid, { include_ops: true })
      const status = String(detail.backfill_parse_status || '').toLowerCase()
      if (status === 'ok' || (!status && detail.answer_content)) {
        await applyBackgroundParseDone(detail, { silent })
        return
      }
      if (status === 'pending') {
        // 仍在跑：轻提示后交给矩阵 resume，勿本地标 failed
        ElMessage.warning('分享页仍在后台解析，请稍后刷新查看')
        await loadMatrix({ quiet: true, skipCache: true })
        return
      }
      patchSlotLocally(sid, { backfill_parse_status: 'failed' })
      syncCellDrawerFromMatrix()
      // 失败始终提示；silent 只禁成功连弹/开详情
      notifyOperationError(error, '快照补录解析失败')
    } catch {
      patchSlotLocally(sid, { backfill_parse_status: 'failed' })
      syncCellDrawerFromMatrix()
      notifyOperationError(error, '快照补录解析失败')
    }
    await loadMatrix({ quiet: true, skipCache: true })
  } finally {
    releaseController()
  }
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
  purposeFilter.value = 'geo'
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
  const parseStatus = String(slot.backfill_parse_status || '').toLowerCase()
  if (parseStatus === 'pending') return '解析中'
  if (parseStatus === 'failed') return '解析失败'
  if (slot.is_gap) return '漏跑待补'
  if (slot.backfill_dismissed) return '已忽略'
  if (slot.needs_backfill && !slot.has_answer) return '失败待补'
  if (slot.needs_backfill) return '待补录'
  if (slot.has_answer) return '已补录'
  return slot.status || '—'
}

function mobileStatusLabel(item: SnapshotBackfillPendingItem) {
  if (item.backfill_dismissed) return '已忽略'
  if (item.needs_backfill && !item.has_answer) return '失败待补'
  if (item.needs_backfill) return '待补录'
  if (item.has_answer) return '已有快照'
  return item.status || item.task_status || '待处理'
}

function mobileSourceLabel(item: SnapshotBackfillPendingItem) {
  if (item.source === 'lead_diagnosis') return '售前诊断'
  return purposeFilter.value === 'brand_word' ? '品牌词监测' : 'GEO 监测'
}

function mobileItemDate(item: SnapshotBackfillPendingItem) {
  const value = item.task_created_at || item.updated_at || ''
  return value ? String(value).replace('T', ' ').slice(0, 16) : '时间未知'
}

function syncMobileViewport(matches: boolean) {
  const changed = isMobileViewport.value !== matches
  isMobileViewport.value = matches
  mobileFiltersOpen.value = false
  if (changed && canViewBackfill.value) void loadMatrix()
}

function onMobileMediaChange(event: MediaQueryListEvent) {
  syncMobileViewport(event.matches)
}

onMounted(async () => {
  mobileMediaQuery = window.matchMedia(MOBILE_BREAKPOINT)
  isMobileViewport.value = mobileMediaQuery.matches
  mobileMediaQuery.addEventListener('change', onMobileMediaChange)
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
  for (const controller of parsePollControllers.values()) controller.abort()
  parsePollControllers.clear()
  mobileMediaQuery?.removeEventListener('change', onMobileMediaChange)
  mobileMediaQuery = null
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
  if (isMobileViewport.value && !filterBootstrapping) scheduleLoadMatrix()
})

watch(purposeFilter, () => {
  if (filterBootstrapping) return
  // 2026-09-08 - 切品牌词轨时清掉售前来源
  if (purposeFilter.value === 'brand_word' && sourceFilter.value === 'lead_diagnosis') {
    sourceFilter.value = ''
  }
  void loadTenantKeywordGroups().then(() => loadMatrix())
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
    <div v-if="!isMobileViewport" class="snapshot-backfill-toolbar">
      <div class="snapshot-backfill-toolbar-inner">
        <div class="sb-purpose-tabs" title="补录分轨">
          <button
            type="button"
            :class="{ on: purposeFilter === 'geo' }"
            @click="purposeFilter = 'geo'"
          >日常监测</button>
          <button
            type="button"
            :class="{ on: purposeFilter === 'brand_word' }"
            @click="purposeFilter = 'brand_word'"
          >品牌词</button>
        </div>
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
          <option value="tenant_monitor">{{ purposeFilter === 'brand_word' ? '品牌词监测' : 'GEO 监测' }}</option>
          <option v-if="purposeFilter === 'geo'" value="lead_diagnosis">售前诊断</option>
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
          :title="tenantFilter ? (purposeFilter === 'brand_word' ? '品牌词组' : '词组') : '请先选择企业'"
        >
          <option value="">{{ tenantFilter ? (purposeFilter === 'brand_word' ? '全部品牌词组' : '全部词组') : '先选企业' }}</option>
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
          :title="tenantFilter ? (purposeFilter === 'brand_word' ? '品牌词' : '监测词') : '请先选择企业'"
        >
          <option value="">{{ tenantFilter ? (purposeFilter === 'brand_word' ? '全部品牌词' : '全部监测词') : '先选企业' }}</option>
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
          <button
            v-if="canSubmitBackfill"
            type="button"
            class="filter-reset-btn tiny-btn"
            :disabled="loading || batchDismissLoading || !batchDismissableCount"
            @click="dismissAllInFilter"
          >
            <EyeOff :size="14" />
            一键忽略{{ batchDismissableCount ? `（${batchDismissableCount}）` : '' }}
          </button>
          <button type="button" class="filter-reset-btn tiny-btn" @click="resetFilters">重置</button>
          <button type="button" class="filter-reset-btn tiny-btn" :disabled="loading" @click="() => loadMatrix()">
            <RefreshCw :size="14" />
            刷新
          </button>
        </div>
      </div>
    </div>

    <div v-if="!isMobileViewport" class="sb-layout" :class="{ 'is-compare': showBeforeCompare }">
      <section class="sb-panel sb-main">
        <div class="sb-main-head">
          <div class="sb-platform-title">
            <div class="sb-platform-logo">
              {{ isAllPlatformsView ? '全' : (activePlatformMeta?.name || activePlatform || '—').slice(0, 1) }}
            </div>
            <div>
              <h2>
                {{
                  isAllPlatformsView
                    ? '全部平台'
                    : (activePlatformMeta?.name || platformLabelMap[activePlatform] || activePlatform || '—')
                }}
              </h2>
              <p>
                {{
                  isAllPlatformsView
                    ? (todoOnly ? '各端待补热力' : '各端词 × 日均位')
                    : (todoOnly ? '只看待补格子' : '全量词 × 日均位')
                }}
              </p>
            </div>
          </div>
          <div class="sb-main-head-right">
            <label class="sb-toggle" :class="{ on: showBeforeCompare }">
              <input v-model="showBeforeCompare" type="checkbox">
              对照补录前
            </label>
            <div class="sb-kpis" :class="{ 'is-compare': showBeforeCompare }">
              <div class="sb-kpi primary">
                <strong v-if="showBeforeCompare">
                  <em>{{ headKpisBefore.todo }}</em><i>→</i>{{ headKpisAfter.todo }}
                </strong>
                <strong v-else>{{ headKpisAfter.todo }}</strong>
                <span>待补录</span>
              </div>
              <div class="sb-kpi">
                <strong v-if="showBeforeCompare">
                  <em>{{ headKpisBefore.fail }}</em><i>→</i>{{ headKpisAfter.fail }}
                </strong>
                <strong v-else>{{ headKpisAfter.fail }}</strong>
                <span>失败未忽略</span>
              </div>
              <div class="sb-kpi secondary">
                <strong v-if="showBeforeCompare">
                  <em>{{ formatKpiAvg(headKpisBefore.avg) }}</em><i>→</i>{{ formatKpiAvg(headKpisAfter.avg) }}
                </strong>
                <strong v-else>{{ formatKpiAvg(headKpisAfter.avg) }}</strong>
                <span>均位</span>
              </div>
            </div>
          </div>
        </div>

        <div v-if="loading" class="mini-empty">加载中…</div>
        <template v-else-if="isAllPlatformsView">
          <div v-if="!visiblePlatforms.length || !dates.length" class="mini-empty snapshot-backfill-empty">
            当前筛选下没有矩阵数据
          </div>
          <template v-else-if="showBeforeCompare">
            <div class="sb-compare has-words">
              <div
                class="sb-compare-words"
                data-compare-scroll="words"
                data-compare-axis="y"
                @scroll.passive="onCompareScroll"
              >
                <div class="sb-compare-label">监测词</div>
                <div class="sb-plat-blocks">
                  <div
                    v-for="p in visiblePlatforms"
                    :key="`words-${p.id}`"
                    class="sb-plat-block"
                  >
                    <!-- 2026-09-01 - 词列平台头与热力同结构，避免行对不齐 -->
                    <div class="sb-plat-block-head">
                      <div class="sb-platform-title">
                        <div class="sb-platform-logo">{{ (p.name || p.id).slice(0, 1) }}</div>
                        <div>
                          <h3>{{ p.name || platformLabelMap[p.id] || p.id }}</h3>
                          <p class="sb-words-plat-meta">
                            {{ p.todo }} 待补 · {{ p.fail }} 失败 · 均位 {{ p.avg ?? '—' }}
                          </p>
                        </div>
                      </div>
                    </div>
                    <div v-if="!wordsForPlatform(p.id).length" class="mini-empty">—</div>
                    <table v-else class="sb-matrix sb-matrix-words">
                      <thead>
                        <tr>
                          <th>监测词</th>
                        </tr>
                      </thead>
                      <tbody>
                        <tr v-for="word in wordsForPlatform(p.id)" :key="`words-${p.id}-${word}`">
                          <th :title="`${word} · 时段提及 ${formatWordPeriodMentionRate(p.id, word)}`">
                            <div class="sb-word-cell">
                              <span class="sb-word-text">{{ word }}</span>
                              <span class="sb-word-rate">{{ formatWordPeriodMentionRate(p.id, word) }}</span>
                            </div>
                          </th>
                        </tr>
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>
              <div
                v-for="pane in comparePanes"
                :key="pane.id"
                class="sb-compare-pane"
                :data-compare-scroll="pane.id"
                data-compare-axis="xy"
                @scroll.passive="onCompareScroll"
              >
                <div class="sb-compare-label">{{ pane.label }}</div>
                <div class="sb-plat-blocks">
                  <div
                    v-for="p in visiblePlatforms"
                    :id="pane.id === 'after' ? `sb-plat-block-${p.id}` : undefined"
                    :key="`${pane.id}-${p.id}`"
                    class="sb-plat-block"
                    :class="{ active: p.id === activePlatform }"
                  >
                    <div class="sb-plat-block-head">
                      <div class="sb-platform-title">
                        <div class="sb-platform-logo">{{ (p.name || p.id).slice(0, 1) }}</div>
                        <div>
                          <h3>{{ p.name || platformLabelMap[p.id] || p.id }}</h3>
                          <p>
                            {{ platformMetaForPane(pane.id, p.id)?.todo ?? p.todo }} 待补 ·
                            {{ platformMetaForPane(pane.id, p.id)?.fail ?? p.fail }} 失败 ·
                            均位 {{ platformMetaForPane(pane.id, p.id)?.avg ?? p.avg ?? '—' }}
                          </p>
                        </div>
                      </div>
                    </div>
                    <div v-if="!wordsForPlatform(p.id).length" class="mini-empty">该端暂无格子</div>
                    <div v-else class="sb-matrix-wrap">
                      <table class="sb-matrix sb-matrix-heat">
                        <thead>
                          <tr>
                            <th v-for="d in dates" :key="d">{{ shortDate(d) }}</th>
                          </tr>
                        </thead>
                        <tbody>
                          <tr
                            v-for="word in wordsForPlatform(p.id)"
                            :key="`${pane.id}-${p.id}-${word}`"
                          >
                            <td v-for="d in dates" :key="`${pane.id}-${p.id}-${word}-${d}`">
                              <button
                                v-if="getCellForPane(pane.id, word, d, p.id)"
                                type="button"
                                class="sb-cell"
                                :class="[
                                  rankClass(getCellForPane(pane.id, word, d, p.id)?.rank),
                                  { 'has-todo': getCellForPane(pane.id, word, d, p.id)?.has_todo },
                                ]"
                                :title="cellHoverTitle(pane.id, word, d, p.id)"
                                @click="openCell(word, d, p.id, pane.id)"
                              >
                                <span>{{ rankText(getCellForPane(pane.id, word, d, p.id)?.rank) }}</span>
                              </button>
                              <span
                                v-else
                                class="sb-cell rank-none is-empty"
                                :title="cellHoverTitle(pane.id, word, d, p.id)"
                              >—</span>
                            </td>
                          </tr>
                        </tbody>
                      </table>
                    </div>
                  </div>
                </div>
              </div>
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
          <div v-else class="sb-plat-blocks">
            <div
              v-for="p in visiblePlatforms"
              :id="`sb-plat-block-${p.id}`"
              :key="p.id"
              class="sb-plat-block"
              :class="{ active: p.id === activePlatform }"
            >
              <div class="sb-plat-block-head">
                <div class="sb-platform-title">
                  <div class="sb-platform-logo">{{ (p.name || p.id).slice(0, 1) }}</div>
                  <div>
                    <h3>{{ p.name || platformLabelMap[p.id] || p.id }}</h3>
                    <p>{{ p.todo }} 待补 · {{ p.fail }} 失败 · 均位 {{ p.avg ?? '—' }}</p>
                  </div>
                </div>
              </div>
              <div v-if="!wordsForPlatform(p.id).length" class="mini-empty">该端暂无格子</div>
              <div v-else class="sb-matrix-wrap">
                <table class="sb-matrix">
                  <thead>
                    <tr>
                      <th>监测词 \\ 日期</th>
                      <th v-for="d in dates" :key="d">{{ shortDate(d) }}</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="word in wordsForPlatform(p.id)" :key="`${p.id}-${word}`">
                      <th :title="word">{{ word }}</th>
                      <td v-for="d in dates" :key="`${p.id}-${word}-${d}`">
                        <button
                          v-if="getCell(word, d, p.id)"
                          type="button"
                          class="sb-cell"
                          :class="[
                            rankClass(getCell(word, d, p.id)?.rank),
                            { 'has-todo': getCell(word, d, p.id)?.has_todo },
                          ]"
                          @click="openCell(word, d, p.id)"
                        >
                          <span>{{ rankText(getCell(word, d, p.id)?.rank) }}</span>
                        </button>
                        <span v-else class="sb-cell rank-none is-empty">—</span>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
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
          </div>
        </template>
        <div v-else-if="!visibleWords.length || !dates.length" class="mini-empty snapshot-backfill-empty">
          当前筛选下没有矩阵数据
        </div>
        <template v-else-if="showBeforeCompare">
          <div class="sb-compare has-words">
            <div
              class="sb-compare-words"
              data-compare-scroll="words"
              data-compare-axis="y"
              @scroll.passive="onCompareScroll"
            >
              <div class="sb-compare-label">监测词</div>
              <table class="sb-matrix sb-matrix-words">
                <thead>
                  <tr>
                    <th>监测词</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="word in visibleWords" :key="`words-${word}`">
                    <th :title="`${word} · 时段提及 ${formatWordPeriodMentionRate(activePlatform, word)}`">
                      <div class="sb-word-cell">
                        <span class="sb-word-text">{{ word }}</span>
                        <span class="sb-word-rate">{{ formatWordPeriodMentionRate(activePlatform, word) }}</span>
                      </div>
                    </th>
                  </tr>
                </tbody>
              </table>
            </div>
            <div
              v-for="pane in comparePanes"
              :key="pane.id"
              class="sb-compare-pane"
              :data-compare-scroll="pane.id"
              data-compare-axis="xy"
              @scroll.passive="onCompareScroll"
            >
              <div class="sb-compare-label">{{ pane.label }}</div>
              <div class="sb-matrix-wrap">
                <table class="sb-matrix sb-matrix-heat">
                  <thead>
                    <tr>
                      <th v-for="d in dates" :key="d">{{ shortDate(d) }}</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr
                      v-for="word in visibleWords"
                      :key="`${pane.id}-${word}`"
                    >
                      <td v-for="d in dates" :key="`${pane.id}-${word}-${d}`">
                        <button
                          v-if="getCellForPane(pane.id, word, d)"
                          type="button"
                          class="sb-cell"
                          :class="[
                            rankClass(getCellForPane(pane.id, word, d)?.rank),
                            { 'has-todo': getCellForPane(pane.id, word, d)?.has_todo },
                          ]"
                          :title="cellHoverTitle(pane.id, word, d)"
                          @click="openCell(word, d, undefined, pane.id)"
                        >
                          <span>{{ rankText(getCellForPane(pane.id, word, d)?.rank) }}</span>
                        </button>
                        <span
                          v-else
                          class="sb-cell rank-none is-empty"
                          :title="cellHoverTitle(pane.id, word, d)"
                        >—</span>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
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

      <!-- 2026-09-01 - 对照补录前时藏侧栏，把宽度让给左右热力 -->
      <aside v-if="!showBeforeCompare" class="sb-panel sb-side">
        <h3>全平台对比</h3>
        <div class="sb-plat-list">
          <button
            v-for="p in displayPlatforms"
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

    <div v-else class="sb-mobile">
      <header class="sb-mobile-head">
        <div>
          <p class="sb-mobile-eyebrow">快照补录</p>
          <h2>{{ purposeFilter === 'brand_word' ? '品牌词待处理' : '监测待处理' }}</h2>
          <p>
            {{ mobileSummary?.pending ?? mobileItems.length }} 条待补
            <template v-if="tenantFilter !== ''"> · {{ tenants.find(item => item.id === tenantFilter)?.name || '当前企业' }}</template>
          </p>
        </div>
        <button type="button" class="sb-mobile-icon-btn" :disabled="loading" @click="() => loadMatrix()">
          <RefreshCw :size="18" />
          <span class="sr-only">刷新</span>
        </button>
      </header>

      <div class="sb-mobile-tabs" role="tablist" aria-label="补录分轨">
        <button type="button" :class="{ on: purposeFilter === 'geo' }" @click="purposeFilter = 'geo'">日常监测</button>
        <button type="button" :class="{ on: purposeFilter === 'brand_word' }" @click="purposeFilter = 'brand_word'">品牌词</button>
      </div>

      <div class="sb-mobile-tools">
        <button type="button" class="sb-mobile-filter-btn" @click="mobileFiltersOpen = true">
          筛选
          <span v-if="tenantFilter !== '' || platformFilter || keywordFilter || sourceFilter" class="sb-mobile-filter-dot" />
        </button>
        <label class="sb-toggle" :class="{ on: todoOnly }">
          <input v-model="todoOnly" type="checkbox">
          只看待补
        </label>
        <span class="sb-mobile-range">{{ filterDateFrom.slice(5) }} 至 {{ filterDateTo.slice(5) }}</span>
      </div>

      <div class="sb-mobile-platforms" aria-label="平台筛选">
        <button type="button" :class="{ on: !platformFilter }" @click="platformFilter = ''">全部</button>
        <button
          v-for="platform in platformFilterOptions"
          :key="platform.code"
          type="button"
          :class="{ on: platformFilter === platform.code }"
          @click="platformFilter = platform.code"
        >{{ platform.name }}</button>
      </div>

      <div v-if="loading" class="sb-mobile-state">正在加载待处理任务…</div>
      <div v-else-if="!mobileItems.length" class="sb-mobile-state is-empty">
        <strong>当前筛选下没有待处理任务</strong>
        <span>可以调整日期、企业或关闭“只看待补”。</span>
      </div>
      <div v-else class="sb-mobile-list">
        <article v-for="item in mobileItems" :key="item.subtask_id" class="sb-mobile-card">
          <div class="sb-mobile-card-top">
            <span class="sb-mobile-platform">{{ platformDisplayName(item.platform) }}</span>
            <span class="sb-mobile-status" :class="{ danger: item.needs_backfill && !item.has_answer }">
              {{ mobileStatusLabel(item) }}
            </span>
          </div>
          <h3>{{ item.prompt || '未命名监测问题' }}</h3>
          <p class="sb-mobile-card-meta">
            {{ item.tenant_name || item.brand_name || '未知企业' }} · {{ mobileSourceLabel(item) }} · {{ mobileItemDate(item) }}
          </p>
          <div class="sb-mobile-card-facts">
            <span>监测词<strong>{{ item.monitor_keywords || '—' }}</strong></span>
            <span>位次<strong>{{ rankText(item.mention_position) }}</strong></span>
          </div>
          <p v-if="item.error_message" class="sb-mobile-error">{{ item.error_message }}</p>
          <div class="sb-mobile-card-actions">
            <button type="button" class="sb-btn ghost" @click="openDetail(item)">查看详情</button>
            <button
              v-if="canSubmitBackfill"
              type="button"
              class="sb-btn"
              @click="openMobileBackfill(item)"
            >
              <Upload :size="15" />
              补录
            </button>
            <button
              v-if="canSubmitBackfill && !item.backfill_dismissed"
              type="button"
              class="sb-btn ghost is-dismiss"
              @click="dismissMobileItem(item)"
            >
              <EyeOff :size="15" />
              忽略
            </button>
          </div>
        </article>
      </div>

      <button
        v-if="mobileSummary?.has_more"
        type="button"
        class="sb-mobile-load-more"
        :disabled="mobileLoadingMore"
        @click="loadMobileItems({ append: true })"
      >{{ mobileLoadingMore ? '加载中…' : '加载更多' }}</button>

      <div v-if="mobileFiltersOpen" class="sb-mobile-filter-layer" @click.self="mobileFiltersOpen = false">
        <section class="sb-mobile-filter-sheet" role="dialog" aria-modal="true" aria-label="筛选待补录任务">
          <header>
            <div>
              <p>筛选条件</p>
              <span>修改后会自动刷新任务列表</span>
            </div>
            <button type="button" class="sb-mobile-filter-close" @click="mobileFiltersOpen = false">完成</button>
          </header>
          <div class="sb-mobile-filter-fields">
            <label>
              <span>企业</span>
              <select v-model="tenantFilter">
                <option value="">全部企业</option>
                <option v-for="tenant in tenants" :key="tenant.id" :value="tenant.id">{{ tenant.name }}</option>
              </select>
            </label>
            <div class="sb-mobile-date-row">
              <label><span>开始日期</span><input v-model="filterDateFrom" type="date"></label>
              <label><span>结束日期</span><input v-model="filterDateTo" type="date"></label>
            </div>
            <label>
              <span>来源</span>
              <select v-model="sourceFilter">
                <option value="">全部来源</option>
                <option value="tenant_monitor">{{ purposeFilter === 'brand_word' ? '品牌词监测' : 'GEO 监测' }}</option>
                <option v-if="purposeFilter === 'geo'" value="lead_diagnosis">售前诊断</option>
              </select>
            </label>
            <label>
              <span>{{ purposeFilter === 'brand_word' ? '品牌词组' : '词组' }}</span>
              <select v-model="keywordGroupFilter" :disabled="!keywordGroupOptions.length">
                <option value="">全部</option>
                <option
                  v-for="(group, index) in keywordGroupOptions"
                  :key="keywordGroupSelectValue(group, index)"
                  :value="keywordGroupSelectValue(group, index)"
                >{{ keywordGroupDisplayName(group, index) }}</option>
              </select>
            </label>
            <label>
              <span>{{ purposeFilter === 'brand_word' ? '品牌词' : '监测词' }}</span>
              <select v-model="keywordFilter" :disabled="!monitorKeywordOptions.length">
                <option value="">全部</option>
                <option v-for="keyword in monitorKeywordOptions" :key="keyword" :value="keyword">{{ keyword }}</option>
              </select>
            </label>
          </div>
          <button type="button" class="sb-mobile-reset" @click="resetFilters">恢复默认筛选</button>
        </section>
      </div>
    </div>

    <div v-if="cellDrawerVisible && cellDrawer" class="sb-drawer" @click.self="closeCellDrawer">
      <div class="sb-drawer-panel">
        <h3>格子待办</h3>
        <div class="sub">
          {{ platformDisplayName(cellDrawer.platform) }} · {{ cellDrawer.word }} · {{ cellDrawer.date }}
          · 均位 {{ rankText(cellDrawer.rank) }}
        </div>

        <label
          v-if="drawerDismissedSlots.length"
          class="sb-dismissed-toggle"
        >
          <input v-model="showDismissedSlots" type="checkbox" />
          显示已忽略（{{ drawerDismissedSlots.length }}）
        </label>

        <div
          v-for="slot in drawerActiveSlots"
          :key="slotKey(slot)"
          class="sb-todo-item"
        >
          <div class="t">{{ slot.schedule_label || slot.schedule_window_key || '场次' }} · {{ slotStatusLabel(slot) }}</div>
          <div class="d">
            位次 {{ rankText(slot.mention_position) }}
            <template v-if="slot.error_message"> · {{ slot.error_message }}</template>
          </div>
          <div class="sb-todo-actions">
            <button v-if="slot.subtask_id" type="button" class="sb-btn ghost" @click="openDetail(slotToItem(slot))">详情</button>
            <button
              v-if="canSubmitBackfill && cellDrawerAllowBackfill"
              type="button"
              class="sb-btn"
              @click="openBackfillFromSlot(slot)"
            >
              <Upload :size="14" />
              补录
            </button>
            <button
              v-if="canSubmitBackfill && cellDrawerAllowBackfill && !slot.backfill_dismissed && (slot.subtask_id || slot.is_gap)"
              type="button"
              class="sb-btn ghost"
              @click="dismissSlot(slot)"
            >
              <EyeOff :size="14" />
              忽略
            </button>
          </div>
        </div>

        <p v-if="!drawerActiveSlots.length && !showDismissedSlots" class="sb-drawer-empty">
          {{ drawerDismissedSlots.length ? '当前无待办场次，可勾选上方「显示已忽略」。' : '当前无场次。' }}
        </p>

        <template v-if="showDismissedSlots && drawerDismissedSlots.length">
          <div class="sb-dismissed-section-title">已忽略</div>
          <div
            v-for="slot in drawerDismissedSlots"
            :key="`dismissed-${slotKey(slot)}`"
            class="sb-todo-item is-dismissed"
          >
            <div class="t">{{ slot.schedule_label || slot.schedule_window_key || '场次' }} · 已忽略</div>
            <div class="d">
              位次 {{ rankText(slot.mention_position) }}
              <template v-if="slot.error_message"> · {{ slot.error_message }}</template>
            </div>
            <div class="sb-todo-actions">
              <button v-if="slot.subtask_id" type="button" class="sb-btn ghost" @click="openDetail(slotToItem(slot))">详情</button>
              <button
                v-if="canSubmitBackfill && cellDrawerAllowBackfill && slot.subtask_id"
                type="button"
                class="sb-btn"
                @click="undismissFromSlot(slot)"
              >
                取消忽略
              </button>
            </div>
          </div>
        </template>

        <button type="button" class="sb-btn ghost" @click="closeCellDrawer">关闭</button>
      </div>
    </div>

    <SnapshotBackfillDetailDrawer
      v-model:visible="detailVisible"
      :loading="detailLoading"
      :item="detailItem"
      :subtask="detailSubtask"
      :can-submit="canSubmitBackfill && cellDrawerAllowBackfill"
      :prefer-before="!cellDrawerAllowBackfill"
      @update:subtask="detailSubtask = $event"
      @backfill="openBackfillFromDetail"
      @undismiss="undismissFromDetail"
    />

    <SnapshotBackfillDialog
      v-model:visible="backfillVisible"
      :subtask="backfillTarget"
      @success="handleSuccess"
      @parse-queued="handleParseQueued"
    />
  </section>
</template>
