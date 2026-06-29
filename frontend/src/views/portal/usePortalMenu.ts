import { ref, watch, type Ref } from 'vue'
import type { Router, RouteLocationNormalizedLoaded } from 'vue-router'
import { normalizeMenuCode } from './constants'

/** Sync active menu with ?menu= query — keeps deep links without breaking in-app navigation. */
export function usePortalMenu(router: Router, route: RouteLocationNormalizedLoaded, defaultCode: string) {
  const activeMenuCode = ref(normalizeMenuCode(String(route.query.menu || defaultCode)))

  function navigateToMenu(menuCode: string, replace = false) {
    const code = normalizeMenuCode(menuCode)
    activeMenuCode.value = code
    const query = { ...route.query, menu: code }
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

  return { activeMenuCode, navigateToMenu }
}

export function setActiveMenuCode(activeMenuCode: Ref<string>, menuCode: string) {
  activeMenuCode.value = normalizeMenuCode(menuCode)
}
