import { http, type GeoHttpRequestConfig } from './http'

export type IdentityType = 'PLATFORM' | 'CUSTOMER'

export interface IdentityInfo {
  id: number
  identity_type: IdentityType
  identity_name: string
  role_code: string
  position_id: number | null
  position_name: string | null
  position_code?: string | null
  tenant_id: number | null
  tenant_name: string | null
  tenant_has_logo?: boolean
  tenant_logo_updated_at?: string | null
  is_default: boolean
}

export interface UserInfo {
  id: number
  username: string
  display_name: string
  must_change_password?: boolean
  phone_masked?: string | null
  phone_login_enabled?: boolean
  can_bind_phone?: boolean
  created_at?: string | null
}

export interface MenuInfo {
  id: number
  menu_code: string
  menu_name: string
  identity_type: IdentityType
  route_path: string
  icon: string
  sort_order: number
  can_create: boolean
  can_update: boolean
  can_delete: boolean
  can_export: boolean
  show_in_sidebar?: boolean
}

export interface AuthSession {
  access_token?: string
  token_type?: string
  user: UserInfo
  identity: IdentityInfo
  identities: IdentityInfo[]
  menus: MenuInfo[]
  /** 有平台范围编辑权时生效；空数组=不可勾任何端 */
  allowed_monitor_platforms?: string[]
  /** 算力自助客户监测数据含今日；托管客户为 false */
  customer_includes_today?: boolean
}

export interface LoginResult {
  requires_identity_selection: boolean
  ticket?: string
  user?: UserInfo
  identities?: IdentityInfo[]
  session?: AuthSession
}

export async function loginApi(username: string, password: string): Promise<LoginResult> {
  const response = await http.post('/v1/auth/login', { username, password })
  return response.data.data
}

export async function checkResetApi(username: string): Promise<{ phone_masked: string }> {
  const response = await http.post('/v1/auth/password/reset-check', { username })
  return response.data.data
}

export async function sendResetCodeApi(username: string): Promise<{ sent: boolean; phone_masked?: string; dev_code?: string }> {
  const response = await http.post('/v1/auth/password/reset-code', { username })
  return response.data.data
}

export async function resetPasswordApi(username: string, code: string, newPassword: string): Promise<void> {
  await http.post('/v1/auth/password/reset', {
    username,
    code,
    new_password: newPassword,
  })
}

export async function sendLoginCodeApi(phone: string): Promise<{ sent: boolean; dev_code?: string }> {
  const response = await http.post('/v1/auth/sms/login-code', { phone })
  return response.data.data
}

export async function smsLoginApi(phone: string, code: string): Promise<LoginResult> {
  const response = await http.post('/v1/auth/sms/login', { phone, code })
  return response.data.data
}

export async function sendPhoneCodeApi(purpose: 'bind' | 'change_old' | 'change_new' | 'password', phone?: string): Promise<{ sent: boolean; dev_code?: string }> {
  const response = await http.post('/v1/auth/phone/code', { purpose, phone: phone || null })
  return response.data.data
}

export async function bindPhoneApi(phone: string, code: string): Promise<UserInfo> {
  const response = await http.post('/v1/auth/phone/bind', { phone, code })
  return response.data.data
}

export async function setPhoneLoginApi(enabled: boolean): Promise<UserInfo> {
  const response = await http.post('/v1/auth/phone/login-enabled', { enabled })
  return response.data.data
}

export async function changePhoneApi(oldCode: string, newPhone: string, newCode: string): Promise<UserInfo> {
  const response = await http.post('/v1/auth/phone/change', {
    old_code: oldCode,
    new_phone: newPhone,
    new_code: newCode,
  })
  return response.data.data
}

/** 2026-09-01 - H5 落地页一键体验观察号（免密） */
export async function demoObserverLoginApi(): Promise<LoginResult> {
  // 2026-09-02 - vue-tsc 不认 silentError - 与 announcements 一样走 GeoHttpRequestConfig
  const response = await http.post('/v1/auth/demo/observer', null, { silentError: true } as GeoHttpRequestConfig)
  return response.data.data
}

export async function selectIdentityApi(ticket: string, identityId: number): Promise<AuthSession> {
  const response = await http.post('/v1/auth/select-identity', { ticket, identity_id: identityId })
  return response.data.data
}

export async function switchIdentityApi(identityId: number): Promise<AuthSession> {
  const response = await http.post('/v1/auth/switch-identity', { identity_id: identityId })
  return response.data.data
}

export async function meApi(): Promise<Omit<AuthSession, 'access_token' | 'token_type'>> {
  // 2026-09-02 - Portal 自处理刷新失败 - 避免与「会话已失效」叠 500 toast
  const response = await http.get('/v1/auth/me', { silentError: true } as GeoHttpRequestConfig)
  return response.data.data
}

/** Sliding renew: extends idle cookie TTL; polling must not call this. */
export async function refreshSessionApi(): Promise<void> {
  await http.post('/v1/auth/refresh', null, {
    silentError: true,
    skipLoading: true,
  } as GeoHttpRequestConfig)
}

export async function logoutApi(): Promise<void> {
  await http.post('/v1/auth/logout')
}

export async function changePasswordApi(code: string, newPassword: string): Promise<void> {
  await http.post('/v1/auth/change-password', {
    code,
    new_password: newPassword,
  })
}
