<script setup lang="ts">
import { computed, inject, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import BrandAuditPage from './BrandAuditPage.vue'
import { resolveEnterprisePreviewTenantId } from '../customerPreview'
import { PreviewCustomerMenusKey } from '../injectionKeys'
import {
  createEnterpriseCreditRechargeOrder,
  createEnterpriseMember,
  deleteEnterpriseMember,
  enterpriseCreditLedgerExportUrl,
  getCurrentCreditTerms,
  getEnterpriseAudit,
  getEnterpriseCreditLedger,
  getEnterpriseCreditLedgerDetail,
  getEnterpriseCreditLedgerGroupLines,
  getEnterpriseCreditRechargeOrderStatus,
  getEnterpriseCreditSummary,
  getEnterpriseMembers,
  markEnterpriseCreditRechargeDevPaid,
  resetEnterpriseMemberPassword,
  updateEnterpriseMember,
  type CreditLedgerDetail,
  type CreditLedgerGroupItem,
  type CreditLedgerItem,
  type CreditLedgerView,
  type CreditRechargeOrder,
  type EnterpriseMemberItem,
} from '../../../services/credit'
import { useAuthStore } from '../../../stores/auth'
import type { MenuInfo } from '../../../services/auth'
import { extractErrorDetail, isRequestCanceled } from '../../../utils/requestError'
import { getPlatformMeta } from '../platformMeta'
import {
  createCreditRechargePoll,
  type CreditRechargePollController,
} from '../composables/creditRechargePoll'

const props = defineProps<{ initialTab?: string; previewReadonly?: boolean }>()
const route = useRoute()
const auth = useAuthStore()
const previewCustomerMenus = inject(PreviewCustomerMenusKey, ref<MenuInfo[]>([]))

// 2026-08-27 - 预览成员空列表 - 解析 tenant_id 须含 query.tenant_id 回退并在路由就绪后重载
const previewTenantId = computed(() => (
  props.previewReadonly ? resolveEnterprisePreviewTenantId(route) : null
))
const enterpriseTenantId = computed(() => previewTenantId.value ?? undefined)

const TAB_DEFS = [
  { id: 'monitor', label: '监测配置', menu: 'customer.enterprise_monitor' },
  // 2026-09-09 - 与侧栏 sys_menu.sort_order 一致：成员(132) 再算力(133)
  { id: 'members', label: '成员与权限', menu: 'customer.enterprise_members' },
  { id: 'credit', label: '算力中心', menu: 'customer.enterprise_credit' },
  { id: 'audit', label: '操作记录', menu: 'customer.enterprise_audit' },
] as const

const tab = ref('monitor')
const loading = ref(false)
const summary = ref<Awaited<ReturnType<typeof getEnterpriseCreditSummary>> | null>(null)
const ledger = ref<Awaited<ReturnType<typeof getEnterpriseCreditLedger>> | null>(null)
const ledgerPage = ref(1)
const ledgerPageSize = 20
const ledgerView = ref<CreditLedgerView>('window')
const members = ref<Awaited<ReturnType<typeof getEnterpriseMembers>> | null>(null)
const audit = ref<Awaited<ReturnType<typeof getEnterpriseAudit>> | null>(null)
const terms = ref<Awaited<ReturnType<typeof getCurrentCreditTerms>> | null>(null)
const termsViewVisible = ref(false)
const ledgerDetail = ref<CreditLedgerDetail | null>(null)
const ledgerDetailVisible = ref(false)
const ledgerDetailLoading = ref(false)
const ledgerDetailRowId = ref<number | null>(null)
const expandedGroupKey = ref<string | null>(null)
const groupLines = ref<CreditLedgerItem[]>([])
const groupLinesLoading = ref(false)
const groupLinesTotal = ref(0)

const memberFormVisible = ref(false)
const memberSaving = ref(false)
const editingMember = ref<EnterpriseMemberItem | null>(null)
const memberForm = ref({
  display_name: '',
  username: '',
  password: '',
  customer_position_id: 0,
  status: true,
})

function menuGrant(code: string) {
  if (props.previewReadonly) {
    return previewCustomerMenus.value.find(menu => menu.menu_code === code)
  }
  return auth.allowedMenus.find(menu => menu.menu_code === code)
}

function canViewTab(menuCode: string) {
  const grant = menuGrant(menuCode)
  return Boolean(grant && (grant.can_export || grant.can_update || grant.can_create || grant.can_delete))
}

const isCreditBilling = computed(() => String(summary.value?.billing_mode || '') === 'credit')

const visibleTabs = computed(() => TAB_DEFS.filter((item) => {
  // 2026-09-07 - Tab 按菜单权限藏；托管不露算力中心
  if (item.id === 'credit') {
    if (summary.value && !isCreditBilling.value) return false
    return canViewTab(item.menu)
  }
  return canViewTab(item.menu)
}))

const canEditMembers = computed(() => !props.previewReadonly && Boolean(menuGrant('customer.enterprise_members')?.can_create))
const canUpdateMembers = computed(() => !props.previewReadonly && Boolean(menuGrant('customer.enterprise_members')?.can_update))
const canDeleteMembers = computed(() => !props.previewReadonly && Boolean(menuGrant('customer.enterprise_members')?.can_delete))

const entryTypeLabel: Record<string, string> = {
  recharge: '充值',
  adjust: '调整',
  settle: '扣费',
}

const subtaskStatusLabel: Record<string, string> = {
  settled: '已结算',
  settled_backfill: '已结算',
  released_unbilled: '未计费已释放',
  released: '已释放',
  pending: '待处理',
  submitted: '已提交',
  completed: '已完成',
  failed: '失败',
  stopped: '已停止',
}

function formatSubtaskStatus(status: unknown) {
  const key = String(status || '').trim()
  if (!key) return '—'
  return subtaskStatusLabel[key] || subtaskStatusLabel[key.toLowerCase()] || key
}

function formatCreditNumber(value: unknown) {
  const num = Number(value)
  if (!Number.isFinite(num)) return '—'
  return num.toLocaleString('zh-CN', { maximumFractionDigits: 1 })
}

function formatLedgerAmount(amount: number) {
  const value = Number(amount)
  if (!Number.isFinite(value)) return '—'
  const text = Number.isInteger(value) ? String(value) : value.toFixed(1)
  return value > 0 ? `+${text}` : text
}

function formatLedgerTime(value: unknown) {
  const text = String(value || '').trim()
  if (!text) return '—'
  const matched = text.match(/(\d{2}-\d{2})\s+(\d{2}:\d{2})/)
  if (matched) return `${matched[1]} ${matched[2]}`
  try {
    return new Date(text).toLocaleString('zh-CN', {
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    })
  } catch {
    return text
  }
}

function isInternalLedgerReason(reason: string) {
  const text = reason.trim()
  if (!text) return true
  return /amount|晚到误释放|模力未计费|监测未计费|prepaid|backfill|补扣：/i.test(text)
}

function formatLedgerReason(row: CreditLedgerItem) {
  const platform = row.platform_code ? getPlatformMeta(row.platform_code).name : ''
  const hint = [row.window_key, row.keyword, platform]
    .map(part => (part || '').trim())
    .filter(Boolean)
    .join(' · ')
  const reason = (row.reason || '').trim()
  if (row.entry_type === 'settle') {
    if (hint) return hint
    if (reason && !isInternalLedgerReason(reason)) return reason
    return '监测扣费'
  }
  if (reason && !isInternalLedgerReason(reason)) return reason
  return hint || '—'
}

/** 流水主文案：监测词 + 平台；充值/调整用 reason */
function ledgerPrimary(row: CreditLedgerItem) {
  if (row.entry_type === 'settle') {
    const keyword = (row.keyword || '').trim()
    const platform = row.platform_code ? getPlatformMeta(row.platform_code).name : ''
    if (keyword && platform) return `${keyword} · ${platform}`
    if (keyword) return keyword
    return formatLedgerReason(row)
  }
  const reason = (row.reason || '').trim()
  if (reason && !isInternalLedgerReason(reason)) return reason
  return entryTypeLabel[row.entry_type] || '账单变动'
}

/** 流水次文案：时间 · 类型 · 窗口 */
function ledgerSecondary(row: CreditLedgerItem) {
  const parts = [
    formatLedgerTime(row.created_at),
    entryTypeLabel[row.entry_type] || row.entry_type,
  ]
  if (row.entry_type === 'settle' && (row.window_key || '').trim()) {
    parts.push(String(row.window_key).trim())
  }
  return parts.filter(Boolean).join(' · ')
}

const canExportCredit = computed(() => Boolean(menuGrant('customer.enterprise_credit')?.can_export) || props.previewReadonly)
const canOnlineRecharge = computed(() => (
  !props.previewReadonly
  && isCreditBilling.value
  && Boolean(menuGrant('customer.enterprise_credit')?.can_create)
))
const creditsPerYuan = computed(() => {
  const rate = Number(summary.value?.credits_per_yuan)
  return Number.isFinite(rate) && rate > 0 ? rate : 4.2
})

const rechargeVisible = ref(false)
const rechargeYuan = ref('')
const rechargeChannel = ref<'wechat' | 'alipay'>('wechat')
const rechargeSubmitting = ref(false)
const rechargePolling = ref(false)
const rechargeError = ref('')
const rechargeOrder = ref<CreditRechargeOrder | null>(null)
let rechargePoll: CreditRechargePollController | null = null

const rechargeYuanValue = computed(() => {
  const num = Number(rechargeYuan.value)
  return Number.isFinite(num) ? num : NaN
})
const rechargeCreditsPreview = computed(() => {
  if (!Number.isFinite(rechargeYuanValue.value) || rechargeYuanValue.value <= 0) return null
  return Math.round(rechargeYuanValue.value * creditsPerYuan.value * 10) / 10
})
const rechargeQrSrc = computed(() => {
  const code = String(rechargeOrder.value?.code_url || '').trim()
  if (!code) return ''
  return `https://api.qrserver.com/v1/create-qr-code/?size=220x220&margin=10&data=${encodeURIComponent(code)}`
})
const rechargeQrTitle = computed(() => (
  rechargeChannel.value === 'alipay' ? '请使用支付宝扫码支付' : '请使用微信扫码支付'
))

const RECHARGE_QUICK_YUAN = [100, 500, 1000, 2000, 5000]

function clearRechargePoll() {
  rechargePoll?.stop()
  rechargePoll = null
  rechargePolling.value = false
}

function pickQuickYuan(amount: number) {
  if (Boolean(rechargeOrder.value?.code_url) || rechargeSubmitting.value) return
  rechargeYuan.value = String(amount)
  rechargeError.value = ''
}

function resetRechargeDialog() {
  clearRechargePoll()
  rechargeYuan.value = ''
  rechargeChannel.value = 'wechat'
  rechargeSubmitting.value = false
  rechargeError.value = ''
  rechargeOrder.value = null
}

function openRechargeDialog() {
  resetRechargeDialog()
  rechargeVisible.value = true
}

function closeRechargeDialog() {
  rechargeVisible.value = false
  resetRechargeDialog()
}

function backToRechargeForm() {
  clearRechargePoll()
  rechargeOrder.value = null
  rechargeError.value = ''
  rechargeSubmitting.value = false
}

async function refreshCreditAfterPaid() {
  const tenantId = enterpriseTenantId.value
  summary.value = await getEnterpriseCreditSummary(tenantId)
  await loadCreditLedger(1)
}

function startRechargePoll(outTradeNo: string) {
  clearRechargePoll()
  rechargePolling.value = true
  rechargePoll = createCreditRechargePoll({
    outTradeNo,
    isActive: () => rechargeVisible.value,
    fetchStatus: (no) => getEnterpriseCreditRechargeOrderStatus(no, enterpriseTenantId.value),
    onStatus: (status) => {
      rechargeOrder.value = {
        ...(rechargeOrder.value || {}),
        ...status,
      } as CreditRechargeOrder
    },
    onPaid: async (status) => {
      ElMessage.success(`充值成功，已到账 ${formatCreditNumber(status.credits_amount)} 算力`)
      await refreshCreditAfterPaid()
      closeRechargeDialog()
    },
    onTimeout: () => {
      rechargeError.value = '等待支付超时，请稍后刷新流水确认'
    },
    onError: (message) => {
      rechargeError.value = message
    },
    isCanceledError: isRequestCanceled,
    extractError: extractErrorDetail,
  })
  rechargePoll.start()
}

async function submitRecharge() {
  if (!canOnlineRecharge.value) return
  const yuan = Number(rechargeYuan.value)
  if (!Number.isFinite(yuan) || yuan < 1) {
    rechargeError.value = '请输入至少 1 元'
    return
  }
  if (yuan > 50000) {
    rechargeError.value = '单笔最高 5 万元'
    return
  }
  rechargeSubmitting.value = true
  rechargeError.value = ''
  clearRechargePoll()
  try {
    const order = await createEnterpriseCreditRechargeOrder({
      yuan_amount: Math.round(yuan * 100) / 100,
      pay_channel: rechargeChannel.value,
      tenant_id: enterpriseTenantId.value,
    })
    if (!order.code_url) {
      throw new Error('未拿到支付二维码，请稍后重试')
    }
    rechargeOrder.value = order
    // 开发模式也先出码；真实回调不可用时点「模拟支付」
    if (!order.dev_auto_paid) {
      startRechargePoll(order.out_trade_no)
    }
  } catch (error) {
    rechargeError.value = extractErrorDetail(error, '发起充值失败')
  } finally {
    rechargeSubmitting.value = false
  }
}

async function simulateDevPaid() {
  const outTradeNo = String(rechargeOrder.value?.out_trade_no || '').trim()
  if (!outTradeNo || !rechargeOrder.value?.dev_auto_paid) return
  rechargeSubmitting.value = true
  rechargeError.value = ''
  try {
    const paid = await markEnterpriseCreditRechargeDevPaid(outTradeNo, enterpriseTenantId.value)
    ElMessage.success(`充值成功，已到账 ${formatCreditNumber(paid.credits_amount)} 算力`)
    await refreshCreditAfterPaid()
    closeRechargeDialog()
  } catch (error) {
    rechargeError.value = extractErrorDetail(error, '模拟支付失败')
  } finally {
    rechargeSubmitting.value = false
  }
}

const ledgerTotal = computed(() => Number((ledger.value as { total?: number } | null)?.total || 0))
const ledgerTotalPages = computed(() => Math.max(1, Math.ceil(ledgerTotal.value / ledgerPageSize) || 1))
const isGroupedLedger = computed(() => ledgerView.value === 'window' || ledgerView.value === 'day')
const ledgerGroupItems = computed(() => (
  isGroupedLedger.value ? ((ledger.value?.items || []) as CreditLedgerGroupItem[]) : []
))
const ledgerDetailItems = computed(() => (
  ledgerView.value === 'detail' ? ((ledger.value?.items || []) as CreditLedgerItem[]) : []
))
const ledgerMetaLabel = computed(() => {
  if (!ledgerTotal.value) return ''
  if (ledgerView.value === 'window') return `共 ${ledgerTotal.value} 批`
  if (ledgerView.value === 'day') return `共 ${ledgerTotal.value} 天`
  return `共 ${ledgerTotal.value} 条明细`
})

function groupSecondary(row: CreditLedgerGroupItem) {
  const parts = [
    formatLedgerTime(row.ended_at || row.started_at),
    entryTypeLabel[row.primary_entry_type] || (row.primary_entry_type === 'mixed' ? '汇总' : row.primary_entry_type),
  ]
  if (row.entry_count > 1) parts.push(`${row.entry_count} 条`)
  if (row.platform_count > 0 && row.primary_entry_type === 'settle') parts.push(`${row.platform_count} 个平台`)
  if (row.window_key) parts.push(row.window_key)
  return parts.filter(Boolean).join(' · ')
}

async function loadCreditLedger(page = ledgerPage.value) {
  const tenantId = enterpriseTenantId.value
  ledgerPage.value = page
  ledgerDetailVisible.value = false
  ledgerDetailRowId.value = null
  ledgerDetail.value = null
  expandedGroupKey.value = null
  groupLines.value = []
  groupLinesTotal.value = 0
  ledger.value = await getEnterpriseCreditLedger(page, ledgerPageSize, tenantId, ledgerView.value)
}

async function changeLedgerView(view: CreditLedgerView) {
  if (ledgerView.value === view) return
  ledgerView.value = view
  loading.value = true
  try {
    await loadCreditLedger(1)
  } catch (error) {
    if (!isRequestCanceled(error)) {
      ElMessage.error(extractErrorDetail(error, '加载流水失败'))
    }
  } finally {
    loading.value = false
  }
}

async function changeLedgerPage(delta: number) {
  const next = Math.min(ledgerTotalPages.value, Math.max(1, ledgerPage.value + delta))
  if (next === ledgerPage.value) return
  loading.value = true
  try {
    await loadCreditLedger(next)
  } catch (error) {
    if (!isRequestCanceled(error)) {
      ElMessage.error(extractErrorDetail(error, '加载流水失败'))
    }
  } finally {
    loading.value = false
  }
}

async function toggleLedgerGroup(row: CreditLedgerGroupItem) {
  if (expandedGroupKey.value === row.group_key) {
    expandedGroupKey.value = null
    groupLines.value = []
    groupLinesTotal.value = 0
    return
  }
  expandedGroupKey.value = row.group_key
  groupLinesLoading.value = true
  groupLines.value = []
  try {
    const data = await getEnterpriseCreditLedgerGroupLines(
      row.group_key,
      row.group_by,
      1,
      100,
      enterpriseTenantId.value,
    )
    groupLines.value = data.items || []
    groupLinesTotal.value = Number(data.total || 0)
  } catch (error) {
    ElMessage.error(extractErrorDetail(error, '加载批次明细失败'))
    expandedGroupKey.value = null
  } finally {
    groupLinesLoading.value = false
  }
}

function exportCreditLedger() {
  window.open(enterpriseCreditLedgerExportUrl(ledgerView.value, enterpriseTenantId.value), '_blank')
}

type AuditListDiff = {
  removed: string[]
  added: string[]
}

type AuditChangeLine = {
  field: string
  before?: string
  after?: string
  raw?: string
  listDiff?: AuditListDiff | null
}

function splitAuditList(value: string): string[] {
  return String(value || '')
    .split(/[、,，]/)
    .map(part => part.trim())
    .filter(Boolean)
}

function buildAuditListDiff(before?: string, after?: string): AuditListDiff | null {
  if (before == null || after == null) return null
  const beforeItems = splitAuditList(before)
  const afterItems = splitAuditList(after)
  // 单值字段（如词组数量）不走列表 diff
  if (beforeItems.length <= 1 && afterItems.length <= 1) return null
  if (beforeItems.length + afterItems.length < 3) return null
  const afterSet = new Set(afterItems)
  const beforeSet = new Set(beforeItems)
  const removed = beforeItems.filter(item => !afterSet.has(item))
  const added = afterItems.filter(item => !beforeSet.has(item))
  if (!removed.length && !added.length) return null
  return { removed, added }
}

/** 企业页内已有上下文：去掉「保存…「企业名」：」前缀，按；拆成变更行 */
function parseAuditDescription(description: string): AuditChangeLine[] {
  let text = String(description || '').trim()
  text = text.replace(/^(保存企业配置|修改企业配置|保存品牌词|修改品牌词|新增竞品|删除竞品|更新竞品)「[^」]*」[：:]\s*/, '')
  text = text.replace(/^(保存企业配置|修改企业配置|保存品牌词|修改品牌词)[：:]\s*/, '')
  const parts = text.split(/；/).map(part => part.trim()).filter(Boolean)
  if (!parts.length) return text ? [{ field: '', raw: text }] : []
  return parts.map((part) => {
    const matched = part.match(/^(.+?)[：:]([\s\S]+)$/)
    if (!matched) return { field: '', raw: part }
    const field = matched[1].trim()
    const rest = matched[2].trim()
    const sides = rest.split(/\s*(?:→|->)\s*/)
    if (sides.length >= 2) {
      const before = sides.slice(0, -1).join(' → ').trim()
      const after = sides[sides.length - 1].trim()
      return {
        field,
        before,
        after,
        listDiff: buildAuditListDiff(before, after),
      }
    }
    return { field, after: rest }
  })
}

const auditExpanded = ref<Record<number, boolean>>({})

function toggleAuditExpand(idx: number) {
  auditExpanded.value = { ...auditExpanded.value, [idx]: !auditExpanded.value[idx] }
}

function auditNeedsExpand(lines: AuditChangeLine[]) {
  return lines.length > 2
}

function visibleAuditLines(row: { idx: number; lines: AuditChangeLine[]; needsExpand: boolean }) {
  if (!row.needsExpand || auditExpanded.value[row.idx]) return row.lines
  return row.lines.slice(0, 2)
}

const auditViewRows = computed(() => {
  const items = (audit.value?.items || []) as Array<{
    created_at?: string
    action_type?: string
    operator_name?: string
    description?: string
  }>
  return items.map((row, idx) => {
    const lines = parseAuditDescription(String(row.description || ''))
    return {
      idx,
      created_at: row.created_at || '—',
      action_type: row.action_type || '—',
      operator_name: row.operator_name || '—',
      lines,
      needsExpand: auditNeedsExpand(lines),
    }
  })
})


function applyInitialTab() {
  if (props.initialTab === 'customer.enterprise_credit') tab.value = 'credit'
  else if (props.initialTab === 'customer.enterprise_members') tab.value = 'members'
  else if (props.initialTab === 'customer.enterprise_audit') tab.value = 'audit'
  else if (props.initialTab === 'customer.enterprise_monitor') tab.value = 'monitor'
}

function ensureAllowedTab() {
  const allowed = visibleTabs.value.map(item => item.id)
  if (!allowed.length) return
  if (!allowed.includes(tab.value as typeof allowed[number])) {
    tab.value = allowed[0]
  }
}

async function refreshBillingMode() {
  try {
    summary.value = await getEnterpriseCreditSummary(enterpriseTenantId.value)
  } catch (error) {
    if (isRequestCanceled(error)) return
    const status = (error as { response?: { status?: number } })?.response?.status
    const detail = extractErrorDetail(error)
    // 仅明确「托管/停服」才按非 credit 藏 Tab；其它失败勿假写成 hosted
    if (status === 403 && (detail.includes('托管') || detail.includes('停服'))) {
      summary.value = { billing_mode: 'hosted' } as Awaited<ReturnType<typeof getEnterpriseCreditSummary>>
      return
    }
    ElMessage.warning(detail || '算力状态加载失败，请稍后重试')
  }
}

async function loadTab() {
  if (tab.value === 'monitor') return
  loading.value = true
  try {
    const tenantId = enterpriseTenantId.value
    if (tab.value === 'credit') {
      summary.value = await getEnterpriseCreditSummary(tenantId)
      await loadCreditLedger(1)
      terms.value = await getCurrentCreditTerms(tenantId)
    } else if (tab.value === 'members') {
      members.value = await getEnterpriseMembers(tenantId)
    } else if (tab.value === 'audit') {
      // 2026-09-04 - 切 Tab 取消旧请求时勿把 audit 留成 null，否则误显「暂无记录」
      const data = await getEnterpriseAudit(1, 20, tenantId)
      audit.value = data
      auditExpanded.value = {}
    }
  } catch (error) {
    if (!isRequestCanceled(error)) {
      ElMessage.error(extractErrorDetail(error, '加载失败'))
    }
  } finally {
    loading.value = false
  }
}

function openTermsView() {
  if (!terms.value?.content_html) return
  termsViewVisible.value = true
}

/** 弹窗标题固定，避免与正文大标题重复 */
const termsDialogTitle = computed(() => '服务条款')

async function openLedgerDetail(row: CreditLedgerItem) {
  // 再点同一行收起；展开插在该行下方，避免滚到页面底
  if (ledgerDetailVisible.value && ledgerDetailRowId.value === row.id) {
    ledgerDetailVisible.value = false
    ledgerDetailRowId.value = null
    ledgerDetail.value = null
    return
  }
  ledgerDetailRowId.value = row.id
  ledgerDetailVisible.value = true
  ledgerDetailLoading.value = true
  ledgerDetail.value = null
  try {
    ledgerDetail.value = await getEnterpriseCreditLedgerDetail(row.id, enterpriseTenantId.value)
  } catch (error) {
    ElMessage.error(extractErrorDetail(error, '加载明细失败'))
    ledgerDetailVisible.value = false
    ledgerDetailRowId.value = null
  } finally {
    ledgerDetailLoading.value = false
  }
}

function selectTab(code: string) {
  tab.value = code
  void loadTab()
}

function openMemberForm(row?: EnterpriseMemberItem) {
  editingMember.value = row || null
  memberForm.value = {
    display_name: row?.display_name || '',
    username: row?.username || '',
    password: '',
    customer_position_id: row?.customer_position_id || members.value?.positions?.[0]?.id || 0,
    status: row?.status ?? true,
  }
  memberFormVisible.value = true
}

async function submitMemberForm() {
  if (memberSaving.value) return
  const password = String(memberForm.value.password || '')
  if (!editingMember.value) {
    if (!String(memberForm.value.username || '').trim()) {
      ElMessage.warning('请填写登录账号')
      return
    }
    if (password.length < 8) {
      // 2026-09-07 - 邀请成员密码不足 8 位时勿等接口回英文校验
      ElMessage.warning('初始密码至少 8 位')
      return
    }
  } else if (password && password.length < 8) {
    ElMessage.warning('重置密码至少 8 位')
    return
  }
  memberSaving.value = true
  try {
    if (editingMember.value) {
      await updateEnterpriseMember(editingMember.value.identity_id, {
        display_name: memberForm.value.display_name,
        customer_position_id: memberForm.value.customer_position_id,
        status: memberForm.value.status,
      })
      if (password) {
        await resetEnterpriseMemberPassword(editingMember.value.identity_id, password)
      }
    } else {
      await createEnterpriseMember(memberForm.value)
    }
    memberFormVisible.value = false
    ElMessage.success('已保存')
    await loadTab()
  } catch (error) {
    ElMessage.error(extractErrorDetail(error, '保存失败'))
  } finally {
    memberSaving.value = false
  }
}

async function removeMember(row: EnterpriseMemberItem) {
  try {
    await ElMessageBox.confirm(`确定删除成员「${row.display_name}」？`, '删除成员', { type: 'warning' })
    await deleteEnterpriseMember(row.identity_id)
    ElMessage.success('已删除')
    await loadTab()
  } catch (error) {
    if (error !== 'cancel') ElMessage.error(extractErrorDetail(error, '删除失败'))
  }
}

onBeforeUnmount(() => {
  clearRechargePoll()
})

onMounted(async () => {
  applyInitialTab()
  await refreshBillingMode()
  ensureAllowedTab()
  void loadTab()
})

watch(() => props.initialTab, async () => {
  applyInitialTab()
  ensureAllowedTab()
  await loadTab()
})

watch(previewTenantId, async (tenantId, prev) => {
  if (!props.previewReadonly || tenantId == null || tenantId === prev) return
  await refreshBillingMode()
  ensureAllowedTab()
  if (tab.value !== 'monitor') void loadTab()
})

watch(visibleTabs, () => ensureAllowedTab())
</script>

<template>
  <div class="enterprise-config-page" v-loading="loading">
    <aside class="enterprise-side">
      <button
        v-for="item in visibleTabs"
        :key="item.id"
        type="button"
        :class="{ on: tab === item.id }"
        @click="selectTab(item.id)"
      >{{ item.label }}</button>
    </aside>
    <section class="enterprise-main">
      <BrandAuditPage v-if="tab === 'monitor'" customer-config-embed />

        <div v-else-if="tab === 'credit' && isCreditBilling" class="panel credit-panel">
        <header class="credit-hero">
          <div class="credit-hero-metrics">
            <div class="credit-metric is-primary">
              <span class="credit-metric-label">可用算力</span>
              <strong class="credit-metric-value">{{ formatCreditNumber(summary?.available) }}</strong>
            </div>
            <div class="credit-metric">
              <span class="credit-metric-label">今日已扣</span>
              <strong class="credit-metric-value">{{ formatCreditNumber(summary?.today_deduct ?? 0) }}</strong>
            </div>
            <div class="credit-metric">
              <span class="credit-metric-label">总用量</span>
              <strong class="credit-metric-value">{{ formatCreditNumber(summary?.total_usage ?? 0) }}</strong>
            </div>
          </div>
          <div class="credit-hero-links">
            <button
              v-if="canOnlineRecharge"
              type="button"
              class="credit-notice-link"
              @click="openRechargeDialog"
            >在线充值</button>
            <template v-if="canOnlineRecharge">
              <span class="credit-hero-sep" aria-hidden="true">·</span>
            </template>
            <span>对公付款请联系客户经理</span>
            <template v-if="terms">
              <span class="credit-hero-sep" aria-hidden="true">·</span>
              <button type="button" class="credit-notice-link" @click="openTermsView">服务条款</button>
            </template>
          </div>
        </header>

        <el-dialog
          v-model="rechargeVisible"
          width="420px"
          class="credit-recharge-modal"
          :show-close="true"
          :close-on-click-modal="false"
          @closed="resetRechargeDialog"
        >
          <template #header>
            <div class="credit-recharge-head">
              <p class="credit-recharge-kicker">算力中心</p>
              <h3 class="credit-recharge-title">{{ rechargeOrder?.code_url ? '扫码支付' : '在线充值' }}</h3>
              <p class="credit-recharge-sub">
                <template v-if="rechargeOrder?.code_url">
                  ¥{{ Number(rechargeOrder.yuan_amount).toLocaleString('zh-CN', { maximumFractionDigits: 2 }) }}
                  · 预计 {{ formatCreditNumber(rechargeOrder.credits_amount) }} 算力
                </template>
                <template v-else>微信支付或支付宝扫码，到账后立即可用</template>
              </p>
            </div>
          </template>
          <div class="credit-recharge-dialog">
            <template v-if="!rechargeOrder?.code_url">
              <div class="credit-recharge-amount-block">
                <span class="credit-recharge-label">充值金额</span>
                <div class="credit-recharge-amount-field">
                  <em>¥</em>
                  <input
                    v-model="rechargeYuan"
                    type="number"
                    min="1"
                    max="50000"
                    step="0.01"
                    placeholder="0"
                    :disabled="rechargeSubmitting"
                  >
                </div>
                <div class="credit-recharge-quick" role="group" aria-label="常用金额">
                  <button
                    v-for="amt in RECHARGE_QUICK_YUAN"
                    :key="amt"
                    type="button"
                    :class="{ on: Number(rechargeYuan) === amt }"
                    :disabled="rechargeSubmitting"
                    @click="pickQuickYuan(amt)"
                  >{{ amt.toLocaleString('zh-CN') }}</button>
                </div>
              </div>

              <div class="credit-recharge-result" :class="{ ready: rechargeCreditsPreview != null }">
                <span>预计到账</span>
                <strong>
                  <template v-if="rechargeCreditsPreview != null">{{ formatCreditNumber(rechargeCreditsPreview) }}</template>
                  <template v-else>—</template>
                </strong>
                <em>算力 · 1 元 = {{ creditsPerYuan }} 算力</em>
              </div>

              <div class="credit-recharge-channels" role="radiogroup" aria-label="支付方式">
                <button
                  type="button"
                  class="channel-wechat"
                  :class="{ on: rechargeChannel === 'wechat' }"
                  :disabled="rechargeSubmitting"
                  @click="rechargeChannel = 'wechat'"
                >
                  <span class="channel-mark" aria-hidden="true">微</span>
                  <span class="channel-copy">
                    <strong>微信支付</strong>
                    <small>手机微信扫码</small>
                  </span>
                </button>
                <button
                  type="button"
                  class="channel-alipay"
                  :class="{ on: rechargeChannel === 'alipay' }"
                  :disabled="rechargeSubmitting"
                  @click="rechargeChannel = 'alipay'"
                >
                  <span class="channel-mark" aria-hidden="true">支</span>
                  <span class="channel-copy">
                    <strong>支付宝</strong>
                    <small>手机支付宝扫码</small>
                  </span>
                </button>
              </div>
            </template>

            <div v-else class="credit-recharge-qr">
              <p class="credit-recharge-qr-title">{{ rechargeQrTitle }}</p>
              <div class="credit-recharge-qr-frame">
                <img class="credit-recharge-qr-img" :src="rechargeQrSrc" :alt="rechargeQrTitle">
              </div>
              <p class="credit-recharge-qr-hint">
                <template v-if="rechargeOrder.dev_auto_paid">当前为支付开发模式，码不可真付</template>
                <template v-else-if="rechargePolling">等待支付结果…</template>
                <template v-else>扫码后请勿关闭本窗</template>
              </p>
              <p class="credit-recharge-qr-no">单号 {{ rechargeOrder.out_trade_no }}</p>
            </div>
            <p v-if="rechargeError" class="credit-recharge-error">{{ rechargeError }}</p>
          </div>
          <template #footer>
            <div class="credit-recharge-footer">
              <button
                v-if="rechargeOrder?.code_url"
                type="button"
                class="btn-secondary"
                @click="backToRechargeForm"
              >返回修改</button>
              <button
                v-else
                type="button"
                class="btn-secondary"
                @click="closeRechargeDialog"
              >取消</button>
              <button
                v-if="rechargeOrder?.dev_auto_paid && rechargeOrder?.code_url"
                type="button"
                class="btn-primary"
                :disabled="rechargeSubmitting"
                @click="simulateDevPaid"
              >{{ rechargeSubmitting ? '入账中…' : '模拟支付成功' }}</button>
              <button
                v-if="!rechargeOrder?.code_url"
                type="button"
                class="btn-primary"
                :disabled="rechargeSubmitting"
                @click="submitRecharge"
              >{{ rechargeSubmitting ? '下单中…' : '确认支付' }}</button>
            </div>
          </template>
        </el-dialog>

        <el-dialog v-model="termsViewVisible" width="560px" :title="termsDialogTitle">
          <div v-if="terms?.content_html" class="terms-box terms-box-dialog" v-html="terms.content_html" />
        </el-dialog>

        <section class="credit-ledger">
          <div class="credit-ledger-head">
            <div class="credit-ledger-head-main">
              <h3 class="credit-ledger-title">算力流水</h3>
              <span v-if="ledgerMetaLabel" class="credit-ledger-meta">{{ ledgerMetaLabel }}</span>
            </div>
            <div class="credit-ledger-toolbar">
              <div class="credit-ledger-views" role="tablist" aria-label="流水视图">
                <button type="button" :class="{ on: ledgerView === 'window' }" @click="changeLedgerView('window')">按批次</button>
                <button type="button" :class="{ on: ledgerView === 'day' }" @click="changeLedgerView('day')">按日</button>
                <button type="button" :class="{ on: ledgerView === 'detail' }" @click="changeLedgerView('detail')">明细</button>
              </div>
              <button
                v-if="canExportCredit"
                type="button"
                class="plain-btn credit-export-btn"
                @click="exportCreditLedger"
              >导出 CSV</button>
            </div>
          </div>

          <div v-if="isGroupedLedger && ledgerGroupItems.length" class="credit-ledger-list">
            <div
              v-for="row in ledgerGroupItems"
              :key="row.group_key"
              class="credit-ledger-block"
              :class="{ open: expandedGroupKey === row.group_key }"
            >
              <button
                type="button"
                class="credit-ledger-item"
                :class="{ 'is-active': expandedGroupKey === row.group_key }"
                @click="toggleLedgerGroup(row)"
              >
                <div class="credit-ledger-main">
                  <strong class="credit-ledger-primary" :title="row.title">{{ row.title }}</strong>
                  <span class="credit-ledger-secondary">{{ groupSecondary(row) }}</span>
                </div>
                <div class="credit-ledger-side">
                  <strong
                    class="credit-ledger-amount"
                    :class="{ plus: row.amount_sum > 0, minus: row.amount_sum < 0 }"
                  >{{ formatLedgerAmount(row.amount_sum) }}</strong>
                  <span v-if="row.balance_after != null" class="credit-ledger-balance">
                    余额 {{ formatCreditNumber(row.balance_after) }}
                  </span>
                </div>
              </button>
              <div
                v-if="expandedGroupKey === row.group_key"
                v-loading="groupLinesLoading"
                class="credit-ledger-expand"
              >
                <ul v-if="groupLines.length" class="credit-group-lines">
                  <li v-for="line in groupLines" :key="line.id">
                    <div>
                      <strong>{{ ledgerPrimary(line) }}</strong>
                      <span>{{ ledgerSecondary(line) }}</span>
                    </div>
                    <em :class="{ plus: line.amount > 0, minus: line.amount < 0 }">{{ formatLedgerAmount(line.amount) }}</em>
                  </li>
                </ul>
                <p v-else-if="!groupLinesLoading" class="hint credit-expand-empty">暂无明细</p>
                <p v-if="groupLinesTotal > groupLines.length" class="hint credit-expand-empty">
                  已展示 {{ groupLines.length }} / {{ groupLinesTotal }} 条
                </p>
              </div>
            </div>
          </div>

          <div v-else-if="ledgerView === 'detail' && ledgerDetailItems.length" class="credit-ledger-list">
            <div
              v-for="row in ledgerDetailItems"
              :key="row.id"
              class="credit-ledger-block"
              :class="{ open: ledgerDetailVisible && ledgerDetailRowId === row.id }"
            >
              <button
                type="button"
                class="credit-ledger-item"
                :class="{ 'is-active': ledgerDetailVisible && ledgerDetailRowId === row.id }"
                @click="openLedgerDetail(row)"
              >
                <div class="credit-ledger-main">
                  <strong class="credit-ledger-primary" :title="ledgerPrimary(row)">{{ ledgerPrimary(row) }}</strong>
                  <span class="credit-ledger-secondary">{{ ledgerSecondary(row) }}</span>
                </div>
                <div class="credit-ledger-side">
                  <strong
                    class="credit-ledger-amount"
                    :class="{ plus: row.amount > 0, minus: row.amount < 0 }"
                  >{{ formatLedgerAmount(row.amount) }}</strong>
                  <span class="credit-ledger-balance">余额 {{ formatCreditNumber(row.balance_after) }}</span>
                </div>
              </button>
              <div
                v-if="ledgerDetailVisible && ledgerDetailRowId === row.id"
                v-loading="ledgerDetailLoading"
                class="credit-ledger-expand"
              >
                <template v-if="ledgerDetail">
                  <dl class="credit-expand-dl">
                    <div><dt>类型</dt><dd>{{ entryTypeLabel[ledgerDetail.entry_type] || ledgerDetail.entry_type }}</dd></div>
                    <div><dt>时间</dt><dd>{{ ledgerDetail.created_at }}</dd></div>
                    <div>
                      <dt>变动</dt>
                      <dd :class="{ plus: ledgerDetail.amount > 0, minus: ledgerDetail.amount < 0 }">
                        {{ formatLedgerAmount(ledgerDetail.amount) }}
                      </dd>
                    </div>
                    <div><dt>余额</dt><dd>{{ formatCreditNumber(ledgerDetail.balance_after) }}</dd></div>
                    <div v-if="ledgerDetail.window_key"><dt>窗口</dt><dd>{{ ledgerDetail.window_key }}</dd></div>
                    <div><dt>说明</dt><dd>{{ formatLedgerReason(ledgerDetail) }}</dd></div>
                  </dl>
                  <div v-if="ledgerDetail.subtasks?.length" class="credit-expand-subs-wrap">
                    <h4 class="credit-expand-subhead">明细</h4>
                    <ul class="credit-expand-subs">
                      <li v-for="(st, idx) in ledgerDetail.subtasks" :key="st.subtask_id || idx">
                        <div>
                          <strong>{{ st.keyword || '—' }}</strong>
                          <span>{{ st.platform_code ? getPlatformMeta(st.platform_code).name : '—' }} · {{ formatSubtaskStatus(st.status) }}</span>
                        </div>
                        <em>{{ st.credits ?? '—' }}</em>
                      </li>
                    </ul>
                  </div>
                  <p v-else-if="!ledgerDetailLoading" class="hint credit-expand-empty">暂无子任务明细</p>
                </template>
              </div>
            </div>
          </div>
          <p v-else class="hint">暂无流水</p>

          <div v-if="ledgerTotalPages > 1" class="ledger-pagination">
            <span class="ledger-pagination-meta">第 {{ ledgerPage }} / {{ ledgerTotalPages }} 页</span>
            <button type="button" class="plain-btn" :disabled="ledgerPage <= 1" @click="changeLedgerPage(-1)">上一页</button>
            <button type="button" class="plain-btn" :disabled="ledgerPage >= ledgerTotalPages" @click="changeLedgerPage(1)">下一页</button>
          </div>
        </section>
      </div>

      <div v-else-if="tab === 'members'" class="panel">
        <div class="panel-head">
          <h3>成员列表</h3>
          <button v-if="canEditMembers" type="button" class="btn-primary" @click="openMemberForm()">邀请成员</button>
        </div>
        <div class="table-scroll">
          <table v-if="members?.items?.length" class="table">
            <thead><tr><th>姓名</th><th>账号</th><th>职位</th><th>状态</th><th v-if="canUpdateMembers">操作</th></tr></thead>
            <tbody>
              <tr v-for="row in members.items" :key="row.identity_id">
                <td>{{ row.display_name }}</td>
                <td>{{ row.username }}</td>
                <td>{{ row.position_name }}</td>
                <td>{{ row.status ? '启用' : '停用' }}</td>
                <td v-if="canUpdateMembers || canDeleteMembers">
                  <button v-if="canUpdateMembers" type="button" class="btn-link-inline" @click="openMemberForm(row)">编辑</button>
                  <button v-if="canDeleteMembers" type="button" class="btn-link-inline danger" @click="removeMember(row)">删除</button>
                </td>
              </tr>
            </tbody>
          </table>
          <p v-else class="hint">暂无成员</p>
        </div>
        <el-dialog v-model="memberFormVisible" width="480px" :title="editingMember ? '编辑成员' : '邀请成员'">
          <label class="field"><span>姓名</span><input v-model="memberForm.display_name" class="input" /></label>
          <label v-if="!editingMember" class="field"><span>登录账号</span><input v-model="memberForm.username" class="input" /></label>
          <label class="field"><span>{{ editingMember ? '重置密码（留空不改）' : '初始密码（至少 8 位）' }}</span><input v-model="memberForm.password" type="password" class="input" /></label>
          <label class="field">
            <span>职位</span>
            <select v-model="memberForm.customer_position_id" class="input">
              <option v-for="p in members?.positions || []" :key="p.id" :value="p.id">{{ p.position_name }}</option>
            </select>
          </label>
          <label class="check"><input v-model="memberForm.status" type="checkbox" />启用</label>
          <template #footer>
            <button type="button" class="btn-secondary" @click="memberFormVisible = false">取消</button>
            <button type="button" class="btn-primary" :disabled="memberSaving" @click="submitMemberForm">
              {{ memberSaving ? '保存中…' : '保存' }}
            </button>
          </template>
        </el-dialog>
      </div>

      <div v-else-if="tab === 'audit'" class="panel">
        <div class="table-scroll">
          <table v-if="auditViewRows.length" class="table audit-table">
            <thead>
              <tr>
                <th class="col-time">时间</th>
                <th class="col-action">操作</th>
                <th>说明</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in auditViewRows" :key="row.idx">
                <td class="col-time">{{ row.created_at }}</td>
                <td class="col-action">
                  <div class="audit-action-cell">
                    <span class="audit-action-tag">{{ row.action_type }}</span>
                    <span class="audit-operator" :title="row.operator_name">{{ row.operator_name }}</span>
                  </div>
                </td>
                <td class="col-desc">
                  <div class="audit-desc">
                    <div
                      v-for="(line, lineIdx) in visibleAuditLines(row)"
                      :key="lineIdx"
                      class="audit-change"
                    >
                      <template v-if="line.raw">
                        <span class="audit-raw">{{ line.raw }}</span>
                      </template>
                      <template v-else>
                        <span v-if="line.field" class="audit-field">{{ line.field }}</span>
                        <div v-if="line.listDiff" class="audit-list-diff">
                          <p v-if="line.listDiff.removed.length" class="audit-list-row is-removed">
                            <span class="audit-list-label">移除</span>
                            <span>{{ line.listDiff.removed.join('、') }}</span>
                          </p>
                          <p v-if="line.listDiff.added.length" class="audit-list-row is-added">
                            <span class="audit-list-label">新增</span>
                            <span>{{ line.listDiff.added.join('、') }}</span>
                          </p>
                          <p
                            v-if="!line.listDiff.removed.length && !line.listDiff.added.length"
                            class="audit-list-row"
                          >
                            <span class="audit-list-label">变更后</span>
                            <span>{{ line.after }}</span>
                          </p>
                        </div>
                        <div v-else-if="line.before != null || line.after != null" class="audit-stack-diff">
                          <p v-if="line.before != null" class="audit-stack-row">
                            <span class="audit-list-label">变更前</span>
                            <span class="audit-before">{{ line.before }}</span>
                          </p>
                          <p v-if="line.after != null" class="audit-stack-row">
                            <span class="audit-list-label">变更后</span>
                            <span class="audit-after">{{ line.after }}</span>
                          </p>
                        </div>
                      </template>
                    </div>
                  </div>
                  <button
                    v-if="row.needsExpand"
                    type="button"
                    class="audit-expand-btn"
                    @click="toggleAuditExpand(row.idx)"
                  >
                    {{ auditExpanded[row.idx] ? '收起' : `展开其余 ${row.lines.length - 2} 项` }}
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
          <p v-else class="hint">暂无记录</p>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.enterprise-config-page { display: flex; gap: 0; min-height: 520px; border: 1px solid var(--el-border-color); border-radius: 10px; overflow: hidden; background: #fff; }
.enterprise-side { width: 200px; background: #f8fafc; border-right: 1px solid var(--el-border-color); padding: 12px 0; flex-shrink: 0; }
.enterprise-side button { display: block; width: 100%; text-align: left; border: none; background: transparent; padding: 10px 16px; cursor: pointer; color: #64748b; }
.enterprise-side button.on { background: #fff; color: var(--el-color-primary); font-weight: 600; border-right: 2px solid var(--el-color-primary); }
.enterprise-main { flex: 1; padding: 18px; min-width: 0; }
.panel-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 12px; margin-bottom: 16px; }
.card { border: 1px solid var(--el-border-color); border-radius: 10px; padding: 16px; }
.card.warn { background: #fffbeb; border-color: #fcd34d; }
.card span { display: block; font-size: 12px; color: #64748b; margin-bottom: 6px; }
.card strong { font-size: 22px; }
.credit-panel { padding-top: 4px; }
.credit-hero {
  margin-bottom: 20px;
  padding-bottom: 16px;
  border-bottom: 1px solid #eef2f7;
}
.credit-hero-metrics {
  display: grid;
  grid-template-columns: minmax(0, 1.4fr) repeat(2, minmax(0, 1fr));
  gap: 12px 20px;
  align-items: end;
}
.credit-metric-label {
  display: block;
  margin-bottom: 6px;
  color: #64748b;
  font-size: 12px;
  letter-spacing: 0.02em;
}
.credit-metric-value {
  display: block;
  color: #0f172a;
  font-size: 22px;
  font-weight: 700;
  line-height: 1.15;
  letter-spacing: -0.02em;
  font-variant-numeric: tabular-nums;
}
.credit-metric.is-primary .credit-metric-value {
  font-size: 34px;
  color: #0f172a;
}
.credit-hero-links {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px 4px;
  margin-top: 12px;
  color: #94a3b8;
  font-size: 12px;
}
.credit-hero-sep {
  margin: 0 6px;
  color: #cbd5e1;
}
.credit-ledger-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
  flex-wrap: wrap;
}
.credit-ledger-head-main {
  display: flex;
  align-items: baseline;
  gap: 10px;
  min-width: 0;
}
.credit-ledger-title {
  margin: 0;
  font-size: 15px;
  font-weight: 700;
  color: #0f172a;
}
.credit-ledger-meta {
  color: #94a3b8;
  font-size: 12px;
}
.credit-ledger-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.credit-ledger-views {
  display: inline-flex;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  overflow: hidden;
  background: #fff;
}
.credit-ledger-views button {
  border: 0;
  background: transparent;
  padding: 6px 12px;
  font-size: 13px;
  color: #475569;
  cursor: pointer;
}
.credit-ledger-views button + button {
  border-left: 1px solid #e2e8f0;
}
.credit-ledger-views button.on {
  background: #0f172a;
  color: #fff;
}
.credit-export-btn {
  font-size: 13px;
}
.credit-ledger-list {
  border-top: 1px solid #eef2f7;
}
.credit-ledger-block {
  border-bottom: 1px solid #eef2f7;
}
.credit-ledger-block.open {
  background: #f8fafc;
}
.credit-group-lines {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.credit-group-lines li {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
  font-size: 13px;
}
.credit-group-lines li div {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.credit-group-lines li strong {
  font-weight: 600;
  color: #0f172a;
}
.credit-group-lines li span {
  color: #94a3b8;
  font-size: 12px;
}
.credit-group-lines li em {
  font-style: normal;
  font-weight: 650;
  white-space: nowrap;
}
.credit-group-lines li em.plus { color: #047857; }
.credit-group-lines li em.minus { color: #b45309; }
.credit-ledger-item {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  width: 100%;
  margin: 0;
  padding: 14px 4px;
  border: none;
  background: transparent;
  text-align: left;
  cursor: pointer;
}
.credit-ledger-item:hover {
  background: #f8fafc;
}
.credit-ledger-item.is-active {
  background: transparent;
}
.credit-ledger-main {
  min-width: 0;
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.credit-ledger-primary {
  color: #0f172a;
  font-size: 14px;
  font-weight: 600;
  line-height: 1.4;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.credit-ledger-block.open .credit-ledger-primary {
  color: var(--el-color-primary);
}
.credit-ledger-secondary {
  color: #94a3b8;
  font-size: 12px;
  line-height: 1.35;
}
.credit-ledger-side {
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 4px;
  min-width: 96px;
}
.credit-ledger-amount {
  font-size: 15px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  line-height: 1.2;
}
.credit-ledger-amount.plus { color: #047857; }
.credit-ledger-amount.minus { color: #b45309; }
.credit-ledger-balance {
  color: #94a3b8;
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}
.credit-ledger-expand {
  min-height: 48px;
  margin: 0 4px 12px;
  padding: 12px 14px;
  border: 1px solid #e8eef5;
  border-radius: 8px;
  background: #fff;
}
.credit-expand-dl {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px 16px;
  margin: 0;
}
.credit-expand-dl > div {
  display: grid;
  grid-template-columns: 40px 1fr;
  gap: 8px;
  align-items: start;
}
.credit-expand-dl dt {
  margin: 0;
  color: #94a3b8;
  font-size: 12px;
}
.credit-expand-dl dd {
  margin: 0;
  color: #0f172a;
  font-size: 13px;
  word-break: break-word;
}
.credit-expand-dl dd.plus { color: #047857; font-weight: 600; }
.credit-expand-dl dd.minus { color: #b45309; font-weight: 600; }
.credit-expand-subs-wrap { margin-top: 12px; }
.credit-expand-subhead {
  margin: 0 0 6px;
  font-size: 12px;
  font-weight: 600;
  color: #64748b;
}
.credit-expand-subs {
  list-style: none;
  margin: 0;
  padding: 0;
  border-top: 1px solid #eef2f7;
}
.credit-expand-subs li {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  padding: 8px 0;
  border-bottom: 1px solid #eef2f7;
}
.credit-expand-subs strong {
  display: block;
  color: #0f172a;
  font-size: 13px;
}
.credit-expand-subs span {
  display: block;
  margin-top: 2px;
  color: #94a3b8;
  font-size: 12px;
}
.credit-expand-subs em {
  flex-shrink: 0;
  font-style: normal;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  color: #0f172a;
}
.credit-expand-empty { margin: 8px 0 0; }
.ledger-pagination {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 12px;
}
.ledger-pagination-meta {
  margin-right: auto;
  color: #94a3b8;
  font-size: 12px;
}
.ledger-pagination .plain-btn {
  border: 1px solid #dbe3ee;
  background: #fff;
  border-radius: 6px;
  padding: 6px 12px;
  font-size: 13px;
  cursor: pointer;
}
.ledger-pagination .plain-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.hint { color: #64748b; font-size: 13px; }
.credit-notice-link {
  border: none;
  background: transparent;
  padding: 0;
  color: var(--el-color-primary);
  font-size: 12px;
  cursor: pointer;
}
.credit-notice-link:hover { text-decoration: underline; }
.credit-recharge-dialog {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.credit-recharge-head {
  padding-right: 20px;
}
.credit-recharge-kicker {
  margin: 0 0 4px;
  color: #64748b;
  font-size: 12px;
  letter-spacing: 0.04em;
}
.credit-recharge-title {
  margin: 0;
  color: #0f172a;
  font-size: 20px;
  font-weight: 700;
  letter-spacing: -0.02em;
  line-height: 1.25;
}
.credit-recharge-sub {
  margin: 6px 0 0;
  color: #94a3b8;
  font-size: 13px;
  line-height: 1.4;
}
.credit-recharge-label {
  display: block;
  margin-bottom: 8px;
  color: #64748b;
  font-size: 12px;
  font-weight: 600;
}
.credit-recharge-amount-field {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  border: 1px solid #dbe3ee;
  border-radius: 12px;
  background: #f8fafc;
}
.credit-recharge-amount-field:focus-within {
  border-color: var(--el-color-primary);
  background: #fff;
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--el-color-primary) 18%, transparent);
}
.credit-recharge-amount-field em {
  font-style: normal;
  color: #94a3b8;
  font-size: 22px;
  font-weight: 650;
  line-height: 1;
}
.credit-recharge-amount-field input {
  flex: 1;
  min-width: 0;
  border: none;
  outline: none;
  background: transparent;
  color: #0f172a;
  font-size: 32px;
  font-weight: 700;
  letter-spacing: -0.03em;
  font-variant-numeric: tabular-nums;
  line-height: 1.1;
}
.credit-recharge-amount-field input:disabled {
  opacity: 0.7;
  cursor: not-allowed;
}
.credit-recharge-amount-field input::-webkit-outer-spin-button,
.credit-recharge-amount-field input::-webkit-inner-spin-button {
  -webkit-appearance: none;
  margin: 0;
}
.credit-recharge-amount-field input[type='number'] {
  -moz-appearance: textfield;
  appearance: textfield;
}
.credit-recharge-quick {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
}
.credit-recharge-quick button {
  border: 1px solid #e2e8f0;
  background: #fff;
  border-radius: 999px;
  padding: 6px 12px;
  color: #475569;
  font-size: 12px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  cursor: pointer;
}
.credit-recharge-quick button:hover:not(:disabled) {
  border-color: #cbd5e1;
  color: #0f172a;
}
.credit-recharge-quick button.on {
  border-color: color-mix(in srgb, var(--el-color-primary) 55%, #fff);
  background: color-mix(in srgb, var(--el-color-primary) 10%, #fff);
  color: var(--el-color-primary);
}
.credit-recharge-quick button:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
.credit-recharge-result {
  display: grid;
  grid-template-columns: auto 1fr;
  grid-template-rows: auto auto;
  column-gap: 12px;
  row-gap: 2px;
  align-items: baseline;
  padding: 14px 16px;
  border-radius: 12px;
  background: linear-gradient(180deg, #f8fafc 0%, #f1f5f9 100%);
  border: 1px solid #e8eef5;
}
.credit-recharge-result.ready {
  background: linear-gradient(180deg, #f0f7ff 0%, #eef6ff 100%);
  border-color: color-mix(in srgb, var(--el-color-primary) 22%, #e8eef5);
}
.credit-recharge-result > span {
  grid-column: 1;
  grid-row: 1;
  color: #64748b;
  font-size: 12px;
  font-weight: 600;
}
.credit-recharge-result > strong {
  grid-column: 2;
  grid-row: 1 / span 2;
  justify-self: end;
  align-self: center;
  color: #0f172a;
  font-size: 28px;
  font-weight: 700;
  letter-spacing: -0.03em;
  font-variant-numeric: tabular-nums;
  line-height: 1;
}
.credit-recharge-result.ready > strong {
  color: var(--el-color-primary);
}
.credit-recharge-result > em {
  grid-column: 1;
  grid-row: 2;
  font-style: normal;
  color: #94a3b8;
  font-size: 12px;
}
.credit-recharge-channels {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}
.credit-recharge-channels > button {
  display: flex;
  align-items: center;
  gap: 10px;
  border: 1px solid #e2e8f0;
  background: #fff;
  border-radius: 12px;
  padding: 12px;
  text-align: left;
  cursor: pointer;
  transition: border-color 0.15s ease, background 0.15s ease, box-shadow 0.15s ease;
}
.credit-recharge-channels > button:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
.credit-recharge-channels .channel-mark {
  flex-shrink: 0;
  width: 34px;
  height: 34px;
  border-radius: 10px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  font-weight: 700;
  color: #fff;
}
.channel-wechat .channel-mark { background: #07c160; }
.channel-alipay .channel-mark { background: #1677ff; }
.credit-recharge-channels .channel-copy {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.credit-recharge-channels .channel-copy strong {
  color: #0f172a;
  font-size: 14px;
  font-weight: 700;
  line-height: 1.2;
}
.credit-recharge-channels .channel-copy small {
  color: #94a3b8;
  font-size: 12px;
  line-height: 1.2;
}
.channel-wechat.on {
  border-color: #07c160;
  background: #f3fbf6;
  box-shadow: 0 0 0 3px rgba(7, 193, 96, 0.12);
}
.channel-alipay.on {
  border-color: #1677ff;
  background: #f3f8ff;
  box-shadow: 0 0 0 3px rgba(22, 119, 255, 0.12);
}
.credit-recharge-qr {
  margin: 0;
  padding: 4px 0 0;
  border: none;
  border-radius: 0;
  text-align: center;
  background: transparent;
}
.credit-recharge-qr-title {
  margin: 0 0 14px;
  font-size: 15px;
  font-weight: 700;
  color: #0f172a;
}
.credit-recharge-qr-frame {
  display: inline-flex;
  padding: 12px;
  border-radius: 14px;
  background: #f8fafc;
  border: 1px solid #e8eef5;
}
.credit-recharge-qr-img {
  width: 200px;
  height: 200px;
  display: block;
  background: #fff;
  border-radius: 6px;
}
.credit-recharge-qr-hint {
  margin: 12px 0 4px;
  font-size: 13px;
  color: #64748b;
}
.credit-recharge-qr-no {
  margin: 0;
  font-size: 12px;
  color: #94a3b8;
  font-variant-numeric: tabular-nums;
}
.credit-recharge-error {
  margin: 0;
  color: #dc2626;
  font-size: 13px;
}
.credit-recharge-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  width: 100%;
}
.field { display: block; margin-bottom: 12px; }
.field span { display: block; font-size: 12px; color: #64748b; margin-bottom: 4px; }
.input { width: 100%; border: 1px solid var(--el-border-color); border-radius: 6px; padding: 8px 10px; }
.check { display: flex; align-items: center; gap: 8px; margin: 12px 0; }
.btn-primary { background: var(--el-color-primary); color: #fff; border: none; border-radius: 6px; padding: 8px 14px; cursor: pointer; }
.btn-secondary { border: 1px solid var(--el-border-color); background: #fff; border-radius: 6px; padding: 8px 14px; cursor: pointer; }
.btn-link-inline { border: none; background: transparent; color: var(--el-color-primary); cursor: pointer; margin-right: 8px; }
.btn-link-inline.danger { color: #dc2626; }
.table-scroll { width: 100%; overflow-x: auto; }
.table { width: 100%; border-collapse: collapse; margin-top: 12px; font-size: 13px; }
.table th, .table td { border: 1px solid var(--el-border-color); padding: 8px 10px; text-align: left; vertical-align: top; }
.table tr.clickable { cursor: pointer; }
.table tr.clickable:hover { background: #f8fafc; }
.audit-table { table-layout: fixed; margin-top: 0; }
.audit-table th, .audit-table td { overflow: hidden; }
.audit-table .col-time { width: 138px; white-space: nowrap; color: #64748b; font-variant-numeric: tabular-nums; }
.audit-table .col-action { width: 128px; }
.audit-table .col-desc { min-width: 0; }
.audit-action-cell {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}
.audit-action-tag {
  display: inline-block;
  max-width: 100%;
  padding: 2px 8px;
  border-radius: 6px;
  background: #f1f5f9;
  color: #334155;
  font-size: 12px;
  font-weight: 600;
  line-height: 1.4;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.audit-operator {
  display: block;
  min-width: 0;
  color: #94a3b8;
  font-size: 12px;
  line-height: 1.35;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.audit-desc { display: flex; flex-direction: column; gap: 10px; min-width: 0; }
.audit-change {
  min-width: 0;
  padding-bottom: 8px;
  border-bottom: 1px dashed #e2e8f0;
}
.audit-change:last-child {
  padding-bottom: 0;
  border-bottom: none;
}
.audit-field {
  display: block;
  margin-bottom: 4px;
  font-size: 12px;
  font-weight: 600;
  color: #334155;
  line-height: 1.4;
}
.audit-stack-diff,
.audit-list-diff {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}
.audit-stack-row,
.audit-list-row {
  display: grid;
  grid-template-columns: 44px minmax(0, 1fr);
  gap: 8px;
  margin: 0;
  font-size: 12px;
  line-height: 1.45;
  word-break: break-word;
}
.audit-list-label {
  color: #94a3b8;
  flex-shrink: 0;
}
.audit-list-row.is-removed span:last-child { color: #b45309; }
.audit-list-row.is-added span:last-child { color: #047857; }
.audit-before { color: #94a3b8; }
.audit-after { color: #0f172a; }
.audit-raw { font-size: 12px; color: #475569; word-break: break-word; line-height: 1.45; }
.audit-expand-btn {
  margin-top: 8px;
  border: none;
  background: transparent;
  padding: 0;
  color: var(--el-color-primary);
  font-size: 12px;
  cursor: pointer;
}
.audit-expand-btn:hover { text-decoration: underline; }
.terms-box { max-height: 200px; overflow: auto; border: 1px solid var(--el-border-color); padding: 12px; margin: 12px 0; font-size: 13px; }
.terms-box-dialog { max-height: 420px; margin: 0; }
@media (max-width: 900px) {
  /* 2026-09-07 - 企业配置窄屏：侧栏改顶栏横滑 */
  .enterprise-config-page { flex-direction: column; min-height: 0; }
  .enterprise-side {
    width: 100%;
    display: flex;
    gap: 4px;
    overflow-x: auto;
    border-right: none;
    border-bottom: 1px solid var(--el-border-color);
    padding: 8px;
  }
  .enterprise-side button {
    width: auto;
    white-space: nowrap;
    border-radius: 8px;
    padding: 8px 12px;
  }
  .enterprise-side button.on {
    border-right: none;
    background: #eff6ff;
  }
  .enterprise-main { padding: 12px; }
  .cards { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .credit-hero-metrics { grid-template-columns: 1fr; gap: 10px; }
  .credit-metric.is-primary .credit-metric-value { font-size: 30px; }
  .credit-expand-dl { grid-template-columns: 1fr; }
  .credit-ledger-item { gap: 12px; padding: 12px 0; }
}
</style>

<style>
/* teleported el-dialog shell; keep recharge modal chrome with the page */
.credit-recharge-modal.el-dialog {
  border-radius: 16px;
  overflow: hidden;
}
.credit-recharge-modal .el-dialog__header {
  margin: 0;
  padding: 20px 20px 0;
}
.credit-recharge-modal .el-dialog__body {
  padding: 16px 20px 8px;
}
.credit-recharge-modal .el-dialog__footer {
  padding: 8px 20px 20px;
}
.credit-recharge-modal .el-dialog__headerbtn {
  top: 18px;
  right: 16px;
}
</style>
