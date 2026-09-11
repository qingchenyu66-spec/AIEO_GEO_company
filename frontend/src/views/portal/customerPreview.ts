import type { MenuInfo } from '../../services/auth'
import type { RouteLocationNormalizedLoaded } from 'vue-router'
import { hiddenCustomerMenus, hiddenEnterpriseConfigPermissionMenus } from './constants'

/** 预览导航允许的客户菜单编码（仅鉴权放行，不提供展示名）。 */
export const CUSTOMER_PREVIEW_MENU_CODES = [
  'customer.workspace',
  'customer.brand_analysis',
  'customer.realtime',
  'customer.competitor',
  'customer.sources',
  'customer.reports',
  'customer.knowledge',
  'customer.goods_cards',
  'customer.enterprise_config',
] as const

export type CustomerPreviewMenuCode = (typeof CUSTOMER_PREVIEW_MENU_CODES)[number]

export function isCustomerPreviewMenuCode(code: string): boolean {
  return (CUSTOMER_PREVIEW_MENU_CODES as readonly string[]).includes(code)
    || code.startsWith('customer.enterprise_')
}

/** 客户/预览侧栏过滤：商品卡是否出现由接口菜单决定，此处不写死。 */
export function buildCustomerPortalSidebarMenus(sourceMenus: MenuInfo[]): MenuInfo[] {
  // 2026-09-09 - 企业配置子项只做页内 Tab/权限，侧栏只留父级，避免两套菜单
  return sourceMenus.filter(menu => (
    !['customer.assets', ...hiddenCustomerMenus, ...hiddenEnterpriseConfigPermissionMenus].includes(menu.menu_code)
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

/** 企业管理/企业配置预览：优先 preview_tenant_id，回退 tenant_id（避免成员列表空）。 */
export function resolveEnterprisePreviewTenantId(route: RouteLocationNormalizedLoaded): number | null {
  return parsePreviewTenantId(route) ?? parsePositiveTenantId(route.query.tenant_id)
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
