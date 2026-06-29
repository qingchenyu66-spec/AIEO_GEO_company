<script setup lang="ts">
import { Users } from '@lucide/vue'

defineProps<{
  loadingUsers: boolean
  managementUsers: any[]
  userFilters: any
  tenants: any[]
  loadUserManagement: () => void
  resetUserFilters: () => void
  identityDisplayName: (identity: any) => string
  openEditUser: (user: any) => void
  openPasswordDialog: (user: any) => void
  toggleUserStatus: (user: any) => void
  deleteUser: (user: any) => void
  restoreUser: (user: any) => void
}>()

const emit = defineEmits<{
  createUser: []
}>()
</script>

<template>
  <section class="user-page user-list-page">
    <article class="panel managed-users-panel">
      <div class="panel-head user-list-head">
        <div>
          <h2>用户列表</h2>
          <p>集中管理平台账号、客户账号、双身份账号和账号状态</p>
        </div>
        <div class="user-list-actions">
          <span>{{ loadingUsers ? '加载中' : `共 ${managementUsers.length} 人` }}</span>
          <button class="primary-btn small-btn" @click="emit('createUser')">新增用户</button>
        </div>
      </div>
      <div class="user-filter-bar">
        <label>
          <span>搜索</span>
          <input v-model="userFilters.keyword" placeholder="姓名 / 账号 / 职位" @keyup.enter="loadUserManagement" />
        </label>
        <label>
          <span>所属公司</span>
          <select v-model.number="userFilters.tenant_id">
            <option :value="null">全部公司</option>
            <option v-for="tenant in tenants" :key="tenant.id" :value="tenant.id">{{ tenant.name }}</option>
          </select>
        </label>
        <label>
          <span>身份</span>
          <select v-model="userFilters.identity_type">
            <option value="">全部身份</option>
            <option value="PLATFORM">平台运营端</option>
            <option value="CUSTOMER">客户企业端</option>
          </select>
        </label>
        <label>
          <span>状态</span>
          <select v-model="userFilters.enabled">
            <option value="">全部状态</option>
            <option value="true">启用</option>
            <option value="false">停用</option>
          </select>
        </label>
        <label class="deleted-filter">
          <input v-model="userFilters.deleted" type="checkbox" />
          <span>已删除账号</span>
        </label>
        <button class="filter-search-btn" @click="loadUserManagement">查询</button>
        <button class="filter-reset-btn" @click="resetUserFilters">重置</button>
      </div>
      <div class="managed-user-list">
        <div v-if="!loadingUsers && !managementUsers.length" class="empty-users">
          <Users />
          <b>暂无匹配用户</b>
          <span>当前筛选条件下没有账号。可以重置筛选，或新增一个用户。</span>
          <div>
            <button class="filter-reset-btn" @click="resetUserFilters">重置筛选</button>
            <button class="filter-search-btn" @click="emit('createUser')">新增用户</button>
          </div>
        </div>
        <div v-for="user in managementUsers" :key="user.id" class="managed-user-card" :class="{ deleted: user.deleted }">
          <div><b>{{ user.display_name }}</b><small>{{ user.username }}</small></div>
          <span :class="{ disabled: !user.status || user.deleted, deleted: user.deleted }">{{ user.deleted ? '已删除' : user.status ? '启用' : '停用' }}</span>
          <p v-for="identity in user.identities" :key="identity.id">{{ identityDisplayName(identity) }}<em v-if="identity.tenant_name"> · {{ identity.tenant_name }}</em></p>
          <div class="managed-user-actions">
            <template v-if="!user.deleted">
              <button @click="openEditUser(user)">编辑/权限</button>
              <button @click="openPasswordDialog(user)">重置密码</button>
              <button :class="{ danger: user.status }" @click="toggleUserStatus(user)">{{ user.status ? '禁用' : '启用' }}</button>
              <button class="danger" @click="deleteUser(user)">删除</button>
            </template>
            <button v-else @click="restoreUser(user)">恢复账号</button>
          </div>
        </div>
      </div>
    </article>
  </section>
</template>
