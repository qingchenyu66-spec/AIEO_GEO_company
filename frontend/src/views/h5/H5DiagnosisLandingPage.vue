<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { fetchH5DiagnosisConfig, type H5DiagnosisConfig } from '../../services/h5Diagnosis'
import { getPlatformMeta } from '../portal/platformMeta'

const router = useRouter()
const loading = ref(true)
const config = ref<H5DiagnosisConfig | null>(null)

const platformItems = computed(() => {
  const codes = config.value?.platforms || []
  return codes.map(code => getPlatformMeta(code))
})

const scheduleSummary = computed(() => {
  const cfg = config.value
  if (!cfg) return ''
  return `${cfg.schedule_days} 天 · 每天 3 档 · 共 ${cfg.schedule_total} 次抓取`
})

const priceText = computed(() => `¥${config.value?.price_yuan ?? '9.9'}`)

const stats = computed(() => [
  { value: String(config.value?.platforms?.length || '—'), label: '本次覆盖 AI 平台' },
  { value: String(config.value?.schedule_total || '—'), label: '自动抓取次数' },
  { value: '3–5', label: '真实检测问法' },
  { value: '报告', label: '可见度诊断结论' },
])

const reasons = [
  {
    value: '真实抓取',
    title: '看清有没有被推荐',
    desc: '直接问豆包、DeepSeek 等平台，记录品牌是否出现在答案里。',
  },
  {
    value: '问法可配',
    title: '对准高意向提问',
    desc: '支持一键推荐行业问法，也可自定义检测问题，贴近真实搜索场景。',
  },
  {
    value: '结果可跟进',
    title: '顾问按微信号对接',
    desc: '抓取完成后生成售前诊断，方便销售继续沟通优化方向。',
  },
]

const steps = computed(() => [
  {
    no: '01',
    title: '填写品牌与问法',
    desc: '填写品牌信息，选择或自定义 3–5 条检测问题。',
  },
  {
    no: '02',
    title: '支付后自动开跑',
    desc: `支付 ${priceText.value} 后系统自动提交监测，无需人工催促。`,
  },
  {
    no: '03',
    title: '查看诊断结论',
    desc: scheduleSummary.value
      ? `${scheduleSummary.value}，完成后输出可见度诊断报告。`
      : '完成后输出可见度诊断报告，顾问可继续跟进。',
  },
])

onMounted(async () => {
  try {
    config.value = await fetchH5DiagnosisConfig()
  } finally {
    loading.value = false
  }
})

function goApply() {
  router.push('/h5/diagnosis/apply')
}
</script>

<template>
  <div class="landing">
    <div class="orb orb-a" aria-hidden="true" />
    <div class="orb orb-b" aria-hidden="true" />

    <header class="topbar">
      <div class="logo">
        <span class="logo-mark">艾</span>
        <span class="logo-text">艾迪亚 GEO</span>
      </div>
      <span class="top-link">体验诊断</span>
    </header>

    <section class="hero">
      <p class="badge">
        <i />
        AI 可见度诊断 · 体验版
      </p>
      <h1>
        让品牌在 AI 搜索时代
        <span>占据推荐位</span>
      </h1>
      <p class="sub">
        每天有大量用户通过豆包、DeepSeek 等 AI 平台做决策。
        先花 {{ priceText }} 做一次真实抓取诊断，看清品牌有没有被推荐。
      </p>

      <div class="hero-actions">
        <button type="button" class="btn-primary" :disabled="loading || !config?.enabled" @click="goApply">
          {{ config?.enabled ? `${priceText} 立即诊断` : '活动暂未开放' }}
        </button>
        <button type="button" class="btn-secondary" :disabled="loading || !config?.enabled" @click="goApply">
          填写信息开跑
        </button>
      </div>

      <div class="platform-block">
        <p>本次体验覆盖平台</p>
        <div class="platform-row">
          <span v-for="item in platformItems" :key="item.code" class="platform-pill">
            <img v-if="item.icon" :src="item.icon" :alt="item.name" loading="lazy">
            {{ item.name }}
          </span>
          <span v-if="!platformItems.length" class="platform-pill">加载中…</span>
        </div>
      </div>
    </section>

    <section class="stats">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <b>{{ item.value }}</b>
        <span>{{ item.label }}</span>
      </article>
    </section>

    <section class="section">
      <p class="eyebrow">WHY DIAGNOSIS</p>
      <h2>先诊断，再谈优化</h2>
      <p class="section-sub">不知道品牌在 AI 里有没有被推荐，优化就没有起点。</p>
      <div class="reason-grid">
        <article v-for="item in reasons" :key="item.title" class="reason-card">
          <strong>{{ item.value }}</strong>
          <h3>{{ item.title }}</h3>
          <p>{{ item.desc }}</p>
        </article>
      </div>
    </section>

    <section class="section soft">
      <p class="eyebrow">HOW IT WORKS</p>
      <h2>3 步完成体验诊断</h2>
      <p class="section-sub">{{ scheduleSummary || '支付后自动抓取，结果可追溯' }}</p>
      <div class="step-list">
        <article v-for="step in steps" :key="step.no" class="step-card">
          <span>{{ step.no }}</span>
          <div>
            <h3>{{ step.title }}</h3>
            <p>{{ step.desc }}</p>
          </div>
        </article>
      </div>
    </section>

    <section class="bottom-cta">
      <h2>准备好让品牌被 AI 看见了吗？</h2>
      <p>体验价 {{ priceText }}，真实抓取 · 输出可见度诊断结论</p>
      <button type="button" class="btn-primary wide" :disabled="loading || !config?.enabled" @click="goApply">
        {{ config?.enabled ? '立即开始诊断' : '活动暂未开放' }}
      </button>
    </section>

    <footer class="cta-bar">
      <div class="cta-inner">
        <div class="cta-price">
          <em>体验价</em>
          <strong>{{ priceText }}</strong>
        </div>
        <button type="button" class="btn-primary" :disabled="loading || !config?.enabled" @click="goApply">
          {{ config?.enabled ? '立即诊断' : '暂未开放' }}
        </button>
      </div>
    </footer>
  </div>
</template>

<style scoped>
.landing {
  position: relative;
  min-height: 100vh;
  padding: 0 0 calc(92px + env(safe-area-inset-bottom));
  overflow-x: hidden;
  color: #0f172a;
  background: #ffffff;
  font-family: system-ui, -apple-system, 'PingFang SC', 'Segoe UI', sans-serif;
}

.orb {
  position: absolute;
  width: 260px;
  height: 260px;
  border-radius: 999px;
  filter: blur(70px);
  pointer-events: none;
}
.orb-a {
  top: -80px;
  right: -60px;
  background: rgba(37, 99, 235, 0.16);
}
.orb-b {
  top: 220px;
  left: -100px;
  background: rgba(59, 130, 246, 0.10);
}

.topbar {
  position: relative;
  z-index: 1;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 18px 0;
}
.logo {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}
.logo-mark {
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  border-radius: 8px;
  background: #2563eb;
  color: #fff;
  font-size: 13px;
  font-weight: 800;
}
.logo-text {
  font-size: 15px;
  font-weight: 700;
  color: #0f172a;
}
.top-link {
  font-size: 13px;
  color: #64748b;
}

.hero {
  position: relative;
  z-index: 1;
  padding: 22px 18px 8px;
  text-align: center;
}
.badge {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  margin: 0 0 14px;
  padding: 6px 12px;
  border-radius: 999px;
  background: #eff6ff;
  color: #2563eb;
  font-size: 12px;
  font-weight: 600;
}
.badge i {
  width: 7px;
  height: 7px;
  border-radius: 999px;
  background: #2563eb;
  box-shadow: 0 0 0 4px rgba(37, 99, 235, 0.16);
}
.hero h1 {
  margin: 0 0 12px;
  font-size: 32px;
  line-height: 1.25;
  font-weight: 800;
  letter-spacing: -0.02em;
  color: #0f172a;
}
.hero h1 span {
  color: #2563eb;
}
.sub {
  margin: 0 auto;
  max-width: 34em;
  font-size: 14px;
  line-height: 1.7;
  color: #64748b;
}

.hero-actions {
  display: flex;
  justify-content: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-top: 18px;
}
.btn-primary {
  border: none;
  border-radius: 12px;
  padding: 12px 18px;
  font-size: 15px;
  font-weight: 700;
  color: #fff;
  background: #2563eb;
  box-shadow: 0 10px 24px rgba(37, 99, 235, 0.28);
}
.btn-primary:disabled,
.btn-secondary:disabled {
  opacity: 0.55;
  box-shadow: none;
}
.btn-primary.wide {
  width: 100%;
  max-width: 280px;
}
.btn-secondary {
  border: 1px solid #dbe3ef;
  border-radius: 12px;
  padding: 12px 18px;
  font-size: 15px;
  font-weight: 600;
  color: #0f172a;
  background: #fff;
}

.platform-block {
  margin-top: 22px;
}
.platform-block > p {
  margin: 0 0 10px;
  font-size: 12px;
  color: #94a3b8;
}
.platform-row {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 8px;
}
.platform-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 12px 7px 8px;
  border-radius: 999px;
  border: 1px solid #e2e8f0;
  background: #fff;
  color: #334155;
  font-size: 12px;
  font-weight: 600;
}
.platform-pill img {
  width: 18px;
  height: 18px;
  object-fit: contain;
}

.stats {
  position: relative;
  z-index: 1;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  padding: 18px 18px 4px;
}
.stat-card {
  padding: 16px 12px;
  border-radius: 16px;
  background: #fff;
  border: 1px solid #eef2f7;
  box-shadow: 0 8px 24px rgba(15, 23, 42, 0.04);
  text-align: center;
}
.stat-card b {
  display: block;
  margin-bottom: 4px;
  font-size: 26px;
  line-height: 1.1;
  color: #2563eb;
}
.stat-card span {
  font-size: 12px;
  color: #64748b;
}

.section {
  position: relative;
  z-index: 1;
  padding: 28px 18px 8px;
  text-align: center;
}
.section.soft {
  margin: 18px 14px 0;
  padding: 22px 14px 16px;
  border-radius: 20px;
  background: #f8fbff;
  border: 1px solid #eaf0f8;
}
.eyebrow {
  margin: 0 0 8px;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.08em;
  color: #2563eb;
}
.section h2 {
  margin: 0 0 8px;
  font-size: 24px;
  line-height: 1.3;
  color: #0f172a;
}
.section-sub {
  margin: 0 auto 16px;
  max-width: 28em;
  font-size: 13px;
  line-height: 1.6;
  color: #64748b;
}

.reason-grid {
  display: grid;
  gap: 10px;
  text-align: left;
}
.reason-card {
  padding: 16px;
  border-radius: 16px;
  background: #fff;
  border: 1px solid #eef2f7;
  box-shadow: 0 8px 20px rgba(15, 23, 42, 0.04);
}
.reason-card strong {
  display: inline-block;
  margin-bottom: 8px;
  font-size: 20px;
  color: #2563eb;
}
.reason-card h3 {
  margin: 0 0 6px;
  font-size: 16px;
  color: #0f172a;
}
.reason-card p {
  margin: 0;
  font-size: 13px;
  line-height: 1.6;
  color: #64748b;
}

.step-list {
  display: grid;
  gap: 10px;
  text-align: left;
}
.step-card {
  display: grid;
  grid-template-columns: 44px 1fr;
  gap: 12px;
  padding: 14px;
  border-radius: 16px;
  background: #fff;
  border: 1px solid #e8eef7;
}
.step-card > span {
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  border-radius: 14px;
  background: #eff6ff;
  color: #2563eb;
  font-size: 13px;
  font-weight: 800;
}
.step-card h3 {
  margin: 0 0 4px;
  font-size: 15px;
  color: #0f172a;
}
.step-card p {
  margin: 0;
  font-size: 13px;
  line-height: 1.55;
  color: #64748b;
}

.bottom-cta {
  margin: 22px 14px 10px;
  padding: 24px 16px;
  border-radius: 20px;
  background: linear-gradient(180deg, #eff6ff 0%, #f8fbff 100%);
  border: 1px solid #dbeafe;
  text-align: center;
}
.bottom-cta h2 {
  margin: 0 0 8px;
  font-size: 22px;
  line-height: 1.35;
  color: #0f172a;
}
.bottom-cta p {
  margin: 0 0 16px;
  font-size: 13px;
  color: #64748b;
}

.cta-bar {
  position: fixed;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: 10;
  padding: 10px 16px calc(10px + env(safe-area-inset-bottom));
  background: rgba(255, 255, 255, 0.96);
  backdrop-filter: blur(12px);
  border-top: 1px solid #e8eef7;
  box-shadow: 0 -8px 24px rgba(15, 23, 42, 0.05);
}
.cta-inner {
  display: grid;
  grid-template-columns: auto 1fr;
  align-items: center;
  gap: 12px;
  max-width: 640px;
  margin: 0 auto;
}
.cta-price {
  display: grid;
  gap: 2px;
  min-width: 72px;
}
.cta-price em {
  font-style: normal;
  font-size: 11px;
  color: #64748b;
}
.cta-price strong {
  font-size: 24px;
  line-height: 1;
  color: #2563eb;
}
</style>
