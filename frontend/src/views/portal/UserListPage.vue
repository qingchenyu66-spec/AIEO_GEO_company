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
  filterPositionOptions,
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

function identitySummary(user: {
  identities?: Array<{
    id: number
    tenant_name?: string | null
    position_name?: string | null
    identity_name?: string | null
    position_id?: number | null
    role_code?: string
    identity_type?: string
  }>
}) {
  const rows = user.identities || []
  if (!rows.length) return '—'
  return rows
    .map((identity) => {
      const label = identityDisplayName(identity)
      return identity.tenant_name ? `${label} · ${identity.tenant_name}` : label
    })
    .join('；')
}

function statusLabel(user: { deleted?: boolean; status?: boolean }) {
  if (user.deleted) return '已删除'
  return user.status ? '启用' : '停用'
}
</script>

<template>
  <section class="user-page user-list-page">
    <article class="panel managed-users-panel admin-list-panel">
      <div class="admin-toolbar">
        <div class="admin-toolbar-meta">
          <span v-if="loadingUsers">加载中</span>
          <template v-else>
            <span>共 {{ managementUsers.length }} 人</span>
            <span v-if="managementUsers.length">第 {{ userPage }} / {{ userTotalPages }} 页</span>
          </template>
        </div>
        <button type="button" class="primary-btn small-btn" @click="goToUserCreate">新增用户</button>
      </div>

      <div class="user-filter-bar">
        <label class="user-filter-search">
          <span>搜索</span>
          <input v-model="userFilters.keyword" placeholder="姓名 / 账号 / 职位" @keyup.enter="loadUserManagement" />
        </label>
        <label>
          <span>所属公司</span>
          <ElSelect
            v-model="userFilters.tenant_id"
            clearable
            filterable
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
          <span>所属端</span>
          <ElSelect
            v-model="userFilters.identity_type"
            clearable
            placeholder="全部端"
            class="portal-field-select"
          >
            <ElOption label="平台运营端" value="PLATFORM" />
            <ElOption label="客户企业端" value="CUSTOMER" />
          </ElSelect>
        </label>
        <label>
          <span>职位</span>
          <ElSelect
            v-model="userFilters.position_id"
            clearable
            filterable
            placeholder="全部职位"
            class="portal-field-select"
          >
            <ElOption
              v-for="position in filterPositionOptions"
              :key="position.id"
              :label="position.label"
              :value="position.id"
            />
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
        <div class="user-filter-actions">
          <label class="deleted-filter">
            <input v-model="userFilters.deleted" type="checkbox" />
            <span>已删除账号</span>
          </label>
          <button type="button" class="filter-search-btn" @click="loadUserManagement">查询</button>
          <button type="button" class="filter-reset-btn" @click="resetUserFilters">重置</button>
        </div>
      </div>

      <div v-if="!loadingUsers && !managementUsers.length" class="empty-users">
        <Users />
        <b>暂无匹配用户</b>
        <span>当前筛选条件下没有账号。可以重置筛选，或新增一个用户。</span>
        <div>
          <button type="button" class="filter-reset-btn" @click="resetUserFilters">重置筛选</button>
          <button type="button" class="filter-search-btn" @click="goToUserCreate">新增用户</button>
        </div>
      </div>

      <div v-else class="admin-table-wrap">
        <table class="admin-table">
          <thead>
            <tr>
              <th class="col-user">用户</th>
              <th class="col-identity">身份</th>
              <th class="col-status">状态</th>
              <th class="col-ops">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="user in pagedUsers" :key="user.id" :class="{ deleted: user.deleted }">
              <td class="col-user">
                <strong>{{ user.display_name }}</strong>
                <span class="sub">{{ user.username }}</span>
              </td>
              <td class="col-identity" :title="identitySummary(user)">{{ identitySummary(user) }}</td>
              <td class="col-status">
                <span
                  class="status-tag"
                  :class="{
                    disabled: !user.status || user.deleted,
                    deleted: user.deleted,
                  }"
                >{{ statusLabel(user) }}</span>
              </td>
              <td class="col-ops">
                <div class="ops-cell">
                  <template v-if="!user.deleted">
                    <button type="button" class="plain-btn" @click="openEditUser(user)">编辑/权限</button>
                    <button type="button" class="plain-btn" @click="openPasswordDialog(user)">重置密码</button>
                    <button
                      type="button"
                      class="plain-btn"
                      :class="{ danger: user.status }"
                      @click="toggleUserStatus(user)"
                    >{{ user.status ? '禁用' : '启用' }}</button>
                    <button type="button" class="plain-btn danger" @click="deleteUser(user)">删除</button>
                  </template>
                  <button v-else type="button" class="plain-btn" @click="restoreUser(user)">恢复账号</button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>

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

<style scoped>
.admin-list-panel {
  padding-top: 16px;
}
.admin-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.admin-toolbar-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  color: #64748b;
  font-size: 13px;
}
.admin-table-wrap {
  margin-top: 4px;
}
.admin-table {
  width: 100%;
  border-collapse: collapse;
  table-layout: fixed;
  font-size: 13px;
}
.admin-table th,
.admin-table td {
  border-bottom: 1px solid #eef2f7;
  padding: 12px 10px;
  text-align: left;
  vertical-align: middle;
}
.admin-table th {
  color: #5f7390;
  font-weight: 700;
  background: #f7fafc;
  white-space: nowrap;
}
.admin-table tbody tr:hover td {
  background: #fafcff;
}
.admin-table tbody tr.deleted td {
  opacity: 0.78;
}
.col-user { width: 22%; }
.col-identity { width: 38%; }
.col-status { width: 10%; }
.col-ops { width: 30%; }
.col-user strong {
  display: block;
  color: #12253f;
  font-size: 14px;
}
.col-user .sub {
  display: block;
  margin-top: 3px;
  color: #8494a8;
  font-size: 12px;
}
.col-identity {
  color: #425a78;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.status-tag {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 600;
  color: #047857;
  background: #ecfdf5;
}
.status-tag.disabled {
  color: #b91c1c;
  background: #fef2f2;
}
.status-tag.deleted {
  color: #64748b;
  background: #edf2f7;
}
.ops-cell {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
@media (max-width: 900px) {
  .admin-table { table-layout: auto; }
  .col-identity { white-space: normal; }
}
</style>
