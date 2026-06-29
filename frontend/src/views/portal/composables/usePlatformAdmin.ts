import { computed, onMounted, watch, type ComputedRef, type Ref } from 'vue'
import type { IdentityType } from '../../../services/auth'
import {
  USER_CREATE_CUSTOMER_MENU,
  USER_CREATE_MENU,
  USER_CREATE_PLATFORM_MENU,
  USER_LIST_MENU,
  POSITION_MENU,
} from '../constants'
import { permissionGroupsForForm as buildPermissionGroupsForForm, type UserIdentityForm } from '../permissionGroups'
import { managementErrorMessage } from '../managementErrorMessage'
import type { useAuthStore } from '../../../stores/auth'
import { useAssignableOptions } from './useAssignableOptions'
import { useMenuConfigDialog } from './useMenuConfigDialog'
import { usePositionManagement } from './usePositionManagement'
import { useUserManagement } from './useUserManagement'

type AuthStore = ReturnType<typeof useAuthStore>

type PlatformAdminOptions = {
  auth: AuthStore
  isPlatform: ComputedRef<boolean>
  activeMenuCode: Ref<string>
  userMenuExpanded: Ref<boolean>
}

export function usePlatformAdmin(options: PlatformAdminOptions) {
  const { auth, isPlatform, activeMenuCode, userMenuExpanded } = options

  const assignable = useAssignableOptions()

  function menuGrant(code: string) {
    return auth.allowedMenus.find(menu => menu.menu_code === code)
  }

  const canCreatePlatformUser = computed(() => Boolean(menuGrant(USER_CREATE_PLATFORM_MENU)?.can_create))
  const canCreateCustomerUser = computed(() => Boolean(menuGrant(USER_CREATE_CUSTOMER_MENU)?.can_create))
  const creatableIdentityTypes = computed(() => {
    const types: IdentityType[] = []
    if (canCreatePlatformUser.value) types.push('PLATFORM')
    if (canCreateCustomerUser.value) types.push('CUSTOMER')
    return types
  })

  const isUserCreatePage = computed(() => activeMenuCode.value === USER_CREATE_MENU)
  const isUserListPage = computed(() => activeMenuCode.value === USER_LIST_MENU)
  const isUserManagementPage = computed(() => isUserCreatePage.value || isUserListPage.value)
  const isPositionManagementPage = computed(() => activeMenuCode.value === POSITION_MENU)

  const userMgmt = useUserManagement({
    isPlatform,
    isUserManagementPage,
    isUserListPage,
    isUserCreatePage,
    activeMenuCode,
    userMenuExpanded,
    creatableIdentityTypes,
    canCreatePlatformUser,
    canCreateCustomerUser,
    assignable,
  })

  const positionMgmt = usePositionManagement({
    isPlatform,
    isPositionManagementPage,
    assignable,
    userForm: userMgmt.userForm,
  })

  const menuConfig = useMenuConfigDialog({ isPlatform })

  function permissionGroupsForForm(type: IdentityType, form: UserIdentityForm) {
    return buildPermissionGroupsForForm(type, assignable.assignMenus, form)
  }

  function goToUserCreate() {
    activeMenuCode.value = USER_CREATE_MENU
    userMenuExpanded.value = true
  }

  watch(activeMenuCode, userMgmt.loadUserManagement)
  watch(activeMenuCode, positionMgmt.loadPositionManagement)
  watch(menuConfig.selectedMenuIdentityType, menuConfig.loadMenuConfigs)

  onMounted(userMgmt.loadUserManagement)
  onMounted(positionMgmt.loadPositionManagement)

  return {
    ...assignable,
    ...userMgmt,
    ...positionMgmt,
    ...menuConfig,
    canCreatePlatformUser,
    canCreateCustomerUser,
    creatableIdentityTypes,
    isUserCreatePage,
    isUserListPage,
    isUserManagementPage,
    isPositionManagementPage,
    permissionGroupsForForm,
    goToUserCreate,
    errorMessage: managementErrorMessage,
  }
}

export type PlatformAdminContext = ReturnType<typeof usePlatformAdmin>
