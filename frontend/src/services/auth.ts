import { http } from './http'

export type IdentityType = 'PLATFORM' | 'CUSTOMER'

export interface IdentityInfo {
  id: number
  identity_type: IdentityType
  identity_name: string
  role_code: string
  position_id: number | null
  position_name: string | null
  tenant_id: number | null
  tenant_name: string | null
  is_default: boolean
}

export interface UserInfo {
  id: number
  username: string
  display_name: string
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
}

export interface AuthSession {
  access_token: string
  token_type: string
  user: UserInfo
  identity: IdentityInfo
  identities: IdentityInfo[]
  menus: MenuInfo[]
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

export async function selectIdentityApi(ticket: string, identityId: number): Promise<AuthSession> {
  const response = await http.post('/v1/auth/select-identity', { ticket, identity_id: identityId })
  return response.data.data
}

export async function switchIdentityApi(identityId: number): Promise<AuthSession> {
  const response = await http.post('/v1/auth/switch-identity', { identity_id: identityId })
  return response.data.data
}

export async function meApi(): Promise<Omit<AuthSession, 'access_token' | 'token_type'>> {
  const response = await http.get('/v1/auth/me')
  return response.data.data
}
