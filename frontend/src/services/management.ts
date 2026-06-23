import { http } from './http'
import type { IdentityType, MenuInfo } from './auth'

export interface RoleInfo {
  id: number
  role_code: string
  role_name: string
  identity_type: IdentityType
  data_scope: string
}

export interface TenantInfo {
  id: number
  name: string
  code: string
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
    tenant_id: number | null
    tenant_name: string | null
    menu_ids: number[]
  }>
}

export interface CreateUserPayload {
  username: string
  password: string
  display_name: string
  identities: Array<{
    identity_type: IdentityType
    role_code: string
    identity_name: string
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

export async function getTenants(): Promise<TenantInfo[]> {
  const response = await http.get('/v1/management/tenants')
  return response.data.data
}

export async function createTenant(payload: { name: string; code?: string | null }): Promise<TenantInfo> {
  const response = await http.post('/v1/management/tenants', payload)
  return response.data.data
}

export async function deleteTenant(tenantId: number): Promise<void> {
  await http.delete(`/v1/management/tenants/${tenantId}`)
}

export interface ManagedUserQuery {
  keyword?: string
  tenant_id?: number | null
  identity_type?: IdentityType | ''
  enabled?: boolean | null
  deleted?: boolean
}

export async function getManagedUsers(params?: ManagedUserQuery): Promise<ManagedUser[]> {
  const response = await http.get('/v1/management/users', { params })
  return response.data.data
}

export async function createManagedUser(payload: CreateUserPayload): Promise<void> {
  await http.post('/v1/management/users', payload)
}

export type UpdateUserPayload = Omit<CreateUserPayload, 'username' | 'password'>

export async function updateManagedUser(userId: number, payload: UpdateUserPayload): Promise<void> {
  await http.put(`/v1/management/users/${userId}`, payload)
}

export async function resetManagedUserPassword(userId: number, password: string): Promise<void> {
  await http.patch(`/v1/management/users/${userId}/password`, { password })
}

export async function setManagedUserStatus(userId: number, enabled: boolean): Promise<void> {
  await http.patch(`/v1/management/users/${userId}/status`, null, { params: { enabled } })
}

export async function deleteManagedUser(userId: number): Promise<void> {
  await http.delete(`/v1/management/users/${userId}`)
}

export async function restoreManagedUser(userId: number): Promise<void> {
  await http.patch(`/v1/management/users/${userId}/restore`)
}
