<script setup lang="ts">
import { usePlatformAdminInject } from './composables/usePlatformAdminInject'

const {
  positionRows,
  openCreatePosition,
  editPosition,
  removePosition,
} = usePlatformAdminInject()
</script>

<template>
  <section class="user-page user-create-page position-page">
    <article class="panel managed-users-panel">
      <div class="panel-head user-list-head">
        <div><h2>职位列表</h2><p>维护运营、销售、交付、客户管理员等职位模板。</p></div>
        <div class="user-list-actions">
          <span>共 {{ positionRows.length }} 个职位</span>
          <button class="primary-btn small-btn" @click="openCreatePosition('PLATFORM')">新增职位</button>
        </div>
      </div>
      <div class="managed-user-list">
        <div v-for="position in positionRows" :key="position.id" class="managed-user-card">
          <div><b>{{ position.position_name }}</b><small>{{ position.identity_type === 'PLATFORM' ? '平台运营端' : '客户企业端' }}</small></div>
          <span>{{ (position.menu_grants?.length || position.menu_ids.length) }} 项权限</span>
          <p>{{ position.description || '暂无说明' }}</p>
          <div class="managed-user-actions">
            <button @click="editPosition(position)">编辑</button>
            <button class="danger" @click="removePosition(position)">删除</button>
          </div>
        </div>
        <div v-if="!positionRows.length" class="mini-empty">暂无职位，请先新增一个。</div>
      </div>
    </article>
  </section>
</template>
