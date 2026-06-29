import { computed, reactive, ref, watch, type ComputedRef } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { notifyOperationError } from '../../../utils/requestError'
import type { IdentityType } from '../../../services/auth'
import {
  createManagementPosition, deleteManagementPosition, updateManagementPosition, type PositionInfo,
} from '../../../services/management'
import { managementErrorMessage } from '../managementErrorMessage'
import { permissionGroupsFor } from '../permissionGroups'
import type { UserIdentityForm } from '../permissionGroups'
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
  const positionForm = reactive({
    position_name: '',
    identity_type: 'PLATFORM' as IdentityType,
    role_code: '',
    description: '',
    menu_ids: [] as number[],
    status: true,
  })

  const positionFormMenus = computed(() => assignMenus[positionForm.identity_type] || [])

  function notifyError(error: unknown, context: string) {
    notifyOperationError(error, context, managementErrorMessage)
  }

  function permissionGroupsForPosition(type: IdentityType, selectedMenuIds: number[] = []) {
    return permissionGroupsFor(type, assignMenus, selectedMenuIds)
  }

  function resetPositionForm(type: IdentityType = positionForm.identity_type) {
    editingPosition.value = null
    positionForm.position_name = ''
    positionForm.identity_type = type
    positionForm.role_code = defaultRoleForIdentityType(type)
    positionForm.description = ''
    positionForm.menu_ids = []
    positionForm.status = true
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
    positionForm.menu_ids = [...row.menu_ids]
    positionForm.status = true
    positionDialog.value = true
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
    savingPosition.value = true
    try {
      const payload = {
        position_name: positionForm.position_name.trim(),
        identity_type: positionForm.identity_type,
        role_code: positionForm.role_code,
        description: positionForm.description.trim() || null,
        menu_ids: positionForm.menu_ids,
        status: positionForm.status,
      }
      if (editingPosition.value) {
        await updateManagementPosition(editingPosition.value.id, payload)
        ElMessage.success('职位已更新')
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

  watch(() => positionForm.identity_type, (type) => {
    positionForm.role_code = defaultRoleForIdentityType(type)
    positionForm.menu_ids = positionForm.menu_ids.filter(menuId => positionFormMenus.value.some(menu => menu.id === menuId))
  })

  return {
    positionRows,
    editingPosition,
    positionDialog,
    savingPosition,
    positionForm,
    positionFormMenus,
    permissionGroupsForPosition,
    openCreatePosition,
    editPosition,
    loadPositionManagement,
    savePosition,
    removePosition,
  }
}
