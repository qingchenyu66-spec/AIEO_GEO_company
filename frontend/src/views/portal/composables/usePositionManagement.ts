import { computed, reactive, ref, type ComputedRef } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { notifyOperationError } from '../../../utils/requestError'
import type { IdentityType } from '../../../services/auth'
import {
  createManagementPosition,
  deleteManagementPosition,
  updateManagementPosition,
  type PositionInfo,
} from '../../../services/management'
import { managementErrorMessage } from '../managementErrorMessage'
import type { UserIdentityForm } from '../permissionGroups'
import {
  assignablePermissionMenus,
  countActiveGrants,
  createEmptyGrantState,
  grantsFromPosition,
  grantsToPayload,
  permissionModulesFor,
  type MenuGrantState,
} from '../menuPermissionMatrix'
import type { AssignableOptions } from './useAssignableOptions'

type PositionManagementOptions = {
  isPlatform: ComputedRef<boolean>
  isPositionManagementPage: ComputedRef<boolean>
  assignable: AssignableOptions
  userForm: UserIdentityForm & { username: string; password: string }
}

export function usePositionManagement(options: PositionManagementOptions) {
  const { isPlatform, isPositionManagementPage, assignable, userForm } = options
  const { assignMenus, positions, defaultRoleForIdentityType, loadAssignableOptions, refreshPositions } = assignable

  const positionRows = ref<PositionInfo[]>([])
  const editingPosition = ref<PositionInfo | null>(null)
  const positionDialog = ref(false)
  const savingPosition = ref(false)
  const menuGrants = reactive<MenuGrantState>(createEmptyGrantState())
  const allowedMonitorPlatforms = ref<string[]>([])
  const positionForm = reactive({
    position_name: '',
    identity_type: 'PLATFORM' as IdentityType,
    role_code: '',
    description: '',
    status: true,
  })

  const positionFormMenus = computed(() => assignablePermissionMenus(positionForm.identity_type, assignMenus[positionForm.identity_type] || []))
  const permissionModules = computed(() => permissionModulesFor(positionForm.identity_type, assignMenus[positionForm.identity_type] || []))
  const activeGrantCount = computed(() => countActiveGrants(menuGrants))
  const modelsMenu = computed(() => positionFormMenus.value.find(menu => menu.menu_code === 'platform.audit.models') || null)
  // 2026-07-30 - 职位直接勾可选平台；有「平台范围」菜单行就出多选
  const showPlatformAllowSelect = computed(() => Boolean(modelsMenu.value))

  function syncModelsGrantFromAllowlist() {
    const menu = modelsMenu.value
    if (!menu) return
    const on = allowedMonitorPlatforms.value.length > 0
    menuGrants[menu.id] = {
      can_export: on,
      can_create: false,
      can_update: on,
      can_delete: false,
    }
  }

  function notifyError(error: unknown, context: string) {
    notifyOperationError(error, context, managementErrorMessage)
  }

  function resetMenuGrants(type: IdentityType = positionForm.identity_type) {
    const menus = assignablePermissionMenus(type, assignMenus[type] || [])
    for (const key of Object.keys(menuGrants)) {
      delete menuGrants[Number(key)]
    }
    for (const menu of menus) {
      menuGrants[menu.id] = { can_export: false, can_create: false, can_update: false, can_delete: false }
    }
  }

  function resetPositionForm(type: IdentityType = positionForm.identity_type) {
    editingPosition.value = null
    positionForm.position_name = ''
    positionForm.identity_type = type
    positionForm.role_code = defaultRoleForIdentityType(type)
    positionForm.description = ''
    positionForm.status = true
    allowedMonitorPlatforms.value = []
    resetMenuGrants(type)
  }

  function openCreatePosition(type: IdentityType = 'PLATFORM') {
    resetPositionForm(type)
    positionDialog.value = true
  }

  function editPosition(row: PositionInfo) {
    editingPosition.value = row
    positionForm.position_name = row.position_name
    positionForm.identity_type = row.identity_type
    positionForm.role_code = row.role_code
    positionForm.description = row.description || ''
    positionForm.status = true
    allowedMonitorPlatforms.value = [...(row.allowed_monitor_platforms || [])]
    resetMenuGrants(row.identity_type)
    Object.assign(
      menuGrants,
      grantsFromPosition(
        assignablePermissionMenus(row.identity_type, assignMenus[row.identity_type] || []),
        row.menu_grants?.length ? row.menu_grants : row.menu_ids.map(menuId => ({
          menu_id: menuId,
          can_create: false,
          can_update: false,
          can_delete: false,
          can_export: true,
        })),
      ),
    )
    syncModelsGrantFromAllowlist()
    positionDialog.value = true
  }

  function onPositionIdentityTypeChange() {
    positionForm.role_code = defaultRoleForIdentityType(positionForm.identity_type)
    resetMenuGrants(positionForm.identity_type)
  }

  async function loadPositionManagement() {
    if (!isPlatform.value || !isPositionManagementPage.value) return
    await loadAssignableOptions([], userForm)
    positionRows.value = [...positions.PLATFORM, ...positions.CUSTOMER]
    if (!positionForm.role_code) resetPositionForm(positionForm.identity_type)
  }

  async function savePosition() {
    if (!positionForm.position_name.trim()) {
      ElMessage.warning('请填写职位名称')
      return
    }
    if (!positionForm.role_code) {
      ElMessage.warning('职位底层权限未初始化，请刷新后重试')
      return
    }
    // 白名单非空 → 同步 models 授权，再计有效权限项
    syncModelsGrantFromAllowlist()
    if (!activeGrantCount.value) {
      ElMessage.warning('请至少勾选一项功能权限')
      return
    }
    savingPosition.value = true
    try {
      const payload = {
        position_name: positionForm.position_name.trim(),
        identity_type: positionForm.identity_type,
        role_code: positionForm.role_code,
        description: positionForm.description.trim() || null,
        menu_grants: grantsToPayload(menuGrants, positionFormMenus.value),
        menu_ids: [],
        allowed_monitor_platforms: showPlatformAllowSelect.value ? [...allowedMonitorPlatforms.value] : [],
        status: positionForm.status,
      }
      if (editingPosition.value) {
        await updateManagementPosition(editingPosition.value.id, payload)
        ElMessage.success('职位已更新，已绑定该职位的人员需重新登录后生效')
      } else {
        await createManagementPosition(payload)
        ElMessage.success('职位已新增')
      }
      await refreshPositions()
      positionRows.value = [...positions.PLATFORM, ...positions.CUSTOMER]
      positionDialog.value = false
      resetPositionForm(positionForm.identity_type)
    } catch (error: unknown) {
      notifyError(error, '职位保存失败')
    } finally {
      savingPosition.value = false
    }
  }

  async function removePosition(row: PositionInfo) {
    try {
      await ElMessageBox.confirm(`确认删除职位「${row.position_name}」吗？如果已有人员使用该职位，系统会阻止删除。`, '删除职位', { type: 'warning' })
      await deleteManagementPosition(row.id)
      ElMessage.success('职位已删除')
      await refreshPositions()
      positionRows.value = [...positions.PLATFORM, ...positions.CUSTOMER]
      if (editingPosition.value?.id === row.id) resetPositionForm(row.identity_type)
    } catch (error: unknown) {
      notifyError(error, '职位删除失败')
    }
  }

  return {
    positionRows,
    editingPosition,
    positionDialog,
    savingPosition,
    positionForm,
    menuGrants,
    allowedMonitorPlatforms,
    showPlatformAllowSelect,
    positionFormMenus,
    permissionModules,
    activeGrantCount,
    openCreatePosition,
    editPosition,
    onPositionIdentityTypeChange,
    loadPositionManagement,
    savePosition,
    removePosition,
  }
}
