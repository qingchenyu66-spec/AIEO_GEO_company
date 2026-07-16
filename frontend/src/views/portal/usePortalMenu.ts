import { ref, watch, type Ref } from 'vue'
import { ElMessage } from 'element-plus'
import type { Router, RouteLocationNormalizedLoaded } from 'vue-router'
import { CUSTOMER_PREVIEW_MENU, normalizeMenuCode, hiddenCustomerMenus, hiddenPlatformMenus } from './constants'
import { shouldKeepTenantQuery } from './tenantQueryScope'

function isCustomerPreviewAllowed(code: string, route: RouteLocationNormalizedLoaded) {
  return code === CUSTOMER_PREVIEW_MENU && route.path.startsWith('/platform')
}

/** Sync active menu with ?menu= query — keeps deep links without breaking in-app navigation. */
export function usePortalMenu(
  router: Router,
  route: RouteLocationNormalizedLoaded,
  defaultCode: string,
  allowedMenuCodes?: Ref<string[]>,
) {
  const activeMenuCode = ref(normalizeMenuCode(String(route.query.menu || defaultCode)))

  function navigateToMenu(menuCode: string, replace = false, extraQuery?: Record<string, string>) {
    const code = normalizeMenuCode(menuCode)
    if (hiddenCustomerMenus.includes(code) || hiddenPlatformMenus.includes(code)) {
      ElMessage.warning('该功能暂未开放')
      return
    }
    const allowed = allowedMenuCodes?.value || []
    const previewOk = isCustomerPreviewAllowed(code, route)
    if (allowed.length && !allowed.includes(code) && !previewOk) {
      ElMessage.warning('当前账号没有该菜单权限')
      const fallback = allowed[0]
      if (fallback && fallback !== code) {
        navigateToMenu(fallback, true)
      }
      return
    }
    activeMenuCode.value = code
    const query: Record<string, unknown> = { ...route.query, menu: code, ...extraQuery }
    // Sticky ?tenant_id= from 洞察/信源/实时监测 must not leak into 报告中心等页面，
    // or PortalView brand prefetch will 403 sales users on unrelated enterprises.
    if (!shouldKeepTenantQuery(code) && extraQuery?.tenant_id === undefined) {
      delete query.tenant_id
    }
    if (code !== CUSTOMER_PREVIEW_MENU) {
      delete query.preview_tenant_id
      delete query.preview_tenant_name
    }
    const nav = replace ? router.replace : router.push
    nav({ path: route.path, query: query as typeof route.query }).catch(() => undefined)
  }

  watch(
    () => route.query.menu,
    (value) => {
      if (typeof value === 'string' && value) {
        activeMenuCode.value = normalizeMenuCode(value)
      }
    },
  )

  return { activeMenuCode, navigateToMenu, isMenuBlocked: (code: string) => hiddenCustomerMenus.includes(code) || hiddenPlatformMenus.includes(code) }
}

export function setActiveMenuCode(activeMenuCode: Ref<string>, menuCode: string) {
  activeMenuCode.value = normalizeMenuCode(menuCode)
}
