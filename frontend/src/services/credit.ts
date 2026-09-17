import { http } from './http'

function enterpriseTenantParams(tenantId?: number) {
  return tenantId ? { tenant_id: tenantId } : undefined
}

export interface CreditSummary {
  balance: number
  available: number
  today_deduct?: number
  total_usage?: number
  daily_estimate: Record<string, unknown>
  billing_mode: string
  credits_per_yuan?: number
}

export interface CreditRechargeOrder {
  out_trade_no: string
  status: string
  pay_channel: string
  yuan_amount: number
  credits_amount: number
  credits_per_yuan: number
  code_url?: string | null
  paid_at?: string | null
  available?: number | null
  dev_auto_paid?: boolean
}

export interface CreditLedgerItem {
  id: number
  amount: number
  balance_after: number
  entry_type: string
  reason: string | null
  ref_type?: string | null
  ref_id?: string | null
  platform_code?: string | null
  keyword?: string | null
  window_key?: string | null
  created_at: string
  tenant_id?: number
  tenant_name?: string | null
  has_detail?: boolean
}

export type CreditLedgerView = 'window' | 'day' | 'detail'

export interface CreditLedgerGroupItem {
  group_key: string
  group_by: 'window' | 'day'
  title: string
  primary_entry_type: string
  amount_sum: number
  settle_sum: number
  entry_count: number
  keyword_count: number
  platform_count: number
  window_key?: string | null
  started_at?: string | null
  ended_at?: string | null
  balance_after?: number | null
  has_lines?: boolean
}

export interface CreditLedgerListResult {
  items: CreditLedgerItem[] | CreditLedgerGroupItem[]
  total?: number
  page: number
  page_size: number
  view?: CreditLedgerView
}

export interface CreditLedgerSubtaskItem {
  subtask_id?: string
  platform_code?: string | null
  keyword?: string | null
  status?: string | null
  credits?: number
}

export interface CreditLedgerDetail extends CreditLedgerItem {
  subtasks: CreditLedgerSubtaskItem[]
}

export interface EnterpriseMemberItem {
  identity_id: number
  user_id: number
  display_name: string
  username: string
  customer_position_id: number | null
  position_name: string
  status: boolean
}

export interface CustomerPositionOption {
  id: number
  position_code: string
  position_name: string
}

export async function getEnterpriseCreditSummary(tenantId?: number): Promise<CreditSummary> {
  const response = await http.get('/v1/customer/enterprise/credit/summary', { params: enterpriseTenantParams(tenantId) })
  return response.data.data
}

export async function createEnterpriseCreditRechargeOrder(payload: {
  yuan_amount: number
  pay_channel: 'wechat' | 'alipay' | string
  tenant_id?: number
}): Promise<CreditRechargeOrder> {
  const response = await http.post('/v1/customer/enterprise/credit/recharge/orders', payload)
  return response.data.data
}

export async function getEnterpriseCreditRechargeOrderStatus(
  outTradeNo: string,
  tenantId?: number,
): Promise<CreditRechargeOrder> {
  const response = await http.get(
    `/v1/customer/enterprise/credit/recharge/orders/${encodeURIComponent(outTradeNo)}`,
    { params: enterpriseTenantParams(tenantId) },
  )
  return response.data.data
}

export async function markEnterpriseCreditRechargeDevPaid(
  outTradeNo: string,
  tenantId?: number,
): Promise<CreditRechargeOrder> {
  const response = await http.post(
    `/v1/customer/enterprise/credit/recharge/orders/${encodeURIComponent(outTradeNo)}/dev-paid`,
    null,
    { params: enterpriseTenantParams(tenantId) },
  )
  return response.data.data
}

export async function getEnterpriseCreditLedger(
  page = 1,
  pageSize = 20,
  tenantId?: number,
  view: CreditLedgerView = 'window',
) {
  const response = await http.get('/v1/customer/enterprise/credit/ledger', {
    params: { page, page_size: pageSize, view, ...enterpriseTenantParams(tenantId) },
  })
  return response.data.data as CreditLedgerListResult
}

export async function getEnterpriseCreditLedgerGroupLines(
  groupKey: string,
  groupBy: 'window' | 'day',
  page = 1,
  pageSize = 100,
  tenantId?: number,
) {
  const response = await http.get(
    `/v1/customer/enterprise/credit/ledger/groups/${encodeURIComponent(groupKey)}/lines`,
    {
      params: { group_by: groupBy, page, page_size: pageSize, ...enterpriseTenantParams(tenantId) },
    },
  )
  return response.data.data as {
    items: CreditLedgerItem[]
    total: number
    page: number
    page_size: number
    group_key: string
    group_by: string
  }
}

export async function getEnterpriseCreditLedgerDetail(ledgerId: number, tenantId?: number) {
  const response = await http.get(`/v1/customer/enterprise/credit/ledger/${ledgerId}`, {
    params: enterpriseTenantParams(tenantId),
  })
  return response.data.data as CreditLedgerDetail
}

export function enterpriseCreditLedgerExportUrl(view: CreditLedgerView = 'window', tenantId?: number) {
  const params = new URLSearchParams({ view })
  if (tenantId) params.set('tenant_id', String(tenantId))
  return `/api/v1/customer/enterprise/credit/ledger/export?${params.toString()}`
}

export async function getEnterpriseMonitor(tenantId?: number) {
  const response = await http.get('/v1/customer/enterprise/monitor', { params: enterpriseTenantParams(tenantId) })
  return response.data.data
}

export async function saveEnterpriseMonitor(payload: Record<string, unknown>) {
  const response = await http.put('/v1/customer/enterprise/monitor', payload)
  return response.data.data
}

export async function estimateEnterpriseMonitor() {
  const response = await http.post('/v1/customer/enterprise/monitor/estimate')
  return response.data.data
}

export async function estimateEnterpriseBrandWords(payload: Record<string, unknown>) {
  const response = await http.post('/v1/customer/enterprise/monitor/brand-words/estimate', payload)
  return response.data.data as { credits: number; group_count: number; region_count: number }
}

export async function saveEnterpriseBrandWords(payload: Record<string, unknown>) {
  const response = await http.put('/v1/customer/enterprise/monitor/brand-words', payload)
  return response.data.data
}

export async function saveEnterpriseCompetitor(payload: Record<string, unknown>) {
  const response = await http.post('/v1/customer/enterprise/monitor/competitors', payload)
  return response.data.data
}

export async function deleteEnterpriseCompetitor(competitorId: number) {
  const response = await http.delete(`/v1/customer/enterprise/monitor/competitors/${competitorId}`)
  return response.data.data
}

export async function createEnterpriseMember(payload: Record<string, unknown>) {
  const response = await http.post('/v1/customer/enterprise/members', payload)
  return response.data.data
}

export async function updateEnterpriseMember(identityId: number, payload: Record<string, unknown>) {
  const response = await http.put(`/v1/customer/enterprise/members/${identityId}`, payload)
  return response.data.data
}

export async function resetEnterpriseMemberPassword(identityId: number, password: string) {
  const response = await http.post(`/v1/customer/enterprise/members/${identityId}/password`, { password })
  return response.data.data
}

export async function deleteEnterpriseMember(identityId: number) {
  const response = await http.delete(`/v1/customer/enterprise/members/${identityId}`)
  return response.data.data
}

export async function getCreditTenants() {
  const response = await http.get('/v1/management/credit/tenants')
  return response.data.data as Array<Record<string, unknown>>
}

export async function getTenantMembers(tenantId: number) {
  const response = await http.get(`/v1/management/credit/tenants/${tenantId}/members`)
  return response.data.data as { items: Array<Record<string, unknown>> }
}

export function tenantCreditLedgerExportUrl(tenantId: number) {
  return `/api/v1/management/credit/tenants/${tenantId}/ledger/export`
}

export async function getEnterpriseMembers(tenantId?: number) {
  const response = await http.get('/v1/customer/enterprise/members', { params: enterpriseTenantParams(tenantId) })
  return response.data.data as {
    items: EnterpriseMemberItem[]
    positions: CustomerPositionOption[]
  }
}

export async function getEnterpriseAudit(page = 1, pageSize = 20, tenantId?: number) {
  const response = await http.get('/v1/customer/enterprise/audit', {
    params: { page, page_size: pageSize, ...enterpriseTenantParams(tenantId) },
  })
  return response.data.data
}

export async function getCurrentCreditTerms(tenantId?: number) {
  const response = await http.get('/v1/customer/enterprise/credit/terms/current', {
    params: enterpriseTenantParams(tenantId),
  })
  return response.data.data
}

export async function getCreditOpsSummary() {
  const response = await http.get('/v1/management/credit/ops-summary')
  return response.data.data
}

export async function listCreditPlatformLedger(
  page = 1,
  options?: { tenantName?: string },
) {
  const response = await http.get('/v1/management/credit/ledger', {
    params: {
      page,
      page_size: 20,
      tenant_name: options?.tenantName?.trim() || undefined,
    },
  })
  return response.data.data as { items: CreditLedgerItem[]; page: number; page_size: number }
}

export function creditPlatformLedgerExportUrl(options?: { tenantName?: string }) {
  const params = new URLSearchParams()
  const name = options?.tenantName?.trim()
  if (name) params.set('tenant_name', name)
  const q = params.toString()
  return `/api/v1/management/credit/ledger/export${q ? `?${q}` : ''}`
}

export async function getCreditPlatformLedgerDetail(tenantId: number, ledgerId: number) {
  const response = await http.get(`/v1/management/credit/tenants/${tenantId}/ledger/${ledgerId}`)
  return response.data.data as CreditLedgerDetail
}

export async function getCreditBlocks(blockReason?: string, page = 1) {
  // 2026-09-07 - 不传 block_reason 时拉全量拦截，原因列自行区分
  const params: Record<string, string | number> = { page, page_size: 20 }
  if (blockReason) params.block_reason = blockReason
  const response = await http.get('/v1/management/credit/blocks', { params })
  return response.data.data
}

export async function getTenantCredit(tenantId: number) {
  const response = await http.get(`/v1/management/credit/tenants/${tenantId}`)
  return response.data.data
}

export async function adjustTenantCredit(
  tenantId: number,
  payload: { amount?: number; yuan_amount?: number; reason: string },
) {
  const response = await http.post(`/v1/management/credit/tenants/${tenantId}/adjust`, payload)
  return response.data.data as { ledger_id: number; balance: number; credits?: number; yuan_amount?: number | null }
}

export async function getTenantCreditLedger(
  tenantId: number,
  page = 1,
  options?: { excludeInternal?: boolean },
) {
  const response = await http.get(`/v1/management/credit/tenants/${tenantId}/ledger`, {
    params: {
      page,
      page_size: 20,
      exclude_internal: options?.excludeInternal ? 1 : undefined,
    },
  })
  return response.data.data as { items: CreditLedgerItem[]; page: number; page_size: number }
}

export async function previewBillingModeSwitch(tenantId: number, target: 'hosted' | 'credit') {
  const response = await http.get(`/v1/management/credit/tenants/${tenantId}/billing-mode/preview`, { params: { target } })
  return response.data.data
}

export async function switchBillingMode(tenantId: number, payload: Record<string, unknown>) {
  const response = await http.post(`/v1/management/credit/tenants/${tenantId}/billing-mode/switch`, payload)
  return response.data.data as {
    id: number
    to_mode: string
    effective_policy: string
    status: string
    effective_at: string | null
  }
}

export async function cancelPendingBillingMode(tenantId: number) {
  const response = await http.post(`/v1/management/credit/tenants/${tenantId}/billing-mode/pending/cancel`)
  return response.data.data as { cancelled: number }
}

export async function getBillingModeHistory(tenantId: number) {
  const response = await http.get(`/v1/management/credit/tenants/${tenantId}/billing-mode/history`)
  return response.data.data as Array<{
    id: number
    from_mode: string
    to_mode: string
    reason: string
    effective_policy: string
    effective_at: string | null
    opening_credit_amount: number | null
    status: 'pending' | 'applied' | 'cancelled' | 'superseded' | string
    created_at: string
  }>
}

export async function releaseCreditReserve(tenantId: number, refId: string, reason?: string) {
  const response = await http.post('/v1/management/credit/release-reserve', {
    tenant_id: tenantId,
    ref_id: refId,
    reason,
  })
  return response.data.data
}

export async function getTenantOpenReserves(tenantId: number) {
  const response = await http.get(`/v1/management/credit/tenants/${tenantId}/reserves`)
  return response.data.data as Array<{
    ref_id: string
    amount: number
    window_key: string | null
    reason: string | null
    created_at: string
  }>
}

export async function updateTenantCreditPolicy(
  tenantId: number,
  payload: { credit_policy?: Record<string, unknown>; platform_whitelist?: string[] },
) {
  const response = await http.put(`/v1/management/credit/tenants/${tenantId}/policy`, payload)
  return response.data.data
}

export async function listCreditTerms() {
  const response = await http.get('/v1/management/credit/terms')
  return response.data.data
}

export async function publishCreditTerms(payload: Record<string, unknown>) {
  const response = await http.post('/v1/management/credit/terms', payload)
  return response.data.data
}

export interface CreditPriceRuleItem {
  id: number
  scope: string
  tenant_id: number | null
  tenant_name: string | null
  platform_code: string | null
  credits_per_subtask: number
  status: boolean
}

export async function listCreditPriceRules(scope?: 'global' | 'tenant', tenantId?: number) {
  const response = await http.get('/v1/management/credit/price-rules', {
    params: { scope, tenant_id: tenantId },
  })
  return response.data.data as CreditPriceRuleItem[]
}

export async function upsertCreditPriceRule(payload: {
  scope: 'global' | 'tenant'
  tenant_id?: number | null
  platform_code?: string | null
  credits_per_subtask: number
  status?: boolean
}) {
  const response = await http.put('/v1/management/credit/price-rules', payload)
  return response.data.data
}
