<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  createAnnouncement,
  deleteAnnouncement,
  listAnnouncements,
  offlineAnnouncement,
  updateAnnouncement,
  type AnnouncementAction,
  type AnnouncementItem,
  type AnnouncementTarget,
} from '../../../services/announcements'
import { getTenants, type TenantInfo } from '../../../services/management'
import { useAuthStore } from '../../../stores/auth'
import { notifyOperationError } from '../../../utils/requestError'
import AnnouncementEditor from '../components/AnnouncementEditor.vue'
import { persistAnnouncementHtml } from '../../../services/announcementHtml'

const auth = useAuthStore()
const loading = ref(false)
const saving = ref(false)
const rows = ref<AnnouncementItem[]>([])
const tenants = ref<TenantInfo[]>([])
const editingId = ref<number | null>(null)
const dialogVisible = ref(false)

const grant = computed(() => auth.allowedMenus.find(m => m.menu_code === 'platform.announcements'))
const canCreate = computed(() => Boolean(grant.value?.can_create))
const canUpdate = computed(() => Boolean(grant.value?.can_update))
const canDelete = computed(() => Boolean(grant.value?.can_delete))

const form = reactive({
  title: '',
  body_html: '',
  target_platform_all: true,
  target_customer_all: false,
  target_customer_tenants: false,
  tenant_ids: [] as number[],
  publish_at: '' as string,
  expire_at: '' as string,
  action: 'publish_now' as AnnouncementAction,
})

const statusLabel: Record<string, string> = {
  draft: '草稿',
  scheduled: '定时待发',
  published: '已发布',
  off: '已下线',
}

function resetForm() {
  editingId.value = null
  form.title = ''
  form.body_html = ''
  form.target_platform_all = true
  form.target_customer_all = false
  form.target_customer_tenants = false
  form.tenant_ids = []
  form.publish_at = ''
  form.expire_at = ''
  form.action = 'publish_now'
}

function openCreate() {
  resetForm()
  dialogVisible.value = true
}

function openEdit(row: AnnouncementItem) {
  editingId.value = row.id
  form.title = row.title
  form.body_html = row.body_html
  form.target_platform_all = row.targets.includes('platform_all')
  form.target_customer_all = row.targets.includes('customer_all')
  form.target_customer_tenants = row.targets.includes('customer_tenants')
  form.tenant_ids = [...(row.tenant_ids || [])]
  form.publish_at = row.publish_at ? row.publish_at.slice(0, 16) : ''
  form.expire_at = row.expire_at ? row.expire_at.slice(0, 16) : ''
  form.action = row.status === 'scheduled' ? 'schedule' : row.status === 'draft' ? 'draft' : 'publish_now'
  dialogVisible.value = true
}

function buildTargets(): AnnouncementTarget[] {
  const targets: AnnouncementTarget[] = []
  if (form.target_platform_all) targets.push('platform_all')
  if (form.target_customer_all) targets.push('customer_all')
  if (form.target_customer_tenants) targets.push('customer_tenants')
  return targets
}

function onCustomerAllChange(val: boolean) {
  if (val) {
    form.target_customer_tenants = false
    form.tenant_ids = []
  }
}

function onCustomerTenantsChange(val: boolean) {
  if (val) form.target_customer_all = false
}

function toIsoOrNull(local: string) {
  if (!local) return null
  // datetime-local → 本地墙钟，不加 Z，与服务器 Asia/Shanghai 一致
  return local.length === 16 ? `${local}:00` : local
}

async function load() {
  loading.value = true
  try {
    rows.value = await listAnnouncements()
  } catch (error: unknown) {
    notifyOperationError(error, '加载公告失败')
  } finally {
    loading.value = false
  }
}

async function save() {
  const targets = buildTargets()
  if (!form.title.trim()) {
    ElMessage.warning('请填写标题')
    return
  }
  if (!form.body_html.trim() || form.body_html === '<br>') {
    ElMessage.warning('请填写正文')
    return
  }
  // 确保持久化路径而非 blob:
  form.body_html = persistAnnouncementHtml(form.body_html)
  // 2026-07-28 - 残留 data: 图会被消毒丢掉且曾撑爆字数上限
  if (/data:image\//i.test(form.body_html)) {
    ElMessage.warning('正文里还有未上传的粘贴图片，请删除后重新粘贴或用工具栏插入')
    return
  }
  if (!targets.length) {
    ElMessage.warning('请至少选择一个受众')
    return
  }
  if (targets.includes('customer_tenants') && !form.tenant_ids.length) {
    ElMessage.warning('请选择指定企业')
    return
  }
  saving.value = true
  try {
    const payload = {
      title: form.title.trim(),
      body_html: form.body_html,
      targets,
      tenant_ids: form.tenant_ids,
      publish_at: form.action === 'schedule' ? toIsoOrNull(form.publish_at) : form.publish_at ? toIsoOrNull(form.publish_at) : null,
      expire_at: toIsoOrNull(form.expire_at),
      action: form.action,
    }
    if (editingId.value) {
      await updateAnnouncement(editingId.value, payload)
      ElMessage.success('公告已更新')
    } else {
      await createAnnouncement(payload)
      ElMessage.success('公告已创建')
    }
    dialogVisible.value = false
    await load()
  } catch (error: unknown) {
    notifyOperationError(error, '保存失败')
  } finally {
    saving.value = false
  }
}

async function takeOffline(row: AnnouncementItem) {
  try {
    await ElMessageBox.confirm(`确认下线「${row.title}」？`, '下线公告', { type: 'warning' })
  } catch {
    return
  }
  try {
    await offlineAnnouncement(row.id)
    ElMessage.success('已下线')
    await load()
  } catch (error: unknown) {
    notifyOperationError(error, '下线失败')
  }
}

async function removeRow(row: AnnouncementItem) {
  try {
    await ElMessageBox.confirm(`确认删除「${row.title}」？`, '删除公告', { type: 'warning' })
  } catch {
    return
  }
  try {
    await deleteAnnouncement(row.id)
    ElMessage.success('已删除')
    await load()
  } catch (error: unknown) {
    notifyOperationError(error, '删除失败')
  }
}

function audienceText(row: AnnouncementItem) {
  const parts: string[] = []
  if (row.targets.includes('platform_all')) parts.push('运营全员')
  if (row.targets.includes('customer_all')) parts.push('客户全员')
  if (row.targets.includes('customer_tenants')) parts.push(`指定企业(${row.tenant_ids.length})`)
  return parts.join('、') || '-'
}

onMounted(async () => {
  await load()
  try {
    tenants.value = await getTenants()
  } catch {
    tenants.value = []
  }
})
</script>

<template>
  <section class="announcement-page">
    <div class="announcement-toolbar">
      <span class="announcement-toolbar-meta">共 {{ rows.length }} 条</span>
      <button v-if="canCreate" type="button" class="primary-btn small-btn" @click="openCreate">新建公告</button>
    </div>

    <div v-loading="loading" class="announcement-table-wrap">
      <table class="data-table">
        <thead>
          <tr>
            <th>标题</th>
            <th>受众</th>
            <th>状态</th>
            <th>上线</th>
            <th>失效</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="row.id">
            <td>{{ row.title }}</td>
            <td>{{ audienceText(row) }}</td>
            <td>{{ statusLabel[row.status] || row.status }}</td>
            <td>{{ row.publish_at || '-' }}</td>
            <td>{{ row.expire_at || '-' }}</td>
            <td class="ops">
              <button v-if="canUpdate" type="button" class="plain-btn" @click="openEdit(row)">编辑</button>
              <button
                v-if="canUpdate && row.status === 'published'"
                type="button"
                class="plain-btn"
                @click="takeOffline(row)"
              >
                下线
              </button>
              <button v-if="canDelete" type="button" class="plain-btn danger" @click="removeRow(row)">删除</button>
            </td>
          </tr>
          <tr v-if="!rows.length && !loading">
            <td colspan="6" class="empty">暂无公告</td>
          </tr>
        </tbody>
      </table>
    </div>

    <el-dialog
      v-model="dialogVisible"
      :title="editingId ? '编辑公告' : '新建公告'"
      width="760px"
      destroy-on-close
      class="announcement-edit-dialog"
      align-center
    >
      <form class="announcement-form" @submit.prevent="save">
        <label class="announcement-field">
          <span class="field-label">标题</span>
          <input v-model="form.title" maxlength="200" placeholder="公告标题">
        </label>
        <div class="announcement-field">
          <span class="field-label">正文</span>
          <AnnouncementEditor v-model="form.body_html" />
        </div>
        <div class="announcement-field">
          <span class="field-label">受众（可多选）</span>
          <div class="audience-options">
            <label class="audience-chip">
              <input v-model="form.target_platform_all" type="checkbox">
              <span>运营全员</span>
            </label>
            <label class="audience-chip">
              <input
                v-model="form.target_customer_all"
                type="checkbox"
                @change="onCustomerAllChange(form.target_customer_all)"
              >
              <span>客户全员</span>
            </label>
            <label class="audience-chip">
              <input
                v-model="form.target_customer_tenants"
                type="checkbox"
                @change="onCustomerTenantsChange(form.target_customer_tenants)"
              >
              <span>指定企业</span>
            </label>
          </div>
          <el-select
            v-if="form.target_customer_tenants"
            v-model="form.tenant_ids"
            multiple
            filterable
            collapse-tags
            collapse-tags-tooltip
            placeholder="选择企业"
            class="tenant-select"
          >
            <el-option v-for="t in tenants" :key="t.id" :label="t.name" :value="t.id" />
          </el-select>
        </div>
        <div class="announcement-row">
          <label class="announcement-field">
            <span class="field-label">发布方式</span>
            <select v-model="form.action">
              <option value="draft">存草稿</option>
              <option value="publish_now">立即发布</option>
              <option value="schedule">定时发布</option>
            </select>
          </label>
          <label v-if="form.action === 'schedule'" class="announcement-field">
            <span class="field-label">上线时间</span>
            <input v-model="form.publish_at" type="datetime-local">
          </label>
          <label class="announcement-field">
            <span class="field-label">失效时间（可选）</span>
            <input v-model="form.expire_at" type="datetime-local">
          </label>
        </div>
      </form>
      <template #footer>
        <button type="button" class="plain-btn" @click="dialogVisible = false">取消</button>
        <button type="button" class="primary-btn" :disabled="saving" @click="save">
          {{ saving ? '保存中…' : '保存' }}
        </button>
      </template>
    </el-dialog>
  </section>
</template>

<style scoped>
.announcement-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.announcement-toolbar-meta {
  color: #64748b;
  font-size: 13px;
}
.announcement-table-wrap {
  background: #fff;
  border-radius: 12px;
  border: 1px solid #e8eef5;
  overflow: auto;
}
.data-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.data-table th,
.data-table td {
  padding: 10px 12px;
  border-bottom: 1px solid #eef2f7;
  text-align: left;
}
.data-table th {
  background: #f8fafc;
  color: #475569;
}
.ops {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.empty {
  text-align: center;
  color: #94a3b8;
}
.announcement-form {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.announcement-field {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 8px;
  min-width: 0;
}
.field-label {
  color: #64748b;
  font-size: 12px;
  font-weight: 700;
}
.announcement-field > input,
.announcement-field > select {
  height: 40px;
  border: 1px solid #d7e3f4;
  border-radius: 10px;
  padding: 0 12px;
  background: #f8fbff;
  color: #24324a;
}
.announcement-field > input:focus,
.announcement-field > select:focus {
  outline: none;
  border-color: #4288e8;
  background: #fff;
  box-shadow: 0 0 0 3px rgba(66, 136, 232, 0.1);
}
.audience-options {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}
.audience-chip {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  margin: 0;
  padding: 8px 12px;
  border: 1px solid #dbe3f0;
  border-radius: 999px;
  background: #fff;
  cursor: pointer;
  font-size: 13px;
  color: #334155;
  user-select: none;
}
.audience-chip input {
  width: 16px;
  height: 16px;
  margin: 0;
  accent-color: #2563eb;
}
.audience-chip:has(input:checked) {
  border-color: #93c5fd;
  background: #eff6ff;
  color: #1d4ed8;
}
.tenant-select {
  width: 100%;
}
.announcement-row {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}
.danger {
  color: #dc2626;
}
@media (max-width: 720px) {
  .announcement-row {
    grid-template-columns: 1fr;
  }
}
</style>

<style>
/* 2026-09-08 - 公告编辑弹窗限高，避免长文把受众/保存顶出视口 */
.announcement-edit-dialog.el-dialog {
  margin-top: 4vh !important;
  max-height: 92vh;
  display: flex;
  flex-direction: column;
}
.announcement-edit-dialog .el-dialog__body {
  flex: 1 1 auto;
  overflow: auto;
  max-height: calc(92vh - 130px);
}
</style>
