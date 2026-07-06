import { ref, watch, type Ref } from 'vue'
import { ElMessage } from 'element-plus'
import type { Router, RouteLocationNormalizedLoaded } from 'vue-router'
import { normalizeMenuCode, hiddenCustomerMenus, hiddenPlatformMenus } from './constants'

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
    if (allowed.length && !allowed.includes(code)) {
      ElMessage.warning('当前账号没有该菜单权限')
      const fallback = allowed[0]
      if (fallback && fallback !== code) {
        navigateToMenu(fallback, true)
      }
      return
    }
    activeMenuCode.value = code
    const query = { ...route.query, menu: code, ...extraQuery }
    const nav = replace ? router.replace : router.push
    nav({ path: route.path, query }).catch(() => undefined)
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
