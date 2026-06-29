import { reactive } from 'vue'
import { withRetry } from '../../../composables/useRetry'
import type { IdentityType, MenuInfo } from '../../../services/auth'
import { getManagementMenus, getManagementPositions, getManagementRoles, type PositionInfo, type RoleInfo } from '../../../services/management'
import type { UserIdentityForm } from '../permissionGroups'

export function useAssignableOptions() {
  const assignMenus = reactive<Record<IdentityType, MenuInfo[]>>({ PLATFORM: [], CUSTOMER: [] })
  const roles = reactive<Record<IdentityType, RoleInfo[]>>({ PLATFORM: [], CUSTOMER: [] })
  const positions = reactive<Record<IdentityType, PositionInfo[]>>({ PLATFORM: [], CUSTOMER: [] })

  function defaultRoleForIdentityType(type: IdentityType) {
    return type === 'PLATFORM'
      ? (roles.PLATFORM.find(role => role.role_code === 'PLATFORM_OPERATOR')?.role_code || roles.PLATFORM[0]?.role_code || '')
      : (roles.CUSTOMER.find(role => role.role_code === 'TENANT_ADMIN')?.role_code || roles.CUSTOMER[0]?.role_code || '')
  }

  function applyPositionToConfig(type: IdentityType, form: UserIdentityForm & { username?: string; password?: string }, positionId: number | null) {
    const config = form.identity_configs[type]
    config.position_id = positionId
    const position = positions[type].find(item => item.id === positionId)
    if (!position) return
    config.role_code = position.role_code
    config.identity_name = position.position_name
    config.menu_ids = position.menu_ids.length ? [...position.menu_ids] : assignMenus[type].map(item => item.id)
  }

  async function loadAssignableOptions(tenants: { id: number }[], userForm: UserIdentityForm & { username?: string; password?: string }) {
    const [platformMenus, platformRoles, platformPositions, customerMenus, customerRoles, customerPositions] = await Promise.all([
      withRetry(() => getManagementMenus('PLATFORM')),
      withRetry(() => getManagementRoles('PLATFORM')),
      withRetry(() => getManagementPositions('PLATFORM')),
      withRetry(() => getManagementMenus('CUSTOMER')),
      withRetry(() => getManagementRoles('CUSTOMER')),
      withRetry(() => getManagementPositions('CUSTOMER')),
    ])
    assignMenus.PLATFORM = platformMenus
    assignMenus.CUSTOMER = customerMenus
    roles.PLATFORM = platformRoles
    roles.CUSTOMER = customerRoles
    positions.PLATFORM = platformPositions
    positions.CUSTOMER = customerPositions
    if (!userForm.identity_configs.PLATFORM.role_code) userForm.identity_configs.PLATFORM.role_code = defaultRoleForIdentityType('PLATFORM')
    if (!userForm.identity_configs.CUSTOMER.role_code) userForm.identity_configs.CUSTOMER.role_code = defaultRoleForIdentityType('CUSTOMER')
    if (!userForm.identity_configs.PLATFORM.position_id) applyPositionToConfig('PLATFORM', userForm, platformPositions[0]?.id || null)
    if (!userForm.identity_configs.CUSTOMER.position_id) applyPositionToConfig('CUSTOMER', userForm, customerPositions[0]?.id || null)
    if (!userForm.identity_configs.PLATFORM.menu_ids.length) userForm.identity_configs.PLATFORM.menu_ids = platformMenus.map(item => item.id)
    if (!userForm.identity_configs.CUSTOMER.menu_ids.length) userForm.identity_configs.CUSTOMER.menu_ids = customerMenus.map(item => item.id)
    if (!userForm.identity_configs.CUSTOMER.tenant_id && tenants[0]) userForm.identity_configs.CUSTOMER.tenant_id = tenants[0].id
  }

  async function refreshPositions() {
    positions.PLATFORM = await withRetry(() => getManagementPositions('PLATFORM'))
    positions.CUSTOMER = await withRetry(() => getManagementPositions('CUSTOMER'))
  }

  return {
    assignMenus,
    roles,
    positions,
    defaultRoleForIdentityType,
    applyPositionToConfig,
    loadAssignableOptions,
    refreshPositions,
  }
}

export type AssignableOptions = ReturnType<typeof useAssignableOptions>
