/**
 * 职位权限：品牌洞察/信源分析/商品卡/旧算力子页不进勾选，保存时保留已有授权。
 * Run: npx --yes tsx frontend/src/views/portal/menuPermissionMatrix.selfcheck.ts
 */
import type { MenuInfo } from '../../services/auth'
import {
  assignablePermissionMenus,
  preserveHiddenAssignableGrants,
  sanitizeGrantForMenu,
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
  menu({ id: 4, menu_code: 'platform.tenant_credit' }),
  menu({ id: 5, menu_code: 'platform.credit_ops_board' }),
  menu({ id: 6, menu_code: 'customer.links', identity_type: 'CUSTOMER' }),
  menu({ id: 7, menu_code: 'customer.diagnosis', identity_type: 'CUSTOMER' }),
  menu({ id: 8, menu_code: 'customer.goods_cards', identity_type: 'CUSTOMER' }),
  menu({ id: 9, menu_code: 'customer.enterprise_config', identity_type: 'CUSTOMER' }),
  menu({ id: 10, menu_code: 'customer.enterprise_credit', identity_type: 'CUSTOMER' }),
]

const assignable = assignablePermissionMenus('PLATFORM', menus)
if (assignable.some(item => item.menu_code === 'platform.competitor' || item.menu_code === 'platform.sources')) {
  throw new Error('competitor/sources must be hidden from assignable list')
}
if (!assignable.some(item => item.menu_code === 'platform.reports')) {
  throw new Error('platform.reports should remain assignable')
}
if (assignable.some(item => item.menu_code === 'platform.tenant_credit')) {
  throw new Error('tenant_credit is product/legacy subpage; must not be assignable')
}
if (!assignable.some(item => item.menu_code === 'platform.credit_ops_board')) {
  throw new Error('credit_ops_board should remain assignable')
}

const customerAssignable = assignablePermissionMenus('CUSTOMER', menus)
if (customerAssignable.some(item => ['customer.links', 'customer.diagnosis', 'customer.goods_cards', 'customer.enterprise_config', 'customer.enterprise_credit'].includes(item.menu_code))) {
  throw new Error('disabled/product customer menus must not be assignable')
}

const preserved = preserveHiddenAssignableGrants(menus, [
  { menu_id: 2, menu_code: 'platform.competitor', can_export: true },
  { menu_id: 3, menu_code: 'platform.sources', can_export: true },
  { menu_id: 1, menu_code: 'platform.reports', can_export: true },
  { menu_id: 4, menu_code: 'platform.tenant_credit', can_export: true },
  { menu_id: 6, menu_code: 'customer.links', can_export: true },
  { menu_id: 8, menu_code: 'customer.goods_cards', can_export: true },
  { menu_id: 9, menu_code: 'customer.enterprise_config', can_export: true },
])
const preservedCodes = preserved.map(item => item.menu_code).sort()
const expected = ['customer.enterprise_config', 'customer.goods_cards', 'customer.links', 'platform.competitor', 'platform.sources', 'platform.tenant_credit'].sort()
if (preservedCodes.join(',') !== expected.join(',')) {
  throw new Error(`unexpected preserved codes: ${preservedCodes.join(',')}`)
}

const filesGrant = sanitizeGrantForMenu('platform.audit.files', 'PLATFORM', {
  can_export: true,
  can_create: true,
  can_update: false,
  can_delete: true,
})
if (!filesGrant.can_export || !filesGrant.can_create || filesGrant.can_update || filesGrant.can_delete) {
  throw new Error(`audit.files sanitize mismatch: ${JSON.stringify(filesGrant)}`)
}

const creditGrant = sanitizeGrantForMenu('platform.credit_ops_board', 'PLATFORM', {
  can_export: true,
  can_create: true,
  can_update: true,
  can_delete: true,
})
if (!creditGrant.can_export || !creditGrant.can_update || creditGrant.can_create || creditGrant.can_delete) {
  throw new Error(`credit_ops sanitize mismatch: ${JSON.stringify(creditGrant)}`)
}

console.log('menuPermissionMatrix.selfcheck ok')
