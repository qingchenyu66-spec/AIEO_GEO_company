/** Menus that intentionally keep ?tenant_id= as enterprise context across navigations. */
export const TENANT_QUERY_SCOPED_MENUS = new Set([
  'customer.realtime',
  'customer.competitor',
  'platform.competitor',
  'customer.sources',
  'platform.sources',
])

/** PortalView global brand prefetch is only for pages that inject PortalAnalytics brandAsset. */
export const BRAND_PREFETCH_MENUS = new Set([
  'customer.competitor',
  'platform.competitor',
  'customer.sources',
  'platform.sources',
])

export function shouldKeepTenantQuery(menuCode: string): boolean {
  return TENANT_QUERY_SCOPED_MENUS.has(menuCode)
}

export function shouldPrefetchBrandForMenu(menuCode: string): boolean {
  return BRAND_PREFETCH_MENUS.has(menuCode)
}

/** Prefer route tenant only when it is in the account's accessible tenant list. */
export function resolveAccessibleTenantId(
  requested: number | null,
  accessibleIds: readonly number[],
): number | null {
  if (requested != null && accessibleIds.includes(requested)) return requested
  return accessibleIds[0] ?? null
}
