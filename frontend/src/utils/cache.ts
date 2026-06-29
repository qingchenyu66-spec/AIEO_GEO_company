import { invalidateCache as httpInvalidateCache, getCacheStats } from '../services/http'

export function clearUserCache() {
  httpInvalidateCache('/management/users')
  httpInvalidateCache('/management/positions')
  httpInvalidateCache('/management/roles')
}

export function clearEnterpriseCache() {
  httpInvalidateCache('/brand')
  httpInvalidateCache('/management/tenants')
}

export function clearMonitorCache() {
  httpInvalidateCache('/monitor')
}

export function clearAllCache() {
  httpInvalidateCache()
}

export function showCacheInfo() {
  if (!import.meta.env.DEV) return
  const stats = getCacheStats()
  console.table(stats.items)
  console.log(`Total cached requests: ${stats.size}`)
}
