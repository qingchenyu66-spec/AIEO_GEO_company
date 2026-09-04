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
  const previewMenusLoading = ref(false)
  const previewMenusError = ref('')

  async function loadPreviewCustomerMenus() {
    const tenantId = previewTenantId.value
    if (!isPreviewActive.value || tenantId == null) {
      previewCustomerMenus.value = []
      previewMenusError.value = ''
      return
    }
    previewMenusLoading.value = true
    previewMenusError.value = ''
    try {
      // 2026-09-04 - 预览侧栏跟开通状态走接口，避免写死商品卡
      const meta = await withRetry(() => getTenantCustomerPreviewMenus(tenantId))
      previewCustomerMenus.value = meta.menus
    } catch (error: unknown) {
      previewCustomerMenus.value = []
      previewMenusError.value = extractErrorDetail(error) || '客户菜单加载失败'
    } finally {
      previewMenusLoading.value = false
    }
  }

  watch([isPreviewActive, previewTenantId], () => {
    void loadPreviewCustomerMenus()
  }, { immediate: true })

  return {
    previewCustomerMenus,
    previewMenusLoading,
    previewMenusError,
    reloadPreviewCustomerMenus: loadPreviewCustomerMenus,
  }
}
