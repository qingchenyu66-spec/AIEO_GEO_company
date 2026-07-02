import type { IdentityType, MenuInfo } from '../../services/auth'
import {
  POSITION_MENU,
  USER_CREATE_CUSTOMER_MENU,
  USER_CREATE_PLATFORM_MENU,
  USER_LIST_MENU,
} from './constants'
import { permissionGroupKey, permissionGroupNote, permissionGroupTitle } from './permissionGroups'

export type PermissionAction = 'can_export' | 'can_create' | 'can_update' | 'can_delete'

export const PERMISSION_ACTION_LABELS: Record<PermissionAction, string> = {
  can_export: '查看',
  can_create: '新增',
  can_update: '编辑',
  can_delete: '删除',
}

const MENU_ACTIONS: Record<string, PermissionAction[]> = {
  'platform.dashboard': ['can_export'],

  'platform.audit.list': ['can_export'],
  'platform.audit.profile': ['can_export', 'can_update'],
  'platform.audit.keywords': ['can_export', 'can_update'],
  'platform.audit.models': ['can_export', 'can_update'],
  'platform.audit.schedule': ['can_export', 'can_update'],
  'platform.audit.competitors': ['can_export', 'can_update'],
  'platform.audit.files': ['can_export'],

  'platform.competitor': ['can_export'],
  'platform.sources': ['can_export'],
  'platform.diagnosis': ['can_export'],
  'platform.lead_diagnosis': ['can_export', 'can_create'],
  'platform.reports': ['can_export', 'can_create', 'can_update'],

  'platform.plans': ['can_export'],
  'platform.admins': ['can_export'],
  'platform.models': ['can_export'],
  'platform.alerts': ['can_export', 'can_update'],
  'platform.logs': ['can_export'],
  'platform.settings': ['can_export', 'can_update'],

  [USER_LIST_MENU]: ['can_export', 'can_update', 'can_delete'],
  [USER_CREATE_PLATFORM_MENU]: ['can_create'],
  [USER_CREATE_CUSTOMER_MENU]: ['can_create'],
  [POSITION_MENU]: ['can_export', 'can_update', 'can_delete'],

  'customer.workspace': ['can_export'],
  'customer.realtime': ['can_export'],
  'customer.links': ['can_export'],
  'customer.diagnosis': ['can_export'],
  'customer.competitor': ['can_export'],
  'customer.sources': ['can_export'],
  'customer.reports': ['can_export'],
  'customer.knowledge': ['can_export', 'can_create', 'can_update'],
}

const MENU_ACTION_LABELS: Record<string, Partial<Record<PermissionAction, string>>> = {
  'platform.audit.profile': { can_export: '查看', can_update: '编辑资料' },
  'platform.audit.keywords': { can_export: '查看', can_update: '编辑监测词' },
  'platform.audit.models': { can_export: '查看', can_update: '编辑平台范围' },
  'platform.audit.schedule': { can_export: '查看', can_update: '编辑监控计划' },
  'platform.audit.competitors': { can_export: '查看', can_update: '编辑竞品' },
  'platform.lead_diagnosis': { can_export: '查看/导出 PDF', can_create: '新建诊断' },
  'platform.reports': { can_export: '查看/导出', can_create: '生成报告', can_update: '编辑/发布' },
  'platform.alerts': { can_export: '查看', can_update: '配置规则' },
  'platform.settings': { can_export: '查看', can_update: '修改配置' },
  [USER_LIST_MENU]: { can_export: '查看', can_update: '编辑', can_delete: '禁用/删除' },
  [USER_CREATE_PLATFORM_MENU]: { can_create: '创建平台账号' },
  [USER_CREATE_CUSTOMER_MENU]: { can_create: '创建客户账号' },
  [POSITION_MENU]: { can_export: '查看', can_update: '编辑', can_delete: '停用' },
  'customer.knowledge': { can_export: '查看', can_create: '上传文件', can_update: '管理文件' },
  'customer.reports': { can_export: '查看/导出' },
}

export type MenuGrantFlags = Record<PermissionAction, boolean>

export type MenuGrantState = Record<number, MenuGrantFlags>

export const ROUTE_ONLY_MENU_CODES = new Set(['platform.audit', 'platform.users'])

const HIDDEN_ASSIGNABLE = new Set([
  'customer.assets',
  'customer.batch',
  'customer.geo',
  'customer.sentiment',
  'platform.sentiment',
])

function emptyGrant(): MenuGrantFlags {
  return { can_export: false, can_create: false, can_update: false, can_delete: false }
}

export function createEmptyGrantState(): MenuGrantState {
  return {}
}

export function assignablePermissionMenus(type: IdentityType, menus: MenuInfo[]) {
  return menus.filter(menu => (
    menu.identity_type === type
    && !ROUTE_ONLY_MENU_CODES.has(menu.menu_code)
    && !HIDDEN_ASSIGNABLE.has(menu.menu_code)
  ))
}

export function actionsForMenu(menuCode: string, type: IdentityType): PermissionAction[] {
  if (MENU_ACTIONS[menuCode]) return MENU_ACTIONS[menuCode]
  if (menuCode.startsWith('platform.audit.')) {
    return menuCode === 'platform.audit.list' ? ['can_export'] : ['can_export', 'can_update']
  }
  if (type === 'CUSTOMER') return ['can_export']
  return ['can_export']
}

export function actionLabelForMenu(menuCode: string, action: PermissionAction): string {
  return MENU_ACTION_LABELS[menuCode]?.[action] || PERMISSION_ACTION_LABELS[action]
}

export function grantHasAccess(grant: Partial<MenuGrantFlags>) {
  return Boolean(grant.can_export || grant.can_create || grant.can_update || grant.can_delete)
}

export function grantsFromPosition(
  menus: MenuInfo[],
  menuGrants: Array<{ menu_id: number; can_create?: boolean; can_update?: boolean; can_delete?: boolean; can_export?: boolean }>,
): MenuGrantState {
  const state = createEmptyGrantState()
  for (const menu of menus) {
    state[menu.id] = emptyGrant()
  }
  for (const grant of menuGrants) {
    state[grant.menu_id] = {
      can_create: Boolean(grant.can_create),
      can_update: Boolean(grant.can_update),
      can_delete: Boolean(grant.can_delete),
      can_export: Boolean(grant.can_export),
    }
  }
  return state
}

export function grantsToPayload(state: MenuGrantState, menus: MenuInfo[]) {
  return menus
    .map(menu => ({
      menu_id: menu.id,
      menu_code: menu.menu_code,
      ...state[menu.id],
    }))
    .filter(item => grantHasAccess(item))
}

export function countActiveGrants(state: MenuGrantState) {
  return Object.values(state).filter(grantHasAccess).length
}

export function summarizeGrant(menu: MenuInfo, grant: MenuGrantFlags | undefined) {
  if (!grant || !grantHasAccess(grant)) return null
  const actions = actionsForMenu(menu.menu_code, menu.identity_type as IdentityType)
  return actions
    .filter(action => grant[action])
    .map(action => actionLabelForMenu(menu.menu_code, action))
    .join('、')
}

export function permissionModulesFor(type: IdentityType, menus: MenuInfo[]) {
  const assignable = assignablePermissionMenus(type, menus)
  const buckets: Record<string, MenuInfo[]> = {}
  for (const menu of assignable) {
    const key = permissionGroupKey(menu)
    if (!buckets[key]) buckets[key] = []
    buckets[key].push(menu)
  }
  const order = type === 'PLATFORM'
    ? ['dashboard', 'audit', 'analysis', 'users', 'diagnosis', 'system', 'other']
    : ['workspace', 'monitor', 'analysis', 'knowledge', 'other']
  return order
    .filter(key => buckets[key]?.length)
    .map(key => ({
      key,
      title: permissionGroupTitle(type, key),
      note: permissionGroupNote(type, key),
      menus: buckets[key].sort((a, b) => a.sort_order - b.sort_order || a.id - b.id),
    }))
}
