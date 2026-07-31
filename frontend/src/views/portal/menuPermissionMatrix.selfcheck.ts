/**
 * 职位权限：品牌洞察/信源分析不进勾选，保存时保留已有授权。
 * Run: npx --yes tsx frontend/src/views/portal/menuPermissionMatrix.selfcheck.ts
 */
import type { MenuInfo } from '../../services/auth'
import {
  assignablePermissionMenus,
  preserveHiddenAssignableGrants,
} from './menuPermissionMatrix'

function menu(partial: Partial<MenuInfo> & Pick<MenuInfo, 'id' | 'menu_code'>): MenuInfo {
  return {
    menu_name: partial.menu_code,
    identity_type: 'PLATFORM',
    route_path: '/',
    icon: '',
    sort_order: 1,
    can_create: false,
    can_update: false,
    can_delete: false,
    can_export: true,
    ...partial,
  }
}

const menus = [
  menu({ id: 1, menu_code: 'platform.reports' }),
  menu({ id: 2, menu_code: 'platform.competitor' }),
  menu({ id: 3, menu_code: 'platform.sources' }),
]

const assignable = assignablePermissionMenus('PLATFORM', menus)
if (assignable.some(item => item.menu_code === 'platform.competitor' || item.menu_code === 'platform.sources')) {
  throw new Error('competitor/sources must be hidden from assignable list')
}
if (!assignable.some(item => item.menu_code === 'platform.reports')) {
  throw new Error('platform.reports should remain assignable')
}

const preserved = preserveHiddenAssignableGrants(menus, [
  { menu_id: 2, menu_code: 'platform.competitor', can_export: true },
  { menu_id: 3, menu_code: 'platform.sources', can_export: true },
  { menu_id: 1, menu_code: 'platform.reports', can_export: true },
])
if (preserved.length !== 2) {
  throw new Error(`expected 2 preserved grants, got ${preserved.length}`)
}
if (!preserved.every(item => ['platform.competitor', 'platform.sources'].includes(item.menu_code))) {
  throw new Error(`unexpected preserved codes: ${preserved.map(item => item.menu_code).join(',')}`)
}

console.log('menuPermissionMatrix.selfcheck ok')
