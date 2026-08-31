<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { getSystemConfigs, updateSystemConfig, type SystemConfigRecord } from '../../../services/management'
import { extractErrorDetail } from '../../../utils/requestError'
import { platformLabelMap, supportedPlatforms } from '../portalMaps'

const props = defineProps<{ canEdit: boolean }>()

const SLOTS_PER_DAY = 3
const MIN_RUNS = 3
const MAX_RUNS = 90 // 30 天 × 每天 3 档

const loading = ref(false)
const saving = ref(false)
const rows = ref<SystemConfigRecord[]>([])

const form = ref({
  enabled: true,
  price_yuan: 9.9,
  schedule_runs: 9,
  platforms: [] as string[],
})

const derivedDays = computed(() => Math.max(1, Math.round(Number(form.value.schedule_runs) || MIN_RUNS) / SLOTS_PER_DAY))

function rowByKey(key: string) {
  return rows.value.find(item => item.config_key === key)
}

function parsePlatforms(raw: string | undefined) {
  if (!raw) return []
  try {
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed.map(item => String(item)) : []
  } catch {
    return raw.split(/[,，;；\s]+/).map(item => item.trim()).filter(Boolean)
  }
}

function normalizeRuns(raw: number) {
  let runs = Math.round(Number(raw) || MIN_RUNS)
  // 2026-08-31 - 后台改配次数：每天最多 3 档，次数须为 3 的倍数，天数=次数÷3
  if (runs % SLOTS_PER_DAY !== 0) {
    runs = Math.max(MIN_RUNS, Math.round(runs / SLOTS_PER_DAY) * SLOTS_PER_DAY)
  }
  return Math.max(MIN_RUNS, Math.min(MAX_RUNS, runs))
}

function loadFormFromRows() {
  form.value.enabled = String(rowByKey('h5_diagnosis_enabled')?.config_value || 'true').toLowerCase() !== 'false'
  form.value.price_yuan = Number(rowByKey('h5_diagnosis_price_fen')?.config_value || 990) / 100
  const days = Number(rowByKey('h5_diagnosis_schedule_days')?.config_value || 3)
  form.value.schedule_runs = normalizeRuns(Math.max(1, days) * SLOTS_PER_DAY)
  form.value.platforms = parsePlatforms(rowByKey('h5_diagnosis_platforms')?.config_value)
}

async function loadRows() {
  loading.value = true
  try {
    rows.value = (await getSystemConfigs('schedule')).filter(item => item.config_key.startsWith('h5_diagnosis_'))
    loadFormFromRows()
  } finally {
    loading.value = false
  }
}

function togglePlatform(code: string) {
  if (!props.canEdit) return
  const set = new Set(form.value.platforms)
  if (set.has(code)) set.delete(code)
  else set.add(code)
  form.value.platforms = [...set]
}

async function saveAll() {
  if (!props.canEdit) return
  if (!form.value.platforms.length) {
    ElMessage.warning('请至少选择一个监测平台')
    return
  }
  const runs = normalizeRuns(form.value.schedule_runs)
  form.value.schedule_runs = runs
  const days = runs / SLOTS_PER_DAY
  saving.value = true
  try {
    const updates: Array<[string, string]> = [
      ['h5_diagnosis_enabled', form.value.enabled ? 'true' : 'false'],
      ['h5_diagnosis_price_fen', String(Math.round(Number(form.value.price_yuan) * 100))],
      ['h5_diagnosis_schedule_days', String(days)],
      ['h5_diagnosis_platforms', JSON.stringify(form.value.platforms)],
    ]
    for (const [key, value] of updates) {
      const row = rowByKey(key)
      if (!row?.id) continue
      await updateSystemConfig(row.id, value)
    }
    ElMessage.success('H5 付费诊断配置已保存')
    await loadRows()
  } catch (error: unknown) {
    ElMessage.error(extractErrorDetail(error) || '保存失败')
  } finally {
    saving.value = false
  }
}

onMounted(loadRows)
</script>

<template>
  <section class="h5-config-panel">
    <div class="head">
      <div>
        <h3>H5 付费诊断（9.9）</h3>
        <p>按监测次数配置（每天最多 {{ SLOTS_PER_DAY }} 档）。当前 {{ form.schedule_runs }} 次 ≈ {{ derivedDays }} 天。</p>
      </div>
      <button v-if="canEdit" type="button" class="primary-btn small-btn" :disabled="saving || loading" @click="saveAll">
        {{ saving ? '保存中…' : '保存 H5 配置' }}
      </button>
    </div>

    <div v-if="loading" class="mini-empty">加载 H5 配置…</div>
    <div v-else class="grid">
      <label class="field">
        <span>开关</span>
        <select v-model="form.enabled" :disabled="!canEdit">
          <option :value="true">开启</option>
          <option :value="false">关闭</option>
        </select>
      </label>
      <label class="field">
        <span>体验价（元）</span>
        <input v-model.number="form.price_yuan" type="number" min="0.01" step="0.01" :disabled="!canEdit">
      </label>
      <label class="field">
        <span>监测次数</span>
        <input
          v-model.number="form.schedule_runs"
          type="number"
          :min="MIN_RUNS"
          :max="MAX_RUNS"
          :step="SLOTS_PER_DAY"
          :disabled="!canEdit"
          @blur="form.schedule_runs = normalizeRuns(form.schedule_runs)"
        >
      </label>
      <div class="field full">
        <span>监测平台</span>
        <div class="platform-grid">
          <button
            v-for="item in supportedPlatforms"
            :key="item.code"
            type="button"
            class="platform-chip"
            :class="{ active: form.platforms.includes(item.code) }"
            :disabled="!canEdit"
            @click="togglePlatform(item.code)"
          >
            {{ platformLabelMap[item.code] || item.name || item.code }}
          </button>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.h5-config-panel {
  margin-bottom: 16px;
  padding: 14px;
  border-radius: 14px;
  border: 1px solid rgba(14, 116, 144, 0.18);
  background: linear-gradient(180deg, rgba(240, 253, 250, 0.95), rgba(248, 250, 252, 0.95));
}
.head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
  margin-bottom: 12px;
}
.head h3 { margin: 0 0 4px; font-size: 16px; }
.head p { margin: 0; font-size: 12px; color: #64748b; line-height: 1.5; }
.grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}
.field { display: grid; gap: 6px; font-size: 13px; }
.field.full { grid-column: 1 / -1; }
.field input, .field select {
  border: 1px solid #cbd5e1;
  border-radius: 10px;
  padding: 8px 10px;
  font-size: 14px;
  background: #fff;
}
.platform-grid { display: flex; flex-wrap: wrap; gap: 8px; }
.platform-chip {
  border: 1px solid #cbd5e1;
  border-radius: 999px;
  padding: 6px 12px;
  background: #fff;
  font-size: 12px;
}
.platform-chip.active {
  border-color: #0f766e;
  background: #ecfdf5;
  color: #0f766e;
}
@media (max-width: 900px) {
  .grid { grid-template-columns: 1fr; }
}
</style>
