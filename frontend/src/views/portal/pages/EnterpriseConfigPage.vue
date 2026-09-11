<script setup lang="ts">
import { computed, inject, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import BrandAuditPage from './BrandAuditPage.vue'
import { resolveEnterprisePreviewTenantId } from '../customerPreview'
import { PreviewCustomerMenusKey } from '../injectionKeys'
import {
  createEnterpriseMember,
  deleteEnterpriseMember,
  getCurrentCreditTerms,
  getEnterpriseAudit,
  getEnterpriseCreditLedger,
  getEnterpriseCreditLedgerDetail,
  getEnterpriseCreditSummary,
  getEnterpriseMembers,
  resetEnterpriseMemberPassword,
  updateEnterpriseMember,
  type CreditLedgerDetail,
  type CreditLedgerItem,
  type EnterpriseMemberItem,
} from '../../../services/credit'
import { useAuthStore } from '../../../stores/auth'
import type { MenuInfo } from '../../../services/auth'
import { extractErrorDetail, isRequestCanceled } from '../../../utils/requestError'

const props = defineProps<{ initialTab?: string; previewReadonly?: boolean }>()
const route = useRoute()
const auth = useAuthStore()
const previewCustomerMenus = inject(PreviewCustomerMenusKey, ref<MenuInfo[]>([]))

// 2026-08-27 - 预览成员空列表 - 解析 tenant_id 须含 query.tenant_id 回退并在路由就绪后重载
const previewTenantId = computed(() => (
  props.previewReadonly ? resolveEnterprisePreviewTenantId(route) : null
))
const enterpriseTenantId = computed(() => previewTenantId.value ?? undefined)

const TAB_DEFS = [
  { id: 'monitor', label: '监测配置', menu: 'customer.enterprise_monitor' },
  // 2026-09-09 - 与侧栏 sys_menu.sort_order 一致：成员(132) 再算力(133)
  { id: 'members', label: '成员与权限', menu: 'customer.enterprise_members' },
  { id: 'credit', label: '算力中心', menu: 'customer.enterprise_credit' },
  { id: 'audit', label: '操作记录', menu: 'customer.enterprise_audit' },
] as const

const tab = ref('monitor')
const loading = ref(false)
const summary = ref<Awaited<ReturnType<typeof getEnterpriseCreditSummary>> | null>(null)
const ledger = ref<Awaited<ReturnType<typeof getEnterpriseCreditLedger>> | null>(null)
const members = ref<Awaited<ReturnType<typeof getEnterpriseMembers>> | null>(null)
const audit = ref<Awaited<ReturnType<typeof getEnterpriseAudit>> | null>(null)
const terms = ref<Awaited<ReturnType<typeof getCurrentCreditTerms>> | null>(null)
const termsViewVisible = ref(false)
const ledgerDetail = ref<CreditLedgerDetail | null>(null)
const ledgerDetailVisible = ref(false)
const ledgerDetailLoading = ref(false)
const ledgerDetailRowId = ref<number | null>(null)

const memberFormVisible = ref(false)
const memberSaving = ref(false)
const editingMember = ref<EnterpriseMemberItem | null>(null)
const memberForm = ref({
  display_name: '',
  username: '',
  password: '',
  customer_position_id: 0,
  status: true,
})

function menuGrant(code: string) {
  if (props.previewReadonly) {
    return previewCustomerMenus.value.find(menu => menu.menu_code === code)
  }
  return auth.allowedMenus.find(menu => menu.menu_code === code)
}

function canViewTab(menuCode: string) {
  const grant = menuGrant(menuCode)
  return Boolean(grant && (grant.can_export || grant.can_update || grant.can_create || grant.can_delete))
}

const isCreditBilling = computed(() => String(summary.value?.billing_mode || '') === 'credit')

const visibleTabs = computed(() => TAB_DEFS.filter((item) => {
  // 2026-09-07 - Tab 按菜单权限藏；托管不露算力中心
  if (item.id === 'credit') {
    if (summary.value && !isCreditBilling.value) return false
    return canViewTab(item.menu)
  }
  return canViewTab(item.menu)
}))

const canEditMembers = computed(() => !props.previewReadonly && Boolean(menuGrant('customer.enterprise_members')?.can_create))
const canUpdateMembers = computed(() => !props.previewReadonly && Boolean(menuGrant('customer.enterprise_members')?.can_update))
const canDeleteMembers = computed(() => !props.previewReadonly && Boolean(menuGrant('customer.enterprise_members')?.can_delete))

const entryTypeLabel: Record<string, string> = {
  recharge: '充值',
  adjust: '调整',
  settle: '扣费',
}

const subtaskStatusLabel: Record<string, string> = {
  settled: '已结算',
  released_unbilled: '未计费已释放',
  released: '已释放',
  pending: '待处理',
  submitted: '已提交',
  completed: '已完成',
  failed: '失败',
  stopped: '已停止',
}

function formatSubtaskStatus(status: unknown) {
  const key = String(status || '').trim()
  if (!key) return '—'
  return subtaskStatusLabel[key] || subtaskStatusLabel[key.toLowerCase()] || key
}

function formatLedgerAmount(amount: number) {
  const value = Number(amount)
  if (!Number.isFinite(value)) return '—'
  const text = Number.isInteger(value) ? String(value) : value.toFixed(1)
  return value > 0 ? `+${text}` : text
}

function formatLedgerReason(row: CreditLedgerItem) {
  const reason = (row.reason || '').trim()
  if (reason) return reason
  if (row.entry_type !== 'settle') return '—'
  const hint = [row.window_key, row.keyword, row.platform_code]
    .map(part => (part || '').trim())
    .filter(Boolean)
    .join(' · ')
  return hint || '监测扣费'
}

type AuditListDiff = {
  removed: string[]
  added: string[]
}

type AuditChangeLine = {
  field: string
  before?: string
  after?: string
  raw?: string
  listDiff?: AuditListDiff | null
}

function splitAuditList(value: string): string[] {
  return String(value || '')
    .split(/[、,，]/)
    .map(part => part.trim())
    .filter(Boolean)
}

function buildAuditListDiff(before?: string, after?: string): AuditListDiff | null {
  if (before == null || after == null) return null
  const beforeItems = splitAuditList(before)
  const afterItems = splitAuditList(after)
  // 单值字段（如词组数量）不走列表 diff
  if (beforeItems.length <= 1 && afterItems.length <= 1) return null
  if (beforeItems.length + afterItems.length < 3) return null
  const afterSet = new Set(afterItems)
  const beforeSet = new Set(beforeItems)
  const removed = beforeItems.filter(item => !afterSet.has(item))
  const added = afterItems.filter(item => !beforeSet.has(item))
  if (!removed.length && !added.length) return null
  return { removed, added }
}

/** 企业页内已有上下文：去掉「保存…「企业名」：」前缀，按；拆成变更行 */
function parseAuditDescription(description: string): AuditChangeLine[] {
  let text = String(description || '').trim()
  text = text.replace(/^(保存企业配置|保存品牌词|新增竞品|删除竞品|更新竞品)「[^」]*」[：:]\s*/, '')
  text = text.replace(/^(保存企业配置|保存品牌词)[：:]\s*/, '')
  const parts = text.split(/；/).map(part => part.trim()).filter(Boolean)
  if (!parts.length) return text ? [{ field: '', raw: text }] : []
  return parts.map((part) => {
    const matched = part.match(/^(.+?)[：:]([\s\S]+)$/)
    if (!matched) return { field: '', raw: part }
    const field = matched[1].trim()
    const rest = matched[2].trim()
    const sides = rest.split(/\s*(?:→|->)\s*/)
    if (sides.length >= 2) {
      const before = sides.slice(0, -1).join(' → ').trim()
      const after = sides[sides.length - 1].trim()
      return {
        field,
        before,
        after,
        listDiff: buildAuditListDiff(before, after),
      }
    }
    return { field, after: rest }
  })
}

const auditExpanded = ref<Record<number, boolean>>({})

function toggleAuditExpand(idx: number) {
  auditExpanded.value = { ...auditExpanded.value, [idx]: !auditExpanded.value[idx] }
}

function auditNeedsExpand(lines: AuditChangeLine[]) {
  return lines.length > 2
}

function visibleAuditLines(row: { idx: number; lines: AuditChangeLine[]; needsExpand: boolean }) {
  if (!row.needsExpand || auditExpanded.value[row.idx]) return row.lines
  return row.lines.slice(0, 2)
}

const auditViewRows = computed(() => {
  const items = (audit.value?.items || []) as Array<{
    created_at?: string
    action_type?: string
    operator_name?: string
    description?: string
  }>
  return items.map((row, idx) => {
    const lines = parseAuditDescription(String(row.description || ''))
    return {
      idx,
      created_at: row.created_at || '—',
      action_type: row.action_type || '—',
      operator_name: row.operator_name || '—',
      lines,
      needsExpand: auditNeedsExpand(lines),
    }
  })
})


function applyInitialTab() {
  if (props.initialTab === 'customer.enterprise_credit') tab.value = 'credit'
  else if (props.initialTab === 'customer.enterprise_members') tab.value = 'members'
  else if (props.initialTab === 'customer.enterprise_audit') tab.value = 'audit'
  else if (props.initialTab === 'customer.enterprise_monitor') tab.value = 'monitor'
}

function ensureAllowedTab() {
  const allowed = visibleTabs.value.map(item => item.id)
  if (!allowed.length) return
  if (!allowed.includes(tab.value as typeof allowed[number])) {
    tab.value = allowed[0]
  }
}

async function refreshBillingMode() {
  try {
    summary.value = await getEnterpriseCreditSummary(enterpriseTenantId.value)
  } catch (error) {
    if (isRequestCanceled(error)) return
    const status = (error as { response?: { status?: number } })?.response?.status
    const detail = extractErrorDetail(error)
    // 仅明确「托管/停服」才按非 credit 藏 Tab；其它失败勿假写成 hosted
    if (status === 403 && (detail.includes('托管') || detail.includes('停服'))) {
      summary.value = { billing_mode: 'hosted' } as Awaited<ReturnType<typeof getEnterpriseCreditSummary>>
      return
    }
    ElMessage.warning(detail || '算力状态加载失败，请稍后重试')
  }
}

async function loadTab() {
  if (tab.value === 'monitor') return
  loading.value = true
  try {
    const tenantId = enterpriseTenantId.value
    if (tab.value === 'credit') {
      summary.value = await getEnterpriseCreditSummary(tenantId)
      ledger.value = await getEnterpriseCreditLedger(1, 20, tenantId)
      terms.value = await getCurrentCreditTerms(tenantId)
    } else if (tab.value === 'members') {
      members.value = await getEnterpriseMembers(tenantId)
    } else if (tab.value === 'audit') {
      // 2026-09-04 - 切 Tab 取消旧请求时勿把 audit 留成 null，否则误显「暂无记录」
      const data = await getEnterpriseAudit(1, 20, tenantId)
      audit.value = data
      auditExpanded.value = {}
    }
  } catch (error) {
    if (!isRequestCanceled(error)) {
      ElMessage.error(extractErrorDetail(error, '加载失败'))
    }
  } finally {
    loading.value = false
  }
}

function openTermsView() {
  if (!terms.value?.content_html) return
  termsViewVisible.value = true
}

/** 弹窗标题固定，避免与正文大标题重复 */
const termsDialogTitle = computed(() => '服务条款')

async function openLedgerDetail(row: CreditLedgerItem) {
  // 再点同一行收起明细
  if (ledgerDetailVisible.value && ledgerDetailRowId.value === row.id) {
    ledgerDetailVisible.value = false
    ledgerDetailRowId.value = null
    ledgerDetail.value = null
    return
  }
  ledgerDetailRowId.value = row.id
  ledgerDetailVisible.value = true
  ledgerDetailLoading.value = true
  ledgerDetail.value = null
  try {
    ledgerDetail.value = await getEnterpriseCreditLedgerDetail(row.id, enterpriseTenantId.value)
  } catch (error) {
    ElMessage.error(extractErrorDetail(error, '加载明细失败'))
    ledgerDetailVisible.value = false
    ledgerDetailRowId.value = null
  } finally {
    ledgerDetailLoading.value = false
  }
}

function onLedgerDrawerClosed() {
  ledgerDetailRowId.value = null
  ledgerDetail.value = null
}

function selectTab(code: string) {
  tab.value = code
  void loadTab()
}

function openMemberForm(row?: EnterpriseMemberItem) {
  editingMember.value = row || null
  memberForm.value = {
    display_name: row?.display_name || '',
    username: row?.username || '',
    password: '',
    customer_position_id: row?.customer_position_id || members.value?.positions?.[0]?.id || 0,
    status: row?.status ?? true,
  }
  memberFormVisible.value = true
}

async function submitMemberForm() {
  if (memberSaving.value) return
  const password = String(memberForm.value.password || '')
  if (!editingMember.value) {
    if (!String(memberForm.value.username || '').trim()) {
      ElMessage.warning('请填写登录账号')
      return
    }
    if (password.length < 8) {
      // 2026-09-07 - 邀请成员密码不足 8 位时勿等接口回英文校验
      ElMessage.warning('初始密码至少 8 位')
      return
    }
  } else if (password && password.length < 8) {
    ElMessage.warning('重置密码至少 8 位')
    return
  }
  memberSaving.value = true
  try {
    if (editingMember.value) {
      await updateEnterpriseMember(editingMember.value.identity_id, {
        display_name: memberForm.value.display_name,
        customer_position_id: memberForm.value.customer_position_id,
        status: memberForm.value.status,
      })
      if (password) {
        await resetEnterpriseMemberPassword(editingMember.value.identity_id, password)
      }
    } else {
      await createEnterpriseMember(memberForm.value)
    }
    memberFormVisible.value = false
    ElMessage.success('已保存')
    await loadTab()
  } catch (error) {
    ElMessage.error(extractErrorDetail(error, '保存失败'))
  } finally {
    memberSaving.value = false
  }
}

async function removeMember(row: EnterpriseMemberItem) {
  try {
    await ElMessageBox.confirm(`确定删除成员「${row.display_name}」？`, '删除成员', { type: 'warning' })
    await deleteEnterpriseMember(row.identity_id)
    ElMessage.success('已删除')
    await loadTab()
  } catch (error) {
    if (error !== 'cancel') ElMessage.error(extractErrorDetail(error, '删除失败'))
  }
}

onMounted(async () => {
  applyInitialTab()
  await refreshBillingMode()
  ensureAllowedTab()
  void loadTab()
})

watch(() => props.initialTab, async () => {
  applyInitialTab()
  ensureAllowedTab()
  await loadTab()
})

watch(previewTenantId, async (tenantId, prev) => {
  if (!props.previewReadonly || tenantId == null || tenantId === prev) return
  await refreshBillingMode()
  ensureAllowedTab()
  if (tab.value !== 'monitor') void loadTab()
})

watch(visibleTabs, () => ensureAllowedTab())
</script>

<template>
  <div class="enterprise-config-page" v-loading="loading">
    <aside class="enterprise-side">
      <button
        v-for="item in visibleTabs"
        :key="item.id"
        type="button"
        :class="{ on: tab === item.id }"
        @click="selectTab(item.id)"
      >{{ item.label }}</button>
    </aside>
    <section class="enterprise-main">
      <BrandAuditPage v-if="tab === 'monitor'" customer-config-embed />

        <div v-else-if="tab === 'credit' && isCreditBilling" class="panel">
        <div class="cards">
          <article class="card"><span>可用算力</span><strong>{{ summary?.available ?? '—' }}</strong></article>
          <article class="card"><span>今日已扣</span><strong>{{ summary?.today_deduct ?? 0 }}</strong></article>
          <!-- 2026-09-08 - 方案甲：客户侧不展示预扣中，后台仍预扣防并发 -->
        </div>
        <!-- 2026-09-08 - 服务条款改为查阅即可，去掉强制确认按钮与内嵌正文 -->
        <div class="credit-notice">
          <span>充值请联系客户经理</span>
          <button v-if="terms" type="button" class="credit-notice-link" @click="openTermsView">查看服务条款</button>
        </div>
        <el-dialog v-model="termsViewVisible" width="560px" :title="termsDialogTitle">
          <div v-if="terms?.content_html" class="terms-box terms-box-dialog" v-html="terms.content_html" />
        </el-dialog>
        <div class="table-scroll">
          <table v-if="ledger?.items?.length" class="table ledger-table">
            <thead><tr><th>时间</th><th>类型</th><th>变动</th><th>余额</th><th>说明</th></tr></thead>
            <tbody>
              <tr
                v-for="row in ledger.items"
                :key="row.id"
                class="clickable"
                :class="{ 'is-active': ledgerDetailVisible && ledgerDetailRowId === row.id }"
                @click="openLedgerDetail(row)"
              >
                <td>{{ row.created_at }}</td>
                <td>{{ entryTypeLabel[row.entry_type] || row.entry_type }}</td>
                <td :class="{ plus: row.amount > 0, minus: row.amount < 0 }">{{ formatLedgerAmount(row.amount) }}</td>
                <td>{{ row.balance_after }}</td>
                <td class="reason-cell">{{ formatLedgerReason(row) }}</td>
              </tr>
            </tbody>
          </table>
          <!-- 2026-09-07 - v-else 须紧挨 table 的 v-if，不能隔一层 div 否则编译失败 -->
          <p v-else class="hint">暂无流水</p>
        </div>
        <el-drawer
          v-model="ledgerDetailVisible"
          size="520px"
          title="流水明细"
          direction="rtl"
          @closed="onLedgerDrawerClosed"
        >
          <div v-loading="ledgerDetailLoading">
            <template v-if="ledgerDetail">
              <p>类型：{{ entryTypeLabel[ledgerDetail.entry_type] || ledgerDetail.entry_type }}</p>
              <p>时间：{{ ledgerDetail.created_at }}</p>
              <p>变动：{{ formatLedgerAmount(ledgerDetail.amount) }} · 余额：{{ ledgerDetail.balance_after }}</p>
              <p>窗口：{{ ledgerDetail.window_key || '—' }}</p>
              <p>说明：{{ formatLedgerReason(ledgerDetail) }}</p>
              <h4 v-if="ledgerDetail.subtasks?.length">子任务明细</h4>
              <table v-if="ledgerDetail.subtasks?.length" class="table subtask-table">
                <thead><tr><th>平台</th><th>关键词</th><th>状态</th><th>算力</th></tr></thead>
                <tbody>
                  <tr v-for="(st, idx) in ledgerDetail.subtasks" :key="st.subtask_id || idx">
                    <td>{{ st.platform_code || '—' }}</td>
                    <td>{{ st.keyword || '—' }}</td>
                    <td>{{ formatSubtaskStatus(st.status) }}</td>
                    <td>{{ st.credits ?? '—' }}</td>
                  </tr>
                </tbody>
              </table>
              <p v-else class="hint">暂无子任务明细</p>
            </template>
          </div>
        </el-drawer>
      </div>

      <div v-else-if="tab === 'members'" class="panel">
        <div class="panel-head">
          <h3>成员列表</h3>
          <button v-if="canEditMembers" type="button" class="btn-primary" @click="openMemberForm()">邀请成员</button>
        </div>
        <div class="table-scroll">
          <table v-if="members?.items?.length" class="table">
            <thead><tr><th>姓名</th><th>账号</th><th>职位</th><th>状态</th><th v-if="canUpdateMembers">操作</th></tr></thead>
            <tbody>
              <tr v-for="row in members.items" :key="row.identity_id">
                <td>{{ row.display_name }}</td>
                <td>{{ row.username }}</td>
                <td>{{ row.position_name }}</td>
                <td>{{ row.status ? '启用' : '停用' }}</td>
                <td v-if="canUpdateMembers || canDeleteMembers">
                  <button v-if="canUpdateMembers" type="button" class="btn-link-inline" @click="openMemberForm(row)">编辑</button>
                  <button v-if="canDeleteMembers" type="button" class="btn-link-inline danger" @click="removeMember(row)">删除</button>
                </td>
              </tr>
            </tbody>
          </table>
          <p v-else class="hint">暂无成员</p>
        </div>
        <el-dialog v-model="memberFormVisible" width="480px" :title="editingMember ? '编辑成员' : '邀请成员'">
          <label class="field"><span>姓名</span><input v-model="memberForm.display_name" class="input" /></label>
          <label v-if="!editingMember" class="field"><span>登录账号</span><input v-model="memberForm.username" class="input" /></label>
          <label class="field"><span>{{ editingMember ? '重置密码（留空不改）' : '初始密码（至少 8 位）' }}</span><input v-model="memberForm.password" type="password" class="input" /></label>
          <label class="field">
            <span>职位</span>
            <select v-model="memberForm.customer_position_id" class="input">
              <option v-for="p in members?.positions || []" :key="p.id" :value="p.id">{{ p.position_name }}</option>
            </select>
          </label>
          <label class="check"><input v-model="memberForm.status" type="checkbox" />启用</label>
          <template #footer>
            <button type="button" class="btn-secondary" @click="memberFormVisible = false">取消</button>
            <button type="button" class="btn-primary" :disabled="memberSaving" @click="submitMemberForm">
              {{ memberSaving ? '保存中…' : '保存' }}
            </button>
          </template>
        </el-dialog>
      </div>

      <div v-else-if="tab === 'audit'" class="panel">
        <div class="table-scroll">
          <table v-if="auditViewRows.length" class="table audit-table">
            <thead>
              <tr>
                <th class="col-time">时间</th>
                <th class="col-action">操作</th>
                <th>说明</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in auditViewRows" :key="row.idx">
                <td class="col-time">{{ row.created_at }}</td>
                <td class="col-action">
                  <div class="audit-action-cell">
                    <span class="audit-action-tag">{{ row.action_type }}</span>
                    <span class="audit-operator" :title="row.operator_name">{{ row.operator_name }}</span>
                  </div>
                </td>
                <td class="col-desc">
                  <div class="audit-desc">
                    <div
                      v-for="(line, lineIdx) in visibleAuditLines(row)"
                      :key="lineIdx"
                      class="audit-change"
                    >
                      <template v-if="line.raw">
                        <span class="audit-raw">{{ line.raw }}</span>
                      </template>
                      <template v-else>
                        <span v-if="line.field" class="audit-field">{{ line.field }}</span>
                        <div v-if="line.listDiff" class="audit-list-diff">
                          <p v-if="line.listDiff.removed.length" class="audit-list-row is-removed">
                            <span class="audit-list-label">移除</span>
                            <span>{{ line.listDiff.removed.join('、') }}</span>
                          </p>
                          <p v-if="line.listDiff.added.length" class="audit-list-row is-added">
                            <span class="audit-list-label">新增</span>
                            <span>{{ line.listDiff.added.join('、') }}</span>
                          </p>
                          <p
                            v-if="!line.listDiff.removed.length && !line.listDiff.added.length"
                            class="audit-list-row"
                          >
                            <span class="audit-list-label">变更后</span>
                            <span>{{ line.after }}</span>
                          </p>
                        </div>
                        <div v-else-if="line.before != null || line.after != null" class="audit-stack-diff">
                          <p v-if="line.before != null" class="audit-stack-row">
                            <span class="audit-list-label">变更前</span>
                            <span class="audit-before">{{ line.before }}</span>
                          </p>
                          <p v-if="line.after != null" class="audit-stack-row">
                            <span class="audit-list-label">变更后</span>
                            <span class="audit-after">{{ line.after }}</span>
                          </p>
                        </div>
                      </template>
                    </div>
                  </div>
                  <button
                    v-if="row.needsExpand"
                    type="button"
                    class="audit-expand-btn"
                    @click="toggleAuditExpand(row.idx)"
                  >
                    {{ auditExpanded[row.idx] ? '收起' : `展开其余 ${row.lines.length - 2} 项` }}
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
          <p v-else class="hint">暂无记录</p>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.enterprise-config-page { display: flex; gap: 0; min-height: 520px; border: 1px solid var(--el-border-color); border-radius: 10px; overflow: hidden; background: #fff; }
.enterprise-side { width: 200px; background: #f8fafc; border-right: 1px solid var(--el-border-color); padding: 12px 0; flex-shrink: 0; }
.enterprise-side button { display: block; width: 100%; text-align: left; border: none; background: transparent; padding: 10px 16px; cursor: pointer; color: #64748b; }
.enterprise-side button.on { background: #fff; color: var(--el-color-primary); font-weight: 600; border-right: 2px solid var(--el-color-primary); }
.enterprise-main { flex: 1; padding: 18px; min-width: 0; }
.panel-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 12px; margin-bottom: 16px; }
.card { border: 1px solid var(--el-border-color); border-radius: 10px; padding: 16px; }
.card.warn { background: #fffbeb; border-color: #fcd34d; }
.card span { display: block; font-size: 12px; color: #64748b; margin-bottom: 6px; }
.card strong { font-size: 22px; }
.hint { color: #64748b; font-size: 13px; }
.credit-notice {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 14px;
  margin: 0 0 14px;
  padding: 10px 12px;
  border-radius: 8px;
  background: #f8fafc;
  color: #64748b;
  font-size: 13px;
}
.credit-notice span + span::before,
.credit-notice span + .credit-notice-link::before {
  content: '·';
  margin-right: 14px;
  color: #cbd5e1;
}
.credit-notice-link {
  border: none;
  background: transparent;
  padding: 0;
  color: var(--el-color-primary);
  font-size: 13px;
  cursor: pointer;
}
.credit-notice-link:hover { text-decoration: underline; }
.field { display: block; margin-bottom: 12px; }
.field span { display: block; font-size: 12px; color: #64748b; margin-bottom: 4px; }
.input { width: 100%; border: 1px solid var(--el-border-color); border-radius: 6px; padding: 8px 10px; }
.check { display: flex; align-items: center; gap: 8px; margin: 12px 0; }
.btn-primary { background: var(--el-color-primary); color: #fff; border: none; border-radius: 6px; padding: 8px 14px; cursor: pointer; }
.btn-secondary { border: 1px solid var(--el-border-color); background: #fff; border-radius: 6px; padding: 8px 14px; cursor: pointer; }
.btn-link-inline { border: none; background: transparent; color: var(--el-color-primary); cursor: pointer; margin-right: 8px; }
.btn-link-inline.danger { color: #dc2626; }
.table-scroll { width: 100%; overflow-x: auto; }
.table { width: 100%; border-collapse: collapse; margin-top: 12px; font-size: 13px; }
.table th, .table td { border: 1px solid var(--el-border-color); padding: 8px 10px; text-align: left; vertical-align: top; }
.table tr.clickable { cursor: pointer; }
.table tr.clickable:hover { background: #f8fafc; }
.ledger-table tr.clickable.is-active { background: #eff6ff; }
.audit-table { table-layout: fixed; margin-top: 0; }
.audit-table th, .audit-table td { overflow: hidden; }
.audit-table .col-time { width: 138px; white-space: nowrap; color: #64748b; font-variant-numeric: tabular-nums; }
.audit-table .col-action { width: 128px; }
.audit-table .col-desc { min-width: 0; }
.audit-action-cell {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}
.audit-action-tag {
  display: inline-block;
  max-width: 100%;
  padding: 2px 8px;
  border-radius: 6px;
  background: #f1f5f9;
  color: #334155;
  font-size: 12px;
  font-weight: 600;
  line-height: 1.4;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.audit-operator {
  display: block;
  min-width: 0;
  color: #94a3b8;
  font-size: 12px;
  line-height: 1.35;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.audit-desc { display: flex; flex-direction: column; gap: 10px; min-width: 0; }
.audit-change {
  min-width: 0;
  padding-bottom: 8px;
  border-bottom: 1px dashed #e2e8f0;
}
.audit-change:last-child {
  padding-bottom: 0;
  border-bottom: none;
}
.audit-field {
  display: block;
  margin-bottom: 4px;
  font-size: 12px;
  font-weight: 600;
  color: #334155;
  line-height: 1.4;
}
.audit-stack-diff,
.audit-list-diff {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}
.audit-stack-row,
.audit-list-row {
  display: grid;
  grid-template-columns: 44px minmax(0, 1fr);
  gap: 8px;
  margin: 0;
  font-size: 12px;
  line-height: 1.45;
  word-break: break-word;
}
.audit-list-label {
  color: #94a3b8;
  flex-shrink: 0;
}
.audit-list-row.is-removed span:last-child { color: #b45309; }
.audit-list-row.is-added span:last-child { color: #047857; }
.audit-before { color: #94a3b8; }
.audit-after { color: #0f172a; }
.audit-raw { font-size: 12px; color: #475569; word-break: break-word; line-height: 1.45; }
.audit-expand-btn {
  margin-top: 8px;
  border: none;
  background: transparent;
  padding: 0;
  color: var(--el-color-primary);
  font-size: 12px;
  cursor: pointer;
}
.audit-expand-btn:hover { text-decoration: underline; }
.terms-box { max-height: 200px; overflow: auto; border: 1px solid var(--el-border-color); padding: 12px; margin: 12px 0; font-size: 13px; }
.terms-box-dialog { max-height: 420px; margin: 0; }
.subtask-table { margin-top: 8px; }
.subtask-table th, .subtask-table td { font-size: 12px; padding: 6px 8px; }
.ledger-table td.plus { color: #047857; font-weight: 600; }
.ledger-table td.minus { color: #b45309; font-weight: 600; }
.ledger-table .reason-cell { max-width: 280px; word-break: break-word; }
@media (max-width: 900px) {
  /* 2026-09-07 - 企业配置窄屏：侧栏改顶栏横滑 */
  .enterprise-config-page { flex-direction: column; min-height: 0; }
  .enterprise-side {
    width: 100%;
    display: flex;
    gap: 4px;
    overflow-x: auto;
    border-right: none;
    border-bottom: 1px solid var(--el-border-color);
    padding: 8px;
  }
  .enterprise-side button {
    width: auto;
    white-space: nowrap;
    border-radius: 8px;
    padding: 8px 12px;
  }
  .enterprise-side button.on {
    border-right: none;
    background: #eff6ff;
  }
  .enterprise-main { padding: 12px; }
  .cards { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
</style>
