import type { InjectionKey } from 'vue'
import type { WorkspaceFullscreenContext } from '../../composables/useWorkspaceFullscreen'
import type { useMonitorAnalytics } from './composables/useMonitorAnalytics'
import type { PlatformAdminContext } from './composables/usePlatformAdmin'

export const PortalAnalyticsKey: InjectionKey<ReturnType<typeof useMonitorAnalytics>> = Symbol('portal-analytics')
export const PlatformAdminKey: InjectionKey<PlatformAdminContext> = Symbol('platform-admin')
export const WorkspaceFullscreenKey: InjectionKey<WorkspaceFullscreenContext> = Symbol('workspace-fullscreen')
export const PortalNavigateKey: InjectionKey<(menuCode: string, replace?: boolean, extraQuery?: Record<string, string>) => void> = Symbol('portal-navigate')
export const ApprovalPendingRefreshKey: InjectionKey<() => void | Promise<void>> = Symbol('approval-pending-refresh')
export const PlatformBrandLogoTenantKey: InjectionKey<import('vue').Ref<number | null>> = Symbol('platform-brand-logo-tenant')
export const PlatformTenantsRefreshKey: InjectionKey<() => void | Promise<void>> = Symbol('platform-tenants-refresh')
export const PlatformDefaultLogoRefreshKey: InjectionKey<() => void | Promise<void>> = Symbol('platform-default-logo-refresh')
