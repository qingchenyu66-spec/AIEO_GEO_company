import { ref, watch, type Ref } from 'vue'
import { ElMessage } from 'element-plus'
import type { Router, RouteLocationNormalizedLoaded } from 'vue-router'
import { CUSTOMER_PREVIEW_MENU, normalizeMenuCode, hiddenCustomerMenus, hiddenPlatformMenus } from './constants'
import {
  isCustomerPreviewActive,
  isCustomerPreviewMenuCode,
  parsePreviewTenantId,
  parsePreviewTenantName,
  previewQueryFields,
} from './customerPreview'
import { shouldKeepTenantQuery } from './tenantQueryScope'

/** Sync active menu with ?menu= query — keeps deep links without breaking in-app navigation. */
export function usePortalMenu(
  router: Router,
  route: RouteLocationNormalizedLoaded,
  defaultCode: string,
  allowedMenuCodes?: Ref<string[]>,
  isPlatform?: Ref<boolean>,
) {
  const activeMenuCode = ref(normalizeMenuCode(String(route.query.menu || defaultCode)))

  function navigateToMenu(menuCode: string, replace = false, extraQuery?: Record<string, string>) {
    let code = normalizeMenuCode(menuCode)
    if (hiddenCustomerMenus.includes(code) || hiddenPlatformMenus.includes(code)) {
      ElMessage.warning('该功能暂未开放')
      return
    }

    const previewTenantId = parsePreviewTenantId(route)
    const previewActive = Boolean(isPlatform?.value && previewTenantId)

    // 旧入口 platform.customer_preview → 客户工作台
    if (code === CUSTOMER_PREVIEW_MENU && previewTenantId) {
      code = 'customer.workspace'
    }

    const allowed = allowedMenuCodes?.value || []
    const previewMenuOk = previewActive && isCustomerPreviewMenuCode(code)
    const exitingPreview = previewActive && code === 'platform.audit'

    if (allowed.length && !allowed.includes(code) && !previewMenuOk && !exitingPreview) {
      if (previewActive && !isCustomerPreviewMenuCode(code)) {
        ElMessage.info('预览模式为只读，请先返回企业管理')
        return
      }
      ElMessage.warning('当前账号没有该菜单权限')
      const fallback = allowed[0]
      if (fallback && fallback !== code) {
        navigateToMenu(fallback, true)
      }
      return
    }
    activeMenuCode.value = code
    const query: Record<string, unknown> = { ...route.query, menu: code, ...extraQuery }

    if (exitingPreview) {
      delete query.preview_tenant_id
      delete query.preview_tenant_name
      delete query.tenant_id
    } else if (previewActive && previewTenantId) {
      Object.assign(query, previewQueryFields(previewTenantId, parsePreviewTenantName(route)))
    } else {
      if (!shouldKeepTenantQuery(code) && extraQuery?.tenant_id === undefined) {
        delete query.tenant_id
      }
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
        const code = normalizeMenuCode(value)
        if (code === CUSTOMER_PREVIEW_MENU && isCustomerPreviewActive(route, Boolean(isPlatform?.value))) {
          activeMenuCode.value = 'customer.workspace'
          return
        }
        activeMenuCode.value = code
      }
    },
  )

  return { activeMenuCode, navigateToMenu, isMenuBlocked: (code: string) => hiddenCustomerMenus.includes(code) || hiddenPlatformMenus.includes(code) }
}

export function setActiveMenuCode(activeMenuCode: Ref<string>, menuCode: string) {
  activeMenuCode.value = normalizeMenuCode(menuCode)
}
