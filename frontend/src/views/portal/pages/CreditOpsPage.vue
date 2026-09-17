<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { Gauge, TrendingDown, Wallet } from '@lucide/vue'
import { ElDrawer, ElMessage, ElMessageBox } from 'element-plus'
import 'element-plus/es/components/drawer/style/css'
import {
  adjustTenantCredit,
  cancelPendingBillingMode,
  creditPlatformLedgerExportUrl,
  getBillingModeHistory,
  getCreditBlocks,
  getCreditOpsSummary,
  getCreditPlatformLedgerDetail,
  getCreditTenants,
  getTenantCredit,
  getTenantCreditLedger,
  listCreditPlatformLedger,
  previewBillingModeSwitch,
  switchBillingMode,
  updateTenantCreditPolicy,
  type CreditLedgerDetail,
  type CreditLedgerItem,
} from '../../../services/credit'
import { getTenants, isTenantInService, type TenantInfo } from '../../../services/management'
import { useAuthStore } from '../../../stores/auth'
import { extractErrorDetail } from '../../../utils/requestError'
import CreditBillingConfigPanel from '../components/CreditBillingConfigPanel.vue'

// 2026-09-08 - 方案甲：去掉独立「零余额」Tab，并进概览筛选；顶栏改轻量导航
type PageTab = 'overview' | 'recharge' | 'blocks' | 'pricing' | 'mode'
/** @deprecated 旧 deep-link `credit_tab=zero` 仍接收，映射到概览+仅零余额 */
type IncomingTab = PageTab | 'zero'
type BlockReason = 'tenant_credit' | 'platform_balance' | 'terms' | 'inactive' | 'balance_capped'

const props = defineProps<{
  initialTab?: IncomingTab
  initialTenantId?: number
  /** @deprecated 2026-09-07 - 提交拦截已合并为一张表，不再按原因分 Tab */
  initialBlockTab?: BlockReason | 'daily_cap'
}>()

const auth = useAuthStore()
// 2026-08-28 - 侧栏合并后充值权限挂在 credit_ops_board.can_update
const canRecharge = computed(() => {
  const menus = auth.allowedMenus
  return Boolean(
    menus.find(menu => menu.menu_code === 'platform.credit_ops_board')?.can_update
    || menus.find(menu => menu.menu_code === 'platform.tenant_credit')?.can_update,
  )
})
const canEditPricing = computed(() => canRecharge.value)

function resolvePageTab(tab: IncomingTab | undefined): PageTab {
  if (!tab || tab === 'zero') return 'overview'
  return tab
}

const loading = ref(false)
const pageTab = ref<PageTab>(resolvePageTab(props.initialTab))
const summary = ref<Record<string, unknown> | null>(null)
const TENANT_INLINE_LIMIT = 30
const TENANT_PAGE_SIZE = 20
const LEDGER_PAGE_SIZE = 20
/** 充值页只展示短列表，完整巡检走概览全平台流水 */
const RECHARGE_LEDGER_PAGE_SIZE = 5
const LEDGER_FILTER_DEBOUNCE_MS = 300
const DEFAULT_CREDITS_PER_YUAN = 4.2

const creditTenants = ref<Array<Record<string, unknown>>>([])
const tenantSearch = ref('')
const tenantZeroOnly = ref(props.initialTab === 'zero')
const tenantPage = ref(1)
const platformLedger = ref<{ items: CreditLedgerItem[]; page_size?: number } | null>(null)
const ledgerPage = ref(1)
const ledgerTenantNameFilter = ref('')
let ledgerFilterDebounceTimer: ReturnType<typeof setTimeout> | null = null
const ledgerDetail = ref<CreditLedgerDetail | null>(null)
const ledgerDrawerVisible = ref(false)
const ledgerDetailLoading = ref(false)
const ledgerDetailRowKey = ref<string | null>(null)

const rechargeTenantSearch = ref('')
const rechargeTenantPage = ref(1)
const selectedRechargeTenantId = ref<number | null>(props.initialTenantId ?? null)
const rechargeTenantDetail = ref<Record<string, unknown> | null>(null)
const rechargeTenantLedger = ref<CreditLedgerItem[]>([])
const rechargeTenantLedgerPage = ref(1)
const showInternalLedger = ref(false)
const rechargeYuan = ref('')
const rechargeRateInput = ref(String(DEFAULT_CREDITS_PER_YUAN))
const savingRechargeRate = ref(false)
const rechargeCredits = ref('')
const rechargeCreditsTouched = ref(false)
const rechargeReason = ref('')
const recharging = ref(false)
const showDeductForm = ref(false)
const deductAmount = ref('')
const deductReason = ref('')
const deducting = ref(false)

// 2026-09-08 - 托管↔自助只走算力运营，企业详情不再挂切换表单
const modeTenants = ref<TenantInfo[]>([])
const modeTenantSearch = ref('')
const selectedModeTenantId = ref<number | null>(props.initialTenantId ?? null)
const modeSwitchTarget = ref<'hosted' | 'credit'>('credit')
const modeSwitchEffective = ref<'next_window' | 'immediate'>('next_window')
const modeSwitchOpening = ref('')
const modeSwitchReason = ref('')
const modeSwitching = ref(false)
const modeCancelling = ref(false)
const modePreviewLoading = ref(false)
const modeSuggestedOpening = ref<number | null>(null)
const modeHistory = ref<Array<{
  id: number
  from_mode: string
  to_mode: string
  reason: string
  effective_policy: string
  effective_at: string | null
  opening_credit_amount: number | null
  status: string
  created_at: string
}>>([])

const pendingModeSwitch = computed(() => modeHistory.value.find(row => row.status === 'pending') || null)

/** 待下窗超过该天数仍未提交监测 → 提示改立即 */
const PENDING_MODE_STALE_DAYS = 3

const pendingModeStaleDays = computed(() => {
  const createdAt = pendingModeSwitch.value?.created_at
  if (!createdAt) return 0
  const ts = Date.parse(String(createdAt).replace(' ', 'T'))
  if (!Number.isFinite(ts)) return 0
  return Math.floor((Date.now() - ts) / 86_400_000)
})

const pendingModeIsStale = computed(() => pendingModeStaleDays.value >= PENDING_MODE_STALE_DAYS)

function modeStatusLabel(status: string) {
  if (status === 'pending') return '待下窗生效'
  if (status === 'cancelled') return '已取消'
  if (status === 'superseded') return '已被覆盖'
  return '已生效'
}

// 2026-09-07 - 提交拦截合并为一表，不再按原因分 Tab
const blocksLoading = ref(false)
const blocks = ref<{ items: Array<Record<string, unknown>> } | null>(null)

const entryTypeLabel: Record<string, string> = {
  recharge: '充值', adjust: '扣减', reserve: '预扣', release: '释放', settle: '结算',
}

const rechargeLedgerTypeLabel: Record<string, string> = {
  recharge: '充值',
  adjust: '扣减',
  settle: '扣费',
}

const blockReasonLabel: Record<string, string> = {
  tenant_credit: '客户算力不足',
  platform_balance: '平台余额不足',
  terms: '条款相关（已不拦截）',
  inactive: '企业停服',
  balance_capped: '结算少收（余额封顶）',
  daily_cap: '日上限（已退役）',
}

const subtaskStatusLabel: Record<string, string> = {
  settled: '已结算',
  released_unbilled: '未计费已释放',
  released: '已释放',
  pending: '待处理',
  submitted: '已提交',
  completed: '已完成',
  failed: '失败',
  stopped: '已停止',
}

function formatBlockReason(code: unknown) {
  const key = String(code || '')
  return blockReasonLabel[key] || key || '—'
}

function formatSubtaskStatus(status: unknown) {
  const key = String(status || '').trim()
  if (!key) return '—'
  return subtaskStatusLabel[key] || subtaskStatusLabel[key.toLowerCase()] || key
}

function ledgerRowKey(row: CreditLedgerItem) {
  return `${row.tenant_id || ''}:${row.id}`
}

function filterTenantsByKeyword(rows: Array<Record<string, unknown>>, keyword: string) {
  const q = keyword.trim().toLowerCase()
  if (!q) return rows
  return rows.filter(row => String(row.name || '').toLowerCase().includes(q))
}

function dedupeTenantsByName(rows: Array<Record<string, unknown>>) {
  // 2026-08-28 - 同名企业去重 - 与后端 tenants 接口一致，前端兜底
  const byName = new Map<string, Record<string, unknown>>()
  for (const row of rows) {
    const tenantId = Number(row.tenant_id)
    const nameKey = String(row.name || '').trim().toLowerCase() || `#${tenantId}`
    const prev = byName.get(nameKey)
    if (!prev || tenantId > Number(prev.tenant_id)) byName.set(nameKey, row)
  }
  return Array.from(byName.values()).sort((a, b) => String(a.name || '').localeCompare(String(b.name || ''), 'zh-CN'))
}

function paginateTenants(rows: Array<Record<string, unknown>>, page: number) {
  if (rows.length <= TENANT_INLINE_LIMIT) return rows
  const start = (page - 1) * TENANT_PAGE_SIZE
  return rows.slice(start, start + TENANT_PAGE_SIZE)
}

const uniqueCreditTenants = computed(() => dedupeTenantsByName(creditTenants.value))

const zeroBalanceCount = computed(() => {
  const fromSummary = Number(summary.value?.zero_balance_count)
  if (Number.isFinite(fromSummary) && fromSummary >= 0) return fromSummary
  return uniqueCreditTenants.value.filter(row => Number(row.credit_balance || 0) <= 0).length
})

const filteredCreditTenants = computed(() => {
  let rows = filterTenantsByKeyword(uniqueCreditTenants.value, tenantSearch.value)
  if (tenantZeroOnly.value) {
    rows = rows.filter(row => Number(row.credit_balance || 0) <= 0)
  }
  return rows
})
const filteredRechargeTenants = computed(() => filterTenantsByKeyword(uniqueCreditTenants.value, rechargeTenantSearch.value))

const tenantPagerVisible = computed(() => filteredCreditTenants.value.length > TENANT_INLINE_LIMIT)
const rechargeTenantPagerVisible = computed(() => filteredRechargeTenants.value.length > TENANT_INLINE_LIMIT)

const tenantPageCount = computed(() => (
  tenantPagerVisible.value
    ? Math.max(1, Math.ceil(filteredCreditTenants.value.length / TENANT_PAGE_SIZE))
    : 1
))
const rechargeTenantPageCount = computed(() => (
  rechargeTenantPagerVisible.value
    ? Math.max(1, Math.ceil(filteredRechargeTenants.value.length / TENANT_PAGE_SIZE))
    : 1
))

const visibleCreditTenants = computed(() => paginateTenants(filteredCreditTenants.value, tenantPage.value))
const visibleRechargeTenants = computed(() => paginateTenants(filteredRechargeTenants.value, rechargeTenantPage.value))

const selectedRechargeTenant = computed(() => (
  uniqueCreditTenants.value.find(row => Number(row.tenant_id) === selectedRechargeTenantId.value) || null
))

function policyCreditsPerYuan(detail: Record<string, unknown> | null) {
  const policy = detail?.credit_policy as Record<string, unknown> | undefined
  const rate = Number(policy?.credits_per_yuan)
  return Number.isFinite(rate) && rate > 0 ? rate : DEFAULT_CREDITS_PER_YUAN
}

function parseRechargeRateInput(raw: string) {
  const rate = Number(raw)
  return Number.isFinite(rate) && rate > 0 ? rate : null
}

const rechargeCreditsPerYuan = computed(() => (
  parseRechargeRateInput(rechargeRateInput.value) ?? policyCreditsPerYuan(rechargeTenantDetail.value)
))

function syncRechargeRateFromDetail() {
  rechargeRateInput.value = String(policyCreditsPerYuan(rechargeTenantDetail.value))
}

function previewCreditsFromYuan(yuan: number) {
  if (!Number.isFinite(yuan) || yuan <= 0) return null
  return Math.round(yuan * rechargeCreditsPerYuan.value * 10) / 10
}

const rechargeCreditPreview = computed(() => previewCreditsFromYuan(Number(rechargeYuan.value)))

function syncRechargeCreditsFromYuan() {
  if (rechargeCreditsTouched.value) return
  const preview = rechargeCreditPreview.value
  rechargeCredits.value = preview != null ? String(preview) : ''
}

const rechargeCreditsValue = computed(() => {
  const credits = Number(rechargeCredits.value)
  return Number.isFinite(credits) && credits > 0 ? credits : null
})

const canSubmitRecharge = computed(() => (
  rechargeCreditsValue.value != null || (Number(rechargeYuan.value) > 0 && rechargeCreditPreview.value != null)
))

const rechargeAvailable = computed(() => {
  const balance = Number(rechargeTenantDetail.value?.credit_balance || 0)
  const reserved = Number(rechargeTenantDetail.value?.credit_reserved || 0)
  return Math.max(0, balance - reserved)
})

const ledgerHasNextPage = computed(() => (
  (platformLedger.value?.items.length || 0) >= (platformLedger.value?.page_size || LEDGER_PAGE_SIZE)
))

const rechargeTenantLedgerHasNext = computed(() => rechargeTenantLedger.value.length >= RECHARGE_LEDGER_PAGE_SIZE)

const filteredModeTenants = computed(() => {
  const q = modeTenantSearch.value.trim().toLowerCase()
  const rows = modeTenants.value.filter(isTenantInService)
  if (!q) return rows
  return rows.filter(row => String(row.name || '').toLowerCase().includes(q))
})

const selectedModeTenant = computed(() => (
  modeTenants.value.find(row => row.id === selectedModeTenantId.value) || null
))
const selectedModeIsCredit = computed(() => selectedModeTenant.value?.billing_mode === 'credit')

function modeTenantBillingLabel(row: TenantInfo) {
  if (row.billing_mode !== 'credit') return '托管'
  const balance = Number(row.credit_balance)
  if (Number.isFinite(balance) && balance <= 0) return '自助·零余额'
  return '算力自助'
}

function formatLedgerAmount(amount: number) {
  const value = Number(amount)
  if (!Number.isFinite(value)) return '—'
  const text = Number.isInteger(value) ? String(value) : value.toFixed(1)
  return value > 0 ? `+${text}` : text
}

async function loadModeTabData() {
  modeTenants.value = await getTenants()
  if (selectedModeTenantId.value) {
    await selectModeTenant(selectedModeTenantId.value)
  }
}

async function selectModeTenant(tenantId: number) {
  selectedModeTenantId.value = tenantId
  const tenant = modeTenants.value.find(row => row.id === tenantId)
  const isCredit = tenant?.billing_mode === 'credit'
  modeSwitchTarget.value = isCredit ? 'hosted' : 'credit'
  modeSwitchOpening.value = ''
  modeSuggestedOpening.value = null
  modeHistory.value = []
  try {
    modeHistory.value = await getBillingModeHistory(tenantId)
  } catch {
    modeHistory.value = []
  }
  if (!isCredit) {
    await refreshModePreview()
  }
}

async function refreshModePreview() {
  if (!selectedModeTenantId.value || modeSwitchTarget.value !== 'credit') {
    modeSuggestedOpening.value = null
    return
  }
  modePreviewLoading.value = true
  try {
    const preview = await previewBillingModeSwitch(selectedModeTenantId.value, 'credit')
    const suggested = Number(preview.suggested_opening_credit || 0)
    modeSuggestedOpening.value = Number.isFinite(suggested) ? suggested : null
    if (!modeSwitchOpening.value && modeSuggestedOpening.value != null && modeSuggestedOpening.value > 0) {
      modeSwitchOpening.value = String(Math.ceil(modeSuggestedOpening.value))
    }
  } catch {
    modeSuggestedOpening.value = null
  } finally {
    modePreviewLoading.value = false
  }
}

async function submitModeSwitch() {
  if (!canRecharge.value || !selectedModeTenantId.value || modeSwitching.value) return
  const reason = modeSwitchReason.value.trim()
  if (modeSwitchTarget.value === 'credit') {
    const opening = Number(modeSwitchOpening.value)
    if (!Number.isFinite(opening) || opening <= 0) {
      ElMessage.warning('转自助须填写起步算力')
      return
    }
  }
  const label = modeSwitchTarget.value === 'credit' ? '算力自助' : '平台托管'
  // 2026-09-09 - confirm 前加锁，避免弹窗期间连点双提交
  modeSwitching.value = true
  try {
    await ElMessageBox.confirm(`确认将该企业切换为「${label}」？`, '模式切换', { type: 'warning' })
  } catch {
    modeSwitching.value = false
    return
  }
  try {
    const payload: Record<string, unknown> = {
      target_mode: modeSwitchTarget.value,
      reason,
      effective_policy: modeSwitchEffective.value,
    }
    if (modeSwitchTarget.value === 'credit') {
      payload.opening_credit_amount = Number(modeSwitchOpening.value)
    }
    const result = await switchBillingMode(selectedModeTenantId.value, payload)
    if (result?.status === 'pending' || modeSwitchEffective.value === 'next_window') {
      ElMessage.success('已登记，待该企业下次监测提交时生效（新单会覆盖旧待生效）')
    } else {
      ElMessage.success('模式已立即切换')
    }
    modeSwitchReason.value = ''
    await loadModeTabData()
    try {
      summary.value = await getCreditOpsSummary()
      creditTenants.value = await getCreditTenants()
    } catch {
      /* overview refresh best-effort */
    }
  } catch (error) {
    ElMessage.error(extractErrorDetail(error, '切换失败'))
  } finally {
    modeSwitching.value = false
  }
}

async function cancelPendingModeSwitch() {
  if (!canRecharge.value || !selectedModeTenantId.value || !pendingModeSwitch.value) return
  try {
    await ElMessageBox.confirm('取消待生效的模式切换？当前计费模式不变。', '取消待生效', { type: 'warning' })
  } catch {
    return
  }
  modeCancelling.value = true
  try {
    await cancelPendingBillingMode(selectedModeTenantId.value)
    ElMessage.success('已取消待生效切换')
    await loadModeTabData()
  } catch (error) {
    ElMessage.error(extractErrorDetail(error, '取消失败'))
  } finally {
    modeCancelling.value = false
  }
}

/** A甲：空闲企业一键把当前 pending 改为立即生效（覆盖登记） */
async function applyPendingModeImmediately() {
  if (!canRecharge.value || !selectedModeTenantId.value || !pendingModeSwitch.value || modeSwitching.value) return
  const pending = pendingModeSwitch.value
  const toMode = pending.to_mode === 'hosted' ? 'hosted' : 'credit'
  if (toMode === 'credit') {
    const opening = Number(pending.opening_credit_amount)
    if (!Number.isFinite(opening) || opening <= 0) {
      ElMessage.warning('待生效单缺少起步算力，请在下方表单改「立即」后重新确认')
      modeSwitchTarget.value = 'credit'
      modeSwitchEffective.value = 'immediate'
      return
    }
  }
  modeSwitching.value = true
  try {
    await ElMessageBox.confirm(
      '确认立即生效？将马上改模式并动算力，不再等待下次监测提交。',
      '立即生效',
      { type: 'warning' },
    )
  } catch {
    modeSwitching.value = false
    return
  }
  try {
    const payload: Record<string, unknown> = {
      target_mode: toMode,
      reason: (pending.reason || '').trim() || '待下窗超时，改为立即生效',
      effective_policy: 'immediate',
    }
    if (toMode === 'credit') {
      payload.opening_credit_amount = Number(pending.opening_credit_amount)
    }
    await switchBillingMode(selectedModeTenantId.value, payload)
    ElMessage.success('模式已立即切换')
    modeSwitchReason.value = ''
    await loadModeTabData()
    try {
      summary.value = await getCreditOpsSummary()
      creditTenants.value = await getCreditTenants()
    } catch {
      /* overview refresh best-effort */
    }
  } catch (error) {
    ElMessage.error(extractErrorDetail(error, '立即生效失败'))
  } finally {
    modeSwitching.value = false
  }
}

async function loadSummary() {
  summary.value = await getCreditOpsSummary()
}

async function ensureCreditTenants() {
  if (creditTenants.value.length) return
  creditTenants.value = await getCreditTenants()
}

async function loadOverviewData() {
  loading.value = true
  try {
    await loadSummary()
    await ensureCreditTenants()
    await loadPlatformLedger()
  } catch (error) {
    ElMessage.error(extractErrorDetail(error, '加载失败'))
  } finally {
    loading.value = false
  }
}

async function loadRechargeTabData() {
  loading.value = true
  try {
    await ensureCreditTenants()
    if (selectedRechargeTenantId.value) {
      await loadRechargeTenantData()
    }
  } catch (error) {
    ElMessage.error(extractErrorDetail(error, '加载失败'))
  } finally {
    loading.value = false
  }
}

async function loadPlatformLedger(page = ledgerPage.value) {
  ledgerPage.value = Math.max(1, page)
  try {
    platformLedger.value = await listCreditPlatformLedger(ledgerPage.value, {
      tenantName: ledgerTenantNameFilter.value.trim() || undefined,
    })
  } catch (error) {
    ElMessage.error(extractErrorDetail(error, '加载流水失败'))
  }
}

function scheduleLedgerReload() {
  if (ledgerFilterDebounceTimer) clearTimeout(ledgerFilterDebounceTimer)
  ledgerFilterDebounceTimer = setTimeout(() => {
    ledgerFilterDebounceTimer = null
    ledgerPage.value = 1
    void loadPlatformLedger(1)
  }, LEDGER_FILTER_DEBOUNCE_MS)
}

async function loadRechargeTenantLedger(page = rechargeTenantLedgerPage.value) {
  if (!selectedRechargeTenantId.value) return
  rechargeTenantLedgerPage.value = Math.max(1, page)
  const data = await getTenantCreditLedger(selectedRechargeTenantId.value, page, {
    excludeInternal: !showInternalLedger.value,
    pageSize: RECHARGE_LEDGER_PAGE_SIZE,
  })
  rechargeTenantLedger.value = data.items || []
}

async function loadRechargeTenantData(page = rechargeTenantLedgerPage.value) {
  const tenantId = selectedRechargeTenantId.value
  if (!tenantId) {
    rechargeTenantDetail.value = null
    rechargeTenantLedger.value = []
    return
  }
  rechargeTenantDetail.value = await getTenantCredit(tenantId)
  syncRechargeRateFromDetail()
  await loadRechargeTenantLedger(page)
}

async function persistRechargeRate() {
  const tenantId = selectedRechargeTenantId.value
  if (!tenantId || !canRecharge.value) return
  const rate = parseRechargeRateInput(rechargeRateInput.value)
  const saved = policyCreditsPerYuan(rechargeTenantDetail.value)
  if (rate == null) {
    ElMessage.warning('汇率须大于 0')
    rechargeRateInput.value = String(saved)
    return
  }
  if (Math.abs(rate - saved) < 0.0001) return
  savingRechargeRate.value = true
  try {
    const data = await updateTenantCreditPolicy(tenantId, { credit_policy: { credits_per_yuan: rate } })
    rechargeTenantDetail.value = {
      ...(rechargeTenantDetail.value || {}),
      credit_policy: data.credit_policy,
    }
    syncRechargeRateFromDetail()
    ElMessage.success('充值汇率已保存')
    syncRechargeCreditsFromYuan()
  } catch (error) {
    rechargeRateInput.value = String(saved)
    ElMessage.error(extractErrorDetail(error, '保存汇率失败'))
  } finally {
    savingRechargeRate.value = false
  }
}

function selectRechargeTenant(tenantId: number) {
  selectedRechargeTenantId.value = tenantId
}

async function submitRecharge() {
  const tenantId = selectedRechargeTenantId.value
  if (!tenantId || recharging.value) {
    if (!tenantId) ElMessage.warning('请先选择企业')
    return
  }
  const yuan = Number(rechargeYuan.value)
  const credits = rechargeCreditsValue.value ?? rechargeCreditPreview.value
  const reason = rechargeReason.value.trim()
  if (credits == null || credits <= 0) {
    ElMessage.warning('请填写大于 0 的到账算力')
    return
  }
  const tenantName = String(selectedRechargeTenant.value?.name || tenantId)
  const rate = rechargeCreditsPerYuan.value
  const confirmText = Number.isFinite(yuan) && yuan > 0
    ? `确认为「${tenantName}」充值 ${credits} 算力？（填单 ${yuan} 元，参考 1 元 = ${rate} 算力）`
    : `确认为「${tenantName}」充值 ${credits} 算力？`
  // 2026-09-09 - confirm 前加锁；yuan 一并提交作审计快照
  recharging.value = true
  try {
    await ElMessageBox.confirm(confirmText, '充值确认', { type: 'warning' })
  } catch {
    recharging.value = false
    return
  }
  try {
    const payload: { amount: number; reason: string; yuan_amount?: number } = { amount: credits, reason }
    if (Number.isFinite(yuan) && yuan > 0) payload.yuan_amount = yuan
    await adjustTenantCredit(tenantId, payload)
    ElMessage.success(`充值成功，到账 ${credits} 算力`)
    rechargeYuan.value = ''
    rechargeCredits.value = ''
    rechargeCreditsTouched.value = false
    rechargeReason.value = ''
    creditTenants.value = await getCreditTenants()
    await Promise.all([loadRechargeTenantData(rechargeTenantLedgerPage.value), loadSummary()])
  } catch (error) {
    ElMessage.error(extractErrorDetail(error, '充值失败'))
  } finally {
    recharging.value = false
  }
}

async function submitDeduct() {
  const tenantId = selectedRechargeTenantId.value
  if (!tenantId || deducting.value) return
  const amount = Number(deductAmount.value)
  const reason = deductReason.value.trim()
  if (!Number.isFinite(amount) || amount <= 0) {
    ElMessage.warning('请填写大于 0 的扣减金额')
    return
  }
  if (reason.length < 2) {
    ElMessage.warning('请填写扣减原因')
    return
  }
  const tenantName = String(selectedRechargeTenant.value?.name || tenantId)
  deducting.value = true
  try {
    await ElMessageBox.confirm(
      `确认从「${tenantName}」扣减 ${amount} 算力？`,
      '扣减确认',
      { type: 'warning' },
    )
  } catch {
    deducting.value = false
    return
  }
  try {
    await adjustTenantCredit(tenantId, { amount: -amount, reason })
    ElMessage.success('扣减成功')
    deductAmount.value = ''
    deductReason.value = ''
    showDeductForm.value = false
    creditTenants.value = await getCreditTenants()
    await Promise.all([loadRechargeTenantData(rechargeTenantLedgerPage.value), loadSummary()])
  } catch (error) {
    ElMessage.error(extractErrorDetail(error, '扣减失败'))
  } finally {
    deducting.value = false
  }
}

async function loadBlocks() {
  blocksLoading.value = true
  try {
    // 不传 block_reason = 全原因合并列表
    blocks.value = await getCreditBlocks()
  } catch (error) {
    ElMessage.error(extractErrorDetail(error, '加载拦截列表失败'))
  } finally {
    blocksLoading.value = false
  }
}

function exportPlatformLedger() {
  window.open(creditPlatformLedgerExportUrl({
    tenantName: ledgerTenantNameFilter.value.trim() || undefined,
  }), '_blank')
}

async function openPlatformLedgerDetail(row: CreditLedgerItem) {
  if (!row.tenant_id) return
  const key = ledgerRowKey(row)
  if (ledgerDrawerVisible.value && ledgerDetailRowKey.value === key) {
    ledgerDrawerVisible.value = false
    ledgerDetailRowKey.value = null
    ledgerDetail.value = null
    return
  }
  ledgerDetailRowKey.value = key
  ledgerDrawerVisible.value = true
  ledgerDetailLoading.value = true
  ledgerDetail.value = null
  try {
    ledgerDetail.value = await getCreditPlatformLedgerDetail(row.tenant_id, row.id)
  } catch (error) {
    ElMessage.error(extractErrorDetail(error, '加载明细失败'))
    ledgerDrawerVisible.value = false
    ledgerDetailRowKey.value = null
  } finally {
    ledgerDetailLoading.value = false
  }
}

function onPlatformLedgerDrawerClosed() {
  ledgerDetailRowKey.value = null
  ledgerDetail.value = null
}

function closePlatformLedgerDrawer() {
  ledgerDrawerVisible.value = false
  onPlatformLedgerDrawerClosed()
}

async function switchPageTab(tab: IncomingTab, tenantId?: number) {
  // 2026-09-08 - 旧链接 credit_tab=zero → 概览并打开「仅零余额」
  if (tab === 'zero') {
    tenantZeroOnly.value = true
    tab = 'overview'
  }
  // 流水明细抽屉只服务概览；切走其他 Tab 时关掉，避免页底残留
  if (tab !== 'overview') {
    closePlatformLedgerDrawer()
  }
  pageTab.value = tab
  if (tab === 'overview') {
    if (!summary.value || !creditTenants.value.length) await loadOverviewData()
  }
  if (tab === 'recharge') {
    if (tenantId) selectedRechargeTenantId.value = tenantId
    await loadRechargeTabData()
  }
  if (tab === 'blocks' && !blocks.value) {
    await loadBlocks()
  }
  if (tab === 'mode') {
    loading.value = true
    try {
      if (tenantId) selectedModeTenantId.value = tenantId
      await loadModeTabData()
    } catch (error) {
      ElMessage.error(extractErrorDetail(error, '加载企业失败'))
    } finally {
      loading.value = false
    }
  }
}

watch(
  () => props.initialTab,
  tab => {
    if (!tab) return
    const next = resolvePageTab(tab)
    if (tab === 'zero') tenantZeroOnly.value = true
    if (next !== pageTab.value) void switchPageTab(tab, props.initialTenantId)
  },
)

watch(
  () => props.initialTenantId,
  tenantId => {
    if (tenantId && pageTab.value === 'recharge') {
      selectRechargeTenant(tenantId)
    }
  },
)

watch(tenantSearch, () => {
  tenantPage.value = 1
})

watch(tenantZeroOnly, () => {
  tenantPage.value = 1
})

watch(rechargeYuan, () => {
  syncRechargeCreditsFromYuan()
})

watch(rechargeCreditsPerYuan, () => {
  syncRechargeCreditsFromYuan()
})

watch(rechargeTenantSearch, () => {
  rechargeTenantPage.value = 1
  const ids = new Set(filteredRechargeTenants.value.map(row => Number(row.tenant_id)))
  if (selectedRechargeTenantId.value && !ids.has(selectedRechargeTenantId.value)) {
    selectedRechargeTenantId.value = null
    rechargeTenantDetail.value = null
    rechargeTenantLedger.value = []
  }
})

watch(modeSwitchTarget, () => {
  void refreshModePreview()
})

watch(
  () => props.initialTenantId,
  tenantId => {
    if (tenantId && pageTab.value === 'mode') {
      void selectModeTenant(tenantId)
    }
  },
)

watch(selectedRechargeTenantId, (tenantId, prev) => {
  if (tenantId && tenantId !== prev) {
    rechargeTenantLedgerPage.value = 1
    rechargeYuan.value = ''
    rechargeCredits.value = ''
    rechargeCreditsTouched.value = false
    rechargeReason.value = ''
    deductAmount.value = ''
    deductReason.value = ''
    showDeductForm.value = false
    void loadRechargeTenantData(1)
  }
  if (!tenantId) {
    rechargeTenantDetail.value = null
    rechargeTenantLedger.value = []
    rechargeRateInput.value = String(DEFAULT_CREDITS_PER_YUAN)
  }
})

watch(ledgerTenantNameFilter, () => {
  scheduleLedgerReload()
})

watch(showInternalLedger, () => {
  if (pageTab.value === 'recharge' && selectedRechargeTenantId.value) {
    rechargeTenantLedgerPage.value = 1
    void loadRechargeTenantLedger(1)
  }
})

watch(filteredCreditTenants, (rows) => {
  const maxPage = Math.max(1, Math.ceil(rows.length / TENANT_PAGE_SIZE))
  if (tenantPage.value > maxPage) tenantPage.value = maxPage
})

watch(filteredRechargeTenants, (rows) => {
  const maxPage = Math.max(1, Math.ceil(rows.length / TENANT_PAGE_SIZE))
  if (rechargeTenantPage.value > maxPage) rechargeTenantPage.value = maxPage
})

onMounted(() => {
  // 2026-09-09 - 旧 block_tab=terms/daily_cap 等 deep-link → 合并提交拦截表
  if (props.initialBlockTab) {
    void switchPageTab('blocks')
    return
  }
  if (pageTab.value === 'blocks') {
    void loadBlocks()
    void loadSummary()
    return
  }
  if (pageTab.value === 'recharge') {
    void switchPageTab('recharge', props.initialTenantId)
    return
  }
  if (pageTab.value === 'mode') {
    void switchPageTab('mode', props.initialTenantId)
    return
  }
  void loadOverviewData()
})

onUnmounted(() => {
  if (ledgerFilterDebounceTimer) clearTimeout(ledgerFilterDebounceTimer)
})
</script>

<template>
  <section class="feature-page">
    <!-- 2026-09-08 - 方案甲：大卡 Tab 改轻量导航；零余额并入概览筛选 -->
    <article class="panel credit-ops-shell">
      <nav class="credit-ops-nav" aria-label="算力运营分区">
        <button type="button" :class="{ active: pageTab === 'overview' }" @click="switchPageTab('overview')">
          概览
          <i v-if="zeroBalanceCount > 0">{{ zeroBalanceCount }}</i>
        </button>
        <button type="button" :class="{ active: pageTab === 'recharge' }" @click="switchPageTab('recharge')">充值与流水</button>
        <button type="button" :class="{ active: pageTab === 'blocks' }" @click="switchPageTab('blocks')">提交拦截</button>
        <button type="button" :class="{ active: pageTab === 'pricing' }" @click="switchPageTab('pricing')">定价与条款</button>
        <button type="button" :class="{ active: pageTab === 'mode' }" @click="switchPageTab('mode')">模式切换</button>
      </nav>

      <template v-if="pageTab === 'overview'">
        <div v-loading="loading" class="credit-ops-body">
          <article class="panel credit-section-panel">
            <div class="panel-head">
              <h2>算力企业列表</h2>
            </div>
            <div class="log-filter-bar credit-tenant-filter">
              <input v-model="tenantSearch" type="search" placeholder="搜索公司名称">
              <div class="credit-filter-chips" role="group" aria-label="余额筛选">
                <button type="button" :class="{ on: !tenantZeroOnly }" @click="tenantZeroOnly = false">全部</button>
                <button type="button" :class="{ on: tenantZeroOnly }" @click="tenantZeroOnly = true">
                  仅零余额
                  <span v-if="zeroBalanceCount > 0">{{ zeroBalanceCount }}</span>
                </button>
              </div>
            </div>
            <div class="credit-data-table">
              <div class="credit-data-head credit-tenant-cols">
                <span>企业</span><span>余额</span><span>预扣</span><span>今日已扣</span><span>日预估</span><span>销售</span>
              </div>
              <div
                v-for="row in visibleCreditTenants"
                :key="String(row.tenant_id)"
                class="credit-data-row credit-tenant-cols"
                :class="{ 'is-zero': Number(row.credit_balance || 0) <= 0 }"
              >
                <span class="cell-name">{{ row.name }}</span>
                <span>{{ row.credit_balance }}</span>
                <span>{{ row.credit_reserved }}</span>
                <span>{{ row.today_deduct ?? 0 }}</span>
                <span>{{ (row.daily_estimate as Record<string, unknown>)?.credits_per_day ?? '—' }}</span>
                <span>{{ row.owner_name || '—' }}</span>
              </div>
              <div v-if="!visibleCreditTenants.length" class="mini-empty">
                {{ tenantZeroOnly ? '暂无零余额企业' : '暂无匹配企业' }}
              </div>
            </div>
            <div v-if="tenantPagerVisible" class="log-pagination">
              <span class="log-pagination-meta">第 {{ tenantPage }} / {{ tenantPageCount }} 页 · 共 {{ filteredCreditTenants.length }} 家</span>
              <div class="log-pagination-actions">
                <button type="button" class="filter-reset-btn tiny-btn" :disabled="tenantPage <= 1" @click="tenantPage -= 1">上一页</button>
                <button type="button" class="filter-reset-btn tiny-btn" :disabled="tenantPage >= tenantPageCount" @click="tenantPage += 1">下一页</button>
              </div>
            </div>
          </article>

          <article class="panel credit-section-panel">
            <div class="panel-head">
              <h2>全平台算力流水</h2>
            </div>
            <div class="log-filter-bar">
              <input v-model="ledgerTenantNameFilter" type="search" placeholder="搜索公司名称">
              <button type="button" class="filter-reset-btn tiny-btn" @click="exportPlatformLedger">导出表格</button>
            </div>
            <div class="credit-data-table">
              <div class="credit-data-head credit-ledger-cols">
                <span>时间</span><span>企业</span><span>类型</span><span>金额</span><span>余额</span><span>说明</span>
              </div>
              <div
                v-for="row in platformLedger?.items || []"
                :key="row.id"
                class="credit-data-row credit-ledger-cols is-clickable"
                :class="{ 'is-active': ledgerDrawerVisible && ledgerDetailRowKey === ledgerRowKey(row) }"
                @click="openPlatformLedgerDetail(row)"
              >
                <span>{{ row.created_at }}</span>
                <span class="cell-name">{{ row.tenant_name || (row.tenant_id ? `#${row.tenant_id}` : '—') }}</span>
                <span>{{ entryTypeLabel[row.entry_type] || row.entry_type }}</span>
                <span>{{ row.amount }}</span>
                <span>{{ row.balance_after }}</span>
                <span class="cell-desc">{{ row.reason || '—' }}</span>
              </div>
              <div v-if="!(platformLedger?.items?.length)" class="mini-empty">暂无流水</div>
            </div>
            <div class="log-pagination">
              <span class="log-pagination-meta">第 {{ ledgerPage }} 页</span>
              <div class="log-pagination-actions">
                <button type="button" class="filter-reset-btn tiny-btn" :disabled="ledgerPage <= 1" @click="loadPlatformLedger(ledgerPage - 1)">上一页</button>
                <button type="button" class="filter-reset-btn tiny-btn" :disabled="!ledgerHasNextPage" @click="loadPlatformLedger(ledgerPage + 1)">下一页</button>
              </div>
            </div>
          </article>
        </div>
      </template>

      <template v-else-if="pageTab === 'recharge'">
        <div v-loading="loading" class="credit-ops-body is-split">
          <div class="enterprise-config-page credit-recharge-layout">
          <aside class="enterprise-side">
            <div class="credit-side-search">
              <input v-model="rechargeTenantSearch" type="search" placeholder="搜索公司名称">
            </div>
            <button
              v-for="row in visibleRechargeTenants"
              :key="String(row.tenant_id)"
              type="button"
              :class="{ on: selectedRechargeTenantId === Number(row.tenant_id) }"
              @click="selectRechargeTenant(Number(row.tenant_id))"
            >
              {{ row.name }}
              <small>余额 {{ row.credit_balance }} · 预扣 {{ row.credit_reserved }}</small>
            </button>
            <div v-if="!visibleRechargeTenants.length" class="mini-empty credit-side-empty">暂无匹配企业</div>
            <div v-if="rechargeTenantPagerVisible" class="credit-side-pager">
              <button type="button" class="filter-reset-btn tiny-btn" :disabled="rechargeTenantPage <= 1" @click="rechargeTenantPage -= 1">上一页</button>
              <span>{{ rechargeTenantPage }} / {{ rechargeTenantPageCount }}</span>
              <button type="button" class="filter-reset-btn tiny-btn" :disabled="rechargeTenantPage >= rechargeTenantPageCount" @click="rechargeTenantPage += 1">下一页</button>
            </div>
          </aside>
          <section class="enterprise-main">
            <template v-if="selectedRechargeTenantId">
              <section class="ops-kpi-grid credit-recharge-kpi">
                <article class="ops-kpi-card tone-cyan">
                  <div><Wallet /></div>
                  <span>可用算力</span>
                  <strong>{{ rechargeAvailable.toFixed(1) }}</strong>
                  <small>余额 {{ Number(rechargeTenantDetail?.credit_balance || 0).toFixed(1) }} · 预扣 {{ Number(rechargeTenantDetail?.credit_reserved || 0).toFixed(1) }}</small>
                </article>
                <article class="ops-kpi-card tone-green">
                  <div><TrendingDown /></div>
                  <span>今日已扣</span>
                  <strong>{{ Number(rechargeTenantDetail?.today_deduct || 0).toFixed(1) }}</strong>
                </article>
                <article class="ops-kpi-card tone-purple">
                  <div><Gauge /></div>
                  <span>日预估消耗</span>
                  <strong>{{ Number((rechargeTenantDetail?.daily_estimate as Record<string, unknown>)?.credits_per_day || 0).toFixed(1) }}</strong>
                </article>
              </section>

              <div v-if="canRecharge" class="schedule-ops-panel credit-recharge-form-panel">
                <div class="panel-head">
                  <h2>充值算力</h2>
                  <label class="credit-rate-edit">
                    <span>1 元 =</span>
                    <input
                      v-model="rechargeRateInput"
                      type="number"
                      min="0.01"
                      step="0.1"
                      :placeholder="String(DEFAULT_CREDITS_PER_YUAN)"
                      :disabled="savingRechargeRate"
                      @blur="persistRechargeRate"
                    >
                    <span>算力</span>
                  </label>
                </div>
                <div class="log-filter-bar credit-recharge-form">
                  <label>
                    <span>充值金额（元）</span>
                    <input v-model="rechargeYuan" type="number" min="0.01" step="0.01" placeholder="例如 100">
                  </label>
                  <label>
                    <span>到账算力</span>
                    <input
                      v-model="rechargeCredits"
                      type="number"
                      min="0.1"
                      step="0.1"
                      placeholder="可改，填元后自动带出"
                      @input="rechargeCreditsTouched = true"
                    >
                  </label>
                  <label class="credit-form-grow">
                    <span>备注</span>
                    <input v-model="rechargeReason" maxlength="500" placeholder="选填">
                  </label>
                  <button type="button" class="primary-btn small-btn" :disabled="recharging || !canSubmitRecharge" @click="submitRecharge">
                    {{ recharging ? '提交中…' : '确认充值' }}
                  </button>
                </div>
                <div class="credit-deduct-toggle">
                  <button type="button" class="ghost-link-btn" @click="showDeductForm = !showDeductForm">
                    {{ showDeductForm ? '收起扣减' : '需要扣减？' }}
                  </button>
                </div>
                <div v-if="showDeductForm" class="log-filter-bar credit-recharge-form">
                  <label>
                    <span>扣减金额</span>
                    <input v-model="deductAmount" type="number" min="0.1" step="0.1" placeholder="例如 50">
                  </label>
                  <label class="credit-form-grow">
                    <span>扣减原因</span>
                    <input v-model="deductReason" maxlength="500" placeholder="必填，便于审计">
                  </label>
                  <button type="button" class="filter-reset-btn tiny-btn" :disabled="deducting" @click="submitDeduct">
                    {{ deducting ? '提交中…' : '确认扣减' }}
                  </button>
                </div>
              </div>
              <p v-else class="mini-empty">当前账号无充值权限</p>

              <article class="panel credit-section-panel credit-recharge-recent-ledger">
                <div class="panel-head">
                  <div>
                    <h2>近期流水</h2>
                    <p class="credit-recharge-ledger-hint">仅本企业最近 {{ RECHARGE_LEDGER_PAGE_SIZE }} 条，核对充值到账；全平台巡检请回「概览」</p>
                  </div>
                  <label class="credit-check-inline">
                    <input v-model="showInternalLedger" type="checkbox">
                    显示内部账务（预扣/释放）
                  </label>
                </div>
                <div class="credit-data-table">
                  <div class="credit-data-head credit-recharge-ledger-cols">
                    <span>时间</span><span>类型</span><span>变动</span><span>余额</span><span>说明</span>
                  </div>
                  <div v-for="row in rechargeTenantLedger" :key="row.id" class="credit-data-row credit-recharge-ledger-cols">
                    <span>{{ row.created_at }}</span>
                    <span>{{ (showInternalLedger ? entryTypeLabel : rechargeLedgerTypeLabel)[row.entry_type] || row.entry_type }}</span>
                    <span :class="{ plus: row.amount > 0, minus: row.amount < 0 }">{{ formatLedgerAmount(row.amount) }}</span>
                    <span>{{ row.balance_after }}</span>
                    <span class="cell-desc">{{ row.reason || '—' }}</span>
                  </div>
                  <div v-if="!rechargeTenantLedger.length" class="mini-empty">暂无流水</div>
                </div>
                <div v-if="rechargeTenantLedgerPage > 1 || rechargeTenantLedgerHasNext" class="log-pagination">
                  <span class="log-pagination-meta">第 {{ rechargeTenantLedgerPage }} 页</span>
                  <div class="log-pagination-actions">
                    <button type="button" class="filter-reset-btn tiny-btn" :disabled="rechargeTenantLedgerPage <= 1" @click="loadRechargeTenantLedger(rechargeTenantLedgerPage - 1)">上一页</button>
                    <button type="button" class="filter-reset-btn tiny-btn" :disabled="!rechargeTenantLedgerHasNext" @click="loadRechargeTenantLedger(rechargeTenantLedgerPage + 1)">下一页</button>
                  </div>
                </div>
              </article>
            </template>
            <div v-else class="mini-empty">请从左侧选择企业</div>
          </section>
          </div>
        </div>
      </template>

      <template v-else-if="pageTab === 'blocks'">
        <div v-loading="blocksLoading" class="credit-ops-body">
          <article class="panel credit-section-panel">
            <div class="panel-head">
              <h2>提交拦截</h2>
              <button type="button" class="filter-reset-btn tiny-btn" :disabled="blocksLoading" @click="loadBlocks">刷新</button>
            </div>
            <p class="hint-line credit-blocks-hint">
              「结算少收（余额封顶）」表示任务已跑、算力只扣到 0，差额不自动补扣；请人工关注充值与单价，无需当提交失败处理。
              <template v-if="summary">
                近 24h：少收事件 {{ summary.balance_capped_blocks_24h ?? 0 }} 次，累计差额约 {{ summary.undercharge_credits_24h ?? 0 }} 算力。
              </template>
            </p>
            <div class="credit-data-table">
              <div class="credit-data-head credit-blocks-cols">
                <span>企业</span><span>原因</span><span>窗口</span><span>需要/可用</span><span>时间</span>
              </div>
              <div v-for="row in blocks?.items || []" :key="String(row.id)" class="credit-data-row credit-blocks-cols">
                <span class="cell-name">{{ row.tenant_name }}</span>
                <span>{{ formatBlockReason(row.block_reason) }}</span>
                <span>{{ row.window_key }}</span>
                <span>{{ row.required_credits ?? '—' }} / {{ row.available_credits ?? '—' }}</span>
                <span>{{ row.created_at }}</span>
              </div>
              <div v-if="!(blocks?.items?.length)" class="mini-empty">暂无拦截记录</div>
            </div>
          </article>
        </div>
      </template>

      <template v-else-if="pageTab === 'pricing'">
        <div class="credit-ops-body">
          <CreditBillingConfigPanel :can-edit="canEditPricing" />
        </div>
      </template>

      <template v-else-if="pageTab === 'mode'">
        <div v-loading="loading" class="credit-ops-body is-split">
          <div class="enterprise-config-page credit-recharge-layout">
          <aside class="enterprise-side">
            <div class="credit-side-search">
              <input v-model="modeTenantSearch" type="search" placeholder="搜索企业">
            </div>
            <button
              v-for="row in filteredModeTenants"
              :key="row.id"
              type="button"
              :class="{ on: selectedModeTenantId === row.id }"
              @click="selectModeTenant(row.id)"
            >
              <span>{{ row.name }}</span>
              <small>{{ modeTenantBillingLabel(row) }}</small>
            </button>
            <p v-if="!filteredModeTenants.length" class="mini-empty">暂无匹配企业</p>
          </aside>
          <div class="enterprise-main">
            <template v-if="selectedModeTenant">
              <!-- 2026-09-08 - 模式切换表单挤乱 - 独立表单卡：2×2 网格 + 底栏确认 -->
              <article class="panel credit-section-panel credit-mode-form-panel">
                <div class="panel-head">
                  <div>
                    <h2>模式切换</h2>
                    <p class="credit-mode-tenant-name">{{ selectedModeTenant.name }}</p>
                  </div>
                  <span
                    class="credit-mode-badge"
                    :class="selectedModeIsCredit ? 'is-credit' : 'is-hosted'"
                  >
                    {{ selectedModeIsCredit
                      ? (Number(selectedModeTenant?.credit_balance) <= 0 ? '算力自助·零余额' : '算力自助')
                      : '平台托管' }}
                  </span>
                </div>
                <div
                  v-if="pendingModeSwitch"
                  class="credit-mode-pending"
                  :class="{ 'is-stale': pendingModeIsStale }"
                >
                  <div>
                    <strong>{{ pendingModeIsStale ? '待下窗生效（已超时）' : '待下窗生效' }}</strong>
                    <p>
                      将切至「{{ pendingModeSwitch.to_mode === 'credit' ? '算力自助' : '平台托管' }}」
                      <template v-if="pendingModeSwitch.to_mode === 'credit' && pendingModeSwitch.opening_credit_amount != null">
                        · 起步算力 {{ pendingModeSwitch.opening_credit_amount }}
                      </template>
                      ；该企业<strong>下次监测提交</strong>时生效。若暂无监测，请改用「立即」或下方一键立即生效。
                    </p>
                    <p v-if="pendingModeIsStale" class="credit-mode-pending-stale">
                      已登记约 {{ pendingModeStaleDays }} 天仍未提交监测，建议立即生效或取消。
                    </p>
                  </div>
                  <div class="credit-mode-pending-actions">
                    <button
                      v-if="canRecharge"
                      type="button"
                      class="primary-btn small-btn"
                      :disabled="modeSwitching"
                      @click="applyPendingModeImmediately"
                    >{{ modeSwitching ? '处理中…' : '立即生效' }}</button>
                    <button
                      v-if="canRecharge"
                      type="button"
                      class="plain-btn small-btn"
                      :disabled="modeCancelling"
                      @click="cancelPendingModeSwitch"
                    >{{ modeCancelling ? '取消中…' : '取消待生效' }}</button>
                  </div>
                </div>                <template v-if="canRecharge">
                  <div class="credit-mode-grid">
                    <label>
                      <span>目标模式</span>
                      <select v-model="modeSwitchTarget">
                        <option value="credit">算力自助</option>
                        <option value="hosted">平台托管</option>
                      </select>
                    </label>
                    <label>
                      <span>生效策略</span>
                      <select v-model="modeSwitchEffective">
                        <option value="next_window">下一监测窗（该企业下次监测提交时生效）</option>
                        <option value="immediate">立即（马上改模式并动算力）</option>
                      </select>
                    </label>
                    <label v-if="modeSwitchTarget === 'credit'" class="credit-mode-opening">
                      <span>起步算力</span>
                      <div class="credit-mode-opening-row">
                        <input
                          v-model="modeSwitchOpening"
                          type="number"
                          min="1"
                          step="1"
                          :placeholder="modeSuggestedOpening != null ? `建议 ≥ ${Math.ceil(modeSuggestedOpening)}` : '必填'"
                        >
                        <small v-if="modePreviewLoading">估算中…</small>
                        <small v-else-if="modeSuggestedOpening != null">约 3 日 ≈ {{ modeSuggestedOpening.toFixed(1) }}</small>
                      </div>
                    </label>
                  </div>
                  <div class="credit-mode-footer">
                    <label class="credit-mode-reason">
                      <span>备注</span>
                      <input v-model="modeSwitchReason" maxlength="500" placeholder="选填">
                    </label>
                    <button type="button" class="primary-btn small-btn" :disabled="modeSwitching" @click="submitModeSwitch">
                      {{ modeSwitching ? '处理中…' : (pendingModeSwitch ? '覆盖并重新登记' : '确认切换') }}
                    </button>
                  </div>
                </template>
                <p v-else class="hint-line">当前账号无算力运营写权限，无法切换。</p>
              </article>
              <article v-if="modeHistory.length" class="panel credit-section-panel">
                <div class="panel-head"><h2>切换记录</h2></div>
                <div class="credit-data-table">
                  <div class="credit-data-head credit-mode-history-cols">
                    <span>时间</span><span>自</span><span>至</span><span>状态</span><span>原因</span>
                  </div>
                  <div v-for="row in modeHistory" :key="String(row.id)" class="credit-data-row credit-mode-history-cols">
                    <span>{{ row.created_at }}</span>
                    <span>{{ row.from_mode === 'credit' ? '算力自助' : '托管' }}</span>
                    <span>{{ row.to_mode === 'credit' ? '算力自助' : '托管' }}</span>
                    <span>{{ modeStatusLabel(row.status) }}</span>
                    <span>{{ row.reason || '—' }}</span>
                  </div>
                </div>
              </article>
            </template>
            <p v-else class="mini-empty">请选择左侧企业</p>
          </div>
          </div>
        </div>
      </template>
    </article>

    <ElDrawer
      v-model="ledgerDrawerVisible"
      size="560px"
      title="流水明细"
      direction="rtl"
      destroy-on-close
      class="credit-ledger-drawer"
      @closed="onPlatformLedgerDrawerClosed"
    >
      <div v-loading="ledgerDetailLoading" class="credit-ledger-drawer-body">
        <template v-if="ledgerDetail">
          <dl class="credit-ledger-meta">
            <div>
              <dt>企业</dt>
              <dd>{{ ledgerDetail.tenant_name || ledgerDetail.tenant_id || '—' }}</dd>
            </div>
            <div>
              <dt>类型</dt>
              <dd>{{ entryTypeLabel[ledgerDetail.entry_type] || ledgerDetail.entry_type }}</dd>
            </div>
            <div>
              <dt>金额</dt>
              <dd>{{ ledgerDetail.amount }}</dd>
            </div>
            <div>
              <dt>余额</dt>
              <dd>{{ ledgerDetail.balance_after }}</dd>
            </div>
            <div v-if="ledgerDetail.reason" class="is-full">
              <dt>说明</dt>
              <dd>{{ ledgerDetail.reason }}</dd>
            </div>
            <div v-if="ledgerDetail.created_at" class="is-full">
              <dt>时间</dt>
              <dd>{{ ledgerDetail.created_at }}</dd>
            </div>
          </dl>

          <div v-if="ledgerDetail.subtasks?.length" class="credit-ledger-subtasks">
            <h4>关联子任务</h4>
            <div class="credit-data-table">
              <div class="credit-data-head credit-ledger-subtask-cols">
                <span>平台</span><span>关键词</span><span>状态</span><span>算力</span>
              </div>
              <div
                v-for="(st, idx) in ledgerDetail.subtasks"
                :key="st.subtask_id || idx"
                class="credit-data-row credit-ledger-subtask-cols"
              >
                <span>{{ st.platform_code || '—' }}</span>
                <span class="cell-name">{{ st.keyword || '—' }}</span>
                <span>{{ formatSubtaskStatus(st.status) }}</span>
                <span>{{ st.credits ?? '—' }}</span>
              </div>
            </div>
          </div>
          <p v-else class="mini-empty">本条流水无关联子任务</p>
        </template>
        <p v-else-if="!ledgerDetailLoading" class="mini-empty">暂无明细</p>
      </div>
    </ElDrawer>
  </section>
</template>

<style scoped>
/* 2026-08-28 - 概览表格列错位 - 不用全局 ops-row（:has 会盖列宽）；独立 credit-data-table + panel 分区 */
/* 2026-09-08 - 方案甲：轻量顶栏 + 零余额筛选项，去掉大卡 Tab / 独立零余额页 */
.credit-ops-shell { padding: 0; overflow: hidden; }
.credit-ops-nav {
  display: flex;
  flex-wrap: wrap;
  gap: 0;
  padding: 0 10px;
  border-bottom: 1px solid #e5eef8;
  background: #fbfcfe;
}
.credit-ops-nav button {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 14px 16px 12px;
  border: none;
  background: transparent;
  color: #58708f;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
}
.credit-ops-nav button.active { color: #17406a; }
.credit-ops-nav button.active::after {
  content: '';
  position: absolute;
  left: 16px;
  right: 16px;
  bottom: -1px;
  height: 2px;
  border-radius: 999px;
  background: linear-gradient(90deg, #2d6cdf, #22c7c4);
}
.credit-ops-nav button i {
  min-width: 20px;
  padding: 1px 7px;
  border-radius: 999px;
  background: rgba(220, 38, 38, 0.1);
  color: #b91c1c;
  font-style: normal;
  font-size: 12px;
  font-weight: 700;
  line-height: 1.4;
  text-align: center;
}
.credit-ops-body { display: grid; gap: 16px; padding: 16px 18px 20px; }
.credit-ops-body.is-split { display: block; padding: 0; }
.credit-tenant-filter {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
}
.credit-filter-chips {
  display: inline-flex;
  gap: 6px;
  margin-left: auto;
}
.credit-filter-chips button {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 32px;
  padding: 0 12px;
  border: 1px solid #d8e7f6;
  border-radius: 999px;
  background: #fff;
  color: #58708f;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
}
.credit-filter-chips button.on {
  border-color: #9ec3ef;
  background: #eef6ff;
  color: #17406a;
}
.credit-filter-chips button span {
  min-width: 18px;
  padding: 0 6px;
  border-radius: 999px;
  background: rgba(220, 38, 38, 0.1);
  color: #b91c1c;
  font-size: 11px;
  line-height: 18px;
  text-align: center;
}
.credit-section-panel { padding: 0; overflow: hidden; }
.credit-section-panel > .panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 18px 18px 0;
  margin-bottom: 0;
}
.credit-section-panel > .panel-head h2 { margin: 0; font-size: 18px; }
.credit-section-panel > .log-filter-bar { margin-top: 12px; border-bottom: 1px solid #e3eef8; }
.credit-section-panel > .log-pagination { border-top: 1px solid #edf3fa; }
.credit-data-table {
  overflow: hidden;
  margin: 0 18px 12px;
  border: 1px solid #d9e8f6;
  border-radius: 12px;
  background: #fff;
}
.credit-section-panel > .log-filter-bar + .credit-data-table { margin-top: 0; border-radius: 0 0 12px 12px; }
.credit-section-panel > .panel-head + .credit-data-table { margin-top: 12px; }
.credit-data-head,
.credit-data-row {
  display: grid;
  gap: 12px;
  align-items: center;
  padding: 12px 16px;
  font-size: 13px;
}
.credit-data-head {
  color: #607692;
  background: #f2f7fc;
  font-weight: 800;
}
.credit-data-row {
  border-top: 1px solid #edf3fa;
  color: #1a3656;
}
.credit-data-row.is-clickable { cursor: pointer; }
.credit-data-row.is-clickable:hover { background: #f8fbff; }
.credit-data-row.is-clickable.is-active { background: #eff6ff; }
.credit-data-row.is-zero { background: #fff8f8; }
.credit-data-row.is-zero .cell-name { color: #b91c1c; }
.cell-name { color: #10233f; font-weight: 700; word-break: break-word; }
.cell-desc { color: #536a86; word-break: break-word; }
.credit-tenant-cols { grid-template-columns: minmax(160px, 1.5fr) 72px 72px 88px 72px 88px; }
.credit-tenant-cols > :not(:first-child) { text-align: right; }
.credit-ledger-cols { grid-template-columns: 140px minmax(120px, 1fr) 72px 72px 72px minmax(160px, 1.4fr); }
.credit-ledger-cols > :nth-child(4),
.credit-ledger-cols > :nth-child(5) { text-align: right; }
.credit-recharge-ledger-cols { grid-template-columns: 140px 80px 88px 88px minmax(160px, 1fr); }
.credit-recharge-ledger-cols > :nth-child(3),
.credit-recharge-ledger-cols > :nth-child(4) { text-align: right; }
.credit-blocks-cols { grid-template-columns: minmax(140px, 1.2fr) 120px 120px 132px 148px; }
.credit-mode-history-cols { grid-template-columns: 140px 72px 72px 96px minmax(140px, 1fr); }
.credit-mode-pending {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin: 0 0 14px;
  padding: 12px 14px;
  border-radius: 8px;
  background: #fffbeb;
  border: 1px solid #fcd34d;
  color: #92400e;
}
.credit-mode-pending.is-stale {
  border-color: #f0b4a0;
  background: #fff1ec;
  color: #9a3412;
}
.credit-mode-pending strong { display: block; margin-bottom: 4px; }
.credit-mode-pending p { margin: 0; font-size: 13px; line-height: 1.45; }
.credit-mode-pending-stale { margin-top: 6px !important; font-weight: 600; }
.credit-mode-pending-actions {
  display: flex;
  flex-direction: column;
  gap: 8px;
  flex-shrink: 0;
}
.credit-blocks-hint { margin: 0 0 12px; }

.enterprise-config-page { display: flex; gap: 0; min-height: 480px; border-top: none; background: #fff; }
.enterprise-side { width: 220px; background: #f8fbff; border-right: 1px solid #edf3fa; padding: 12px 0; flex-shrink: 0; }
.enterprise-side button { display: block; width: 100%; text-align: left; border: none; background: transparent; padding: 10px 16px; cursor: pointer; color: #64748b; font-size: 13px; }
.enterprise-side button small { display: block; margin-top: 4px; font-size: 11px; color: #6a7f9a; font-weight: 400; }
.enterprise-side button.on { background: #fff; color: #236bd1; font-weight: 700; border-right: 2px solid #7eb6ff; }
.enterprise-main { flex: 1; padding: 18px; min-width: 0; display: grid; gap: 16px; align-content: start; }
.credit-side-search { padding: 0 12px 10px; }
.credit-side-search input {
  width: 100%;
  min-height: 34px;
  padding: 0 10px;
  border: 1px solid #d8e7f6;
  border-radius: 8px;
  background: #fff;
  color: #153052;
  font-size: 13px;
}
.hint-line {
  margin: 0 0 12px;
  font-size: 12px;
  color: #64748b;
}
/* 2026-09-08 - 模式切换卡右空白 - 去掉 max-width，主栏铺满 */
.credit-mode-form-panel > .panel-head { align-items: flex-start; }
.credit-mode-tenant-name {
  margin: 4px 0 0;
  color: #64748b;
  font-size: 13px;
  font-weight: 400;
}
.credit-mode-badge {
  flex-shrink: 0;
  margin-top: 2px;
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
  line-height: 1.4;
  white-space: nowrap;
}
.credit-mode-badge.is-hosted {
  color: #64748b;
  background: #f1f5f9;
  border: 1px solid #e2e8f0;
}
.credit-mode-badge.is-credit {
  color: #236bd1;
  background: #f0f7ff;
  border: 1px solid #cfe3fa;
}
.credit-mode-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px 16px;
  margin: 14px 18px 0;
}
.credit-mode-grid label,
.credit-mode-reason {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 12px;
  font-weight: 700;
  color: #6a7f9a;
}
.credit-mode-grid input,
.credit-mode-grid select,
.credit-mode-reason input {
  min-height: 36px;
  padding: 0 10px;
  border: 1px solid #d8e7f6;
  border-radius: 8px;
  background: #fff;
  color: #153052;
  font-size: 13px;
  font-weight: 400;
}
.credit-mode-opening { grid-column: 1 / -1; }
.credit-mode-opening-row {
  display: flex;
  align-items: center;
  gap: 12px;
}
.credit-mode-opening-row input {
  width: 180px;
  flex-shrink: 0;
}
.credit-mode-opening-row small {
  color: #64748b;
  font-size: 12px;
  font-weight: 400;
  white-space: nowrap;
}
.credit-mode-footer {
  display: flex;
  align-items: flex-end;
  gap: 12px;
  margin: 16px 18px 18px;
  padding-top: 14px;
  border-top: 1px solid #edf3fa;
}
.credit-mode-reason { flex: 1; min-width: 0; }
.credit-mode-footer .primary-btn { flex-shrink: 0; margin-bottom: 1px; }
.credit-mode-form-panel > .hint-line { margin: 14px 18px 18px; }
@media (max-width: 720px) {
  .credit-mode-grid { grid-template-columns: 1fr; }
  .credit-mode-opening-row { flex-wrap: wrap; }
  .credit-mode-footer { flex-direction: column; align-items: stretch; }
}
.credit-side-empty { padding: 12px 16px; }
.credit-side-pager { display: flex; align-items: center; justify-content: center; gap: 8px; padding: 10px 12px; font-size: 12px; color: #64748b; }
.credit-recharge-kpi { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.credit-recharge-form-panel { padding: 0; }
.credit-rate-edit {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border: 1px solid #dce8f5;
  border-radius: 999px;
  color: #236bd1;
  background: #f0f7ff;
  font-size: 12px;
  font-weight: 700;
  white-space: nowrap;
  cursor: text;
}
.credit-rate-edit input {
  width: 56px;
  padding: 2px 6px;
  border: 1px solid #b8d4f5;
  border-radius: 6px;
  background: #fff;
  color: #153052;
  font-size: 12px;
  font-weight: 700;
  text-align: center;
}
.credit-rate-edit input:disabled { opacity: 0.6; cursor: wait; }
.credit-recharge-form label { display: flex; flex-direction: column; gap: 4px; min-width: 140px; }
.credit-recharge-form label span { color: #6a7f9a; font-size: 12px; font-weight: 700; }
.credit-recharge-form input[readonly] { background: #f8fbff; color: #153052; cursor: default; }
.credit-form-grow { flex: 1; min-width: 200px; }
.credit-deduct-toggle { padding: 0 16px 8px; }
.credit-check-inline { display: inline-flex; align-items: center; gap: 6px; font-size: 13px; color: #64748b; cursor: pointer; white-space: nowrap; }
.credit-recharge-recent-ledger .panel-head {
  align-items: flex-start;
}
.credit-recharge-ledger-hint {
  margin: 4px 0 0;
  color: #8aa0ba;
  font-size: 12px;
  font-weight: 500;
  line-height: 1.4;
}
.plus { color: #059669; font-weight: 700; }
.minus { color: #dc2626; font-weight: 700; }
.credit-ledger-drawer-body { min-height: 120px; }
.credit-ledger-meta {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px 16px;
  margin: 0 0 20px;
}
.credit-ledger-meta > div {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}
.credit-ledger-meta > div.is-full { grid-column: 1 / -1; }
.credit-ledger-meta dt {
  margin: 0;
  color: #6a7f9a;
  font-size: 12px;
  font-weight: 700;
}
.credit-ledger-meta dd {
  margin: 0;
  color: #153052;
  font-size: 14px;
  line-height: 1.45;
  word-break: break-word;
}
.credit-ledger-subtasks h4 {
  margin: 0 0 10px;
  color: #153052;
  font-size: 14px;
}
.credit-ledger-subtask-cols {
  grid-template-columns: 88px minmax(0, 1.6fr) 88px 64px;
}
@media (max-width: 900px) {
  /* 2026-09-07 - 算力运营窄屏：侧栏横排 + 表格可横滑 */
  .enterprise-config-page.credit-recharge-layout,
  .enterprise-config-page { flex-direction: column; }
  .enterprise-side {
    width: 100%;
    display: flex;
    gap: 4px;
    overflow-x: auto;
    border-right: none;
    border-bottom: 1px solid #edf3fa;
    padding: 8px;
  }
  .enterprise-side button { width: auto; white-space: nowrap; border-radius: 8px; }
  .enterprise-side button.on { border-right: none; background: #eef6ff; }
  .credit-filter-chips { margin-left: 0; width: 100%; }
  .credit-data-row,
  .credit-tenant-cols,
  .credit-ledger-cols,
  .credit-recharge-ledger-cols,
  .credit-blocks-cols,
  .credit-mode-history-cols,
  .credit-ledger-subtask-cols { min-width: 640px; }
  .enterprise-main { overflow-x: auto; }
  .credit-ledger-meta { grid-template-columns: 1fr; }
}
</style>
