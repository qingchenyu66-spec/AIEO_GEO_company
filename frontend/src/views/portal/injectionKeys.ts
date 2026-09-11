import type { InjectionKey, Ref } from 'vue'
import type { MenuInfo } from '../../services/auth'
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
/** 客户门户预览：后端按企业客户权限返回的菜单（含子权限，供页内鉴权） */
export const PreviewCustomerMenusKey: InjectionKey<Ref<MenuInfo[]>> = Symbol('preview-customer-menus')
export const PreviewCustomerIncludesTodayKey: InjectionKey<Ref<boolean | null>> = Symbol('preview-customer-includes-today')
