<script setup lang="ts">
import { Users } from '@lucide/vue'
import { ElOption, ElSelect } from 'element-plus'
import 'element-plus/es/components/select/style/css'
import 'element-plus/es/components/option/style/css'
import { usePlatformAdminInject } from './composables/usePlatformAdminInject'

const {
  loadingUsers,
  managementUsers,
  pagedUsers,
  userPage,
  userTotalPages,
  changeUserPage,
  userFilters,
  tenants,
  loadUserManagement,
  resetUserFilters,
  identityDisplayName,
  openEditUser,
  openPasswordDialog,
  toggleUserStatus,
  deleteUser,
  restoreUser,
  goToUserCreate,
} = usePlatformAdminInject()
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
          <span v-if="loadingUsers">加载中</span>
          <template v-else>
            <span>共 {{ managementUsers.length }} 人</span>
            <span v-if="managementUsers.length">第 {{ userPage }} / {{ userTotalPages }} 页</span>
          </template>
          <button class="primary-btn small-btn" @click="goToUserCreate">新增用户</button>
        </div>
      </div>
      <div class="user-filter-bar">
        <label>
          <span>搜索</span>
          <input v-model="userFilters.keyword" placeholder="姓名 / 账号 / 职位" @keyup.enter="loadUserManagement" />
        </label>
        <label>
          <span>所属公司</span>
          <ElSelect
            v-model="userFilters.tenant_id"
            clearable
            placeholder="全部公司"
            class="portal-field-select"
          >
            <ElOption
              v-for="tenant in tenants"
              :key="tenant.id"
              :label="tenant.name"
              :value="tenant.id"
            />
          </ElSelect>
        </label>
        <label>
          <span>身份</span>
          <ElSelect
            v-model="userFilters.identity_type"
            clearable
            placeholder="全部身份"
            class="portal-field-select"
          >
            <ElOption label="平台运营端" value="PLATFORM" />
            <ElOption label="客户企业端" value="CUSTOMER" />
          </ElSelect>
        </label>
        <label>
          <span>状态</span>
          <ElSelect
            v-model="userFilters.enabled"
            clearable
            placeholder="全部状态"
            class="portal-field-select"
          >
            <ElOption label="启用" value="true" />
            <ElOption label="停用" value="false" />
          </ElSelect>
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
            <button class="filter-search-btn" @click="goToUserCreate">新增用户</button>
          </div>
        </div>
        <div v-for="user in pagedUsers" :key="user.id" class="managed-user-card" :class="{ deleted: user.deleted }">
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
        <div v-if="userTotalPages > 1" class="log-pagination">
          <span class="log-pagination-meta">每页 10 条</span>
          <div class="log-pagination-actions">
            <button
              type="button"
              class="filter-reset-btn tiny-btn"
              :disabled="userPage <= 1"
              @click="changeUserPage(userPage - 1)"
            >
              上一页
            </button>
            <button
              type="button"
              class="filter-reset-btn tiny-btn"
              :disabled="userPage >= userTotalPages"
              @click="changeUserPage(userPage + 1)"
            >
              下一页
            </button>
          </div>
        </div>
      </div>
    </article>
  </section>
</template>
