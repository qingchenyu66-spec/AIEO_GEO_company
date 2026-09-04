import type { MenuInfo } from '../../services/auth'
import type { RouteLocationNormalizedLoaded } from 'vue-router'
import { hiddenCustomerMenus } from './constants'

/** 预览加载失败时的兜底菜单（不含商品卡；商品卡仅接口按开通返回）。 */
export const CUSTOMER_PREVIEW_MENU_CODES = [
  'customer.workspace',
  'customer.brand_analysis',
  'customer.realtime',
  'customer.competitor',
  'customer.sources',
  'customer.reports',
  'customer.knowledge',
] as const

export type CustomerPreviewMenuCode = (typeof CUSTOMER_PREVIEW_MENU_CODES)[number]

export const CUSTOMER_PREVIEW_MENUS: MenuInfo[] = [
  { id: -1, menu_code: 'customer.workspace', menu_name: '运营工作台', identity_type: 'CUSTOMER', route_path: '/customer/workspace', icon: 'LayoutDashboard', sort_order: 10, can_create: false, can_update: false, can_delete: false, can_export: true },
  { id: -7, menu_code: 'customer.brand_analysis', menu_name: '品牌分析', identity_type: 'CUSTOMER', route_path: '/customer/brand-analysis', icon: 'Radar', sort_order: 15, can_create: false, can_update: false, can_delete: false, can_export: true },
  { id: -2, menu_code: 'customer.realtime', menu_name: 'GEO 监测', identity_type: 'CUSTOMER', route_path: '/customer/realtime', icon: 'Search', sort_order: 20, can_create: false, can_update: false, can_delete: false, can_export: true },
  { id: -3, menu_code: 'customer.competitor', menu_name: '竞品分析', identity_type: 'CUSTOMER', route_path: '/customer/competitor', icon: 'BarChart3', sort_order: 30, can_create: false, can_update: false, can_delete: false, can_export: true },
  { id: -4, menu_code: 'customer.sources', menu_name: '信源分析', identity_type: 'CUSTOMER', route_path: '/customer/sources', icon: 'Database', sort_order: 40, can_create: false, can_update: false, can_delete: false, can_export: true },
  { id: -5, menu_code: 'customer.reports', menu_name: '报告中心', identity_type: 'CUSTOMER', route_path: '/customer/reports', icon: 'FileBarChart', sort_order: 50, can_create: false, can_update: false, can_delete: false, can_export: true },
  { id: -6, menu_code: 'customer.knowledge', menu_name: '企业知识库', identity_type: 'CUSTOMER', route_path: '/customer/knowledge', icon: 'BookOpen', sort_order: 60, can_create: false, can_update: false, can_delete: false, can_export: true },
]

export function isCustomerPreviewMenuCode(code: string): boolean {
  return (CUSTOMER_PREVIEW_MENU_CODES as readonly string[]).includes(code)
}

/** 客户/预览侧栏过滤：商品卡是否出现由接口菜单决定，此处不写死。 */
export function buildCustomerPortalSidebarMenus(sourceMenus: MenuInfo[]): MenuInfo[] {
  return sourceMenus.filter(menu => (
    !['customer.assets', ...hiddenCustomerMenus].includes(menu.menu_code)
  ))
}

function parsePositiveTenantId(raw: unknown): number | null {
  const text = Array.isArray(raw) ? raw[0] : raw
  const parsed = Number(text)
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null
}

export function parsePreviewTenantId(route: RouteLocationNormalizedLoaded): number | null {
  return parsePositiveTenantId(route.query.preview_tenant_id)
}

export function parsePreviewTenantName(route: RouteLocationNormalizedLoaded): string {
  const raw = route.query.preview_tenant_name
  const text = Array.isArray(raw) ? raw[0] : raw
  return typeof text === 'string' && text.trim() ? text.trim() : ''
}

/** 当前路由或即将写入的 extraQuery 上的预览企业（进入预览首跳必须看 extra）。 */
export function resolvePreviewTenantId(
  route: RouteLocationNormalizedLoaded,
  extraQuery?: Record<string, string>,
): number | null {
  return parsePositiveTenantId(extraQuery?.preview_tenant_id) ?? parsePreviewTenantId(route)
}

export function resolvePreviewTenantName(
  route: RouteLocationNormalizedLoaded,
  extraQuery?: Record<string, string>,
): string {
  const fromExtra = extraQuery?.preview_tenant_name?.trim()
  if (fromExtra) return fromExtra
  return parsePreviewTenantName(route)
}

export function isCustomerPreviewActive(route: RouteLocationNormalizedLoaded, isPlatform: boolean): boolean {
  return isPlatform && parsePreviewTenantId(route) != null
}

export function previewQueryFields(tenantId: number, tenantName: string): Record<string, string> {
  return {
    preview_tenant_id: String(tenantId),
    preview_tenant_name: tenantName,
    tenant_id: String(tenantId),
  }
}
