<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  getBillingModeHistory,
  getTenantCredit,
  getTenantCreditLedger,
  getTenantMembers,
  getTenantOpenReserves,
  releaseCreditReserve,
  tenantCreditLedgerExportUrl,
  type CreditLedgerItem,
} from '../../../services/credit'
import { useAuthStore } from '../../../stores/auth'
import { extractErrorDetail } from '../../../utils/requestError'

const props = defineProps<{
  tenantId: number
  canEdit: boolean
}>()

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const loading = ref(false)
const detail = ref<Record<string, unknown> | null>(null)
const ledger = ref<CreditLedgerItem[]>([])
const ledgerPage = ref(1)
const history = ref<Array<Record<string, unknown>>>([])
const platformMembers = ref<Array<Record<string, unknown>>>([])
const openReserves = ref<Array<{ ref_id: string; amount: number; window_key: string | null; reason: string | null; created_at: string }>>([])
const releasingRef = ref('')

const billingMode = computed(() => String(detail.value?.billing_mode || 'hosted'))
const isCredit = computed(() => billingMode.value === 'credit')
const dailyEstimate = computed(() => (detail.value?.daily_estimate || {}) as Record<string, unknown>)
const available = computed(() => {
  const balance = Number(detail.value?.credit_balance || 0)
  const reserved = Number(detail.value?.credit_reserved || 0)
  return Math.max(0, balance - reserved)
})
const isZeroBalance = computed(() => isCredit.value && available.value <= 0)
// 2026-09-07 - 充值/调账只走算力运营；2026-09-08 - 模式切换也只走算力运营
const canOpenCreditOps = computed(() => (
  auth.allowedMenus.some(menu => menu.menu_code === 'platform.credit_ops_board')
))

const entryTypeLabel: Record<string, string> = {
  recharge: '充值',
  adjust: '扣减',
  reserve: '预扣',
  release: '释放',
  settle: '结算',
}

function entryLabel(type: string) {
  return entryTypeLabel[type] || type
}

function goCreditOps(tab: 'recharge' | 'mode') {
  if (!canOpenCreditOps.value) {
    ElMessage.warning('当前账号没有算力运营权限')
    return
  }
  void router.push({
    path: route.path,
    query: {
      ...route.query,
      menu: 'platform.credit_ops_board',
      credit_tab: tab,
      tenant_id: String(props.tenantId),
    },
  }).catch(() => undefined)
}

async function loadLedger(page = ledgerPage.value) {
  ledgerPage.value = page
  const data = await getTenantCreditLedger(props.tenantId, page)
  ledger.value = data.items || []
}

async function load() {
  loading.value = true
  try {
    detail.value = await getTenantCredit(props.tenantId)
    await Promise.all([loadLedger(1), loadHistory(), loadPlatformMembers(), loadOpenReserves()])
  } catch (error) {
    ElMessage.error(extractErrorDetail(error, '加载算力信息失败'))
  } finally {
    loading.value = false
  }
}

async function loadOpenReserves() {
  if (!isCredit.value) {
    openReserves.value = []
    return
  }
  try {
    openReserves.value = await getTenantOpenReserves(props.tenantId)
  } catch {
    openReserves.value = []
  }
}

async function submitReleaseReserve(refId: string) {
  releasingRef.value = refId
  try {
    await releaseCreditReserve(props.tenantId, refId, '运营手工释放预扣')
    ElMessage.success('预扣已释放')
    await load()
  } catch (error) {
    ElMessage.error(extractErrorDetail(error, '释放失败'))
  } finally {
    releasingRef.value = ''
  }
}

async function loadPlatformMembers() {
  try {
    const data = await getTenantMembers(props.tenantId)
    platformMembers.value = data.items || []
  } catch {
    platformMembers.value = []
  }
}

function exportLedger() {
  window.open(tenantCreditLedgerExportUrl(props.tenantId), '_blank')
}

async function loadHistory() {
  try {
    history.value = await getBillingModeHistory(props.tenantId)
  } catch {
    history.value = []
  }
}

watch(() => props.tenantId, load, { immediate: true })
</script>

<template>
  <article class="tenant-credit-panel" v-loading="loading">
    <div class="panel-head">
      <div>
        <h2>
          算力与账单
          <span v-if="isZeroBalance" class="zero-balance-tag">零余额</span>
        </h2>
        <p>查看余额与流水；充值、改模式请到算力运营。</p>
      </div>
      <div class="panel-head-actions">
        <button
          v-if="canEdit && canOpenCreditOps"
          type="button"
          class="plain-btn small-btn"
          @click="goCreditOps('mode')"
        >
          去算力运营改模式
        </button>
        <button
          v-if="canEdit && isCredit && canOpenCreditOps"
          type="button"
          class="primary-btn small-btn"
          @click="goCreditOps('recharge')"
        >
          去算力运营充值
        </button>
      </div>
    </div>

    <div class="cards">
      <article class="card">
        <span>可用算力</span>
        <strong>{{ available.toFixed(1) }}</strong>
        <small>余额 {{ Number(detail?.credit_balance || 0).toFixed(1) }} · 预扣 {{ Number(detail?.credit_reserved || 0).toFixed(1) }}</small>
      </article>
      <article v-if="isCredit" class="card">
        <span>今日已扣</span>
        <strong>{{ Number(detail?.today_deduct || 0).toFixed(1) }}</strong>
      </article>
      <article v-if="isCredit" class="card">
        <span>日预估消耗</span>
        <strong>{{ Number(dailyEstimate.credits_per_day || 0).toFixed(1) }}</strong>
        <small>{{ dailyEstimate.keyword_count ?? 0 }} 词 · {{ dailyEstimate.platform_count ?? 0 }} 端 · {{ dailyEstimate.schedule_slots ?? 0 }} 次/日</small>
      </article>
    </div>

    <section v-if="canEdit && isCredit && openReserves.length" class="block">
      <h3>待释放预扣</h3>
      <table class="table">
        <thead><tr><th>时间</th><th>窗口</th><th>金额</th><th>ref</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="row in openReserves" :key="row.ref_id">
            <td>{{ row.created_at }}</td>
            <td>{{ row.window_key || '—' }}</td>
            <td>{{ row.amount }}</td>
            <td class="mono">{{ row.ref_id }}</td>
            <td>
              <button
                type="button"
                class="filter-reset-btn tiny-btn"
                :disabled="releasingRef === row.ref_id"
                @click="submitReleaseReserve(row.ref_id)"
              >
                {{ releasingRef === row.ref_id ? '释放中…' : '释放' }}
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </section>

    <section class="block">
      <div class="block-head-row">
        <h3>算力流水</h3>
        <button type="button" class="filter-reset-btn tiny-btn" @click="exportLedger">导出 CSV</button>
      </div>
      <table class="table">
        <thead><tr><th>时间</th><th>类型</th><th>变动</th><th>余额</th><th>说明</th></tr></thead>
        <tbody>
          <tr v-for="row in ledger" :key="row.id">
            <td>{{ row.created_at }}</td>
            <td>{{ entryLabel(row.entry_type) }}</td>
            <td :class="{ plus: row.amount > 0, minus: row.amount < 0 }">{{ row.amount > 0 ? '+' : '' }}{{ row.amount }}</td>
            <td>{{ row.balance_after }}</td>
            <td>{{ row.reason || '—' }}</td>
          </tr>
          <tr v-if="!ledger.length"><td colspan="5" class="empty">暂无流水</td></tr>
        </tbody>
      </table>
      <div class="pager">
        <button type="button" class="filter-reset-btn tiny-btn" :disabled="ledgerPage <= 1" @click="loadLedger(ledgerPage - 1)">上一页</button>
        <span>第 {{ ledgerPage }} 页</span>
        <button type="button" class="filter-reset-btn tiny-btn" :disabled="ledger.length < 20" @click="loadLedger(ledgerPage + 1)">下一页</button>
      </div>
    </section>

    <section v-if="platformMembers.length" class="block">
      <h3>本企成员（只读）</h3>
      <table class="table">
        <thead><tr><th>姓名</th><th>账号</th><th>职位</th><th>状态</th></tr></thead>
        <tbody>
          <tr v-for="row in platformMembers" :key="String(row.identity_id)">
            <td>{{ row.display_name }}</td>
            <td>{{ row.username }}</td>
            <td>{{ row.position_name }}</td>
            <td>{{ row.status ? '启用' : '停用' }}</td>
          </tr>
        </tbody>
      </table>
    </section>

    <section v-if="history.length" class="block">
      <h3>模式切换记录</h3>
      <table class="table">
        <thead><tr><th>时间</th><th>自</th><th>至</th><th>原因</th></tr></thead>
        <tbody>
          <tr v-for="row in history" :key="String(row.id)">
            <td>{{ row.created_at }}</td>
            <td>{{ row.from_mode === 'credit' ? '算力自助' : '平台托管' }}</td>
            <td>{{ row.to_mode === 'credit' ? '算力自助' : '平台托管' }}</td>
            <td>{{ row.reason || '—' }}</td>
          </tr>
        </tbody>
      </table>
    </section>
  </article>
</template>

<style scoped>
.tenant-credit-panel { display: flex; flex-direction: column; gap: 16px; }
.panel-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }
.panel-head-actions { display: flex; flex-wrap: wrap; gap: 8px; }
.panel-head h2 { margin: 0 0 4px; font-size: 18px; display: flex; align-items: center; gap: 8px; }
.zero-balance-tag {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border-radius: 999px;
  background: #fff7ed;
  border: 1px solid #fdba74;
  color: #c2410c;
  font-size: 12px;
  font-weight: 600;
}
.panel-head p { margin: 0; color: #64748b; font-size: 13px; }
.cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 12px; }
.card { border: 1px solid #e2e8f0; border-radius: 12px; padding: 12px 14px; background: #fff; display: flex; flex-direction: column; gap: 4px; }
.card span { color: #64748b; font-size: 12px; }
.card strong { font-size: 22px; }
.card small { color: #94a3b8; font-size: 12px; }
.block { border: 1px solid #e2e8f0; border-radius: 12px; padding: 12px; background: #fff; }
.block h3 { margin: 0 0 10px; font-size: 15px; }
.block-head-row { display: flex; justify-content: space-between; align-items: center; gap: 8px; margin-bottom: 10px; }
.block-head-row h3 { margin: 0; }
.table { width: 100%; border-collapse: collapse; font-size: 13px; }
.table th, .table td { border-bottom: 1px solid #f1f5f9; padding: 8px 6px; text-align: left; }
.table .empty { color: #94a3b8; text-align: center; }
.plus { color: #15803d; }
.minus { color: #b91c1c; }
.mono { font-family: ui-monospace, monospace; font-size: 12px; }
.pager { display: flex; align-items: center; gap: 10px; margin-top: 10px; }
</style>
