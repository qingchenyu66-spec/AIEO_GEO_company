// import { http } from './http'
import type { IdentityType, MenuInfo } from './auth'
import { http, invalidateCache } from './http'

export interface RoleInfo {
  id: number
  role_code: string
  role_name: string
  identity_type: IdentityType
  data_scope: string
}

export interface PositionInfo {
  id: number
  position_code: string
  position_name: string
  identity_type: IdentityType
  role_code: string
  description: string | null
  menu_ids: number[]
  menu_grants?: MenuGrantInfo[]
  allowed_monitor_platforms?: string[]
}

export interface MenuGrantInfo {
  menu_id: number
  menu_code?: string
  can_create: boolean
  can_update: boolean
  can_delete: boolean
  can_export: boolean
}

export interface TenantInfo {
  id: number
  name: string
  code: string
  status: boolean
  owner_user_id: number | null
  owner_display_name?: string | null
  owner_username?: string | null
  stop_reason: 'manual' | 'canceled' | 'expired' | null
  stopped_at: string | null
  stopped_by: number | null
  service_start_date: string | null
  service_end_date: string | null
  /** 与监测计划联动的每日执行次数；无品牌资产时为 null */
  schedule_frequency?: number | null
  /** 创建时：名称命中软删企业，已允许新建 */
  name_was_purged?: boolean
  has_logo?: boolean
  goods_card_enabled?: boolean
  logo_updated_at?: string | null
  billing_mode?: 'hosted' | 'credit'
  credit_balance?: number | null
  credit_reserved?: number | null
}

/** 与企业管理「服务中」口径一致：启用、非人工停服/取消，且在服务期内 */
export function isTenantInService(tenant: TenantInfo): boolean {
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

export interface TenantSalesOwner {
  id: number
  username: string
  display_name: string
  status: boolean
}

export interface ManagedUser {
  id: number
  username: string
  display_name: string
  status: boolean
  deleted: boolean
  created_by: number | null
  identities: Array<{
    id: number
    identity_type: IdentityType
    identity_name: string
    role_code: string
    position_id: number | null
    tenant_id: number | null
    tenant_name: string | null
    menu_ids: number[]
  }>
}

export interface OperationLogRecord {
  id: number
  operator_name: string
  action_type: string
  description: string
  risk_level: string
  ip_address: string | null
  target_module?: string | null
  tenant_id?: number | null
  tenant_name?: string | null
  created_at: string
}


// ... existing code ...

export interface SystemConfigRecord {
  id: number
  config_key: string
  config_name: string
  config_value: string
  category?: string
  scope: string
  value_type?: 'str' | 'int' | 'float' | 'bool'
  secret?: boolean
  status: string
  remark: string | null
  updated_at: string
}

export type SystemConfigCategory = 'secrets' | 'schedule' | 'cache_queue' | 'notification' | 'menu'

export interface MenuConfigRecord {
  id: number
  menu_code: string
  menu_name: string
  identity_type: 'PLATFORM' | 'CUSTOMER'
  sort_order: number
  is_visible: boolean
  show_in_sidebar?: boolean
  icon: string | null
  route_path: string | null
  remark: string | null
}

export interface MolizhishuBalance {
  available: boolean
  current_balance: number | null
  current_balance_text: string | null
  fetched_at: string
  error: string | null
}

export interface DeepseekBalance extends MolizhishuBalance {
  currency?: string | null
  is_available?: boolean | null
  display_value?: string | null
}

export interface PlatformOverview {
  kpis: {
    today_tasks: number
    today_completed_tasks: number
    today_failed_tasks: number
    today_cost: number
    active_tenants: number
    expiring_tenants: number
    api_success_rate: number
  }
  service_counts: Record<string, number>
  expiring_tenants: Array<{ id: number; name: string; service_end_date: string; days_left: number }>
  platform_stats: Array<{ platform: string; total: number; completed: number; failed: number; cost: number; success_rate: number }>
  cost_ranking: Array<{ tenant_id: number | null; lead_diagnosis_id?: number | null; tenant_name: string; cost: number }>
  quota_overview: {
    used_amount: number
    today_amount: number
    estimated_month_amount: number
    total_subtasks: number
    avg_cost_per_subtask: number
  }
  customer_data: {
    tenant_total: number
    active_tenants: number
    task_total: number
    subtask_total: number
    mention_rate: number
    source_count: number
  }
  recent_tasks: Array<{
    task_id: string
    tenant_name: string
    monitor_keywords: string | null
    status: string
    total_items: number
    completed_items: number
    failed_items: number
    created_at: string
    last_error: string | null
  }>
  alerts: Array<{ title: string; value: number; level: string }>
  todo_items: Array<{ type: string; title: string; count: number; level: string }>
  operation_logs: OperationLogRecord[]
  system_health: Array<{ name: string; status: string; detail: string }>
  molizhishu_balance?: MolizhishuBalance
  deepseek_balance?: DeepseekBalance
  credit_summary?: {
    credit_tenant_count: number
    credit_total_balance: number
    credit_today_deduct: number
    zero_balance_count: number
    blocks_24h: number
    tenant_credit_blocks_24h: number
    platform_balance_blocks_24h: number
    runway_windows: number | null
    runway_low?: boolean
    platform_balance_low?: boolean
    next_window_estimate?: { subtask_count?: number; estimated_yuan?: number; window_key?: string }
  }
}

export interface CreateUserPayload {
  username: string
  password: string
  display_name: string
  identities: Array<{
    identity_type: IdentityType
    role_code: string
    identity_name?: string | null
    position_id?: number | null
    tenant_id: number | null
    tenant_name: string | null
    menu_ids: number[]
  }>
}

export async function getManagementMenus(identityType: IdentityType): Promise<MenuInfo[]> {
  const response = await http.get('/v1/management/menus', { params: { identity_type: identityType } })
  return response.data.data
}

export async function getManagementRoles(identityType: IdentityType): Promise<RoleInfo[]> {
  const response = await http.get('/v1/management/roles', { params: { identity_type: identityType } })
  return response.data.data
}

export async function getManagementPositions(identityType: IdentityType): Promise<PositionInfo[]> {
  const response = await http.get('/v1/management/positions', { params: { identity_type: identityType } })
  return response.data.data
}

export interface PositionPayload {
  position_name: string
  identity_type: IdentityType
  role_code: string
  description?: string | null
  menu_ids?: number[]
  menu_grants?: MenuGrantInfo[]
  allowed_monitor_platforms?: string[]
  status: boolean
}

export async function createManagementPosition(payload: PositionPayload): Promise<PositionInfo> {
  const response = await http.post('/v1/management/positions', payload)
  invalidateCache('/v1/management/positions')
  return response.data.data
}

export async function updateManagementPosition(positionId: number, payload: PositionPayload): Promise<PositionInfo> {
  const response = await http.put(`/v1/management/positions/${positionId}`, payload)
  invalidateCache('/v1/management/positions')
  return response.data.data
}

export async function deleteManagementPosition(positionId: number): Promise<void> {
  await http.delete(`/v1/management/positions/${positionId}`)
  invalidateCache('/v1/management/positions')
}

export async function getTenants(): Promise<TenantInfo[]> {
  const response = await http.get('/v1/management/tenants')
  return response.data.data
}

export interface CustomerPreviewMeta {
  menus: MenuInfo[]
  customer_includes_today: boolean
}

export async function getTenantCustomerPreviewMenus(tenantId: number): Promise<CustomerPreviewMeta> {
  const response = await http.get(`/v1/management/tenants/${tenantId}/customer-preview-menus`)
  const data = response.data.data
  if (Array.isArray(data)) {
    return { menus: data, customer_includes_today: false }
  }
  return {
    menus: (data?.menus || []) as MenuInfo[],
    customer_includes_today: Boolean(data?.customer_includes_today),
  }
}

export async function uploadTenantLogo(tenantId: number, file: File): Promise<{ tenant_id: number; has_logo: boolean; logo_updated_at: string | null }> {
  const form = new FormData()
  form.append('file', file)
  const response = await http.post(`/v1/management/tenants/${tenantId}/logo`, form)
  invalidateCache('/v1/management/tenants')
  return response.data.data
}

export function tenantLogoUrl(tenantId: number, logoUpdatedAt?: string | null): string {
  const query = logoUpdatedAt ? `?v=${encodeURIComponent(logoUpdatedAt)}` : ''
  return `/api/v1/management/tenants/${tenantId}/logo${query}`
}

export type PlatformLogoMeta = { has_logo: boolean; logo_updated_at: string | null }

export async function getPlatformLogoMeta(): Promise<PlatformLogoMeta> {
  const response = await http.get('/v1/management/platform-brand/logo/meta')
  return response.data.data as PlatformLogoMeta
}

export function platformLogoUrl(logoUpdatedAt?: string | null): string {
  const query = logoUpdatedAt ? `?v=${encodeURIComponent(logoUpdatedAt)}` : ''
  return `/api/v1/management/platform-brand/logo${query}`
}

export async function uploadPlatformLogo(file: File): Promise<PlatformLogoMeta> {
  const form = new FormData()
  form.append('file', file)
  const response = await http.post('/v1/management/platform-brand/logo', form)
  return response.data.data as PlatformLogoMeta
}

export async function clearPlatformLogo(): Promise<PlatformLogoMeta> {
  const response = await http.delete('/v1/management/platform-brand/logo')
  return response.data.data as PlatformLogoMeta
}

export async function getOperationLogs(): Promise<OperationLogRecord[]> {
  const response = await http.get('/v1/management/operation-logs')
  return response.data.data
}

export async function getSystemConfigs(category?: SystemConfigCategory): Promise<SystemConfigRecord[]> {
  const params = category && category !== 'menu' ? { category } : {}
  const response = await http.get('/v1/management/system-configs', { params })
  return response.data.data
}

export async function updateSystemConfig(configId: number, configValue: string): Promise<SystemConfigRecord> {
  const response = await http.put(`/v1/management/system-configs/${configId}`, { config_value: configValue })
  invalidateCache('/v1/management/system-configs')
  return response.data.data
}

export async function getMenuConfigs(identityType?: string): Promise<MenuConfigRecord[]> {
  const response = await http.get('/v1/management/menus/config', {
    params: identityType ? { identity_type: identityType } : undefined
  })
  return response.data.data
}

export async function updateMenuConfig(configId: number, payload: Partial<MenuConfigRecord>): Promise<MenuConfigRecord> {
  const response = await http.put(`/v1/management/menus/config/${configId}`, payload)
  return response.data.data
}

export async function deleteMenuConfig(configId: number): Promise<void> {
  await http.delete(`/v1/management/menus/config/${configId}`)
}

export async function batchUpdateMenuConfigs(configs: Array<{ id: number; menu_name?: string; sort_order?: number; is_visible?: boolean; show_in_sidebar?: boolean }>): Promise<void> {
  await http.post('/v1/management/menus/config/batch-update', configs)
}

export async function getPlatformOverview(): Promise<PlatformOverview> {
  const response = await http.get('/v1/management/overview')
  return response.data.data
}

/** 监测按日消耗日历；DeepSeek 无官方日流水 */
export interface QuotaDailyCostDay {
  date: string
  amount: number
  subtask_count: number
  heat: number
}

export interface QuotaDailyCost {
  year: number
  month: number
  month_label: string
  source: string
  source_label: string
  deepseek_note: string
  days_in_month: number
  first_weekday: number
  month_total: number
  max_amount: number
  days: QuotaDailyCostDay[]
}

export async function getQuotaDailyCost(year?: number, month?: number): Promise<QuotaDailyCost> {
  const response = await http.get('/v1/management/quota-daily-cost', {
    params: {
      ...(year != null ? { year } : {}),
      ...(month != null ? { month } : {}),
    },
  })
  return response.data.data
}

export async function checkTenantNameAvailable(name: string): Promise<void> {
  await http.get('/v1/management/tenants/name-check', { params: { name } })
}

export async function createTenant(payload: {
  name: string
  code?: string | null
  service_start_date?: string | null
  service_end_date?: string | null
  billing_mode?: 'hosted' | 'credit'
  opening_credit_amount?: number | null
}): Promise<unknown> {
  const response = await http.post('/v1/management/tenants', payload)
  invalidateCache('/v1/management/tenants')
  return response.data.data
}

// 2026-09-04 - 商品卡开关走租户更新 - payload 补 goods_card_enabled，否则 vue-tsc 拦构建
export async function updateTenant(tenantId: number, payload: { name: string; code?: string | null; service_start_date?: string | null; service_end_date?: string | null; status: boolean; goods_card_enabled?: boolean }): Promise<TenantInfo> {
  const response = await http.put(`/v1/management/tenants/${tenantId}`, payload)
  invalidateCache('/v1/management/tenants')
  return response.data.data
}

export async function deleteTenant(tenantId: number): Promise<void> {
  await http.delete(`/v1/management/tenants/${tenantId}`)
  invalidateCache('/v1/management/tenants')
}

export async function purgeTenant(tenantId: number, confirmName: string): Promise<Record<string, unknown>> {
  const response = await http.post(`/v1/management/tenants/${tenantId}/purge`, { confirm_name: confirmName })
  invalidateCache('/v1/management/tenants')
  return response.data.data
}

export async function restoreTenant(tenantId: number): Promise<unknown> {
  const response = await http.patch(`/v1/management/tenants/${tenantId}/restore`)
  invalidateCache('/v1/management/tenants')
  return response.data.data
}

export async function listTenantSalesOwners(): Promise<TenantSalesOwner[]> {
  const response = await http.get('/v1/management/tenant-sales-owners')
  return response.data.data
}

export async function transferTenantOwner(tenantId: number, ownerUserId: number): Promise<TenantInfo> {
  const response = await http.patch(`/v1/management/tenants/${tenantId}/owner`, { owner_user_id: ownerUserId })
  invalidateCache('/v1/management/tenants')
  return response.data.data
}

export interface ManagedUserQuery {
  keyword?: string
  tenant_id?: number | null
  identity_type?: IdentityType | ''
  position_id?: number | null
  enabled?: boolean | null
  deleted?: boolean
}

export async function getManagedUsers(params?: ManagedUserQuery): Promise<ManagedUser[]> {
  const response = await http.get('/v1/management/users', { params })
  return response.data.data
}

export async function createManagedUser(payload: CreateUserPayload): Promise<unknown> {
  const response = await http.post('/v1/management/users', payload)
  invalidateCache('/v1/management/users')
  return response.data.data
}

export type UpdateUserPayload = Omit<CreateUserPayload, 'username' | 'password'> & {
  /** Explicit soft-delete; omitted identities are kept (PATCH semantics). */
  remove_identity_types?: IdentityType[]
}

export async function updateManagedUser(userId: number, payload: UpdateUserPayload): Promise<unknown> {
  const response = await http.put(`/v1/management/users/${userId}`, payload)
  invalidateCache('/v1/management/users')
  return response.data.data
}

export async function resetManagedUserPassword(userId: number, password: string): Promise<void> {
  await http.patch(`/v1/management/users/${userId}/password`, { password })
  invalidateCache('/v1/management/users')
}

export async function setManagedUserStatus(userId: number, enabled: boolean): Promise<void> {
  await http.patch(`/v1/management/users/${userId}/status`, null, { params: { enabled } })
  invalidateCache('/v1/management/users')
}

export async function deleteManagedUser(userId: number): Promise<void> {
  await http.delete(`/v1/management/users/${userId}`)
  invalidateCache('/v1/management/users')
}

export async function restoreManagedUser(userId: number): Promise<void> {
  await http.patch(`/v1/management/users/${userId}/restore`)
  invalidateCache('/v1/management/users')
}
