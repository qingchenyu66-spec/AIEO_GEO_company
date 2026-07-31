<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { RefreshCw, Save, Wallet, X } from '@lucide/vue'
import CeleryMonitorPanel from '../components/CeleryMonitorPanel.vue'
import {
  getAlertThresholds,
  getMolizhishuBalance,
  updateAlertThreshold,
  type AlertThreshold,
  type MolizhishuBalance,
  type UpdateAlertThresholdPayload,
} from '../../../services/platforms'
import { extractErrorDetail } from '../../../utils/requestError'

const businessThresholds = ref<AlertThreshold[]>([])
const queueThresholds = ref<AlertThreshold[]>([])
const balance = ref<MolizhishuBalance | null>(null)
const loading = ref(false)
const savingId = ref<number | null>(null)
const errorText = ref('')
const successText = ref('')
const editingId = ref<number | null>(null)
const draft = reactive<UpdateAlertThresholdPayload>({})

const balanceThreshold = computed(() =>
  businessThresholds.value.find(item => item.metric_type === 'molizhishu_balance'),
)

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

const balanceStatusLabel = computed(() => {
  if (!balance.value?.available) return '暂无法获取'
  if (balanceStatus.value === 'normal') return '正常'
  if (balanceStatus.value === 'warning') return '余额偏低'
  if (balanceStatus.value === 'critical') return '余额不足'
  return '未知'
})

function startEdit(item: AlertThreshold) {
  editingId.value = item.id
  draft.threshold_name = item.threshold_name
  draft.warning_value = item.warning_value
  draft.critical_value = item.critical_value
  draft.unit = item.unit
  draft.enabled = item.enabled
  errorText.value = ''
  successText.value = ''
}

function cancelEdit() {
  editingId.value = null
}

async function saveEdit(item: AlertThreshold) {
  savingId.value = item.id
  errorText.value = ''
  successText.value = ''
  try {
    await updateAlertThreshold(item.id, {
      threshold_name: draft.threshold_name,
      warning_value: draft.warning_value,
      critical_value: draft.critical_value,
      unit: draft.unit,
      enabled: draft.enabled,
    })
    successText.value = `已保存「${draft.threshold_name || item.threshold_name}」`
    editingId.value = null
    await loadThresholds()
  } catch (error: unknown) {
    errorText.value = extractErrorDetail(error)
  } finally {
    savingId.value = null
  }
}

async function loadThresholds() {
  loading.value = true
  errorText.value = ''
  try {
    const [businessRows, queueRows, balanceData] = await Promise.all([
      getAlertThresholds('business'),
      getAlertThresholds('technical'),
      getMolizhishuBalance(),
    ])
    businessThresholds.value = businessRows
    queueThresholds.value = queueRows
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
  <!-- 2026-07-31 - 预警页太乱 - 去重 hero/装饰，规则改卡片行，功能不变 -->
  <section class="feature-page alert-thresholds-page">
    <div v-if="errorText" class="ops-error">{{ errorText }}</div>
    <div v-if="successText" class="ops-success">{{ successText }}</div>

    <!-- 规则放上：先改阈值；调度监控收在下面并默认折叠明细 -->
    <article class="panel alert-rules-panel">
      <div class="panel-head">
        <div>
          <h2>队列积压预警</h2>
          <p>submit / sync 队列深度</p>
        </div>
        <button class="ops-refresh compact" :disabled="loading" @click="loadThresholds">
          <RefreshCw :class="{ spinning: loading }" />
          {{ loading ? '刷新中' : '刷新规则' }}
        </button>
      </div>

      <div v-if="queueThresholds.length" class="alert-rule-list">
        <div v-for="item in queueThresholds" :key="item.id" class="alert-rule-card" :class="{ editing: editingId === item.id }">
          <template v-if="editingId === item.id">
            <div class="alert-rule-main">
              <input v-model="draft.threshold_name" class="alert-threshold-input" placeholder="规则名称" />
              <span class="alert-rule-metric">{{ item.metric_label || item.threshold_name }}</span>
            </div>
            <div class="alert-rule-fields">
              <label><span>预警</span><input v-model="draft.warning_value" class="alert-threshold-input" /></label>
              <label><span>严重</span><input v-model="draft.critical_value" class="alert-threshold-input" /></label>
              <label><span>单位</span><input v-model="draft.unit" class="alert-threshold-input" /></label>
              <label class="alert-threshold-toggle">
                <input v-model="draft.enabled" type="checkbox" />
                启用
              </label>
            </div>
            <div class="alert-threshold-actions">
              <button class="ops-mini-btn primary" :disabled="savingId === item.id" @click="saveEdit(item)">
                <Save /> 保存
              </button>
              <button class="ops-mini-btn" @click="cancelEdit"><X /> 取消</button>
            </div>
          </template>
          <template v-else>
            <div class="alert-rule-main">
              <b>{{ item.threshold_name }}</b>
              <span class="alert-rule-metric">{{ item.metric_label || item.threshold_name }}</span>
            </div>
            <div class="alert-rule-meta">
              <span>预警 <strong>{{ item.warning_value }}</strong>{{ item.unit }}</span>
              <span>严重 <strong>{{ item.critical_value }}</strong>{{ item.unit }}</span>
              <em :class="{ off: !item.enabled }">{{ item.enabled ? '启用' : '停用' }}</em>
            </div>
            <button class="ops-mini-btn" @click="startEdit(item)">编辑</button>
          </template>
        </div>
      </div>
      <div v-else class="mini-empty">暂无队列预警规则。</div>
    </article>

    <article class="panel alert-rules-panel">
      <div class="panel-head">
        <div>
          <h2>业务预警规则</h2>
          <p>排名、舆情、任务失败率与账户余额等</p>
        </div>
      </div>

      <section v-if="balanceThreshold" class="alert-balance-card" :class="`is-${balanceStatus}`">
        <Wallet />
        <div>
          <span>账户余额（实时）</span>
          <strong>{{ balance?.current_balance_text || '—' }}</strong>
          <p>
            预警 ≤ {{ balanceThreshold.warning_value }}{{ balanceThreshold.unit }}
            · 严重 ≤ {{ balanceThreshold.critical_value }}{{ balanceThreshold.unit }}
          </p>
        </div>
        <em>{{ balanceStatusLabel }}</em>
      </section>

      <div v-if="businessThresholds.length" class="alert-rule-list">
        <div v-for="item in businessThresholds" :key="item.id" class="alert-rule-card" :class="{ editing: editingId === item.id }">
          <template v-if="editingId === item.id">
            <div class="alert-rule-main">
              <input v-model="draft.threshold_name" class="alert-threshold-input" placeholder="规则名称" />
              <span class="alert-rule-metric">{{ item.metric_label || item.threshold_name }}</span>
            </div>
            <div class="alert-rule-fields">
              <label><span>预警</span><input v-model="draft.warning_value" class="alert-threshold-input" /></label>
              <label><span>严重</span><input v-model="draft.critical_value" class="alert-threshold-input" /></label>
              <label><span>单位</span><input v-model="draft.unit" class="alert-threshold-input" /></label>
              <label class="alert-threshold-toggle">
                <input v-model="draft.enabled" type="checkbox" />
                启用
              </label>
            </div>
            <div class="alert-threshold-actions">
              <button class="ops-mini-btn primary" :disabled="savingId === item.id" @click="saveEdit(item)">
                <Save /> 保存
              </button>
              <button class="ops-mini-btn" @click="cancelEdit"><X /> 取消</button>
            </div>
          </template>
          <template v-else>
            <div class="alert-rule-main">
              <b>{{ item.threshold_name }}</b>
              <span class="alert-rule-metric">{{ item.metric_label || item.threshold_name }}</span>
            </div>
            <div class="alert-rule-meta">
              <span>预警 <strong>{{ item.warning_value }}</strong>{{ item.unit }}</span>
              <span>严重 <strong>{{ item.critical_value }}</strong>{{ item.unit }}</span>
              <em :class="{ off: !item.enabled }">{{ item.enabled ? '启用' : '停用' }}</em>
            </div>
            <button class="ops-mini-btn" @click="startEdit(item)">编辑</button>
          </template>
        </div>
      </div>
      <div v-else class="mini-empty">暂无业务预警规则。</div>
    </article>

    <CeleryMonitorPanel />
  </section>
</template>
