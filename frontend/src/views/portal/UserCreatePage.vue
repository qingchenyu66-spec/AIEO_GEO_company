<script setup lang="ts">
import { computed } from 'vue'
import { Building2, HelpCircle, ShieldCheck } from '@lucide/vue'

type IdentityType = 'PLATFORM' | 'CUSTOMER'

const props = defineProps<{
  userForm: any
  canCreatePlatformUser: boolean
  canCreateCustomerUser: boolean
  creatableIdentityTypes: IdentityType[]
  positions: Record<IdentityType, any[]>
  tenants: any[]
  creatingUser: boolean
  applyPositionToConfig: (type: IdentityType, form: any, positionId: number | null) => void
  permissionGroupsForForm: (type: IdentityType, form: any) => any[]
  menuIcon: (menu: any) => any
  submitUser: () => void
}>()

const identityTypes = computed(() => props.userForm.identity_types as IdentityType[])
const positionsFor = (type: IdentityType) => props.positions[type] || []
</script>

<template>
  <section class="user-page user-create-page">
    <article class="panel user-create-panel">
      <div class="panel-head"><h2>新增用户与权限分配</h2><span>菜单来自数据库</span></div>
      <div class="form-grid">
        <label>
          <span>登录账号<el-tooltip content="至少 3 个字符，建议使用英文、数字或下划线，例如 zhangsan_01" placement="top"><HelpCircle /></el-tooltip></span>
          <input v-model="userForm.username" placeholder="例如 zhangsan_01" />
        </label>
        <label>
          <span>用户姓名<el-tooltip content="至少 2 个字符，用真实姓名或业务昵称，方便后续分辨创建人" placement="top"><HelpCircle /></el-tooltip></span>
          <input v-model="userForm.display_name" placeholder="例如 张三" />
        </label>
        <label>
          <span>初始密码<el-tooltip content="至少 6 个字符，首次演示可用默认密码，正式环境建议强制首次登录修改" placement="top"><HelpCircle /></el-tooltip></span>
          <input v-model="userForm.password" placeholder="至少 6 位" />
        </label>
      </div>
      <div class="identity-checks">
        <label v-if="canCreatePlatformUser" class="identity-check-card">
          <input v-model="userForm.identity_types" type="checkbox" value="PLATFORM" />
          <ShieldCheck />
          <span><b>平台运营端</b><small>可进入本公司后台，按菜单权限管理客户和系统</small></span>
        </label>
        <label v-if="canCreateCustomerUser" class="identity-check-card">
          <input v-model="userForm.identity_types" type="checkbox" value="CUSTOMER" />
          <Building2 />
          <span><b>客户企业端</b><small>可进入客户侧工作台，查看检测、诊断和报告</small></span>
        </label>
      </div>
      <div v-if="!creatableIdentityTypes.length" class="mini-empty">当前职位没有新增用户身份的权限，请到职位管理中分配“新增平台运营端用户”或“新增客户企业端用户”。</div>

      <div v-for="type in identityTypes" :key="type" class="identity-config-box">
        <div class="permission-head">
          <b>{{ type === 'PLATFORM' ? '平台运营端权限' : '客户企业端权限' }}</b>
          <small>{{ type === 'PLATFORM' ? '允许新建、编辑、禁用和导出' : '客户侧默认只读展示，可导出' }}</small>
        </div>
        <div class="form-grid">
          <label><span>职位<el-tooltip content="职位是业务可选项，例如运营、销售、交付；选择后自动带出默认角色和菜单权限" placement="top"><HelpCircle /></el-tooltip></span><select v-model.number="userForm.identity_configs[type].position_id" :disabled="!positionsFor(type).length" @change="applyPositionToConfig(type, userForm, userForm.identity_configs[type].position_id)"><option disabled :value="null">{{ positionsFor(type).length ? '请选择职位' : '职位加载中或暂无职位' }}</option><option v-for="position in positionsFor(type)" :key="position.id" :value="position.id">{{ position.position_name }}</option></select></label>
          <label v-if="type === 'CUSTOMER'"><span>选择已有企业<el-tooltip content="如果客户公司已经存在，直接从这里选择；没有则选择手动输入" placement="top"><HelpCircle /></el-tooltip></span><select v-model.number="userForm.identity_configs.CUSTOMER.tenant_id"><option :value="null">{{ tenants.length ? '不选择，手动输入' : '暂无企业，手动输入' }}</option><option v-for="tenant in tenants" :key="tenant.id" :value="tenant.id">{{ tenant.name }}</option></select></label>
          <label v-if="type === 'CUSTOMER'"><span>新企业名称<el-tooltip content="仅在没有选择已有企业时填写，保存后系统会自动创建这家公司" placement="top"><HelpCircle /></el-tooltip></span><input v-model="userForm.identity_configs.CUSTOMER.tenant_name" :disabled="Boolean(userForm.identity_configs.CUSTOMER.tenant_id)" placeholder="没有企业时直接输入" /></label>
        </div>
        <div class="permission-box permission-group-box" :class="`permission-${type.toLowerCase()}`">
          <div class="permission-side-note">
            <b>{{ type === 'PLATFORM' ? '平台运营端' : '客户企业端' }}</b>
            <span>{{ type === 'PLATFORM' ? '本公司内部后台菜单。' : '客户登录后可见的展示菜单。' }}</span>
          </div>
          <div v-for="group in permissionGroupsForForm(type, userForm)" :key="group.key" class="permission-group">
            <div class="permission-group-head">
              <div><b>{{ group.title }}</b><small>{{ group.note }}</small></div>
              <span>{{ group.checked }}/{{ group.menus.length }}</span>
            </div>
            <label v-for="menu in group.menus" :key="menu.id" class="permission-item">
              <input :checked="userForm.identity_configs[type].menu_ids.includes(menu.id)" type="checkbox" disabled />
              <component :is="menuIcon(menu)" />
              <span>{{ menu.menu_name }}</span>
            </label>
          </div>
        </div>
        <p class="feature-note">权限由职位决定，如需调整请到“用户管理 / 职位管理”中修改职位权限。</p>
      </div>
      <button class="primary-btn" :disabled="creatingUser" @click="submitUser">新增用户并保存权限</button>
    </article>
  </section>
</template>
