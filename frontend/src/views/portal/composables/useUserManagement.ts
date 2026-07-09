import { reactive, ref, watch, type ComputedRef, type Ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { notifyOperationError } from '../../../utils/requestError'
import { withRetry } from '../../../composables/useRetry'
import type { IdentityType } from '../../../services/auth'
import {
  createManagedUser, deleteManagedUser, getManagedUsers, getTenants, resetManagedUserPassword,
  restoreManagedUser, setManagedUserStatus, updateManagedUser, type ManagedUser, type TenantInfo,
} from '../../../services/management'
import { isDuplicateMergedApproval, isPendingApproval, pendingApprovalMessage } from '../../../services/approvals'
import { USER_LIST_MENU } from '../constants'
import { managementErrorMessage } from '../managementErrorMessage'
import { createEmptyIdentityForm, createUserCreateForm, type UserIdentityForm } from '../permissionGroups'
import { generateInitialPassword } from '../../../utils/password'
import type { AssignableOptions } from './useAssignableOptions'

type UserManagementOptions = {
  isPlatform: ComputedRef<boolean>
  isUserManagementPage: ComputedRef<boolean>
  isUserListPage: ComputedRef<boolean>
  isUserCreatePage: ComputedRef<boolean>
  activeMenuCode: Ref<string>
  userMenuExpanded: Ref<boolean>
  creatableIdentityTypes: ComputedRef<IdentityType[]>
  canCreatePlatformUser: ComputedRef<boolean>
  canCreateCustomerUser: ComputedRef<boolean>
  assignable: AssignableOptions
}

export function useUserManagement(options: UserManagementOptions) {
  const {
    isPlatform, isUserManagementPage, isUserListPage, isUserCreatePage,
    activeMenuCode, userMenuExpanded, creatableIdentityTypes,
    canCreatePlatformUser, canCreateCustomerUser, assignable,
  } = options
  const { assignMenus, roles, positions, loadAssignableOptions, applyPositionToConfig } = assignable

  const tenants = ref<TenantInfo[]>([])
  const managementUsers = ref<ManagedUser[]>([])
  const loadingUsers = ref(false)
  const creatingUser = ref(false)
  const editingUser = ref<ManagedUser | null>(null)
  const editDialog = ref(false)
  const passwordDialog = ref(false)
  const resetPassword = ref(generateInitialPassword())
  const userFilters = reactive({
    keyword: '',
    tenant_id: null as number | null,
    identity_type: '' as IdentityType | '',
    enabled: '' as '' | 'true' | 'false',
    deleted: false,
  })
  const userForm = reactive(createUserCreateForm())
  const editForm = reactive(createEmptyIdentityForm())

  function notifyError(error: unknown, context: string) {
    notifyOperationError(error, context, managementErrorMessage)
  }

  function syncUserFormCreatableIdentities() {
    const allowed = creatableIdentityTypes.value
    userForm.identity_types = userForm.identity_types.filter(type => allowed.includes(type))
    if (!userForm.identity_types.length && allowed.length) userForm.identity_types = [allowed[0]]
  }

  async function loadUserManagement() {
    if (!isPlatform.value || !isUserManagementPage.value) return
    loadingUsers.value = isUserListPage.value
    try {
      const tenantRows = await withRetry(() => getTenants())
      tenants.value = tenantRows
      await loadAssignableOptions(tenants.value, userForm)
      syncUserFormCreatableIdentities()
      if (isUserListPage.value) {
        managementUsers.value = await withRetry(() => getManagedUsers({
          keyword: userFilters.keyword.trim() || undefined,
          tenant_id: userFilters.tenant_id,
          identity_type: userFilters.identity_type,
          enabled: userFilters.enabled === '' ? null : userFilters.enabled === 'true',
          deleted: userFilters.deleted,
        }))
      }
    } catch (error: unknown) {
      notifyError(error, '用户管理基础数据加载失败')
    } finally {
      loadingUsers.value = false
    }
  }

  function resetUserFilters() {
    userFilters.keyword = ''
    userFilters.tenant_id = null
    userFilters.identity_type = ''
    userFilters.enabled = ''
    userFilters.deleted = false
    loadUserManagement()
  }

  function canSelectEditIdentity(type: IdentityType) {
    const alreadyOwned = editingUser.value?.identities.some(identity => identity.identity_type === type)
    if (alreadyOwned) return true
    return type === 'PLATFORM' ? canCreatePlatformUser.value : canCreateCustomerUser.value
  }

  function identityPayloadFromForm(form: UserIdentityForm) {
    return form.identity_types.map((type) => {
      const config = form.identity_configs[type]
      return {
        identity_type: type,
        role_code: config.role_code,
        identity_name: config.identity_name || null,
        position_id: config.position_id,
        tenant_id: type === 'CUSTOMER' ? config.tenant_id : null,
        tenant_name: type === 'CUSTOMER' && !config.tenant_id ? config.tenant_name.trim() : null,
        menu_ids: [],
      }
    })
  }

  function validateEditForm() {
    if (!editForm.display_name.trim() || editForm.display_name.trim().length < 2) {
      ElMessage.warning('用户姓名至少填写 2 个字符')
      return false
    }
    if (!editForm.identity_types.length) {
      ElMessage.warning('至少保留一个登录身份')
      return false
    }
    if (editForm.identity_types.includes('CUSTOMER')) {
      const customerConfig = editForm.identity_configs.CUSTOMER
      if (!customerConfig.tenant_id && !customerConfig.tenant_name.trim()) {
        ElMessage.warning('客户企业端身份需要选择或输入所属企业')
        return false
      }
    }
    if (editForm.identity_types.some(type => !editForm.identity_configs[type].position_id || !editForm.identity_configs[type].role_code)) {
      ElMessage.warning('请补全已勾选身份的职位')
      return false
    }
    return true
  }

  async function submitUser() {
    syncUserFormCreatableIdentities()
    if (!userForm.username || !userForm.display_name || !userForm.password || !userForm.identity_types.length) {
      ElMessage.warning(creatableIdentityTypes.value.length ? '请补全账号、姓名、密码，并至少勾选一个登录身份' : '当前职位没有新增用户身份的权限')
      return
    }
    if (userForm.identity_types.includes('PLATFORM') && !canCreatePlatformUser.value) {
      ElMessage.warning('当前职位无权新增平台运营端用户')
      return
    }
    if (userForm.identity_types.includes('CUSTOMER') && !canCreateCustomerUser.value) {
      ElMessage.warning('当前职位无权新增客户企业端用户')
      return
    }
    if (userForm.username.trim().length < 3) {
      ElMessage.warning('登录账号至少填写 3 个字符')
      return
    }
    if (userForm.display_name.trim().length < 2) {
      ElMessage.warning('用户姓名至少填写 2 个字符')
      return
    }
    if (userForm.password.length < 6) {
      ElMessage.warning('初始密码至少填写 6 个字符')
      return
    }
    if (userForm.identity_types.includes('CUSTOMER')) {
      const customerConfig = userForm.identity_configs.CUSTOMER
      if (!customerConfig.tenant_id && !customerConfig.tenant_name.trim()) {
        ElMessage.warning('客户企业端身份需要选择或输入所属企业')
        return
      }
    }
    const identities = identityPayloadFromForm(userForm)
    if (identities.some(item => !item.role_code || !item.position_id)) {
      ElMessage.warning('请补全已勾选身份的职位')
      return
    }
    creatingUser.value = true
    try {
      const result = await createManagedUser({
        username: userForm.username,
        password: userForm.password,
        display_name: userForm.display_name,
        identities,
      })
      if (isPendingApproval(result)) {
        const msg = pendingApprovalMessage(result, '已提交审批，通过后用户才会创建')
        if (isDuplicateMergedApproval(result)) ElMessage.warning(msg)
        else ElMessage.success(msg)
        userForm.username = ''
        userForm.display_name = ''
        return
      }
      ElMessage.success('用户已新增，并完成菜单权限分配')
      userForm.username = ''
      userForm.display_name = ''
      activeMenuCode.value = USER_LIST_MENU
      userMenuExpanded.value = true
      await loadUserManagement()
    } catch (error: unknown) {
      notifyError(error, '用户新增失败')
    } finally {
      creatingUser.value = false
    }
  }

  async function openEditUser(user: ManagedUser) {
    await loadAssignableOptions(tenants.value, userForm)
    editingUser.value = user
    editForm.display_name = user.display_name
    editForm.identity_types = user.identities.map(identity => identity.identity_type)
    for (const type of ['PLATFORM', 'CUSTOMER'] as IdentityType[]) {
      const current = user.identities.find(identity => identity.identity_type === type)
      editForm.identity_configs[type].role_code = current?.role_code || roles[type][0]?.role_code || ''
      editForm.identity_configs[type].position_id = current?.position_id || positions[type].find(item => item.role_code === editForm.identity_configs[type].role_code)?.id || null
      editForm.identity_configs[type].identity_name = current?.identity_name || (type === 'PLATFORM' ? '平台运营专员' : '客户企业成员')
      editForm.identity_configs[type].tenant_id = current?.tenant_id || (type === 'CUSTOMER' ? tenants.value[0]?.id || null : null)
      editForm.identity_configs[type].tenant_name = ''
      editForm.identity_configs[type].menu_ids = positions[type].find(item => item.id === editForm.identity_configs[type].position_id)?.menu_ids || []
    }
    editDialog.value = true
  }

  async function saveEditUser() {
    if (!editingUser.value || !validateEditForm()) return
    try {
      const identities = identityPayloadFromForm(editForm)
      const keepTypes = new Set(identities.map(item => item.identity_type))
      const remove_identity_types = editingUser.value.identities
        .map(identity => identity.identity_type)
        .filter((type): type is IdentityType => !keepTypes.has(type))
      const result = await updateManagedUser(editingUser.value.id, {
        display_name: editForm.display_name,
        identities,
        remove_identity_types,
      })
      if (isPendingApproval(result)) {
        const msg = pendingApprovalMessage(result, '已提交审批，通过后修改才会生效')
        if (isDuplicateMergedApproval(result)) ElMessage.warning(msg)
        else ElMessage.success(msg)
        editDialog.value = false
        return
      }
      ElMessage.success('用户信息和权限已更新')
      editDialog.value = false
      await loadUserManagement()
    } catch (error: unknown) {
      notifyError(error, '用户信息保存失败')
    }
  }

  function openPasswordDialog(user: ManagedUser) {
    editingUser.value = user
    resetPassword.value = generateInitialPassword()
    passwordDialog.value = true
  }

  async function submitResetPassword() {
    if (!editingUser.value) return
    if (resetPassword.value.length < 6) {
      ElMessage.warning('新密码至少填写 6 个字符')
      return
    }
    try {
      await resetManagedUserPassword(editingUser.value.id, resetPassword.value)
      ElMessage.success('密码已重置')
      passwordDialog.value = false
    } catch (error: unknown) {
      notifyError(error, '密码重置失败')
    }
  }

  async function toggleUserStatus(user: ManagedUser) {
    try {
      await setManagedUserStatus(user.id, !user.status)
      ElMessage.success(user.status ? '账号已禁用' : '账号已启用')
      await loadUserManagement()
    } catch (error: unknown) {
      notifyError(error, '账号状态更新失败')
    }
  }

  async function deleteUser(user: ManagedUser) {
    try {
      await ElMessageBox.confirm(
        `确认删除「${user.display_name}」吗？删除后账号不可登录，默认列表不再展示，可在“已删除账号”中恢复。`,
        '删除用户',
        { confirmButtonText: '确认删除', cancelButtonText: '取消', type: 'warning' },
      )
      await deleteManagedUser(user.id)
      ElMessage.success('账号已删除，可在已删除账号中恢复')
      await loadUserManagement()
    } catch (error: unknown) {
      notifyError(error, '账号删除失败')
    }
  }

  async function restoreUser(user: ManagedUser) {
    try {
      await restoreManagedUser(user.id)
      ElMessage.success('账号已恢复')
      userFilters.deleted = false
      await loadUserManagement()
    } catch (error: unknown) {
      notifyError(error, '账号恢复失败')
    }
  }

  function identityDisplayName(identity?: { position_name?: string | null; identity_name?: string | null; position_id?: number | null; role_code?: string; identity_type?: IdentityType }) {
    if (!identity) return ''
    if (identity.position_name) return identity.position_name
    if (identity.position_id && identity.identity_type) {
      const position = positions[identity.identity_type].find(item => item.id === identity.position_id)
      if (position) return position.position_name
    }
    return identity.identity_name || (identity.identity_type === 'PLATFORM' ? '平台运营端' : '客户企业端')
  }

  watch([isUserCreatePage, creatableIdentityTypes], ([isCreatePage]) => {
    if (isCreatePage) syncUserFormCreatableIdentities()
  }, { immediate: true })

  return {
    tenants,
    managementUsers,
    loadingUsers,
    creatingUser,
    editingUser,
    editDialog,
    passwordDialog,
    resetPassword,
    userFilters,
    userForm,
    editForm,
    notifyError,
    loadUserManagement,
    resetUserFilters,
    canSelectEditIdentity,
    submitUser,
    openEditUser,
    saveEditUser,
    openPasswordDialog,
    submitResetPassword,
    toggleUserStatus,
    deleteUser,
    restoreUser,
    identityDisplayName,
    applyPositionToConfig,
    assignMenus,
    positions,
  }
}
