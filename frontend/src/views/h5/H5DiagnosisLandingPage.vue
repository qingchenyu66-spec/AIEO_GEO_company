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

const priceText = computed(() => `¥${config.value?.price_yuan ?? '9.9'}`)

const heroStats = [
  { value: '数亿+', label: '用户每天问 AI' },
  { value: '高意向', label: '提问即决策场景' },
  { value: '更信任', label: 'AI 推荐转化更高' },
  { value: '可量化', label: '可见度可追踪' },
]

const benefits = [
  {
    value: '精准获客',
    title: '出现在高意向提问里',
    desc: '用户在豆包、DeepSeek 里问「哪家好」「怎么选」时，若答案推荐你，拿到的是带着明确需求的客户。',
  },
  {
    value: '降低成本',
    title: '少花冤枉广告费',
    desc: 'AI 按语义匹配需求，品牌一旦进入推荐答案，可持续曝光，不必完全依赖竞价点击。',
  },
  {
    value: '提升转化',
    title: '推荐位比硬广更可信',
    desc: '用户对 AI 给出的品牌建议信任度更高，咨询与成交意愿往往强于传统广告触达。',
  },
]

const outcomes = [
  {
    tag: '品牌建设',
    title: '让 AI「认识」你的品牌',
    desc: '结构化呈现产品优势、场景与口碑，减少答非所问或被竞品抢走推荐位。',
  },
  {
    tag: '获客转化',
    title: '占住关键决策问法',
    desc: '围绕行业高转化提问布局内容与信源，提高被引用、被推荐的概率。',
  },
  {
    tag: '口碑与信任',
    title: '正面信息更容易被引用',
    desc: '权威信源与清晰事实表，有助于 AI 在回答中给出更稳妥的品牌表述。',
  },
  {
    tag: '效果复盘',
    title: '推荐变化看得见',
    desc: '持续监测收录与推荐表现，知道哪些问法上榜、哪些还是空白。',
  },
]

const steps = computed(() => [
  {
    no: '01',
    title: '先做一次可见度体检',
    desc: `体验价 ${priceText.value}，真实抓取主流 AI，看品牌有没有被提到。`,
  },
  {
    no: '02',
    title: '看清优势与空白',
    desc: '知道哪些问法已有露出，哪些关键场景还没进推荐答案。',
  },
  {
    no: '03',
    title: '再谈优化与增长',
    desc: '顾问按微信号跟进，给出可执行的 GEO 优化方向。',
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
      <button type="button" class="top-cta" :disabled="loading || !config?.enabled" @click="goApply">
        免费体检入口
      </button>
    </header>

    <section class="hero">
      <p class="badge">
        <i />
        AI 驱动的品牌增长 · GEO
      </p>
      <h1>
        让品牌在 AI 搜索时代
        <span>占据推荐位</span>
      </h1>
      <p class="sub">
        每天有大量用户通过豆包、DeepSeek 等 AI 平台做决策。
        谁被推荐，谁就更容易成为「标准答案」。
      </p>

      <div class="hero-actions">
        <button type="button" class="btn-primary" :disabled="loading || !config?.enabled" @click="goApply">
          {{ config?.enabled ? `体验价 ${priceText} 看清可见度` : '活动暂未开放' }}
        </button>
        <button type="button" class="btn-secondary" :disabled="loading || !config?.enabled" @click="goApply">
          预约顾问解读
        </button>
      </div>

      <div class="platform-block">
        <p>已覆盖主流 AI 平台</p>
        <div class="platform-row">
          <span v-for="item in platformItems" :key="item.code" class="platform-pill">
            <img v-if="item.icon" :src="item.icon" :alt="item.name" loading="lazy">
            {{ item.name }}
          </span>
          <template v-if="!platformItems.length">
            <span class="platform-pill">豆包</span>
            <span class="platform-pill">DeepSeek</span>
          </template>
        </div>
      </div>
    </section>

    <section class="stats">
      <article v-for="item in heroStats" :key="item.label" class="stat-card">
        <b>{{ item.value }}</b>
        <span>{{ item.label }}</span>
      </article>
    </section>

    <section class="section">
      <p class="eyebrow">WHY GEO</p>
      <h2>AI 正在改写获客逻辑</h2>
      <p class="section-sub">从「搜索点击」到「AI 推荐」，品牌曝光与转化路径正在被重写。</p>
      <div class="reason-grid">
        <article v-for="item in benefits" :key="item.title" class="reason-card">
          <strong>{{ item.value }}</strong>
          <h3>{{ item.title }}</h3>
          <p>{{ item.desc }}</p>
        </article>
      </div>
    </section>

    <section class="section soft">
      <p class="eyebrow">BRAND VALUE</p>
      <h2>对品牌意味着什么</h2>
      <p class="section-sub">不是多发几篇文章，而是让 AI 在关键场景里愿意提到你、推荐你。</p>
      <div class="outcome-grid">
        <article v-for="item in outcomes" :key="item.title" class="outcome-card">
          <span>{{ item.tag }}</span>
          <h3>{{ item.title }}</h3>
          <p>{{ item.desc }}</p>
        </article>
      </div>
    </section>

    <section class="section">
      <p class="eyebrow">START HERE</p>
      <h2>先看清，再增长</h2>
      <p class="section-sub">很多企业还不知道自己在 AI 答案里的真实位置。先做可见度体检，再定优化路径。</p>
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
      <p>体验价 {{ priceText }} 做一次真实抓取诊断，顾问按微信号解读结果与优化方向。</p>
      <button type="button" class="btn-primary wide" :disabled="loading || !config?.enabled" @click="goApply">
        {{ config?.enabled ? '立即开始品牌可见度体检' : '活动暂未开放' }}
      </button>
    </section>

    <footer class="cta-bar">
      <div class="cta-inner">
        <div class="cta-price">
          <em>体验价</em>
          <strong>{{ priceText }}</strong>
        </div>
        <button type="button" class="btn-primary" :disabled="loading || !config?.enabled" @click="goApply">
          {{ config?.enabled ? '看清推荐位' : '暂未开放' }}
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
  top: 260px;
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
}
.top-cta {
  border: none;
  background: transparent;
  color: #2563eb;
  font-size: 13px;
  font-weight: 600;
  padding: 0;
}
.top-cta:disabled {
  opacity: 0.5;
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
.btn-secondary {
  border: 1px solid #dbe3ef;
  border-radius: 12px;
  padding: 12px 18px;
  font-size: 15px;
  font-weight: 600;
  color: #0f172a;
  background: #fff;
}
.btn-primary:disabled,
.btn-secondary:disabled {
  opacity: 0.55;
  box-shadow: none;
}
.btn-primary.wide {
  width: 100%;
  max-width: 300px;
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
  font-size: 24px;
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
}
.section-sub {
  margin: 0 auto 16px;
  max-width: 30em;
  font-size: 13px;
  line-height: 1.6;
  color: #64748b;
}

.reason-grid,
.outcome-grid,
.step-list {
  display: grid;
  gap: 10px;
  text-align: left;
}
.reason-card,
.outcome-card,
.step-card {
  padding: 16px;
  border-radius: 16px;
  background: #fff;
  border: 1px solid #eef2f7;
  box-shadow: 0 8px 20px rgba(15, 23, 42, 0.04);
}
.reason-card strong {
  display: inline-block;
  margin-bottom: 8px;
  font-size: 18px;
  color: #2563eb;
}
.reason-card h3,
.outcome-card h3,
.step-card h3 {
  margin: 0 0 6px;
  font-size: 16px;
}
.reason-card p,
.outcome-card p,
.step-card p {
  margin: 0;
  font-size: 13px;
  line-height: 1.6;
  color: #64748b;
}
.outcome-card span {
  display: inline-block;
  margin-bottom: 8px;
  padding: 3px 8px;
  border-radius: 999px;
  background: #eff6ff;
  color: #2563eb;
  font-size: 11px;
  font-weight: 700;
}

.step-card {
  display: grid;
  grid-template-columns: 44px 1fr;
  gap: 12px;
  align-items: start;
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
