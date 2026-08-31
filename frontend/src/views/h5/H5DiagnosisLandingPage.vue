<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { fetchH5DiagnosisConfig, type H5DiagnosisConfig } from '../../services/h5Diagnosis'
import { platformLabelMap } from '../portal/portalMaps'

const router = useRouter()
const loading = ref(true)
const config = ref<H5DiagnosisConfig | null>(null)

const platformLabels = computed(() => {
  const codes = config.value?.platforms || []
  return codes.map(code => platformLabelMap[code] || code)
})

const scheduleSummary = computed(() => {
  const cfg = config.value
  if (!cfg) return ''
  return `${cfg.schedule_days} 天 · 每天 3 档 · 共 ${cfg.schedule_total} 次监测`
})

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
    <header class="hero">
      <p class="eyebrow">艾迪亚 GEO · AI 可见度诊断</p>
      <h1>品牌在 AI 搜索里<br>有没有被推荐？</h1>
      <p class="sub">
        覆盖豆包、DeepSeek 等主流平台，自动抓取真实问答结果，输出可见度诊断报告。
      </p>
      <div v-if="config" class="price-tag">
        体验价 <strong>¥{{ config.price_yuan }}</strong>
        <span>{{ scheduleSummary }}</span>
      </div>
    </header>

    <section class="stats">
      <article>
        <b>{{ config?.platforms?.length || '—' }}</b>
        <span>监测平台</span>
      </article>
      <article>
        <b>{{ config?.schedule_total || '—' }}</b>
        <span>自动抓取</span>
      </article>
      <article>
        <b>3–5</b>
        <span>检测问法</span>
      </article>
      <article>
        <b>报告</b>
        <span>可见度结论</span>
      </article>
    </section>

    <section class="steps">
      <h2>3 步完成体验诊断</h2>
      <article>
        <i>01</i>
        <div>
          <h3>填写品牌与问法</h3>
          <p>支持一键推荐行业问法，也可自定义 3–5 条检测问题。</p>
        </div>
      </article>
      <article>
        <i>02</i>
        <div>
          <h3>支付后自动开跑</h3>
          <p>付 {{ config?.price_yuan ?? '9.9' }} 元后系统自动提交监测，无需人工干预。</p>
        </div>
      </article>
      <article>
        <i>03</i>
        <div>
          <h3>查看诊断结果</h3>
          <p>抓取完成后生成售前诊断报告，销售可按微信号跟进。</p>
        </div>
      </article>
    </section>

    <section v-if="platformLabels.length" class="platforms">
      <h2>本次体验覆盖平台</h2>
      <div class="platform-tags">
        <span v-for="label in platformLabels" :key="label">{{ label }}</span>
      </div>
    </section>

    <footer class="cta-bar">
      <button type="button" class="cta" :disabled="loading || !config?.enabled" @click="goApply">
        {{ config?.enabled ? `¥${config.price_yuan} 立即诊断` : '活动暂未开放' }}
      </button>
    </footer>
  </div>
</template>

<style scoped>
.landing {
  min-height: 100vh;
  padding: 0 0 88px;
  color: #e2e8f0;
  background: linear-gradient(180deg, #0b1220 0%, #111827 42%, #0f172a 100%);
  font-family: system-ui, -apple-system, 'Segoe UI', sans-serif;
}
.hero {
  padding: 28px 20px 24px;
  background: radial-gradient(circle at 20% 0%, rgba(14, 165, 233, 0.22), transparent 55%);
}
.eyebrow { margin: 0 0 10px; font-size: 13px; color: #94a3b8; letter-spacing: 0.04em; }
h1 { margin: 0 0 12px; font-size: 28px; line-height: 1.25; color: #fff; }
.sub { margin: 0; font-size: 14px; line-height: 1.6; color: #cbd5e1; }
.price-tag {
  display: inline-grid;
  gap: 4px;
  margin-top: 18px;
  padding: 12px 14px;
  border-radius: 12px;
  background: rgba(15, 118, 110, 0.22);
  border: 1px solid rgba(45, 212, 191, 0.35);
  font-size: 14px;
}
.price-tag strong { font-size: 24px; color: #5eead4; }
.price-tag span { color: #94a3b8; font-size: 12px; }
.stats {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 8px;
  padding: 0 16px 20px;
}
.stats article {
  padding: 12px 8px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(148, 163, 184, 0.14);
  text-align: center;
}
.stats b { display: block; font-size: 18px; color: #f8fafc; }
.stats span { font-size: 11px; color: #94a3b8; }
.steps, .platforms {
  margin: 0 16px 18px;
  padding: 16px;
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(148, 163, 184, 0.12);
}
.steps h2, .platforms h2 { margin: 0 0 14px; font-size: 16px; color: #f8fafc; }
.steps article {
  display: grid;
  grid-template-columns: 36px 1fr;
  gap: 10px;
  padding: 10px 0;
  border-top: 1px solid rgba(148, 163, 184, 0.12);
}
.steps article:first-of-type { border-top: none; padding-top: 0; }
.steps i {
  font-style: normal;
  font-weight: 700;
  color: #38bdf8;
}
.steps h3 { margin: 0 0 4px; font-size: 14px; color: #f1f5f9; }
.steps p { margin: 0; font-size: 12px; line-height: 1.5; color: #94a3b8; }
.platform-tags { display: flex; flex-wrap: wrap; gap: 8px; }
.platform-tags span {
  padding: 6px 10px;
  border-radius: 999px;
  background: rgba(56, 189, 248, 0.12);
  color: #bae6fd;
  font-size: 12px;
}
.cta-bar {
  position: fixed;
  left: 0;
  right: 0;
  bottom: 0;
  padding: 12px 16px calc(12px + env(safe-area-inset-bottom));
  background: rgba(15, 23, 42, 0.92);
  backdrop-filter: blur(8px);
  border-top: 1px solid rgba(148, 163, 184, 0.18);
}
.cta {
  width: 100%;
  border: none;
  border-radius: 14px;
  padding: 14px;
  font-size: 17px;
  font-weight: 700;
  color: #fff;
  background: linear-gradient(135deg, #0f766e, #0284c7);
}
.cta:disabled { opacity: 0.55; }
</style>
