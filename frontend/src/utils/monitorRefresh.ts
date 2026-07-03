export const MONITOR_REFRESH_EVENT = 'geo:monitor-refresh'

export type MonitorRefreshDetail = {
  tenantId?: number | null
}

export function emitMonitorRefresh(detail?: MonitorRefreshDetail) {
  window.dispatchEvent(new CustomEvent<MonitorRefreshDetail>(MONITOR_REFRESH_EVENT, { detail }))
}

export function onMonitorRefresh(handler: (detail?: MonitorRefreshDetail) => void) {
  const listener = (event: Event) => {
    handler((event as CustomEvent<MonitorRefreshDetail>).detail)
  }
  window.addEventListener(MONITOR_REFRESH_EVENT, listener)
  return () => window.removeEventListener(MONITOR_REFRESH_EVENT, listener)
}
