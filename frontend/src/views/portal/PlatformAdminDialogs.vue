<script setup lang="ts">
import { Building2, HelpCircle, ShieldCheck } from '@lucide/vue'
import { usePlatformAdminInject } from './composables/usePlatformAdminInject'
import { menuIcon } from './menuIcons'
import { actionsForMenu, actionLabelForMenu, countPermissionRows } from './menuPermissionMatrix'
import { supportedPlatforms } from './platformMeta'

const admin = usePlatformAdminInject()
const platformAllowOptions = supportedPlatforms
const {
  positionDialog,
  editingPosition,
  positionForm,
  savingPosition,
  savePosition,
  permissionModules,
  activeGrantCount,
  onPositionIdentityTypeChange,
  // 2026-07-30 - admin.xxx 嵌套 ref 不解包，el-select 多选空白 - 提到顶层再绑
  allowedMonitorPlatforms,
  showPlatformAllowSelect,
  editDialog,
  editingUser,
  editForm,
  canSelectEditIdentity,
  positions,
  tenants,
  applyPositionToConfig,
  saveEditUser,
  passwordDialog,
  resetPassword,
  submitResetPassword,
  menuConfigDialog,
  selectedMenuIdentityType,
  loadingMenuConfigs,
  menuConfigs,
  editingMenuConfig,
  menuConfigForm,
  savingMenuConfig,
  loadMenuConfigs,
  startEditMenuConfig,
  cancelEditMenuConfig,
  saveMenuConfig,
} = admin

function actionOptions(type: 'PLATFORM' | 'CUSTOMER', menuCode: string) {
  return actionsForMenu(menuCode, type)
}

function isAllowedPlatform(code: string) {
  return allowedMonitorPlatforms.value.includes(code)
}

function toggleAllowedPlatform(code: string, event: Event) {
  // 2026-07-30 - el-select 未全局注册导致空白；改原生勾选芯片
  const checked = (event.target as HTMLInputElement).checked
  const next = new Set(allowedMonitorPlatforms.value)
  if (checked) next.add(code)
  else next.delete(code)
  allowedMonitorPlatforms.value = platformAllowOptions
    .map(item => item.code)
    .filter(item => next.has(item))
}
</script>

<template>
  <el-dialog v-model="positionDialog" width="920px" :title="editingPosition ? '编辑职位' : '新增职位'" class="user-maintain-dialog">
    <div class="form-grid">
      <label><span>职位名称</span><input v-model="positionForm.position_name" placeholder="例如 运营、销售、交付" /></label>
      <label><span>适用端</span><select v-model="positionForm.identity_type" @change="onPositionIdentityTypeChange"><option value="PLATFORM">平台运营端</option><option value="CUSTOMER">客户企业端</option></select></label>
      <label><span>状态</span><select v-model="positionForm.status"><option :value="true">启用</option><option :value="false">停用</option></select></label>
      <label class="form-field-full"><span>职位说明</span><textarea v-model="positionForm.description" rows="3" placeholder="说明这个职位适合哪些人员、默认能做哪些事"></textarea></label>
    </div>
    <div class="permission-head">
      <b>职位功能权限</b>
        <small>按菜单实际能力勾选；不会出现菜单里没有的功能项。</small>
    </div>
    <div class="permission-box permission-group-box" :class="`permission-${positionForm.identity_type.toLowerCase()}`">
      <div class="permission-side-note">
        <b>{{ positionForm.identity_type === 'PLATFORM' ? '平台运营端' : '客户企业端' }}</b>
        <span>已配置 {{ activeGrantCount }} 项功能权限。</span>
      </div>
      <div v-for="group in permissionModules" :key="group.key" class="permission-group">
        <div class="permission-group-head">
          <div><b>{{ group.title }}</b><small>{{ group.note }}</small></div>
          <span>{{ countPermissionRows(group.rows, admin.menuGrants).active }}/{{ countPermissionRows(group.rows, admin.menuGrants).total }}</span>
        </div>
        <div
          v-for="row in group.rows"
          :key="`${row.menu.id}-${row.headerOnly ? 'header' : 'item'}`"
          class="permission-action-row"
          :class="{ 'permission-action-row-nested': row.indent > 0, 'permission-action-row-header': row.headerOnly }"
        >
          <div class="permission-action-title" :style="row.indent ? { paddingLeft: `${row.indent * 18}px` } : undefined">
            <component :is="menuIcon(row.menu)" />
            <span>{{ row.menu.menu_name }}</span>
          </div>
          <div v-if="!row.headerOnly && actionOptions(positionForm.identity_type, row.menu.menu_code).length" class="permission-action-options">
            <label v-for="action in actionOptions(positionForm.identity_type, row.menu.menu_code)" :key="`${row.menu.id}-${action}`" class="permission-action-chip">
              <input v-model="admin.menuGrants[row.menu.id][action]" type="checkbox" />
              <span>{{ actionLabelForMenu(row.menu.menu_code, action) }}</span>
            </label>
          </div>
          <!-- 2026-07-30 - 平台范围=按职位勾选可配端；不用未注册的 el-select -->
          <div
            v-if="row.menu.menu_code === 'platform.audit.models' && showPlatformAllowSelect"
            class="permission-platform-allow"
          >
            <span class="permission-platform-allow-label">可配置平台（按职位不同；不选则不能勾任何平台）</span>
            <div class="permission-action-options">
              <label
                v-for="platform in platformAllowOptions"
                :key="platform.code"
                class="permission-action-chip"
              >
                <input
                  type="checkbox"
                  :checked="isAllowedPlatform(platform.code)"
                  @change="toggleAllowedPlatform(platform.code, $event)"
                />
                <span>{{ platform.name }}</span>
              </label>
            </div>
          </div>
        </div>
      </div>
    </div>
    <template #footer>
      <button class="plain-btn" @click="positionDialog = false">取消</button>
      <button class="primary-btn" :disabled="savingPosition" @click="savePosition">{{ editingPosition ? '保存职位修改' : '新增职位' }}</button>
    </template>
  </el-dialog>

  <el-dialog v-model="editDialog" width="860px" title="编辑用户与权限" class="user-maintain-dialog">
    <div class="form-grid">
      <label><span>登录账号</span><input :value="editingUser?.username" disabled /></label>
      <label><span>用户姓名<el-tooltip content="至少 2 个字符，展示在用户列表和登录身份信息里" placement="top"><HelpCircle /></el-tooltip></span><input v-model="editForm.display_name" /></label>
    </div>
    <div class="identity-checks">
      <label v-if="canSelectEditIdentity('PLATFORM')" class="identity-check-card">
        <input v-model="editForm.identity_types" type="checkbox" value="PLATFORM" />
        <ShieldCheck />
        <span><b>平台运营端</b><small>允许进入本公司后台</small></span>
      </label>
      <label v-if="canSelectEditIdentity('CUSTOMER')" class="identity-check-card">
        <input v-model="editForm.identity_types" type="checkbox" value="CUSTOMER" />
        <Building2 />
        <span><b>客户企业端</b><small>允许进入客户侧工作台</small></span>
      </label>
    </div>
    <div v-for="type in editForm.identity_types" :key="type" class="identity-config-box">
      <div class="permission-head">
        <b>{{ type === 'PLATFORM' ? '平台运营端权限' : '客户企业端权限' }}</b>
        <small>{{ type === 'PLATFORM' ? '允许新建、编辑、禁用和导出' : '客户侧默认只读展示，可导出' }}</small>
      </div>
      <div class="form-grid">
        <label><span>职位</span><select v-model.number="editForm.identity_configs[type].position_id" :disabled="!positions[type].length" @change="applyPositionToConfig(type, editForm, editForm.identity_configs[type].position_id)"><option disabled :value="null">{{ positions[type].length ? '请选择职位' : '职位加载中或暂无职位' }}</option><option v-for="position in positions[type]" :key="position.id" :value="position.id">{{ position.position_name }}</option></select></label>
        <label v-if="type === 'CUSTOMER'"><span>所属企业<el-tooltip content="请选择已有企业；若列表没有，请先到企业管理新建" placement="top"><HelpCircle /></el-tooltip></span><select v-model.number="editForm.identity_configs.CUSTOMER.tenant_id"><option disabled :value="null">{{ tenants.length ? '请选择企业' : '暂无企业，请先新建' }}</option><option v-for="tenant in tenants" :key="tenant.id" :value="tenant.id">{{ tenant.name }}</option></select></label>
      </div>
      <p class="feature-note">权限由职位决定，如需调整请到「用户管理 / 职位管理」中修改功能权限。</p>
    </div>
    <template #footer>
      <button class="plain-btn" @click="editDialog = false">取消</button>
      <button class="primary-btn" @click="saveEditUser">保存修改</button>
    </template>
  </el-dialog>

  <el-dialog v-model="passwordDialog" width="460px" title="重置密码">
    <div class="form-grid password-grid">
      <label><span>用户</span><input :value="editingUser ? `${editingUser.display_name}（${editingUser.username}）` : ''" disabled /></label>
      <label><span>新密码<el-tooltip content="至少 6 个字符，重置后用户下次登录必须修改密码" placement="top"><HelpCircle /></el-tooltip></span><input v-model="resetPassword" /></label>
    </div>
    <template #footer>
      <button class="plain-btn" @click="passwordDialog = false">取消</button>
      <button class="primary-btn" @click="submitResetPassword">确认重置</button>
    </template>
  </el-dialog>

  <el-dialog v-model="menuConfigDialog" width="920px" title="菜单配置管理" class="user-maintain-dialog">
    <div class="menu-config-header">
      <div class="identity-type-tabs">
        <button :class="{ active: selectedMenuIdentityType === 'PLATFORM' }" @click="selectedMenuIdentityType = 'PLATFORM'">平台运营端</button>
        <button :class="{ active: selectedMenuIdentityType === 'CUSTOMER' }" @click="selectedMenuIdentityType = 'CUSTOMER'">客户企业端</button>
      </div>
      <button class="primary-btn" @click="loadMenuConfigs">刷新</button>
    </div>
    <div v-if="loadingMenuConfigs" class="mini-empty">加载中...</div>
    <div v-else-if="!menuConfigs.length" class="mini-empty">暂无菜单配置，请点「刷新」重试。</div>
    <div v-else class="menu-config-table">
      <table>
        <thead>
          <tr>
            <th>菜单编码</th>
            <th>当前名称</th>
            <th>显示名称</th>
            <th>排序</th>
            <th>功能</th>
            <th>侧栏</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="config in menuConfigs" :key="config.id">
            <td>{{ config.menu_code }}</td>
            <td>{{ config.menu_name }}</td>
            <td>
              <input v-if="editingMenuConfig?.id === config.id" v-model="menuConfigForm.menu_name" placeholder="输入新的显示名称" />
              <span v-else>{{ config.menu_name }}</span>
            </td>
            <td>
              <input v-if="editingMenuConfig?.id === config.id" v-model.number="menuConfigForm.sort_order" type="number" min="1" style="width: 80px" />
              <span v-else>{{ config.sort_order }}</span>
            </td>
            <td>
              <select v-if="editingMenuConfig?.id === config.id" v-model="menuConfigForm.is_visible">
                <option :value="true">启用</option>
                <option :value="false">关闭</option>
              </select>
              <span v-else :class="{ 'status-disabled': !config.is_visible }">{{ config.is_visible ? '启用' : '关闭' }}</span>
            </td>
            <td>
              <select v-if="editingMenuConfig?.id === config.id" v-model="menuConfigForm.show_in_sidebar">
                <option :value="true">显示</option>
                <option :value="false">隐藏</option>
              </select>
              <span v-else :class="{ 'status-disabled': config.show_in_sidebar === false }">{{ config.show_in_sidebar === false ? '隐藏' : '显示' }}</span>
            </td>
            <td class="action-buttons">
              <button v-if="editingMenuConfig?.id !== config.id" class="plain-btn small-btn" @click="startEditMenuConfig(config)">编辑</button>
              <button v-if="editingMenuConfig?.id === config.id" class="primary-btn small-btn" :disabled="savingMenuConfig" @click="saveMenuConfig(config.id)">保存</button>
              <button v-if="editingMenuConfig?.id === config.id" class="plain-btn small-btn" @click="cancelEditMenuConfig">取消</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <template #footer>
      <button class="plain-btn" @click="menuConfigDialog = false">关闭</button>
    </template>
  </el-dialog>
</template>
