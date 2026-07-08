<script setup lang="ts">
import { computed, inject, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { approveOperation, listApprovals, rejectOperation, type ApprovalChangeItem, type OperationApproval } from '../../../services/approvals'
import { useAuthStore } from '../../../stores/auth'
import { ApprovalPendingRefreshKey } from '../injectionKeys'

const auth = useAuthStore()
const refreshPendingCount = inject(ApprovalPendingRefreshKey, () => {})
const loading = ref(false)
const actingId = ref<number | null>(null)
const statusFilter = ref<'pending' | 'approved' | 'rejected' | 'all'>('pending')
const rows = ref<OperationApproval[]>([])
const expandedId = ref<number | null>(null)

const canReview = computed(() => {
  const grant = auth.allowedMenus.find(menu => menu.menu_code === 'platform.approvals')
  return Boolean(grant?.can_update)
})

const filteredRows = computed(() => {
  if (statusFilter.value === 'all') return rows.value
  return rows.value.filter(item => item.status === statusFilter.value)
})

function toggleExpand(row: OperationApproval) {
  expandedId.value = expandedId.value === row.id ? null : row.id
}

function changeKindLabel(kind: string) {
  if (kind === 'add') return '新增'
  if (kind === 'update') return '变更'
  if (kind === 'delete') return '删除'
  return '说明'
}

function changeKindClass(kind: string) {
  if (kind === 'add') return 'is-add'
  if (kind === 'update') return 'is-update'
  if (kind === 'delete') return 'is-delete'
  return 'is-info'
}

async function loadRows() {
  loading.value = true
  try {
    rows.value = await listApprovals({
      status: statusFilter.value === 'all' ? undefined : statusFilter.value,
      mine_only: !canReview.value,
    })
  } catch {
    ElMessage.error('审批列表加载失败')
  } finally {
    loading.value = false
    void refreshPendingCount()
  }
}

async function approveRow(row: OperationApproval) {
  if (actingId.value) return
  try {
    await ElMessageBox.confirm(`确认通过「${row.summary}」？`, '审批通过', { type: 'warning' })
  } catch {
    return
  }
  actingId.value = row.id
  loading.value = true
  try {
    const result = await approveOperation(row.id)
    const executed = (result as { executed_result?: { display_name?: string; username?: string } }).executed_result
    const hint = executed?.display_name && executed?.username
      ? `已创建用户：${executed.display_name}（${executed.username}）`
      : '已通过并执行，相关数据已生效'
    ElMessage.success(hint)
    await loadRows()
  } catch {
    ElMessage.error('审批失败')
  } finally {
    actingId.value = null
    loading.value = false
  }
}

async function rejectRow(row: OperationApproval) {
  if (actingId.value) return
  let comment = ''
  try {
    const { value } = await ElMessageBox.prompt('请输入驳回原因（可选）', '驳回审批', {
      confirmButtonText: '驳回',
      cancelButtonText: '取消',
      inputPlaceholder: '例如：信息不完整，请补充后重新提交',
    })
    comment = value || ''
  } catch {
    return
  }
  actingId.value = row.id
  loading.value = true
  try {
    await rejectOperation(row.id, comment)
    ElMessage.success('已驳回')
    await loadRows()
  } catch {
    ElMessage.error('驳回失败')
  } finally {
    actingId.value = null
    loading.value = false
  }
}

onMounted(loadRows)
</script>

<template>
  <section class="panel approval-page">
    <div class="panel-head">
      <div>
        <h2>操作审批</h2>
        <p>{{ canReview ? '审核销售提交的用户、企业、报告与诊断操作，通过后才会真正生效。' : '查看您已提交、等待运营或管理员审核的操作。' }}</p>
      </div>
      <button class="filter-reset-btn" :disabled="loading" @click="loadRows">刷新</button>
    </div>

    <div class="approval-filter-bar">
      <button :class="{ active: statusFilter === 'pending' }" @click="statusFilter = 'pending'; loadRows()">待审批</button>
      <button :class="{ active: statusFilter === 'approved' }" @click="statusFilter = 'approved'; loadRows()">已通过</button>
      <button :class="{ active: statusFilter === 'rejected' }" @click="statusFilter = 'rejected'; loadRows()">已驳回</button>
      <button :class="{ active: statusFilter === 'all' }" @click="statusFilter = 'all'; loadRows()">全部</button>
    </div>

    <div v-if="loading" class="mini-empty">加载中...</div>
    <div v-else-if="!filteredRows.length" class="mini-empty">暂无审批记录</div>
    <div v-else class="approval-list">
      <article v-for="row in filteredRows" :key="row.id" class="approval-card" :class="[`is-${row.status}`, { expanded: expandedId === row.id }]">
        <div class="approval-card-main">
          <strong>{{ row.summary }}</strong>
          <span>{{ row.module_label }} · {{ row.action_label }} · {{ row.status_label }}</span>
          <span v-if="row.tenant_name">企业：{{ row.tenant_name }}</span>
          <span>申请人：{{ row.requester_name || row.requester_user_id }} · {{ new Date(row.created_at).toLocaleString('zh-CN') }}</span>
          <span v-if="row.review_comment">审批意见：{{ row.review_comment }}</span>
          <button type="button" class="approval-detail-toggle" @click="toggleExpand(row)">
            {{ expandedId === row.id ? '收起详情' : '查看变更详情' }}
            <template v-if="row.preview?.change_count">（{{ row.preview.change_count }} 项）</template>
          </button>
        </div>
        <div v-if="expandedId === row.id" class="approval-detail-panel">
          <table v-if="row.preview?.changes?.length" class="approval-change-table">
            <thead>
              <tr>
                <th>类型</th>
                <th>字段</th>
                <th>变更前</th>
                <th>变更后</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(item, index) in row.preview?.changes as ApprovalChangeItem[]" :key="`${row.id}-${index}`">
                <td><span class="approval-change-kind" :class="changeKindClass(item.kind)">{{ changeKindLabel(item.kind) }}</span></td>
                <td>{{ item.field }}</td>
                <td>{{ item.before || '—' }}</td>
                <td>{{ item.after || '—' }}</td>
              </tr>
            </tbody>
          </table>
          <div v-else class="mini-empty compact">暂无结构化变更明细</div>
        </div>
        <div v-if="canReview && row.status === 'pending'" class="approval-card-actions">
          <button class="filter-search-btn" @click="approveRow(row)">通过</button>
          <button class="danger-text-btn" @click="rejectRow(row)">驳回</button>
        </div>
      </article>
    </div>
  </section>
</template>

<style scoped>
.approval-filter-bar { display:flex; gap:8px; margin-bottom:16px; flex-wrap:wrap; }
.approval-filter-bar button {
  border:1px solid #d7e6f7; background:#fff; border-radius:999px; padding:6px 14px; cursor:pointer;
}
.approval-filter-bar button.active { background:#eef4ff; border-color:#2d6cdf; color:#1d4fbf; }
.approval-list { display:grid; gap:12px; }
.approval-card {
  display:grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap:12px;
  padding:14px 16px;
  border:1px solid #dbe8f5;
  border-radius:12px;
  background:#fff;
}
.approval-card.expanded { grid-template-columns: 1fr; }
.approval-card.is-pending { border-left:4px solid #d97706; }
.approval-card.is-approved { border-left:4px solid #059669; }
.approval-card.is-rejected { border-left:4px solid #dc2626; }
.approval-card-main { display:grid; gap:4px; min-width:0; grid-column: 1 / -1; }
.approval-card-main strong { font-size:15px; color:#12253f; }
.approval-card-main span { color:#6d8099; font-size:12px; }
.approval-detail-toggle {
  justify-self:start;
  margin-top:4px;
  padding:0;
  border:none;
  background:none;
  color:#2d6cdf;
  font-size:12px;
  font-weight:700;
  cursor:pointer;
}
.approval-detail-panel {
  grid-column: 1 / -1;
  padding:12px;
  border:1px solid #e3edf8;
  border-radius:10px;
  background:#f8fbff;
}
.approval-change-table {
  width:100%;
  border-collapse:collapse;
  font-size:12px;
}
.approval-change-table th,
.approval-change-table td {
  padding:8px 10px;
  border-bottom:1px solid #e6eef8;
  text-align:left;
  vertical-align:top;
}
.approval-change-table th { color:#5f7390; font-weight:700; background:#f1f6fd; }
.approval-change-kind {
  display:inline-block;
  padding:2px 8px;
  border-radius:999px;
  font-size:11px;
  font-weight:700;
}
.approval-change-kind.is-add { background:#dcfce7; color:#166534; }
.approval-change-kind.is-update { background:#dbeafe; color:#1d4ed8; }
.approval-change-kind.is-delete { background:#fee2e2; color:#b91c1c; }
.approval-change-kind.is-info { background:#f3f4f6; color:#4b5563; }
.approval-card-actions {
  display:flex;
  gap:8px;
  align-items:flex-start;
  flex-shrink:0;
  grid-column: 2;
  grid-row: 1;
}
.approval-card.expanded .approval-card-actions {
  grid-column: 1 / -1;
  justify-content:flex-end;
}
.mini-empty.compact { padding:8px 0; }
</style>
