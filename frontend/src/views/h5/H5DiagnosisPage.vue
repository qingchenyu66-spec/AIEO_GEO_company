<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  PROMPT_TEMPLATES,
  buildNonbrandPromptSet,
  nonbrandTopicLabel,
} from '../portal/composables/useLeadDiagnosis'
import {
  createH5DiagnosisOrder,
  fetchH5DiagnosisConfig,
  fetchH5DiagnosisSession,
  fetchH5OrderStatus,
  invokeWechatPay,
  markH5OrderDevPaid,
  startH5OAuth,
  type H5DiagnosisConfig,
} from '../../services/h5Diagnosis'

const loading = ref(true)
const submitting = ref(false)
const errorText = ref('')
const successText = ref('')
const config = ref<H5DiagnosisConfig | null>(null)
const sessionReady = ref(false)

const form = ref({
  brand_name: '',
  industry: '',
  product_focus: '',
  website_url: '',
  wechat_id: '',
  contact_phone: '',
  prompts: ['', '', '', '', ''],
})

const filledPromptCount = computed(() => form.value.prompts.map(v => v.trim()).filter(Boolean).length)

const topicLabel = computed(() => nonbrandTopicLabel(form.value.industry, form.value.product_focus))

function applyTemplate(value: string) {
  const emptyIndex = form.value.prompts.findIndex(item => !item.trim())
  if (emptyIndex < 0) return
  form.value.prompts[emptyIndex] = value.replace(/^例如[：:]\s*/, '').replace(/XXX/g, form.value.brand_name.trim() || '品牌')
}

function applyRecommendedSet() {
  const [a, b, c] = buildNonbrandPromptSet(topicLabel.value)
  form.value.prompts = [a, b, c, '', '']
}

function applyBrandDefenseSet() {
  const brand = form.value.brand_name.trim() || '品牌'
  form.value.prompts = [`${brand}公司介绍`, `${brand}公司怎么样`, '', '', '']
}

async function bootstrap() {
  loading.value = true
  errorText.value = ''
  try {
    config.value = await fetchH5DiagnosisConfig()
    const session = await fetchH5DiagnosisSession()
    sessionReady.value = session.ready
    if (!session.ready && config.value.oauth_required) {
      startH5OAuth()
      return
    }
  } catch (error: unknown) {
    errorText.value = error instanceof Error ? error.message : '加载失败'
  } finally {
    loading.value = false
  }
}

async function submitOrder() {
  if (!config.value?.enabled) {
    errorText.value = '活动暂未开放'
    return
  }
  submitting.value = true
  errorText.value = ''
  successText.value = ''
  try {
    const prompts = form.value.prompts.map(v => v.trim()).filter(Boolean)
    const result = await createH5DiagnosisOrder({
      wechat_id: form.value.wechat_id.trim(),
      contact_phone: form.value.contact_phone.trim(),
      brand_name: form.value.brand_name.trim(),
      prompts,
      industry: form.value.industry.trim(),
      product_focus: form.value.product_focus.trim(),
      website_url: form.value.website_url.trim(),
    })
    if (result.pay_params.devAutoPaid) {
      await markH5OrderDevPaid(result.out_trade_no)
      const status = await fetchH5OrderStatus(result.out_trade_no)
      successText.value = `支付成功，诊断已提交（单号 ${status.lead_diagnosis_id || '处理中'}）`
      return
    }
    await invokeWechatPay(result.pay_params)
    const status = await fetchH5OrderStatus(result.out_trade_no)
    if (status.status === 'paid') {
      successText.value = `支付成功，诊断已提交（单号 ${status.lead_diagnosis_id || '处理中'}）`
    } else {
      successText.value = '支付处理中，请稍后在微信通知中查看或联系顾问'
    }
  } catch (error: unknown) {
    errorText.value = error instanceof Error ? error.message : '提交失败'
  } finally {
    submitting.value = false
  }
}

onMounted(bootstrap)
</script>

<template>
  <div class="h5-page">
    <header class="hero">
      <p class="eyebrow">艾迪亚 GEO</p>
      <h1>9.9 元 AI 可见度诊断</h1>
      <p v-if="config" class="price">¥{{ config.price_yuan }} · {{ config.schedule_days }} 天监测</p>
    </header>

    <p v-if="loading" class="hint">加载中…</p>
    <p v-else-if="errorText" class="error">{{ errorText }}</p>
    <p v-else-if="successText" class="success">{{ successText }}</p>

    <form v-if="!loading && !successText && config?.enabled" class="form" @submit.prevent="submitOrder">
      <label>
        品牌名称
        <input v-model="form.brand_name" required maxlength="100" placeholder="公司或品牌全称" />
      </label>
      <label>
        行业
        <input v-model="form.industry" maxlength="200" placeholder="如：蛋白粉、电梯广告" />
      </label>
      <label>
        产品焦点
        <input v-model="form.product_focus" maxlength="200" placeholder="可选" />
      </label>
      <label>
        官网
        <input v-model="form.website_url" maxlength="500" placeholder="https://" />
      </label>
      <label>
        微信号
        <input v-model="form.wechat_id" required maxlength="64" placeholder="方便顾问联系您" />
      </label>
      <label>
        手机号
        <input v-model="form.contact_phone" required maxlength="11" inputmode="numeric" placeholder="11 位手机号" />
      </label>

      <div class="prompt-block">
        <div class="prompt-head">
          <strong>检测问题（{{ filledPromptCount }}/5）</strong>
          <button type="button" class="link" @click="applyRecommendedSet">一键推荐</button>
          <button type="button" class="link" @click="applyBrandDefenseSet">品牌问法</button>
        </div>
        <div class="chips">
          <button
            v-for="item in PROMPT_TEMPLATES"
            :key="item.label"
            type="button"
            class="chip"
            @click="applyTemplate(item.value)"
          >
            {{ item.label }}
          </button>
        </div>
        <label v-for="(_, index) in form.prompts" :key="index">
          问题 {{ index + 1 }}
          <input v-model="form.prompts[index]" maxlength="200" :placeholder="index === 0 ? '至少填 1 条' : '可选'" />
        </label>
      </div>

      <p v-if="config.platforms.length" class="platforms">监测平台：{{ config.platforms.join('、') }}</p>

      <button class="submit" type="submit" :disabled="submitting || !sessionReady">
        {{ submitting ? '提交中…' : `支付 ¥${config.price_yuan}` }}
      </button>
    </form>
  </div>
</template>

<style scoped>
.h5-page {
  max-width: 640px;
  margin: 0 auto;
  padding: 20px 16px 48px;
  font-family: system-ui, -apple-system, 'Segoe UI', sans-serif;
  color: #1f2937;
  background: #f8fafc;
  min-height: 100vh;
}
.hero { margin-bottom: 20px; }
.eyebrow { color: #64748b; font-size: 13px; margin: 0 0 4px; }
h1 { margin: 0 0 8px; font-size: 24px; }
.price { margin: 0; color: #0f766e; font-weight: 600; }
.form { display: grid; gap: 12px; }
label { display: grid; gap: 6px; font-size: 14px; }
input {
  border: 1px solid #cbd5e1;
  border-radius: 10px;
  padding: 10px 12px;
  font-size: 16px;
  background: #fff;
}
.prompt-block { display: grid; gap: 8px; padding: 12px; background: #fff; border-radius: 12px; border: 1px solid #e2e8f0; }
.prompt-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.chips { display: flex; flex-wrap: wrap; gap: 8px; }
.chip, .link {
  border: 1px solid #cbd5e1;
  background: #fff;
  border-radius: 999px;
  padding: 6px 10px;
  font-size: 12px;
}
.link { border: none; color: #0f766e; background: transparent; padding: 0; }
.platforms { font-size: 13px; color: #64748b; }
.submit {
  margin-top: 8px;
  border: none;
  border-radius: 12px;
  padding: 14px;
  font-size: 17px;
  font-weight: 600;
  color: #fff;
  background: linear-gradient(135deg, #0f766e, #0891b2);
}
.submit:disabled { opacity: 0.6; }
.hint, .error, .success { padding: 12px; border-radius: 10px; }
.error { background: #fef2f2; color: #b91c1c; }
.success { background: #ecfdf5; color: #047857; }
</style>
