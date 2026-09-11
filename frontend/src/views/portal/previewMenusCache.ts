import type { MenuInfo } from '../../services/auth'
import { getTenantCustomerPreviewMenus, type CustomerPreviewMeta } from '../../services/management'
import { withRetry } from '../../composables/useRetry'

/** 进入预览前预取的菜单缓存：进门即可渲染，避免空侧栏。 */
const cache = new Map<number, CustomerPreviewMeta>()

export function seedCustomerPreviewMenus(tenantId: number, meta: CustomerPreviewMeta): void {
  cache.set(tenantId, {
    menus: meta.menus || [],
    customer_includes_today: Boolean(meta.customer_includes_today),
  })
}

export function peekCustomerPreviewMenus(tenantId: number): CustomerPreviewMeta | null {
  return cache.get(tenantId) || null
}

export function clearCustomerPreviewMenusCache(tenantId?: number): void {
  if (tenantId == null) {
    cache.clear()
    return
  }
  cache.delete(tenantId)
}

/** 拉接口并写入缓存；进入「查看客户端」前必须成功。 */
export async function prefetchCustomerPreviewMenus(tenantId: number): Promise<CustomerPreviewMeta> {
  const meta = await withRetry(() => getTenantCustomerPreviewMenus(tenantId))
  if (!meta.menus?.length) {
    throw new Error('该企业暂无可用的客户菜单，无法进入预览')
  }
  seedCustomerPreviewMenus(tenantId, meta)
  return meta
}

export type { MenuInfo }
