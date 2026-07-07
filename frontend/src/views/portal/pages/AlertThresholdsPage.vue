<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { BellRing, RefreshCw, Save, Wallet, X } from '@lucide/vue'
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
  <section class="feature-page alert-thresholds-page">
    <section class="ops-hero compact-hero">
      <div>
        <span>系统预警</span>
        <h2>预警阈值与调度监控</h2>
        <p>上方查看任务调度运行情况；下方可编辑业务指标与队列积压预警阈值。</p>
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
          <h2>队列积压预警</h2>
          <p>submit / sync 队列深度阈值，保存后立即用于监控与告警（优先读数据库，未配置时回退 .env）</p>
        </div>
        <BellRing />
      </div>

      <div v-if="errorText" class="ops-error">{{ errorText }}</div>
      <div v-if="successText" class="ops-success">{{ successText }}</div>

      <div v-if="queueThresholds.length" class="alert-threshold-table has-actions">
        <div class="alert-threshold-head">
          <span>规则名称</span>
          <span>指标</span>
          <span>预警值</span>
          <span>严重值</span>
          <span>单位</span>
          <span>状态</span>
          <span>操作</span>
        </div>
        <div v-for="item in queueThresholds" :key="item.id" class="alert-threshold-row">
          <template v-if="editingId === item.id">
            <input v-model="draft.threshold_name" class="alert-threshold-input" />
            <span>{{ item.metric_label || item.threshold_name }}</span>
            <input v-model="draft.warning_value" class="alert-threshold-input narrow" />
            <input v-model="draft.critical_value" class="alert-threshold-input narrow" />
            <input v-model="draft.unit" class="alert-threshold-input narrow" />
            <label class="alert-threshold-toggle">
              <input v-model="draft.enabled" type="checkbox" />
              启用
            </label>
            <span class="alert-threshold-actions">
              <button class="ops-mini-btn primary" :disabled="savingId === item.id" @click="saveEdit(item)">
                <Save /> 保存
              </button>
              <button class="ops-mini-btn" @click="cancelEdit"><X /> 取消</button>
            </span>
          </template>
          <template v-else>
            <b>{{ item.threshold_name }}</b>
            <span>{{ item.metric_label || item.threshold_name }}</span>
            <span>{{ item.warning_value }}</span>
            <span>{{ item.critical_value }}</span>
            <span>{{ item.unit || '—' }}</span>
            <em :class="{ off: !item.enabled }">{{ item.enabled ? '启用' : '停用' }}</em>
            <button class="ops-mini-btn" @click="startEdit(item)">编辑</button>
          </template>
        </div>
      </div>
      <div v-else class="mini-empty">暂无队列预警规则。</div>
    </article>

    <article class="panel">
      <div class="panel-head">
        <div>
          <h2>业务预警规则</h2>
          <p>排名、舆情、任务失败率与账户余额等业务指标</p>
        </div>
        <BellRing />
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
        <em>{{ balance?.available ? (balanceStatus === 'normal' ? '正常' : balanceStatus === 'warning' ? '余额偏低' : '余额不足') : '暂无法获取' }}</em>
      </section>

      <div v-if="businessThresholds.length" class="alert-threshold-table has-actions">
        <div class="alert-threshold-head">
          <span>规则名称</span>
          <span>指标</span>
          <span>预警值</span>
          <span>严重值</span>
          <span>单位</span>
          <span>状态</span>
          <span>操作</span>
        </div>
        <div v-for="item in businessThresholds" :key="item.id" class="alert-threshold-row">
          <template v-if="editingId === item.id">
            <input v-model="draft.threshold_name" class="alert-threshold-input" />
            <span>{{ item.metric_label || item.threshold_name }}</span>
            <input v-model="draft.warning_value" class="alert-threshold-input narrow" />
            <input v-model="draft.critical_value" class="alert-threshold-input narrow" />
            <input v-model="draft.unit" class="alert-threshold-input narrow" />
            <label class="alert-threshold-toggle">
              <input v-model="draft.enabled" type="checkbox" />
              启用
            </label>
            <span class="alert-threshold-actions">
              <button class="ops-mini-btn primary" :disabled="savingId === item.id" @click="saveEdit(item)">
                <Save /> 保存
              </button>
              <button class="ops-mini-btn" @click="cancelEdit"><X /> 取消</button>
            </span>
          </template>
          <template v-else>
            <b>{{ item.threshold_name }}</b>
            <span>{{ item.metric_label || item.threshold_name }}</span>
            <span>{{ item.warning_value }}</span>
            <span>{{ item.critical_value }}</span>
            <span>{{ item.unit || '—' }}</span>
            <em :class="{ off: !item.enabled }">{{ item.enabled ? '启用' : '停用' }}</em>
            <button class="ops-mini-btn" @click="startEdit(item)">编辑</button>
          </template>
        </div>
      </div>
      <div v-else class="mini-empty">
        暂无业务预警规则。请联系管理员在后台配置。
      </div>
    </article>
  </section>
</template>
