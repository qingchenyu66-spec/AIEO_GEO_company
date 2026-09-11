<script setup lang="ts">
import { computed } from 'vue'
import { Building2, HelpCircle, ShieldCheck } from '@lucide/vue'
import type { IdentityType } from '../../services/auth'
import { usePlatformAdminInject } from './composables/usePlatformAdminInject'

const {
  userForm,
  canCreatePlatformUser,
  canCreateCustomerUser,
  creatableIdentityTypes,
  positions,
  tenants,
  creatingUser,
  applyPositionToConfig,
  submitUser,
} = usePlatformAdminInject()

const identityTypes = computed(() => userForm.identity_types as IdentityType[])
const positionsFor = (type: IdentityType) => positions[type] || []
</script>

<template>
  <section class="user-page user-create-page">
    <article class="panel user-create-panel">
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
          <span>初始密码<el-tooltip content="至少 6 个字符；创建后首次登录必须修改密码才能进入系统" placement="top"><HelpCircle /></el-tooltip></span>
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
          <label v-if="type === 'CUSTOMER'"><span>所属企业<el-tooltip content="请选择已有企业；若列表没有，请先到企业管理新建" placement="top"><HelpCircle /></el-tooltip></span><select v-model.number="userForm.identity_configs.CUSTOMER.tenant_id"><option disabled :value="null">{{ tenants.length ? '请选择企业' : '暂无企业，请先新建' }}</option><option v-for="tenant in tenants" :key="tenant.id" :value="tenant.id">{{ tenant.name }}</option></select></label>
        </div>
        <p class="feature-note">权限由职位决定，如需调整请到「用户管理 / 职位管理」中修改功能权限。</p>
      </div>
      <button class="primary-btn" :disabled="creatingUser" @click="submitUser">新增用户并保存权限</button>
    </article>
  </section>
</template>
