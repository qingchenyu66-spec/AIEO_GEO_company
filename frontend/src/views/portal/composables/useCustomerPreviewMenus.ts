import { ref, watch, type ComputedRef, type Ref } from 'vue'
import type { MenuInfo } from '../../../services/auth'
import { getTenantCustomerPreviewMenus } from '../../../services/management'
import { withRetry } from '../../../composables/useRetry'
import { extractErrorDetail } from '../../../utils/requestError'
import {
  clearCustomerPreviewMenusCache,
  peekCustomerPreviewMenus,
  seedCustomerPreviewMenus,
} from '../previewMenusCache'

export function useCustomerPreviewMenus(
  isPreviewActive: ComputedRef<boolean> | Ref<boolean>,
  previewTenantId: ComputedRef<number | null> | Ref<number | null>,
) {
  const previewCustomerMenus = ref<MenuInfo[]>([])
  const previewCustomerIncludesToday = ref<boolean | null>(null)
  const previewMenusLoading = ref(false)
  const previewMenusError = ref('')
  let loadedTenantId: number | null = null
  let loadSeq = 0

  function applyMeta(tenantId: number, menus: MenuInfo[], includesToday: boolean | null) {
    previewCustomerMenus.value = menus
    previewCustomerIncludesToday.value = includesToday
    loadedTenantId = tenantId
    seedCustomerPreviewMenus(tenantId, {
      menus,
      customer_includes_today: Boolean(includesToday),
    })
  }

  async function loadPreviewCustomerMenus() {
    const tenantId = previewTenantId.value
    if (!isPreviewActive.value || tenantId == null) {
      previewCustomerMenus.value = []
      previewCustomerIncludesToday.value = null
      previewMenusError.value = ''
      previewMenusLoading.value = false
      loadedTenantId = null
      return
    }

    // 预取缓存命中：立刻有侧栏，再后台刷新
    const cached = peekCustomerPreviewMenus(tenantId)
    if (cached?.menus?.length) {
      applyMeta(tenantId, cached.menus, cached.customer_includes_today)
      previewMenusError.value = ''
    } else if (loadedTenantId !== tenantId) {
      // 换企业且无缓存：不挂空业务页；loading 期间主区显示加载态
      previewCustomerMenus.value = []
      previewCustomerIncludesToday.value = null
    }

    const seq = ++loadSeq
    previewMenusLoading.value = true
    previewMenusError.value = ''
    try {
      const meta = await withRetry(() => getTenantCustomerPreviewMenus(tenantId))
      if (seq !== loadSeq) return
      if (!meta.menus?.length) {
        previewCustomerMenus.value = []
        previewCustomerIncludesToday.value = null
        loadedTenantId = null
        clearCustomerPreviewMenusCache(tenantId)
        previewMenusError.value = '该企业暂无可用的客户菜单'
        return
      }
      applyMeta(tenantId, meta.menus, meta.customer_includes_today)
    } catch (error: unknown) {
      if (seq !== loadSeq) return
      // 已有菜单时保留展示，只记错误；完全没有才阻断
      if (!previewCustomerMenus.value.length) {
        loadedTenantId = null
        previewMenusError.value = extractErrorDetail(error) || '客户菜单加载失败'
      } else {
        previewMenusError.value = ''
      }
    } finally {
      if (seq === loadSeq) previewMenusLoading.value = false
    }
  }

  watch([isPreviewActive, previewTenantId], () => {
    void loadPreviewCustomerMenus()
  }, { immediate: true })

  return {
    previewCustomerMenus,
    previewCustomerIncludesToday,
    previewMenusLoading,
    previewMenusError,
    reloadPreviewCustomerMenus: loadPreviewCustomerMenus,
  }
}
