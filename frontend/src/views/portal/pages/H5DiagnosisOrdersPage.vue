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

/** 列表只留月日时分，完整时间放 title */
function shortTime(value: string | null | undefined) {
  if (!value) return '—'
  const m = String(value).match(/(\d{2})-(\d{2})\s+(\d{2}:\d{2})/)
  if (m) return `${m[1]}-${m[2]} ${m[3]}`
  return value
}

/** 商户单号过长时中间省略，悬停看全 */
function shortTradeNo(value: string | null | undefined) {
  const text = String(value || '').trim()
  if (text.length <= 18) return text || '—'
  return `${text.slice(0, 8)}…${text.slice(-6)}`
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

async function copyText(text: string) {
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success('已复制')
  } catch {
    ElMessage.warning('复制失败，请手动选择')
  }
}

onMounted(loadOrders)
</script>

<template>
  <section class="h5-orders-page">
    <!-- 2026-08-31 - 标题/副标题已由 Portal 外壳提供，页内勿再重复 -->
    <div class="toolbar">
      <input v-model="keyword" class="search-input" placeholder="品牌 / 手机号 / 商户单号" @keyup.enter="search">
      <select v-model="status" class="status-select" @change="search">
        <option value="">全部状态</option>
        <option value="pending">待支付</option>
        <option value="paid">已支付</option>
        <option value="failed">失败</option>
        <option value="closed">已关闭</option>
      </select>
      <button type="button" class="primary-btn small-btn" :disabled="loading" @click="search">查询</button>
      <span class="toolbar-meta">共 {{ total }} 条</span>
    </div>

    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th class="col-time">下单时间</th>
            <th class="col-brand">品牌</th>
            <th class="col-trade">商户单号</th>
            <th class="col-phone">手机号</th>
            <th class="col-amount">金额</th>
            <th class="col-pay">方式</th>
            <th class="col-status">状态</th>
            <th class="col-ops">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="loading">
            <td colspan="8" class="empty">加载中…</td>
          </tr>
          <tr v-else-if="!items.length">
            <td colspan="8" class="empty">暂无订单</td>
          </tr>
          <tr v-for="row in items" :key="row.id" class="data-row" @click="openDrawer(row)">
            <td class="col-time" :title="row.created_at || ''">{{ shortTime(row.created_at) }}</td>
            <td class="col-brand">{{ row.brand_name }}</td>
            <td class="col-trade">
              <button
                type="button"
                class="trade-btn"
                :title="row.out_trade_no"
                @click.stop="copyText(row.out_trade_no)"
              >
                {{ shortTradeNo(row.out_trade_no) }}
              </button>
            </td>
            <td class="col-phone">{{ row.contact_phone || row.contact_phone_masked || '—' }}</td>
            <td class="col-amount">¥{{ row.amount_yuan }}</td>
            <td class="col-pay">{{ tradeTypeLabel[row.pay_trade_type] || row.pay_trade_type }}</td>
            <td class="col-status">
              <span class="status" :data-status="row.status">{{ statusLabel[row.status] || row.status }}</span>
            </td>
            <td class="col-ops">
              <button type="button" class="detail-btn" @click.stop="openDrawer(row)">详情</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="pager">
      <button type="button" :disabled="loading || page <= 1" @click="page -= 1; loadOrders()">上一页</button>
      <span>第 {{ page }} 页</span>
      <button type="button" :disabled="loading || page * pageSize >= total" @click="page += 1; loadOrders()">下一页</button>
    </div>

    <div v-if="drawerOpen && selected" class="drawer-mask" @click.self="closeDrawer">
      <aside class="drawer" role="dialog" aria-label="订单填报详情">
        <header class="drawer-head">
          <div>
            <h3>{{ selected.brand_name }}</h3>
            <p class="muted">
              <span class="status" :data-status="selected.status">{{ statusLabel[selected.status] || selected.status }}</span>
              <span>¥{{ selected.amount_yuan }}</span>
            </p>
          </div>
          <button type="button" class="ghost-btn" @click="closeDrawer">关闭</button>
        </header>

        <dl class="detail-grid">
          <div>
            <dt>商户单号</dt>
            <dd>
              <button type="button" class="trade-btn block" :title="selected.out_trade_no" @click="copyText(selected.out_trade_no)">
                {{ selected.out_trade_no }}
              </button>
            </dd>
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
            <dt>售前诊断</dt>
            <dd>{{ selected.lead_diagnosis_id ? `#${selected.lead_diagnosis_id}` : '—' }}</dd>
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
.h5-orders-page {
  display: grid;
  gap: 12px;
  max-width: 1120px;
}

.toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  padding: 12px 14px;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  background: #fff;
}

.search-input,
.status-select {
  border: 1px solid #dbe3ef;
  border-radius: 8px;
  padding: 8px 12px;
  background: #f8fafc;
  color: #0f172a;
  font-size: 13px;
  outline: none;
}

.search-input {
  flex: 1 1 220px;
  min-width: 180px;
}

.search-input:focus,
.status-select:focus {
  border-color: #93c5fd;
  background: #fff;
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.12);
}

.status-select {
  min-width: 128px;
}

.toolbar-meta {
  margin-left: auto;
  color: #94a3b8;
  font-size: 12px;
}

.table-wrap {
  overflow: auto;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  background: #fff;
}

table {
  width: 100%;
  border-collapse: collapse;
  table-layout: fixed;
  font-size: 13px;
}

th,
td {
  padding: 12px 14px;
  border-bottom: 1px solid #f1f5f9;
  text-align: left;
  vertical-align: middle;
}

th {
  background: #f8fafc;
  color: #64748b;
  font-weight: 600;
  font-size: 12px;
  letter-spacing: 0.02em;
}

.data-row {
  cursor: pointer;
  transition: background 0.12s ease;
}

.data-row:hover {
  background: #f8fbff;
}

.col-time { width: 118px; color: #475569; white-space: nowrap; }
.col-brand { width: 96px; font-weight: 650; color: #0f172a; }
.col-trade { width: 168px; }
.col-phone { width: 120px; font-variant-numeric: tabular-nums; letter-spacing: 0.02em; }
.col-amount { width: 72px; font-weight: 650; color: #0f172a; white-space: nowrap; }
.col-pay { width: 88px; color: #475569; white-space: nowrap; }
.col-status { width: 88px; }
.col-ops { width: 72px; }

.trade-btn {
  border: none;
  background: transparent;
  padding: 0;
  margin: 0;
  color: #64748b;
  font: inherit;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
  cursor: pointer;
  text-align: left;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.trade-btn:hover { color: #2563eb; }
.trade-btn.block {
  display: block;
  white-space: normal;
  word-break: break-all;
  line-height: 1.4;
}

.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
  word-break: break-all;
}

.muted { color: #94a3b8; font-size: 12px; }
.empty { text-align: center; color: #94a3b8; padding: 36px 12px; }

.status {
  display: inline-flex;
  align-items: center;
  min-height: 22px;
  padding: 0 8px;
  border-radius: 999px;
  background: #f1f5f9;
  color: #475569;
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
}
.status[data-status='paid'] { background: #ecfdf5; color: #047857; }
.status[data-status='pending'] { background: #fff7ed; color: #c2410c; }
.status[data-status='failed'] { background: #fef2f2; color: #b91c1c; }
.status[data-status='closed'] { background: #f1f5f9; color: #64748b; }

.detail-btn {
  border: 1px solid #dbe3ef;
  background: #fff;
  color: #2563eb;
  border-radius: 7px;
  padding: 4px 10px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}
.detail-btn:hover {
  border-color: #93c5fd;
  background: #eff6ff;
}

.pager {
  display: flex;
  align-items: center;
  gap: 10px;
  color: #64748b;
  font-size: 13px;
}
.pager button,
.ghost-btn {
  border: 1px solid #dbe3ef;
  background: #fff;
  border-radius: 8px;
  padding: 6px 12px;
  cursor: pointer;
  color: #334155;
  font-size: 13px;
}
.pager button:disabled { opacity: 0.45; cursor: not-allowed; }
.pager button:not(:disabled):hover,
.ghost-btn:hover {
  border-color: #93c5fd;
  background: #f8fbff;
}

.drawer-mask {
  position: fixed;
  inset: 0;
  z-index: 40;
  background: rgba(15, 23, 42, 0.32);
  display: flex;
  justify-content: flex-end;
}
.drawer {
  width: min(420px, 100vw);
  height: 100%;
  background: #fff;
  box-shadow: -12px 0 32px rgba(15, 23, 42, 0.14);
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 20px 20px 24px;
  overflow: auto;
}
.drawer-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
}
.drawer-head h3 { margin: 0 0 8px; font-size: 18px; color: #0f172a; }
.drawer-head .muted {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 0;
  color: #64748b;
}
.detail-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px 16px;
  margin: 0;
  padding: 14px;
  border-radius: 12px;
  background: #f8fafc;
}
.detail-grid .span-2 { grid-column: 1 / -1; }
.detail-grid dt {
  margin: 0 0 4px;
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
  font-size: 13px;
  color: #64748b;
  font-weight: 600;
}
.prompts-block ol {
  margin: 0;
  padding: 12px 12px 12px 28px;
  border-radius: 12px;
  background: #f8fafc;
  display: grid;
  gap: 8px;
  font-size: 13px;
  color: #334155;
}
.drawer-foot {
  margin-top: auto;
  padding-top: 4px;
}
.drawer-foot .primary-btn {
  width: 100%;
}
.drawer-foot .primary-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
  transform: none;
  box-shadow: none;
}
</style>
