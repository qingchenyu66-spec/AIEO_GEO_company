import type { InjectionKey } from 'vue'
import type { useMonitorAnalytics } from './composables/useMonitorAnalytics'
import type { PlatformAdminContext } from './composables/usePlatformAdmin'

export const PortalAnalyticsKey: InjectionKey<ReturnType<typeof useMonitorAnalytics>> = Symbol('portal-analytics')
export const PlatformAdminKey: InjectionKey<PlatformAdminContext> = Symbol('platform-admin')
