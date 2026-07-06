/** 平台/客户菜单跳转：避免平台账号误进客户页。 */
export function resolveRealtimeMenu(isPlatform: boolean, tenantId?: number | null) {
  if (!isPlatform) {
    return { menu: 'customer.realtime', query: {} as Record<string, string> }
  }
  if (tenantId) {
    return { menu: 'customer.realtime', query: { tenant_id: String(tenantId) } }
  }
  return { menu: 'platform.audit', query: {} as Record<string, string> }
}

export function resolveMonitorActionMenu(isPlatform: boolean, mode: string) {
  if (mode.startsWith('platform')) {
    if (mode === 'report') return 'platform.reports'
    return 'platform.audit'
  }
  if (isPlatform) return 'platform.audit'
  return 'customer.realtime'
}
