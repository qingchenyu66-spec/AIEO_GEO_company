<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { listH5DiagnosisAdminOrders } from '../../../services/h5Diagnosis'
import { extractErrorDetail } from '../../../utils/requestError'

const loading = ref(false)
const keyword = ref('')
const status = ref('')
const page = ref(1)
const pageSize = 20
const total = ref(0)
const items = ref<Awaited<ReturnType<typeof listH5DiagnosisAdminOrders>>['items']>([])

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
    ElMessage.error(extractErrorDetail(error, '加载 H5 订单失败'))
  } finally {
    loading.value = false
  }
}

function search() {
  page.value = 1
  void loadOrders()
}

function goLead(leadId: number | null) {
  if (!leadId) return
  ElMessage.info(`关联售前诊断 #${leadId}，请到侧栏「售前诊断」查看`)
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
            <th>手机号</th>
            <th>金额</th>
            <th>方式</th>
            <th>状态</th>
            <th>微信单号</th>
            <th>售前诊断</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="loading">
            <td colspan="8" class="empty">加载中…</td>
          </tr>
          <tr v-else-if="!items.length">
            <td colspan="8" class="empty">暂无订单</td>
          </tr>
          <tr v-for="row in items" :key="row.id">
            <td>{{ row.created_at || '—' }}</td>
            <td>
              <div class="brand">{{ row.brand_name }}</div>
              <small>{{ row.out_trade_no }}</small>
            </td>
            <td>{{ row.contact_phone_masked }}</td>
            <td>¥{{ row.amount_yuan }}</td>
            <td>{{ tradeTypeLabel[row.pay_trade_type] || row.pay_trade_type }}</td>
            <td>
              <span class="status" :data-status="row.status">{{ statusLabel[row.status] || row.status }}</span>
              <div v-if="row.paid_at" class="muted">{{ row.paid_at }}</div>
            </td>
            <td>{{ row.wx_transaction_id || '—' }}</td>
            <td>
              <button
                v-if="row.lead_diagnosis_id"
                type="button"
                class="link"
                @click="goLead(row.lead_diagnosis_id)"
              >
                #{{ row.lead_diagnosis_id }}
              </button>
              <span v-else>—</span>
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
th { background: #f8fafc; color: #475569; font-weight: 600; }
.brand { font-weight: 600; }
small, .muted { color: #94a3b8; font-size: 12px; }
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
.pager button {
  border: 1px solid #cbd5e1;
  background: #fff;
  border-radius: 8px;
  padding: 6px 10px;
}
.pager button:disabled { opacity: 0.5; }
</style>
