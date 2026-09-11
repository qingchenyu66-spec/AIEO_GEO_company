import { ref, watch, type ComputedRef, type Ref } from 'vue'
import type { MenuInfo } from '../../../services/auth'
import { getTenantCustomerPreviewMenus } from '../../../services/management'
import { withRetry } from '../../../composables/useRetry'
import { extractErrorDetail } from '../../../utils/requestError'

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

  async function loadPreviewCustomerMenus() {
    const tenantId = previewTenantId.value
    if (!isPreviewActive.value || tenantId == null) {
      previewCustomerMenus.value = []
      previewCustomerIncludesToday.value = null
      previewMenusError.value = ''
      loadedTenantId = null
      return
    }
    // 同企业刷新：保留现有侧栏，等接口覆盖，禁止先清空再闪兜底名
    if (loadedTenantId !== tenantId) {
      previewCustomerMenus.value = []
      previewCustomerIncludesToday.value = null
    }
    const seq = ++loadSeq
    previewMenusLoading.value = true
    previewMenusError.value = ''
    try {
      const meta = await withRetry(() => getTenantCustomerPreviewMenus(tenantId))
      if (seq !== loadSeq) return
      previewCustomerMenus.value = meta.menus
      previewCustomerIncludesToday.value = meta.customer_includes_today
      loadedTenantId = tenantId
    } catch (error: unknown) {
      if (seq !== loadSeq) return
      previewCustomerMenus.value = []
      previewCustomerIncludesToday.value = null
      loadedTenantId = null
      previewMenusError.value = extractErrorDetail(error) || '客户菜单加载失败'
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
