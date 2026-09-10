<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  fetchH5DiagnosisResult,
  unlockH5DiagnosisResultByPhone,
  type H5DiagnosisResult,
} from '../../services/h5Diagnosis'

const route = useRoute()
const router = useRouter()

const loading = ref(true)
const unlocking = ref(false)
const errorText = ref('')
const needUnlock = ref(false)
const phoneInput = ref('')
const result = ref<H5DiagnosisResult | null>(null)
let pollTimer: number | null = null

const outTradeNo = computed(() => String(route.query.out_trade_no || '').trim())
const tokenFromQuery = computed(() => String(route.query.t || '').trim())

const progressPercent = computed(() => result.value?.progress.percent ?? 0)
const reportHtmlUrl = computed(() => {
  if (!outTradeNo.value) return ''
  const params = new URLSearchParams()
  if (tokenFromQuery.value) params.set('t', tokenFromQuery.value)
  const qs = params.toString()
  return `/api/v1/h5/diagnosis/orders/${encodeURIComponent(outTradeNo.value)}/report.html${qs ? `?${qs}` : ''}`
})

function stopPolling() {
  if (pollTimer != null) {
    window.clearInterval(pollTimer)
    pollTimer = null
  }
}

async function loadResult() {
  if (!outTradeNo.value) {
    needUnlock.value = true
    errorText.value = ''
    loading.value = false
    return
  }
  loading.value = true
  errorText.value = ''
  try {
    result.value = await fetchH5DiagnosisResult(outTradeNo.value, {
      t: tokenFromQuery.value || undefined,
    })
    needUnlock.value = false
    if (result.value.ready) {
      stopPolling()
    } else {
      startPolling()
    }
  } catch (error: unknown) {
    const msg = error instanceof Error ? error.message : '加载失败'
    if (/无权|过期|手机号|未支付|没有权限/.test(msg)) {
      needUnlock.value = true
      errorText.value = msg
      stopPolling()
    } else {
      errorText.value = msg
    }
  } finally {
    loading.value = false
  }
}

function startPolling() {
  stopPolling()
  pollTimer = window.setInterval(() => {
    void loadResult()
  }, 15000)
}

async function unlock() {
  const phone = phoneInput.value.trim()
  if (!/^1\d{10}$/.test(phone)) {
    errorText.value = '请填写下单时的11位手机号'
    return
  }
  unlocking.value = true
  errorText.value = ''
  try {
    const data = await unlockH5DiagnosisResultByPhone(phone)
    needUnlock.value = false
    await router.replace({
      path: '/h5/diagnosis/result',
      query: { out_trade_no: data.out_trade_no },
    })
    await loadResult()
  } catch (error: unknown) {
    errorText.value = error instanceof Error ? error.message : '验证失败'
  } finally {
    unlocking.value = false
  }
}

watch(
  () => route.query.out_trade_no,
  () => {
    void loadResult()
  },
)

onMounted(() => {
  void loadResult()
})
onUnmounted(stopPolling)
</script>

<template>
  <div class="h5-page">
    <div class="orb orb-a" aria-hidden="true" />
    <div class="orb orb-b" aria-hidden="true" />

    <div class="shell">
      <header class="hero">
        <button type="button" class="back" @click="router.push('/h5/diagnosis')">← 返回</button>
        <h1>诊断结果</h1>
      </header>

      <p v-if="loading && !result" class="banner hint">加载中…</p>
      <p v-else-if="errorText" class="banner" :class="needUnlock ? 'warn' : 'error'">{{ errorText }}</p>

      <div v-if="needUnlock" class="card unlock">
        <p class="section-title">验证后查看</p>
        <label class="field">
          <span>下单手机号</span>
          <input
            v-model="phoneInput"
            maxlength="11"
            inputmode="numeric"
            placeholder="请输入11位手机号"
            autocomplete="tel"
          />
        </label>
        <button type="button" class="primary" :disabled="unlocking" @click="unlock">
          {{ unlocking ? '验证中…' : '查看结果' }}
        </button>
      </div>

      <div v-else-if="result" class="card">
        <div class="brand-row">
          <strong>{{ result.brand_name }}</strong>
          <span class="tag">{{ result.ready ? '已完成' : '检测中' }}</span>
        </div>
        <p class="muted">单号 {{ result.out_trade_no }} · {{ result.contact_phone_masked }}</p>

        <div class="progress-block">
          <div class="progress-head">
            <span>进度</span>
            <span>{{ result.progress.completed_runs }}/{{ result.progress.total_runs }}</span>
          </div>
          <div class="bar">
            <i :style="{ width: `${progressPercent}%` }" />
          </div>
          <p class="muted">{{ result.plan_hint }}</p>
        </div>

        <template v-if="result.ready && result.summary">
          <div class="kpi-grid">
            <div class="kpi">
              <span>健康分</span>
              <strong>{{ result.summary.health_score ?? '—' }}</strong>
            </div>
            <div class="kpi">
              <span>提及率</span>
              <strong>{{ result.summary.mention_rate ?? '—' }}</strong>
            </div>
            <div class="kpi">
              <span>平均排名</span>
              <strong>{{ result.summary.avg_rank ?? '—' }}</strong>
            </div>
          </div>
          <p v-if="result.summary.headline" class="headline">{{ result.summary.headline }}</p>
          <ul v-if="result.summary.bullets?.length" class="bullets">
            <li v-for="(item, idx) in result.summary.bullets" :key="idx">{{ item }}</li>
          </ul>
          <a class="primary link" :href="reportHtmlUrl" target="_blank" rel="noopener">打开完整报告</a>
        </template>
        <p v-else class="muted wait">完成后可在本页查看报告摘要。</p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.h5-page {
  min-height: 100vh;
  padding: 20px 16px 40px;
  background: linear-gradient(180deg, #eff6ff 0%, #f8fafc 42%, #f1f5f9 100%);
  position: relative;
  overflow: hidden;
  font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
}
.orb {
  position: absolute;
  border-radius: 50%;
  filter: blur(40px);
  pointer-events: none;
}
.orb-a {
  width: 220px;
  height: 220px;
  top: -80px;
  right: -60px;
  background: rgba(37, 99, 235, 0.18);
}
.orb-b {
  width: 180px;
  height: 180px;
  bottom: 10%;
  left: -70px;
  background: rgba(14, 165, 233, 0.12);
}
.shell {
  position: relative;
  z-index: 1;
  max-width: 480px;
  margin: 0 auto;
}
.hero {
  margin-bottom: 14px;
}
.back {
  border: none;
  background: transparent;
  color: #64748b;
  padding: 0;
  font-size: 14px;
  cursor: pointer;
}
.hero h1 {
  margin: 10px 0 0;
  font-size: 26px;
  color: #0f172a;
}
.banner {
  margin: 0 0 12px;
  padding: 10px 12px;
  border-radius: 12px;
  font-size: 13px;
}
.banner.hint { background: #eef2ff; color: #3730a3; }
.banner.warn { background: #fff7ed; color: #c2410c; }
.banner.error { background: #fef2f2; color: #b91c1c; }
.card {
  background: #fff;
  border-radius: 18px;
  padding: 18px 16px 20px;
  box-shadow: 0 12px 32px rgba(15, 23, 42, 0.08);
}
.section-title {
  margin: 0 0 12px;
  font-size: 16px;
  font-weight: 700;
  color: #0f172a;
}
.field {
  display: grid;
  gap: 6px;
  margin-bottom: 12px;
  font-size: 13px;
  color: #475569;
}
.field input {
  min-height: 42px;
  border: 1px solid #dbe4f2;
  border-radius: 12px;
  padding: 0 12px;
  font-size: 15px;
}
.primary {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  min-height: 44px;
  border: none;
  border-radius: 12px;
  background: #2563eb;
  color: #fff;
  font-size: 15px;
  font-weight: 700;
  cursor: pointer;
  text-decoration: none;
}
.primary:disabled { opacity: 0.6; cursor: not-allowed; }
.primary.link { margin-top: 14px; }
.brand-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}
.brand-row strong { font-size: 18px; color: #0f172a; }
.tag {
  padding: 4px 10px;
  border-radius: 999px;
  background: #eff6ff;
  color: #2563eb;
  font-size: 12px;
  font-weight: 700;
}
.muted { margin: 8px 0 0; color: #64748b; font-size: 13px; }
.progress-block { margin-top: 16px; }
.progress-head {
  display: flex;
  justify-content: space-between;
  font-size: 13px;
  color: #475569;
}
.bar {
  margin-top: 8px;
  height: 8px;
  border-radius: 999px;
  background: #e2e8f0;
  overflow: hidden;
}
.bar i {
  display: block;
  height: 100%;
  background: linear-gradient(90deg, #2563eb, #0ea5e9);
}
.kpi-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
  margin-top: 16px;
}
.kpi {
  background: #f8fafc;
  border-radius: 12px;
  padding: 10px 8px;
  text-align: center;
}
.kpi span { display: block; font-size: 12px; color: #64748b; }
.kpi strong { display: block; margin-top: 4px; font-size: 18px; color: #0f172a; }
.headline { margin: 14px 0 8px; font-size: 15px; font-weight: 650; color: #0f172a; }
.bullets {
  margin: 0;
  padding-left: 18px;
  color: #334155;
  font-size: 13px;
  line-height: 1.55;
}
.wait { margin-top: 14px; }
</style>
