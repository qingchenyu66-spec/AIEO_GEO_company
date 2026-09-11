<script setup lang="ts">
import { usePlatformAdminInject } from './composables/usePlatformAdminInject'

const {
  positionRows,
  openCreatePosition,
  editPosition,
  removePosition,
  canCreatePosition,
  canUpdatePosition,
  canDeletePosition,
} = usePlatformAdminInject()

function identityLabel(type: string) {
  return type === 'PLATFORM' ? '平台运营端' : '客户企业端'
}

function grantCount(position: { menu_grants?: unknown[]; menu_ids: unknown[] }) {
  return position.menu_grants?.length || position.menu_ids.length || 0
}
</script>

<template>
  <section class="user-page user-create-page position-page">
    <article class="panel managed-users-panel admin-list-panel">
      <div class="admin-toolbar">
        <span class="admin-toolbar-meta">共 {{ positionRows.length }} 个职位</span>
        <button
          v-if="canCreatePosition"
          type="button"
          class="primary-btn small-btn"
          @click="openCreatePosition('PLATFORM')"
        >新增职位</button>
      </div>

      <div v-if="!positionRows.length" class="mini-empty">暂无职位，请先新增一个。</div>
      <div v-else class="admin-table-wrap">
        <table class="admin-table">
          <thead>
            <tr>
              <th class="col-name">职位</th>
              <th class="col-side">所属端</th>
              <th class="col-grants">权限</th>
              <th class="col-desc">说明</th>
              <th class="col-ops">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="position in positionRows" :key="position.id">
              <td class="col-name"><strong>{{ position.position_name }}</strong></td>
              <td class="col-side">{{ identityLabel(position.identity_type) }}</td>
              <td class="col-grants">{{ grantCount(position) }} 项</td>
              <td class="col-desc" :title="position.description || ''">{{ position.description || '—' }}</td>
              <td class="col-ops">
                <div class="ops-cell">
                  <button
                    v-if="canUpdatePosition"
                    type="button"
                    class="plain-btn"
                    @click="editPosition(position)"
                  >编辑</button>
                  <button
                    v-if="canDeletePosition"
                    type="button"
                    class="plain-btn danger"
                    @click="removePosition(position)"
                  >删除</button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
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
  color: #64748b;
  font-size: 13px;
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
.col-name { width: 18%; }
.col-side { width: 14%; color: #425a78; }
.col-grants { width: 10%; color: #425a78; white-space: nowrap; }
.col-desc {
  width: 38%;
  color: #64748b;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.col-ops { width: 20%; }
.col-name strong {
  color: #12253f;
  font-size: 14px;
}
.ops-cell {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
</style>
