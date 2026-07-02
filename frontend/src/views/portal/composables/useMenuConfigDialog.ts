import { reactive, ref, type ComputedRef } from 'vue'
import { ElMessage } from 'element-plus'
import { notifyOperationError } from '../../../utils/requestError'
import { withRetry } from '../../../composables/useRetry'
import { useAuthStore } from '../../../stores/auth'
import type { IdentityType } from '../../../services/auth'
import { getMenuConfigs, updateMenuConfig, type MenuConfigRecord } from '../../../services/management'
import { managementErrorMessage } from '../managementErrorMessage'

type MenuConfigOptions = {
  isPlatform: ComputedRef<boolean>
}

export function useMenuConfigDialog(options: MenuConfigOptions) {
  const { isPlatform } = options
  const auth = useAuthStore()

  const menuConfigDialog = ref(false)
  const menuConfigs = ref<MenuConfigRecord[]>([])
  const loadingMenuConfigs = ref(false)
  const savingMenuConfig = ref(false)
  const selectedMenuIdentityType = ref<IdentityType>('PLATFORM')
  const editingMenuConfig = ref<MenuConfigRecord | null>(null)
  const menuConfigForm = reactive({
    menu_name: '',
    sort_order: 1,
    is_visible: true,
  })

  function notifyError(error: unknown, context: string) {
    notifyOperationError(error, context, managementErrorMessage)
  }

  function openMenuConfigDialog() {
    menuConfigDialog.value = true
    selectedMenuIdentityType.value = 'PLATFORM'
    loadMenuConfigs()
  }

  async function loadMenuConfigs() {
    if (!isPlatform.value) return
    loadingMenuConfigs.value = true
    try {
      menuConfigs.value = await withRetry(() => getMenuConfigs(selectedMenuIdentityType.value))
    } catch (error: unknown) {
      notifyError(error, '菜单配置加载失败')
    } finally {
      loadingMenuConfigs.value = false
    }
  }

  function startEditMenuConfig(config: MenuConfigRecord) {
    editingMenuConfig.value = config
    menuConfigForm.menu_name = config.menu_name
    menuConfigForm.sort_order = config.sort_order
    menuConfigForm.is_visible = config.is_visible
  }

  function cancelEditMenuConfig() {
    editingMenuConfig.value = null
    menuConfigForm.menu_name = ''
    menuConfigForm.sort_order = 1
    menuConfigForm.is_visible = true
  }

  async function saveMenuConfig(configId: number) {
    if (!menuConfigForm.menu_name.trim()) {
      ElMessage.warning('请输入显示名称')
      return
    }
    savingMenuConfig.value = true
    try {
      await updateMenuConfig(configId, {
        menu_name: menuConfigForm.menu_name.trim(),
        sort_order: menuConfigForm.sort_order,
        is_visible: menuConfigForm.is_visible,
      })
      ElMessage.success('菜单配置已更新')
      cancelEditMenuConfig()
      await loadMenuConfigs()
      try {
        await auth.refreshSession()
      } catch {
        ElMessage.info('配置已保存，若侧边栏未更新请重新登录或刷新页面')
      }
    } catch (error: unknown) {
      notifyError(error, '菜单配置保存失败')
    } finally {
      savingMenuConfig.value = false
    }
  }

  return {
    menuConfigDialog,
    menuConfigs,
    loadingMenuConfigs,
    savingMenuConfig,
    selectedMenuIdentityType,
    editingMenuConfig,
    menuConfigForm,
    openMenuConfigDialog,
    loadMenuConfigs,
    startEditMenuConfig,
    cancelEditMenuConfig,
    saveMenuConfig,
  }
}
