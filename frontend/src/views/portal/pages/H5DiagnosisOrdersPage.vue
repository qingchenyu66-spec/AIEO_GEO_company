<script setup lang="ts">
import { inject, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { listH5DiagnosisAdminOrders, type H5DiagnosisAdminOrder } from '../../../services/h5Diagnosis'
import { extractErrorDetail } from '../../../utils/requestError'
import { PortalNavigateKey } from '../injectionKeys'
import { platformLabelMap } from '../portalMaps'

const navigateToMenu = inject(PortalNavigateKey, () => {})

const loading = ref(false)
const keyword = ref('')
const status = ref('')
const page = ref(1)
const pageSize = 20
const total = ref(0)
const items = ref<H5DiagnosisAdminOrder[]>([])
const drawerOpen = ref(false)
const selected = ref<H5DiagnosisAdminOrder | null>(null)

const statusLabel: Record<string, string> = {
  pending: '待支付',
  paid: '已支付',
  failed: '失败',
  closed: '已关闭',
}

const tradeTypeLabel: Record<string, string> = {
  jsapi: '微信内付',
  native: '扫码付',
}

function platformText(codes: string[] | undefined) {
  if (!codes?.length) return '—'
  return codes.map((c) => platformLabelMap[c] || c).join('、')
}

function joinList(list: string[] | undefined) {
  if (!list?.length) return '—'
  return list.filter(Boolean).join('、')
}

async function loadOrders() {
  loading.value = true
  try {
    const data = await listH5DiagnosisAdminOrders({
      page: page.value,
      page_size: pageSize,
      status: status.value || undefined,
      keyword: keyword.value.trim() || undefined,
    })
    items.value = data.items || []
    total.value = Number(data.total || 0)
  } catch (error) {
    ElMessage.error(extractErrorDetail(error) || '加载 H5 订单失败')
  } finally {
    loading.value = false
  }
}

function search() {
  page.value = 1
  void loadOrders()
}

function openDrawer(row: H5DiagnosisAdminOrder) {
  selected.value = row
  drawerOpen.value = true
}

function closeDrawer() {
  drawerOpen.value = false
}

function openLeadDiagnosis() {
  const leadId = selected.value?.lead_diagnosis_id
  if (!leadId) {
    ElMessage.info('支付成功后才会生成售前诊断')
    return
  }
  drawerOpen.value = false
  navigateToMenu('platform.lead_diagnosis', false, { lead_id: String(leadId) })
}

onMounted(loadOrders)
</script>

<template>
  <section class="h5-orders-page">
    <header class="head">
      <div>
        <h2>H5 订单</h2>
        <p>付费诊断成交记录：支付状态、金额、扫码/微信内付、关联售前诊断。</p>
      </div>
    </header>

    <div class="filters">
      <input v-model="keyword" placeholder="品牌 / 手机号 / 商户单号" @keyup.enter="search">
      <select v-model="status" @change="search">
        <option value="">全部状态</option>
        <option value="pending">待支付</option>
        <option value="paid">已支付</option>
        <option value="failed">失败</option>
        <option value="closed">已关闭</option>
      </select>
      <button type="button" class="primary-btn small-btn" :disabled="loading" @click="search">查询</button>
    </div>

    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>下单时间</th>
            <th>品牌</th>
            <th>商户单号</th>
            <th>手机号</th>
            <th>金额</th>
            <th>方式</th>
            <th>状态</th>
            <th>微信单号</th>
            <th>售前诊断</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="loading">
            <td colspan="10" class="empty">加载中…</td>
          </tr>
          <tr v-else-if="!items.length">
            <td colspan="10" class="empty">暂无订单</td>
          </tr>
          <tr v-for="row in items" :key="row.id">
            <td>{{ row.created_at || '—' }}</td>
            <td class="brand">{{ row.brand_name }}</td>
            <td class="mono">{{ row.out_trade_no }}</td>
            <td>{{ row.contact_phone || row.contact_phone_masked || '—' }}</td>
            <td>¥{{ row.amount_yuan }}</td>
            <td>{{ tradeTypeLabel[row.pay_trade_type] || row.pay_trade_type }}</td>
            <td>
              <span class="status" :data-status="row.status">{{ statusLabel[row.status] || row.status }}</span>
              <div v-if="row.paid_at" class="muted">{{ row.paid_at }}</div>
            </td>
            <td class="mono">{{ row.wx_transaction_id || '—' }}</td>
            <td>{{ row.lead_diagnosis_id ? `#${row.lead_diagnosis_id}` : '—' }}</td>
            <td>
              <button type="button" class="link" @click="openDrawer(row)">详情</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="pager">
      <button type="button" :disabled="loading || page <= 1" @click="page -= 1; loadOrders()">上一页</button>
      <span>第 {{ page }} 页 · 共 {{ total }} 条</span>
      <button type="button" :disabled="loading || page * pageSize >= total" @click="page += 1; loadOrders()">下一页</button>
    </div>

    <div v-if="drawerOpen && selected" class="drawer-mask" @click.self="closeDrawer">
      <aside class="drawer" role="dialog" aria-label="订单填报详情">
        <header class="drawer-head">
          <div>
            <h3>{{ selected.brand_name }}</h3>
            <p class="muted">{{ statusLabel[selected.status] || selected.status }} · ¥{{ selected.amount_yuan }}</p>
          </div>
          <button type="button" class="ghost-btn" @click="closeDrawer">关闭</button>
        </header>

        <dl class="detail-grid">
          <div>
            <dt>商户单号</dt>
            <dd class="mono">{{ selected.out_trade_no }}</dd>
          </div>
          <div>
            <dt>手机号</dt>
            <dd>{{ selected.contact_phone || '—' }}</dd>
          </div>
          <div>
            <dt>支付方式</dt>
            <dd>{{ tradeTypeLabel[selected.pay_trade_type] || selected.pay_trade_type }}</dd>
          </div>
          <div>
            <dt>微信单号</dt>
            <dd class="mono">{{ selected.wx_transaction_id || '—' }}</dd>
          </div>
          <div>
            <dt>下单时间</dt>
            <dd>{{ selected.created_at || '—' }}</dd>
          </div>
          <div>
            <dt>支付时间</dt>
            <dd>{{ selected.paid_at || '—' }}</dd>
          </div>
          <div>
            <dt>行业</dt>
            <dd>{{ selected.industry || '—' }}</dd>
          </div>
          <div>
            <dt>产品焦点</dt>
            <dd>{{ selected.product_focus || '—' }}</dd>
          </div>
          <div class="span-2">
            <dt>官网</dt>
            <dd>{{ selected.website_url || '—' }}</dd>
          </div>
          <div class="span-2">
            <dt>品牌别名</dt>
            <dd>{{ joinList(selected.brand_aliases) }}</dd>
          </div>
          <div class="span-2">
            <dt>竞品</dt>
            <dd>{{ joinList(selected.competitors) }}</dd>
          </div>
          <div class="span-2">
            <dt>监测平台</dt>
            <dd>{{ platformText(selected.platforms) }}</dd>
          </div>
          <div>
            <dt>监测天数</dt>
            <dd>{{ selected.schedule_days || '—' }}</dd>
          </div>
          <div>
            <dt>监测次数</dt>
            <dd>{{ selected.schedule_runs || '—' }}</dd>
          </div>
        </dl>

        <div class="prompts-block">
          <h4>检测问题</h4>
          <ol v-if="selected.prompts?.length">
            <li v-for="(p, idx) in selected.prompts" :key="idx">{{ p }}</li>
          </ol>
          <p v-else class="muted">—</p>
        </div>

        <footer class="drawer-foot">
          <button
            type="button"
            class="primary-btn"
            :disabled="!selected.lead_diagnosis_id"
            @click="openLeadDiagnosis"
          >
            {{ selected.lead_diagnosis_id ? `打开售前诊断 #${selected.lead_diagnosis_id}` : '支付后生成售前诊断' }}
          </button>
        </footer>
      </aside>
    </div>
  </section>
</template>

<style scoped>
.h5-orders-page { display: grid; gap: 14px; }
.head h2 { margin: 0 0 4px; font-size: 20px; }
.head p { margin: 0; color: #64748b; font-size: 13px; }
.filters { display: flex; flex-wrap: wrap; gap: 8px; }
.filters input, .filters select {
  border: 1px solid #cbd5e1;
  border-radius: 10px;
  padding: 8px 10px;
  min-width: 180px;
  background: #fff;
}
.table-wrap {
  overflow: auto;
  border: 1px solid #e2e8f0;
  border-radius: 14px;
  background: #fff;
}
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td { padding: 10px 12px; border-bottom: 1px solid #f1f5f9; text-align: left; vertical-align: top; }
th { background: #f8fafc; color: #475569; font-weight: 600; white-space: nowrap; }
.brand { font-weight: 600; }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12px; word-break: break-all; }
.muted { color: #94a3b8; font-size: 12px; }
.empty { text-align: center; color: #94a3b8; padding: 28px 12px; }
.status {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 999px;
  background: #f1f5f9;
  color: #475569;
  font-size: 12px;
  font-weight: 600;
}
.status[data-status='paid'] { background: #ecfdf5; color: #047857; }
.status[data-status='pending'] { background: #fff7ed; color: #c2410c; }
.status[data-status='failed'] { background: #fef2f2; color: #b91c1c; }
.link {
  border: none;
  background: transparent;
  color: #2563eb;
  padding: 0;
  cursor: pointer;
}
.pager {
  display: flex;
  align-items: center;
  gap: 12px;
  color: #64748b;
  font-size: 13px;
}
.pager button, .ghost-btn {
  border: 1px solid #cbd5e1;
  background: #fff;
  border-radius: 8px;
  padding: 6px 10px;
  cursor: pointer;
}
.pager button:disabled { opacity: 0.5; }

.drawer-mask {
  position: fixed;
  inset: 0;
  z-index: 40;
  background: rgba(15, 23, 42, 0.35);
  display: flex;
  justify-content: flex-end;
}
.drawer {
  width: min(440px, 100vw);
  height: 100%;
  background: #fff;
  box-shadow: -8px 0 24px rgba(15, 23, 42, 0.12);
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 18px 18px 24px;
  overflow: auto;
}
.drawer-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
}
.drawer-head h3 { margin: 0 0 4px; font-size: 18px; }
.detail-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px 14px;
  margin: 0;
}
.detail-grid .span-2 { grid-column: 1 / -1; }
.detail-grid dt {
  margin: 0 0 2px;
  color: #94a3b8;
  font-size: 12px;
}
.detail-grid dd {
  margin: 0;
  color: #0f172a;
  font-size: 13px;
  word-break: break-word;
}
.prompts-block h4 {
  margin: 0 0 8px;
  font-size: 14px;
}
.prompts-block ol {
  margin: 0;
  padding-left: 18px;
  display: grid;
  gap: 6px;
  font-size: 13px;
  color: #334155;
}
.drawer-foot {
  margin-top: auto;
  padding-top: 8px;
}
.drawer-foot .primary-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
</style>
