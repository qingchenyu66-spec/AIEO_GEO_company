import type { IdentityType, MenuInfo } from '../../services/auth'
import {
  POSITION_MENU,
  SETTINGS_CACHE_QUEUE_MENU,
  SETTINGS_MENU,
  SETTINGS_MENU_PERM,
  SETTINGS_NOTIFICATION_MENU,
  SETTINGS_SCHEDULE_MENU,
  SETTINGS_SECRETS_MENU,
  USER_CREATE_CUSTOMER_MENU,
  USER_CREATE_MENU,
  USER_CREATE_PLATFORM_MENU,
  USER_LIST_MENU,
  hiddenPlatformMenus,
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

  'platform.audit.list': ['can_export', 'can_update', 'can_delete'],
  'platform.audit.profile': ['can_export', 'can_update'],
  'platform.audit.regions': ['can_export', 'can_update'],
  'platform.audit.keywords': ['can_export', 'can_update'],
  // 2026-07-30 - 平台范围按职位多选，不再用查看/编辑总开关
  'platform.audit.models': [],
  'platform.audit.purge': ['can_delete'],
  'platform.audit.schedule': ['can_export', 'can_update'],
  'platform.audit.competitors': ['can_export', 'can_update'],
  'platform.audit.files': ['can_export'],

  'platform.competitor': ['can_export'],
  'platform.sources': ['can_export'],
  'platform.lead_diagnosis': ['can_export', 'can_create'],
  'platform.snapshot_backfill': ['can_export', 'can_update'],
  'platform.reports': ['can_export', 'can_create'],

  'platform.models': ['can_export'],
  'platform.alerts': ['can_export', 'can_update'],
  'platform.logs': ['can_export'],
  [SETTINGS_SECRETS_MENU]: ['can_export', 'can_update'],
  [SETTINGS_SCHEDULE_MENU]: ['can_export', 'can_update'],
  [SETTINGS_CACHE_QUEUE_MENU]: ['can_export', 'can_update'],
  [SETTINGS_NOTIFICATION_MENU]: ['can_export', 'can_update'],
  [SETTINGS_MENU_PERM]: ['can_export', 'can_update'],

  [USER_LIST_MENU]: ['can_export', 'can_update', 'can_delete'],
  [USER_CREATE_PLATFORM_MENU]: ['can_create'],
  [USER_CREATE_CUSTOMER_MENU]: ['can_create'],
  [POSITION_MENU]: ['can_export', 'can_update', 'can_delete'],
  'platform.approvals': ['can_export', 'can_update'],
  'platform.announcements': ['can_export', 'can_create', 'can_update', 'can_delete'],

  'customer.workspace': ['can_export'],
  'customer.brand_analysis': ['can_export'],
  'customer.realtime': ['can_export'],
  'customer.links': ['can_export'],
  'customer.diagnosis': ['can_export'],
  'customer.competitor': ['can_export'],
  'customer.sources': ['can_export'],
  'customer.reports': ['can_export'],
  'customer.knowledge': ['can_export', 'can_create', 'can_update'],
}

const MENU_ACTION_LABELS: Record<string, Partial<Record<PermissionAction, string>>> = {
  'platform.audit.list': { can_export: '查看', can_update: '新增/编辑', can_delete: '停止服务' },
  'platform.audit.profile': { can_export: '查看', can_update: '编辑资料' },
  'platform.audit.regions': { can_export: '查看', can_update: '编辑服务地区' },
  'platform.audit.keywords': { can_export: '查看', can_update: '编辑监测词' },
  'platform.audit.models': {},
  'platform.audit.purge': { can_delete: '彻底删除' },
  'platform.audit.schedule': { can_export: '查看', can_update: '编辑监控计划' },
  'platform.audit.competitors': { can_export: '查看', can_update: '编辑竞品' },
  'platform.lead_diagnosis': { can_export: '查看/导出 PDF', can_create: '新建诊断' },
  'platform.snapshot_backfill': { can_export: '查看待补录', can_update: '提交补录' },
  'platform.reports': { can_export: '查看/导出', can_create: '生成诊断' },
  'platform.alerts': { can_export: '查看', can_update: '配置规则' },
  [SETTINGS_SECRETS_MENU]: { can_export: '查看', can_update: '修改密钥' },
  [SETTINGS_SCHEDULE_MENU]: { can_export: '查看', can_update: '修改调度' },
  [SETTINGS_CACHE_QUEUE_MENU]: { can_export: '查看', can_update: '修改缓存队列' },
  [SETTINGS_NOTIFICATION_MENU]: { can_export: '查看', can_update: '修改通知规则' },
  [SETTINGS_MENU_PERM]: { can_export: '查看', can_update: '修改菜单配置' },
  [USER_LIST_MENU]: { can_export: '查看', can_update: '编辑', can_delete: '禁用/删除' },
  [USER_CREATE_PLATFORM_MENU]: { can_create: '创建平台账号' },
  [USER_CREATE_CUSTOMER_MENU]: { can_create: '创建客户账号' },
  [POSITION_MENU]: { can_export: '查看', can_update: '编辑', can_delete: '停用' },
  'platform.approvals': { can_export: '查看申请', can_update: '审批通过/驳回' },
  'platform.announcements': { can_export: '查看', can_create: '新建', can_update: '编辑/下线', can_delete: '删除' },
  'customer.knowledge': { can_export: '查看', can_create: '上传文件', can_update: '编辑资料' },
  'customer.reports': { can_export: '查看/导出' },
}

export type MenuGrantFlags = Record<PermissionAction, boolean>

export type MenuGrantState = Record<number, MenuGrantFlags>

export const ROUTE_ONLY_MENU_CODES = new Set(['platform.audit', 'platform.users', USER_CREATE_MENU, SETTINGS_MENU])

export const USER_CREATE_CHILD_MENUS = [USER_CREATE_PLATFORM_MENU, USER_CREATE_CUSTOMER_MENU] as const

export const SETTINGS_CHILD_MENUS = [
  SETTINGS_SECRETS_MENU,
  SETTINGS_SCHEDULE_MENU,
  SETTINGS_CACHE_QUEUE_MENU,
  SETTINGS_NOTIFICATION_MENU,
  SETTINGS_MENU_PERM,
] as const

export type PermissionMenuRow = {
  menu: MenuInfo
  indent: number
  headerOnly?: boolean
}

const HIDDEN_ASSIGNABLE = new Set([
  ...hiddenPlatformMenus,
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

function syntheticUserCreateHeader(): MenuInfo {
  return {
    id: 0,
    menu_code: USER_CREATE_MENU,
    menu_name: '用户新增',
    identity_type: 'PLATFORM',
    route_path: '/platform/users/create',
    icon: 'Users',
    sort_order: 31,
    can_create: false,
    can_update: false,
    can_delete: false,
    can_export: false,
  }
}

function syntheticSettingsHeader(): MenuInfo {
  return {
    id: 0,
    menu_code: SETTINGS_MENU,
    menu_name: '系统配置',
    identity_type: 'PLATFORM',
    route_path: '/platform/settings',
    icon: 'Settings',
    sort_order: 90,
    can_create: false,
    can_update: false,
    can_delete: false,
    can_export: false,
  }
}

export function permissionMenuRows(menus: MenuInfo[]): PermissionMenuRow[] {
  const byCode = new Map(menus.map(menu => [menu.menu_code, menu]))
  const userCreateChildCodes = new Set<string>(USER_CREATE_CHILD_MENUS)
  const settingsChildCodes = new Set<string>(SETTINGS_CHILD_MENUS)
  const rows: PermissionMenuRow[] = []
  let userCreateBlockDone = false
  let settingsBlockDone = false

  const appendUserCreateBlock = () => {
    const children = USER_CREATE_CHILD_MENUS
      .map(code => byCode.get(code))
      .filter((menu): menu is MenuInfo => Boolean(menu))
    if (!children.length) return
    rows.push({
      menu: byCode.get(USER_CREATE_MENU) || syntheticUserCreateHeader(),
      indent: 0,
      headerOnly: true,
    })
    for (const child of children) {
      rows.push({ menu: child, indent: 1 })
    }
    userCreateBlockDone = true
  }

  const appendSettingsBlock = () => {
    const children = SETTINGS_CHILD_MENUS
      .map(code => byCode.get(code))
      .filter((menu): menu is MenuInfo => Boolean(menu))
    if (!children.length) return
    rows.push({
      menu: byCode.get(SETTINGS_MENU) || syntheticSettingsHeader(),
      indent: 0,
      headerOnly: true,
    })
    for (const child of children) {
      rows.push({ menu: child, indent: 1 })
    }
    settingsBlockDone = true
  }

  for (const menu of menus) {
    if (menu.menu_code === USER_CREATE_MENU) {
      if (!userCreateBlockDone) appendUserCreateBlock()
      continue
    }
    if (userCreateChildCodes.has(menu.menu_code)) {
      if (!userCreateBlockDone) appendUserCreateBlock()
      continue
    }
    if (menu.menu_code === SETTINGS_MENU) {
      if (!settingsBlockDone) appendSettingsBlock()
      continue
    }
    if (settingsChildCodes.has(menu.menu_code)) {
      if (!settingsBlockDone) appendSettingsBlock()
      continue
    }
    rows.push({ menu, indent: 0 })
  }
  return rows
}

export function countPermissionRows(rows: PermissionMenuRow[], grants: MenuGrantState) {
  const actionable = rows.filter(row => !row.headerOnly)
  const active = actionable.filter(row => grantHasAccess(grants[row.menu.id] || emptyGrant()))
  return { active: active.length, total: actionable.length }
}

export function actionsForMenu(menuCode: string, type: IdentityType): PermissionAction[] {
  if (MENU_ACTIONS[menuCode]) return MENU_ACTIONS[menuCode]
  if (menuCode === 'platform.audit.purge') return ['can_delete']
  if (menuCode.startsWith('platform.audit.')) {
    return menuCode === 'platform.audit.list'
      ? ['can_export', 'can_update', 'can_delete']
      : ['can_export', 'can_update']
  }
  if (menuCode.startsWith('platform.settings.')) {
    return ['can_export', 'can_update']
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
    ? ['dashboard', 'audit', 'analysis', 'users', 'diagnosis', 'backfill', 'system', 'other']
    : ['workspace', 'monitor', 'analysis', 'knowledge', 'other']
  return order
    .filter(key => buckets[key]?.length)
    .map(key => {
      const menus = buckets[key].sort((a, b) => a.sort_order - b.sort_order || a.id - b.id)
      return {
        key,
        title: permissionGroupTitle(type, key),
        note: permissionGroupNote(type, key),
        menus,
        rows: permissionMenuRows(menus),
      }
    })
}
