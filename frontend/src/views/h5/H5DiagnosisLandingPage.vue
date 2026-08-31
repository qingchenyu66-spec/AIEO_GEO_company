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
  return `${cfg.schedule_days} 天监测 · 每天 3 档 · 共 ${cfg.schedule_total} 次抓取`
})

const statCards = computed(() => [
  { value: String(config.value?.platforms?.length || '—'), label: 'AI 平台', tone: 'blue' },
  { value: String(config.value?.schedule_total || '—'), label: '自动抓取', tone: 'teal' },
  { value: '3–5', label: '检测问法', tone: 'violet' },
  { value: '报告', label: '可见度结论', tone: 'amber' },
])

const steps = computed(() => [
  {
    no: '01',
    title: '填写品牌与问法',
    desc: '支持一键推荐行业问法，也可自定义 3–5 条真实检测问题。',
  },
  {
    no: '02',
    title: '支付后自动开跑',
    desc: `支付 ¥${config.value?.price_yuan ?? '9.9'} 后系统自动提交监测，无需人工干预。`,
  },
  {
    no: '03',
    title: '获取诊断结论',
    desc: '抓取完成后生成售前诊断报告，顾问可按微信号跟进。',
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
    <div class="bg-glow bg-glow-a" aria-hidden="true" />
    <div class="bg-glow bg-glow-b" aria-hidden="true" />

    <header class="topbar">
      <span class="brand-mark">艾迪亚 GEO</span>
      <span class="brand-tag">AI 可见度诊断</span>
    </header>

    <section class="hero">
      <p class="hero-en">Engineering Brand Visibility in AI Search</p>
      <h1>
        品牌在豆包、DeepSeek 等
        <em>AI 搜索里有没有被推荐？</em>
      </h1>
      <p class="hero-sub">
        自动抓取真实问答结果，输出可见度诊断报告。体验价低至
        <strong>¥{{ config?.price_yuan ?? '9.9' }}</strong>
      </p>

      <div v-if="platformItems.length" class="platform-row">
        <article v-for="item in platformItems" :key="item.code" class="platform-chip">
          <img v-if="item.icon" :src="item.icon" :alt="item.name" loading="lazy">
          <span>{{ item.name }}</span>
        </article>
      </div>
    </section>

    <section class="stats">
      <article
        v-for="card in statCards"
        :key="card.label"
        class="stat-card"
        :class="`tone-${card.tone}`"
      >
        <b>{{ card.value }}</b>
        <span>{{ card.label }}</span>
      </article>
    </section>

    <section class="quote-card">
      <p class="quote-q">「不知道品牌在 AI 里有没有被推荐？」</p>
      <p class="quote-a">AI 可见度诊断是 GEO 优化的第一步：扫描收录与推荐现状，给出可执行的优化方向。</p>
    </section>

    <section class="steps">
      <div class="section-head">
        <h2>3 步完成体验诊断</h2>
        <p>{{ scheduleSummary }}</p>
      </div>
      <article v-for="step in steps" :key="step.no" class="step-card">
        <span class="step-no">{{ step.no }}</span>
        <div>
          <h3>{{ step.title }}</h3>
          <p>{{ step.desc }}</p>
        </div>
      </article>
    </section>

    <section class="trust">
      <p>覆盖主流 AI 问答场景 · 真实抓取 · 结果可追溯</p>
    </section>

    <footer class="cta-bar">
      <div class="cta-inner">
        <div class="cta-price">
          <span class="cta-label">体验价</span>
          <strong>¥{{ config?.price_yuan ?? '9.9' }}</strong>
        </div>
        <button type="button" class="cta" :disabled="loading || !config?.enabled" @click="goApply">
          {{ config?.enabled ? '立即开始诊断' : '活动暂未开放' }}
        </button>
      </div>
    </footer>
  </div>
</template>

<style scoped>
.landing {
  position: relative;
  min-height: 100vh;
  padding: 0 0 calc(96px + env(safe-area-inset-bottom));
  overflow-x: hidden;
  color: #0f172a;
  background: linear-gradient(180deg, #f8fbff 0%, #ffffff 38%, #f1f5f9 100%);
  font-family: system-ui, -apple-system, 'PingFang SC', 'Segoe UI', sans-serif;
}

.bg-glow {
  position: absolute;
  border-radius: 999px;
  filter: blur(48px);
  pointer-events: none;
}
.bg-glow-a {
  top: -40px;
  right: -30px;
  width: 220px;
  height: 220px;
  background: rgba(59, 130, 246, 0.18);
}
.bg-glow-b {
  top: 180px;
  left: -60px;
  width: 200px;
  height: 200px;
  background: rgba(20, 184, 166, 0.14);
}

.topbar {
  position: relative;
  z-index: 1;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 18px 0;
}
.brand-mark {
  font-size: 15px;
  font-weight: 700;
  letter-spacing: 0.02em;
  color: #0f172a;
}
.brand-tag {
  padding: 4px 10px;
  border-radius: 999px;
  background: rgba(37, 99, 235, 0.08);
  color: #1d4ed8;
  font-size: 11px;
  font-weight: 600;
}

.hero {
  position: relative;
  z-index: 1;
  padding: 18px 18px 8px;
}
.hero-en {
  margin: 0 0 10px;
  font-size: 11px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: #64748b;
}
.hero h1 {
  margin: 0 0 12px;
  font-size: 30px;
  line-height: 1.28;
  font-weight: 800;
  color: #0f172a;
}
.hero h1 em {
  display: block;
  margin-top: 6px;
  font-style: normal;
  background: linear-gradient(90deg, #2563eb, #0d9488);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}
.hero-sub {
  margin: 0;
  font-size: 15px;
  line-height: 1.65;
  color: #475569;
}
.hero-sub strong {
  color: #0f766e;
  font-size: 18px;
}

.platform-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 18px;
}
.platform-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 12px 7px 8px;
  border-radius: 999px;
  background: #fff;
  border: 1px solid #e2e8f0;
  box-shadow: 0 4px 14px rgba(15, 23, 42, 0.04);
  font-size: 12px;
  font-weight: 600;
  color: #334155;
}
.platform-chip img {
  width: 20px;
  height: 20px;
  object-fit: contain;
}

.stats {
  position: relative;
  z-index: 1;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  padding: 16px 18px 6px;
}
.stat-card {
  padding: 16px 14px;
  border-radius: 16px;
  background: #fff;
  border: 1px solid #e2e8f0;
  box-shadow: 0 8px 24px rgba(15, 23, 42, 0.05);
}
.stat-card b {
  display: block;
  margin-bottom: 4px;
  font-size: 24px;
  line-height: 1.1;
  color: #0f172a;
}
.stat-card span {
  font-size: 12px;
  color: #64748b;
}
.stat-card.tone-blue b { color: #2563eb; }
.stat-card.tone-teal b { color: #0d9488; }
.stat-card.tone-violet b { color: #7c3aed; }
.stat-card.tone-amber b { color: #d97706; }

.quote-card {
  margin: 10px 18px 0;
  padding: 16px 16px 14px;
  border-radius: 18px;
  background: linear-gradient(135deg, #eff6ff 0%, #ecfeff 100%);
  border: 1px solid rgba(37, 99, 235, 0.12);
}
.quote-q {
  margin: 0 0 8px;
  font-size: 16px;
  font-weight: 700;
  line-height: 1.5;
  color: #1e3a8a;
}
.quote-a {
  margin: 0;
  font-size: 13px;
  line-height: 1.65;
  color: #475569;
}

.steps {
  margin: 16px 18px 0;
  padding: 18px 16px;
  border-radius: 20px;
  background: #fff;
  border: 1px solid #e2e8f0;
  box-shadow: 0 10px 30px rgba(15, 23, 42, 0.06);
}
.section-head {
  margin-bottom: 14px;
}
.section-head h2 {
  margin: 0 0 4px;
  font-size: 18px;
  color: #0f172a;
}
.section-head p {
  margin: 0;
  font-size: 12px;
  color: #64748b;
}
.step-card {
  display: grid;
  grid-template-columns: 44px 1fr;
  gap: 12px;
  padding: 14px 0;
  border-top: 1px solid #f1f5f9;
}
.step-card:first-of-type {
  border-top: none;
  padding-top: 0;
}
.step-no {
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  border-radius: 14px;
  background: linear-gradient(135deg, #dbeafe, #ccfbf1);
  color: #1d4ed8;
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

.trust {
  padding: 18px 18px 8px;
  text-align: center;
}
.trust p {
  margin: 0;
  font-size: 12px;
  color: #94a3b8;
}

.cta-bar {
  position: fixed;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: 10;
  padding: 10px 16px calc(10px + env(safe-area-inset-bottom));
  background: rgba(255, 255, 255, 0.94);
  backdrop-filter: blur(12px);
  border-top: 1px solid #e2e8f0;
  box-shadow: 0 -8px 24px rgba(15, 23, 42, 0.06);
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
.cta-label {
  font-size: 11px;
  color: #64748b;
}
.cta-price strong {
  font-size: 24px;
  line-height: 1;
  color: #0f766e;
}
.cta {
  border: none;
  border-radius: 14px;
  padding: 14px 16px;
  font-size: 16px;
  font-weight: 700;
  color: #fff;
  background: linear-gradient(135deg, #2563eb 0%, #0d9488 100%);
  box-shadow: 0 10px 24px rgba(37, 99, 235, 0.28);
}
.cta:disabled {
  opacity: 0.55;
  box-shadow: none;
}
</style>
