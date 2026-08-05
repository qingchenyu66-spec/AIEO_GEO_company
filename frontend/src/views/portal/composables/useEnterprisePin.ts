/** 企业列表个人单条置顶（仅本人可见，localStorage）。 */

const STORAGE_PREFIX = 'geo.portal.enterprisePin'

export function enterprisePinStorageKey(userId: number, identityId: number) {
  return `${STORAGE_PREFIX}:${userId}:${identityId}`
}

export function readEnterprisePin(userId: number, identityId: number): number | null {
  try {
    const raw = localStorage.getItem(enterprisePinStorageKey(userId, identityId))
    if (raw == null || raw === '') return null
    const id = Number(raw)
    return Number.isFinite(id) && id > 0 ? id : null
  } catch {
    return null
  }
}

export function writeEnterprisePin(userId: number, identityId: number, tenantId: number | null) {
  const key = enterprisePinStorageKey(userId, identityId)
  if (tenantId == null) {
    localStorage.removeItem(key)
    return
  }
  localStorage.setItem(key, String(tenantId))
}

/** 当前结果集内：置顶企业（若存在）提到最前，其余保持原序。 */
export function sortTenantsWithPin<T extends { id: number }>(tenants: T[], pinnedId: number | null): T[] {
  if (pinnedId == null) return tenants
  const pinned = tenants.find(item => item.id === pinnedId)
  if (!pinned) return tenants
  return [pinned, ...tenants.filter(item => item.id !== pinnedId)]
}

function selfcheckSortTenantsWithPin() {
  const rows = [{ id: 1 }, { id: 2 }, { id: 3 }]
  const sorted = sortTenantsWithPin(rows, 2)
  if (sorted.map(item => item.id).join(',') !== '2,1,3') {
    throw new Error('sortTenantsWithPin selfcheck failed')
  }
  if (sortTenantsWithPin(rows, 99) !== rows) {
    throw new Error('sortTenantsWithPin missing-pin selfcheck failed')
  }
}

if (import.meta.env.DEV) {
  selfcheckSortTenantsWithPin()
}
