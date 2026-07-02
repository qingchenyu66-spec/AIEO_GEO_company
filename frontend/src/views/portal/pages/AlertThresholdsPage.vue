<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { BellRing, RefreshCw, Wallet } from '@lucide/vue'
import CeleryMonitorPanel from '../components/CeleryMonitorPanel.vue'
import { getAlertThresholds, getMolizhishuBalance, type AlertThreshold, type MolizhishuBalance } from '../../../services/platforms'
import { extractErrorDetail } from '../../../utils/requestError'

const thresholds = ref<AlertThreshold[]>([])
const balance = ref<MolizhishuBalance | null>(null)
const loading = ref(false)
const errorText = ref('')

const balanceThreshold = computed(() => thresholds.value.find(item => item.metric_type === 'molizhishu_balance'))

const balanceStatus = computed(() => {
  const rule = balanceThreshold.value
  const current = balance.value?.current_balance
  if (!rule || current == null) return 'unknown'
  const warning = Number(rule.warning_value)
  const critical = Number(rule.critical_value)
  if (!Number.isFinite(warning) || !Number.isFinite(critical)) return 'unknown'
  if (current <= critical) return 'critical'
  if (current <= warning) return 'warning'
  return 'normal'
})

async function loadThresholds() {
  loading.value = true
  errorText.value = ''
  try {
    const [rows, balanceData] = await Promise.all([getAlertThresholds(), getMolizhishuBalance()])
    thresholds.value = rows
    balance.value = balanceData
  } catch (error: unknown) {
    errorText.value = extractErrorDetail(error)
  } finally {
    loading.value = false
  }
}

onMounted(loadThresholds)
</script>

<template>
  <section class="feature-page alert-thresholds-page">
    <section class="ops-hero compact-hero">
      <div>
        <span>系统预警</span>
        <h2>预警阈值与调度监控</h2>
        <p>上方查看任务调度运行情况；下方配置监测业务指标与账户费用预警。</p>
      </div>
      <button class="ops-refresh" :disabled="loading" @click="loadThresholds">
        <RefreshCw :class="{ spinning: loading }" />
        {{ loading ? '刷新中' : '刷新规则' }}
      </button>
    </section>

    <CeleryMonitorPanel />

    <article class="panel">
      <div class="panel-head">
        <div>
          <h2>业务预警规则</h2>
          <p>排名、舆情、任务失败率与账户余额等业务指标，不含调度队列等技术项</p>
        </div>
        <BellRing />
      </div>

      <div v-if="errorText" class="ops-error">{{ errorText }}</div>

      <section v-if="balanceThreshold" class="alert-balance-card" :class="`is-${balanceStatus}`">
        <Wallet />
        <div>
          <span>模力账户余额（实时）</span>
          <strong>{{ balance?.current_balance_text || '—' }}</strong>
          <p>
            预警 ≤ {{ balanceThreshold.warning_value }}{{ balanceThreshold.unit }}
            · 严重 ≤ {{ balanceThreshold.critical_value }}{{ balanceThreshold.unit }}
          </p>
        </div>
        <em>{{ balance?.available ? (balanceStatus === 'normal' ? '正常' : balanceStatus === 'warning' ? '余额偏低' : '余额不足') : '暂无法获取' }}</em>
      </section>

      <div v-if="thresholds.length" class="alert-threshold-table">
        <div class="alert-threshold-head">
          <span>规则名称</span>
          <span>指标</span>
          <span>预警值</span>
          <span>严重值</span>
          <span>单位</span>
          <span>状态</span>
        </div>
        <div v-for="item in thresholds" :key="item.id" class="alert-threshold-row">
          <b>{{ item.threshold_name }}</b>
          <span>{{ item.metric_label || item.threshold_name }}</span>
          <span>{{ item.warning_value }}</span>
          <span>{{ item.critical_value }}</span>
          <span>{{ item.unit || '—' }}</span>
          <em :class="{ off: !item.enabled }">{{ item.enabled ? '启用' : '停用' }}</em>
        </div>
      </div>
      <div v-else class="mini-empty">
        暂无业务预警规则。请联系管理员在后台配置。
      </div>
    </article>
  </section>
</template>
