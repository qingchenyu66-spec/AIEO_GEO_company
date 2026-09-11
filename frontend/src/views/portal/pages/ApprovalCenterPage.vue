<script setup lang="ts">
import { computed, inject, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  approveOperation,
  listApprovals,
  rejectOperation,
  resubmitTargetForApproval,
  reviseLeadDiagnosisApproval,
  type ApprovalChangeItem,
  type OperationApproval,
} from '../../../services/approvals'
import { useAuthStore } from '../../../stores/auth'
import { ApprovalPendingRefreshKey, PortalNavigateKey } from '../injectionKeys'
import { platformLabelMap } from '../portalMaps'
import { supportedPlatforms } from '../platformMeta'
import {
  buildApprovalScheduleDatetimes,
  formatApprovalScheduleDisplay,
  formatDatetimeLocalInput,
  nextDefaultScheduleDatetime,
  parseScheduleDatetimeMs,
} from '../composables/useLeadDiagnosis'
import RegionMultiSelect from '../components/RegionMultiSelect.vue'
import PlatformBadge from '../../../components/PlatformBadge.vue'

const auth = useAuthStore()
const refreshPendingCount = inject(ApprovalPendingRefreshKey, () => {})
const portalNavigate = inject(PortalNavigateKey, null)
const loading = ref(false)
const savingId = ref<number | null>(null)
const actingId = ref<number | null>(null)
const statusFilter = ref<'pending' | 'approved' | 'rejected' | 'all'>('pending')
const rows = ref<OperationApproval[]>([])
const expandedId = ref<number | null>(null)
const page = ref(1)
const pageSize = 20
const total = ref(0)

type LeadEditForm = {
  brand_name: string
  competitorsText: string
  region_codes: string[]
  platforms: string[]
  schedule_datetimes: string[]
  prompts: string[]
  contact_note: string
}

const scheduleDatetimeMinLocal = computed(() => formatDatetimeLocalInput(new Date()))

const reviewPlatformOptions = supportedPlatforms
const editDialogVisible = ref(false)
const editTarget = ref<OperationApproval | null>(null)
const editForm = reactive<LeadEditForm>({
  brand_name: '',
  competitorsText: '',
  region_codes: [],
  platforms: [],
  schedule_datetimes: [],
  prompts: ['', '', '', '', ''],
  contact_note: '',
})

const canReview = computed(() => {
  const grant = auth.allowedMenus.find(menu => menu.menu_code === 'platform.approvals')
  return Boolean(grant?.can_update)
})

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))
const pagerVisible = computed(() => total.value > pageSize)

function formatCreatedAt(value: string) {
  if (!value) return '—'
  try {
    return new Date(value).toLocaleString('zh-CN', {
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return value
  }
}

function metaLine(row: OperationApproval) {
  const parts = [
    `${row.module_label} · ${row.action_label}`,
    `申请人 ${row.requester_name || row.requester_user_id}`,
  ]
  if (row.tenant_name) parts.push(row.tenant_name)
  parts.push(formatCreatedAt(row.created_at))
  return parts.join(' · ')
}

function isLeadCreate(row: OperationApproval) {
  return row.operation_key === 'lead_diagnosis.create'
}

function detailHint(row: OperationApproval) {
  if (isLeadCreate(row) && leadHasRevision(row)) return '已改'
  if (!isLeadCreate(row) && row.preview?.change_count) return `${row.preview.change_count} 项`
  return ''
}

function leadOriginal(row: OperationApproval): Record<string, unknown> {
  return (row.lead_original_body || row.payload?.original_body || row.payload?.body || {}) as Record<string, unknown>
}

function leadAdopted(row: OperationApproval): Record<string, unknown> {
  return (row.lead_adopted_body || row.payload?.body || {}) as Record<string, unknown>
}

function asStringList(raw: unknown): string[] {
  if (!Array.isArray(raw)) return []
  return raw.map(item => String(item || '').trim()).filter(Boolean)
}

function sameStringList(a: unknown, b: unknown) {
  const left = asStringList(a).slice().sort()
  const right = asStringList(b).slice().sort()
  if (left.length !== right.length) return false
  return left.every((item, idx) => item === right[idx])
}

function sameScheduleDatetimes(a: Record<string, unknown>, b: Record<string, unknown>) {
  const left = buildApprovalScheduleDatetimes(a).slice().sort()
  const right = buildApprovalScheduleDatetimes(b).slice().sort()
  if (left.length !== right.length) return false
  return left.every((item, idx) => item === right[idx])
}

/** 审批采用相对销售原文是否已改过（决定是否出右侧对照列）。 */
function leadHasRevision(row: OperationApproval) {
  const original = leadOriginal(row)
  const adopted = leadAdopted(row)
  return (
    !sameStringList(original.competitors, adopted.competitors)
    || !sameStringList(original.platforms, adopted.platforms)
    || !sameStringList(original.region_codes, adopted.region_codes)
    || !sameScheduleDatetimes(original, adopted)
    || !sameStringList(original.prompts, adopted.prompts)
    || String(original.contact_note || '').trim() !== String(adopted.contact_note || '').trim()
  )
}

function leadFieldRows(row: OperationApproval): Array<{ field: string; before: string; after: string; changed: boolean }> {
  const original = leadOriginal(row)
  const adopted = leadAdopted(row)
  const pairs: Array<{ field: string; before: string; after: string }> = [
    { field: '品牌名称', before: String(original.brand_name || '—'), after: String(adopted.brand_name || '—') },
    { field: '竞品', before: displayList(original.competitors), after: displayList(adopted.competitors) },
    { field: '监测地区', before: displayRegions(original.region_codes), after: displayRegions(adopted.region_codes) },
    { field: '诊断平台', before: displayPlatforms(original.platforms), after: displayPlatforms(adopted.platforms) },
    {
      field: '抓取时间点',
      before: formatApprovalScheduleDisplay(original),
      after: formatApprovalScheduleDisplay(adopted),
    },
    {
      field: '检测问题',
      before: asStringList(original.prompts).map((item, idx) => `${idx + 1}. ${item}`).join('\n') || '（空）',
      after: asStringList(adopted.prompts).map((item, idx) => `${idx + 1}. ${item}`).join('\n') || '（空）',
    },
    {
      field: '销售备注',
      before: String(original.contact_note || '（无）'),
      after: String(adopted.contact_note || '（无）'),
    },
  ]
  return pairs.map(item => ({ ...item, changed: item.before !== item.after }))
}

function fillEditForm(row: OperationApproval) {
  const adopted = leadAdopted(row)
  const original = leadOriginal(row)
  const prompts = asStringList(adopted.prompts)
  while (prompts.length < 5) prompts.push('')
  editForm.brand_name = String(original.brand_name || adopted.brand_name || '')
  editForm.competitorsText = asStringList(adopted.competitors).join('、')
  editForm.region_codes = asStringList(adopted.region_codes)
  editForm.platforms = asStringList(adopted.platforms)
  editForm.schedule_datetimes = buildApprovalScheduleDatetimes(adopted)
  editForm.prompts = prompts.slice(0, 5)
  editForm.contact_note = String(adopted.contact_note || '')
}

function toggleExpand(row: OperationApproval) {
  expandedId.value = expandedId.value === row.id ? null : row.id
}

function openLeadEdit(row: OperationApproval) {
  editTarget.value = row
  fillEditForm(row)
  editDialogVisible.value = true
}

function closeLeadEdit() {
  editDialogVisible.value = false
  editTarget.value = null
}

function changeKindLabel(kind: string) {
  if (kind === 'add') return '新增'
  if (kind === 'update') return '已改'
  if (kind === 'delete') return '删除'
  return '说明'
}

function changeKindClass(kind: string) {
  if (kind === 'add') return 'is-add'
  if (kind === 'update') return 'is-update'
  if (kind === 'delete') return 'is-delete'
  return 'is-info'
}

function displayList(raw: unknown, empty = '（空）') {
  const list = asStringList(raw)
  return list.length ? list.join('、') : empty
}

function displayPlatforms(raw: unknown) {
  const list = asStringList(raw)
  if (!list.length) return '（空）'
  return list.map(code => platformLabelMap[code] || code).join('、')
}

function displayRegions(raw: unknown) {
  const list = asStringList(raw)
  return list.length ? list.join('、') : '全部区域'
}

function addEditScheduleSlot() {
  editForm.schedule_datetimes.push(nextDefaultScheduleDatetime(editForm.schedule_datetimes))
}

function removeEditScheduleSlot(index: number) {
  editForm.schedule_datetimes.splice(index, 1)
}

function togglePlatform(code: string) {
  const idx = editForm.platforms.indexOf(code)
  if (idx >= 0) editForm.platforms.splice(idx, 1)
  else editForm.platforms.push(code)
}

function canResubmit(row: OperationApproval) {
  return !canReview.value && row.status === 'rejected' && Boolean(resubmitTargetForApproval(row))
}

function openResubmit(row: OperationApproval) {
  const target = resubmitTargetForApproval(row)
  if (!target || !portalNavigate) {
    ElMessage.warning('当前审批类型暂不支持在此修改')
    return
  }
  portalNavigate(target.menu, false, target.query)
}

async function loadRows() {
  loading.value = true
  try {
    const data = await listApprovals({
      status: statusFilter.value === 'all' ? undefined : statusFilter.value,
      mine_only: !canReview.value,
      page: page.value,
      page_size: pageSize,
    })
    rows.value = data.items
    total.value = data.total
    if (page.value > 1 && !data.items.length && data.total > 0) {
      page.value = Math.max(1, Math.ceil(data.total / pageSize))
      await loadRows()
      return
    }
  } catch {
    ElMessage.error('审批列表加载失败')
  } finally {
    loading.value = false
    void refreshPendingCount()
  }
}

function switchStatus(next: typeof statusFilter.value) {
  statusFilter.value = next
  page.value = 1
  expandedId.value = null
  void loadRows()
}

function changePage(next: number) {
  if (next < 1 || next > totalPages.value || next === page.value) return
  page.value = next
  expandedId.value = null
  void loadRows()
}

watch(statusFilter, () => {
  expandedId.value = null
})

async function saveLeadReviseFromDialog() {
  const row = editTarget.value
  if (!row || savingId.value) return
  const prompts = editForm.prompts.map(item => item.trim()).filter(Boolean)
  if (!editForm.platforms.length) {
    ElMessage.warning('请至少勾选一个诊断平台')
    return
  }
  if (!prompts.length) {
    ElMessage.warning('请至少填写一个检测问题')
    return
  }
  const scheduleDatetimes = editForm.schedule_datetimes.map(item => item.trim()).filter(Boolean)
  if (!scheduleDatetimes.length) {
    ElMessage.warning('请至少添加一个抓取时间点')
    return
  }
  const now = Date.now()
  for (const value of scheduleDatetimes) {
    const ms = parseScheduleDatetimeMs(value)
    if (ms != null && ms < now) {
      ElMessage.warning('抓取时间点不能早于当前时间')
      return
    }
  }
  savingId.value = row.id
  try {
    const updated = await reviseLeadDiagnosisApproval(row.id, {
      competitors: editForm.competitorsText.split(/[,，、]/).map(item => item.trim()).filter(Boolean),
      platforms: [...editForm.platforms],
      region_codes: [...editForm.region_codes],
      schedule_datetimes: scheduleDatetimes,
      prompts,
      contact_note: editForm.contact_note.trim() || null,
    })
    const idx = rows.value.findIndex(item => item.id === row.id)
    if (idx >= 0) rows.value[idx] = updated
    expandedId.value = updated.id
    closeLeadEdit()
    ElMessage.success('已保存修改（尚未通过，需再点通过才会生效）')
  } catch (error: unknown) {
    const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    ElMessage.error(typeof detail === 'string' && detail ? detail : '保存失败')
  } finally {
    savingId.value = null
  }
}

async function approveRow(row: OperationApproval) {
  if (actingId.value) return
  try {
    await ElMessageBox.confirm(
      isLeadCreate(row) && leadHasRevision(row)
        ? `确认按已保存的「审批采用」内容通过「${row.summary}」？`
        : `确认通过「${row.summary}」？`,
      '审批通过',
      { type: 'warning' },
    )
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
  } catch (error: unknown) {
    const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    ElMessage.error(typeof detail === 'string' && detail ? detail : '审批失败')
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
  } catch (error: unknown) {
    // 2026-08-04 - 已处理单再驳回只显示「驳回失败」- 透出 detail 并刷新列表
    const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    ElMessage.error(typeof detail === 'string' && detail ? detail : '驳回失败')
    await loadRows()
  } finally {
    actingId.value = null
    loading.value = false
  }
}

onMounted(loadRows)
</script>

<template>
  <section class="panel approval-page">
    <div class="approval-toolbar">
      <div class="approval-tabs" role="tablist" aria-label="审批状态">
        <button
          type="button"
          role="tab"
          :aria-selected="statusFilter === 'pending'"
          :class="{ active: statusFilter === 'pending' }"
          @click="switchStatus('pending')"
        >待审批</button>
        <button
          type="button"
          role="tab"
          :aria-selected="statusFilter === 'approved'"
          :class="{ active: statusFilter === 'approved' }"
          @click="switchStatus('approved')"
        >已通过</button>
        <button
          type="button"
          role="tab"
          :aria-selected="statusFilter === 'rejected'"
          :class="{ active: statusFilter === 'rejected' }"
          @click="switchStatus('rejected')"
        >已驳回</button>
        <button
          type="button"
          role="tab"
          :aria-selected="statusFilter === 'all'"
          :class="{ active: statusFilter === 'all' }"
          @click="switchStatus('all')"
        >全部</button>
      </div>
      <div class="approval-toolbar-right">
        <span v-if="!loading" class="approval-total-meta">共 {{ total }} 条</span>
        <button type="button" class="filter-reset-btn" :disabled="loading" @click="loadRows">刷新</button>
      </div>
    </div>

    <div v-if="loading && !rows.length" class="mini-empty">加载中...</div>
    <div v-else-if="!rows.length" class="mini-empty">暂无审批记录</div>
    <div v-else class="approval-inbox">
      <article
        v-for="row in rows"
        :key="row.id"
        class="inbox-item"
        :class="[`is-${row.status}`, { open: expandedId === row.id }]"
      >
        <div class="inbox-row">
          <button type="button" class="inbox-main" @click="toggleExpand(row)">
            <strong class="inbox-title" :title="row.summary">{{ row.summary }}</strong>
            <span class="inbox-meta">{{ metaLine(row) }}</span>
            <span v-if="row.review_comment" class="inbox-comment" :title="row.review_comment">
              意见：{{ row.review_comment }}
            </span>
            <span v-if="detailHint(row)" class="inbox-hint">{{ detailHint(row) }}</span>
          </button>

          <div class="inbox-side">
            <span class="status-tag" :data-status="row.status">{{ row.status_label }}</span>
            <div class="inbox-actions" @click.stop>
              <template v-if="canReview && row.status === 'pending'">
                <button
                  type="button"
                  class="act-btn primary"
                  :disabled="actingId === row.id"
                  @click="approveRow(row)"
                >通过</button>
                <button
                  type="button"
                  class="act-btn ghost"
                  :disabled="actingId === row.id"
                  @click="rejectRow(row)"
                >驳回</button>
              </template>
              <button
                v-else-if="canResubmit(row)"
                type="button"
                class="act-btn primary"
                @click="openResubmit(row)"
              >重新提交</button>
              <button type="button" class="act-btn ghost" @click="toggleExpand(row)">
                {{ expandedId === row.id ? '收起' : '详情' }}
              </button>
            </div>
          </div>
        </div>

        <div v-if="expandedId === row.id" class="inbox-detail">
          <template v-if="isLeadCreate(row)">
            <div class="lead-detail-wrap">
              <button
                v-if="canReview && row.status === 'pending'"
                type="button"
                class="lead-edit-hover-btn"
                @click="openLeadEdit(row)"
              >
                修改
              </button>

              <table v-if="!leadHasRevision(row)" class="approval-change-table">
                <thead>
                  <tr>
                    <th>字段</th>
                    <th>内容</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="item in leadFieldRows(row)" :key="`${row.id}-${item.field}`">
                    <td>{{ item.field }}</td>
                    <td class="pre-line">{{ item.before }}</td>
                  </tr>
                </tbody>
              </table>

              <table v-else class="approval-change-table">
                <thead>
                  <tr>
                    <th>字段</th>
                    <th>销售原文</th>
                    <th>审批采用</th>
                  </tr>
                </thead>
                <tbody>
                  <tr
                    v-for="item in leadFieldRows(row)"
                    :key="`${row.id}-rev-${item.field}`"
                    :class="{ 'is-changed': item.changed }"
                  >
                    <td>{{ item.field }}</td>
                    <td class="pre-line">{{ item.before }}</td>
                    <td class="pre-line">{{ item.after }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </template>

          <template v-else>
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
                  <td>
                    <img v-if="item.before_image_url" :src="item.before_image_url" class="approval-change-logo" alt="" />
                    <template v-else>{{ item.before || '—' }}</template>
                  </td>
                  <td>
                    <img v-if="item.after_image_url" :src="item.after_image_url" class="approval-change-logo" alt="" />
                    <template v-else>{{ item.after || '—' }}</template>
                  </td>
                </tr>
              </tbody>
            </table>
            <div v-else class="mini-empty compact">暂无结构化变更明细</div>
          </template>
        </div>
      </article>

      <div v-if="pagerVisible || total > 0" class="log-pagination">
        <span class="log-pagination-meta">共 {{ total }} 条，第 {{ page }} / {{ totalPages }} 页 · 每页 {{ pageSize }} 条</span>
        <div class="log-pagination-actions">
          <button
            type="button"
            class="filter-reset-btn tiny-btn"
            :disabled="loading || page <= 1"
            @click="changePage(page - 1)"
          >
            上一页
          </button>
          <button
            type="button"
            class="filter-reset-btn tiny-btn"
            :disabled="loading || page >= totalPages"
            @click="changePage(page + 1)"
          >
            下一页
          </button>
        </div>
      </div>
    </div>

    <el-dialog
      v-model="editDialogVisible"
      title="修改审批采用"
      width="720px"
      destroy-on-close
      @closed="editTarget = null"
    >
      <div class="lead-edit-dialog">
        <label class="lead-field">
          <span>品牌名称（不可改）</span>
          <input :value="editForm.brand_name" disabled />
        </label>
        <label class="lead-field">
          <span>竞品</span>
          <input v-model="editForm.competitorsText" placeholder="多个用逗号分隔" />
        </label>
        <div class="lead-field">
          <span>监测地区</span>
          <RegionMultiSelect v-model="editForm.region_codes" />
        </div>
        <div class="lead-field">
          <span>诊断平台</span>
          <div class="platform-check-grid compact">
            <label
              v-for="platform in reviewPlatformOptions"
              :key="platform.code"
              class="platform-check"
              :class="{ 'is-selected': editForm.platforms.includes(platform.code) }"
              @click.prevent="togglePlatform(platform.code)"
            >
              <input type="checkbox" tabindex="-1" :checked="editForm.platforms.includes(platform.code)" />
              <PlatformBadge :code="platform.code" size="sm" :label="platform.name || platformLabelMap[platform.code] || platform.code" />
            </label>
          </div>
        </div>
        <div class="lead-field">
          <span class="lead-schedule-head">
            <em>抓取时间点</em>
            <button type="button" class="filter-reset-btn tiny-btn" @click="addEditScheduleSlot">新增时间</button>
          </span>
          <div
            v-for="(_, index) in editForm.schedule_datetimes"
            :key="`dlg-sch-${index}`"
            class="lead-schedule-row"
          >
            <input
              v-model="editForm.schedule_datetimes[index]"
              type="datetime-local"
              :min="scheduleDatetimeMinLocal"
            />
            <button type="button" class="danger-text-btn" @click="removeEditScheduleSlot(index)">删除</button>
          </div>
          <div v-if="!editForm.schedule_datetimes.length" class="mini-empty compact-empty">
            暂无抓取时间，请点击「新增时间」配置。
          </div>
        </div>
        <label class="lead-field">
          <span>销售备注</span>
          <textarea v-model="editForm.contact_note" rows="2" />
        </label>
        <div class="lead-field">
          <span>检测问题</span>
          <input
            v-for="(_, idx) in editForm.prompts"
            :key="`dlg-p-${idx}`"
            v-model="editForm.prompts[idx]"
            :placeholder="`问题 ${idx + 1}`"
            class="lead-prompt-input"
          />
        </div>
      </div>
      <template #footer>
        <button type="button" class="filter-reset-btn" @click="closeLeadEdit">取消</button>
        <button
          type="button"
          class="filter-search-btn"
          :disabled="savingId === editTarget?.id"
          @click="saveLeadReviseFromDialog"
        >
          {{ savingId === editTarget?.id ? '保存中…' : '保存修改' }}
        </button>
      </template>
    </el-dialog>
  </section>
</template>

<style scoped>
.approval-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
  flex-wrap: wrap;
}
.approval-toolbar-right {
  display: flex;
  align-items: center;
  gap: 10px;
}
.approval-total-meta {
  color: #64748b;
  font-size: 13px;
}
.approval-tabs {
  display: flex;
  gap: 0;
  border-bottom: 1px solid #e6edf5;
}
.approval-tabs button {
  position: relative;
  border: 0;
  background: transparent;
  padding: 10px 16px;
  color: #64748b;
  font-size: 14px;
  cursor: pointer;
}
.approval-tabs button.active {
  color: #1d4fbf;
  font-weight: 600;
}
.approval-tabs button.active::after {
  content: '';
  position: absolute;
  left: 16px;
  right: 16px;
  bottom: -1px;
  height: 2px;
  background: #2d6cdf;
  border-radius: 2px 2px 0 0;
}

.approval-inbox {
  display: flex;
  flex-direction: column;
}
.inbox-item {
  border-bottom: 1px solid #eef2f7;
}
.inbox-item:last-of-type {
  border-bottom: 0;
}
.inbox-item.open {
  background: #f8fbff;
}
.inbox-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 4px;
  min-height: 64px;
}
.inbox-main {
  flex: 1;
  min-width: 0;
  display: grid;
  gap: 4px;
  border: 0;
  background: transparent;
  padding: 0;
  text-align: left;
  cursor: pointer;
}
.inbox-title {
  color: #12253f;
  font-size: 15px;
  font-weight: 600;
  line-height: 1.4;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.inbox-item:hover .inbox-title {
  color: #1d4fbf;
}
.inbox-meta {
  color: #8494a8;
  font-size: 12px;
  line-height: 1.5;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.inbox-comment {
  color: #94a3b8;
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.inbox-hint {
  width: fit-content;
  margin-top: 2px;
  padding: 1px 6px;
  border-radius: 4px;
  background: #eef4ff;
  color: #3b6fd8;
  font-size: 11px;
  font-weight: 600;
}
.inbox-side {
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 8px;
  padding-top: 2px;
}
.status-tag {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 600;
  line-height: 1.4;
}
.status-tag[data-status='pending'] { background: #fff7ed; color: #c2410c; }
.status-tag[data-status='approved'] { background: #ecfdf5; color: #047857; }
.status-tag[data-status='rejected'] { background: #fef2f2; color: #b91c1c; }
.inbox-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.act-btn {
  border: 1px solid #d7e2f0;
  background: #fff;
  color: #334155;
  border-radius: 6px;
  padding: 4px 10px;
  font-size: 12px;
  line-height: 1.4;
  cursor: pointer;
}
.act-btn:hover {
  border-color: #9fc0ea;
  color: #1d4fbf;
}
.act-btn.primary {
  border-color: #2d6cdf;
  background: #2d6cdf;
  color: #fff;
}
.act-btn.primary:hover {
  background: #245dc4;
  border-color: #245dc4;
  color: #fff;
}
.act-btn.ghost {
  background: transparent;
}
.act-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.inbox-detail {
  margin: 0 4px 14px;
  padding: 12px;
  border: 1px solid #e3ebf5;
  border-radius: 8px;
  background: #fff;
}
.approval-change-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.approval-change-table th,
.approval-change-table td {
  border: 1px solid #e3ebf5;
  padding: 8px 10px;
  text-align: left;
  vertical-align: top;
  word-break: break-word;
}
.approval-change-table th {
  color: #5f7390;
  font-weight: 700;
  background: #f1f6fd;
}
.approval-change-table tr.is-changed td:last-child {
  background: #f3f8ff;
}
.approval-change-kind {
  display: inline-block;
  border-radius: 4px;
  padding: 2px 8px;
  font-size: 12px;
}
.approval-change-kind.is-add { background: #dcfce7; color: #166534; }
.approval-change-kind.is-update { background: #dbeafe; color: #1d4ed8; }
.approval-change-kind.is-delete { background: #fee2e2; color: #b91c1c; }
.approval-change-kind.is-info { background: #f3f4f6; color: #4b5563; }
.approval-change-logo {
  max-width: 80px;
  max-height: 80px;
  object-fit: contain;
  vertical-align: middle;
  display: block;
}
.lead-detail-wrap {
  position: relative;
}
.lead-edit-hover-btn {
  position: absolute;
  top: 8px;
  right: 8px;
  z-index: 2;
  opacity: 0;
  pointer-events: none;
  border: 1px solid #2d6cdf;
  background: #fff;
  color: #1d4fbf;
  border-radius: 8px;
  padding: 4px 10px;
  font-size: 12px;
  cursor: pointer;
  transition: opacity .15s ease;
}
.lead-detail-wrap:hover .lead-edit-hover-btn,
.lead-detail-wrap:focus-within .lead-edit-hover-btn {
  opacity: 1;
  pointer-events: auto;
}
@media (hover: none) {
  .lead-edit-hover-btn { opacity: 1; pointer-events: auto; }
}
.pre-line { white-space: pre-line; }
.lead-edit-dialog { display: grid; gap: 12px; }
.lead-field { display: grid; gap: 6px; font-size: 13px; }
.lead-field > span { color: #5f7390; font-size: 12px; font-weight: 600; }
.lead-field input,
.lead-field textarea {
  border: 1px solid #d7e2f0;
  border-radius: 8px;
  padding: 8px 10px;
  font: inherit;
}
.lead-field input:disabled { background: #eef2f7; color: #66788f; }
.lead-prompt-input { margin-top: 6px; }
.lead-schedule-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.lead-schedule-head em {
  font-style: normal;
  color: #5f7390;
  font-size: 12px;
  font-weight: 600;
}
.lead-schedule-row {
  display: flex;
  gap: 8px;
  align-items: center;
}
.lead-schedule-row input { flex: 1; }
.platform-check-grid.compact {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.platform-check {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: 1px solid #d7e2f0;
  border-radius: 999px;
  padding: 4px 10px;
  cursor: pointer;
  background: #fff;
}
.platform-check.is-selected { border-color: #2d6cdf; background: #eef4ff; }
.platform-check input { display: none; }
.mini-empty.compact { padding: 16px; }

@media (max-width: 860px) {
  .inbox-row {
    flex-direction: column;
    gap: 10px;
  }
  .inbox-side {
    width: 100%;
    flex-direction: row;
    align-items: center;
    justify-content: space-between;
  }
}
</style>
