<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
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

type PayEnv = 'wechat' | 'pc' | 'mobile_other'

const router = useRouter()
const loading = ref(true)
const submitting = ref(false)
const errorText = ref('')
const successText = ref('')
const config = ref<H5DiagnosisConfig | null>(null)
const sessionReady = ref(false)
const payEnv = ref<PayEnv>('pc')
const nativeCodeUrl = ref('')
const nativeOutTradeNo = ref('')
const polling = ref(false)
let pollTimer: number | null = null

const form = ref({
  brand_name: '',
  brand_aliases: '',
  industry: '',
  website_url: '',
  competitors: '',
  contact_phone: '',
  prompts: ['', '', '', '', ''],
})

const filledPromptCount = computed(() => form.value.prompts.map(v => v.trim()).filter(Boolean).length)
const topicLabel = computed(() => nonbrandTopicLabel(form.value.industry, ''))
const canSubmit = computed(() => {
  if (!config.value?.enabled || submitting.value) return false
  if (payEnv.value === 'wechat') return sessionReady.value
  if (payEnv.value === 'mobile_other') return false
  return true
})
const nativeQrSrc = computed(() => {
  if (!nativeCodeUrl.value) return ''
  // ponytail: 第三方出码服务；若不可用再换本地 qrcode 库
  return `https://api.qrserver.com/v1/create-qr-code/?size=220x220&margin=10&data=${encodeURIComponent(nativeCodeUrl.value)}`
})

function detectPayEnv(): PayEnv {
  const ua = navigator.userAgent || ''
  const isWechat = /MicroMessenger/i.test(ua)
  if (isWechat) {
    // 2026-08-31 - 电脑微信内置页调 JSAPI 常报 system:access_denied，改走 Native 扫码
    const isMobilePhone = /Android|iPhone|iPod|iPad|Mobile/i.test(ua)
    const isWechatDesktop = /WindowsWechat|MacWechat/i.test(ua) || (!isMobilePhone && /Windows NT|Macintosh/i.test(ua))
    if (isWechatDesktop) return 'pc'
    return 'wechat'
  }
  const isMobile = /Android|iPhone|iPod|iPad|Mobile/i.test(ua)
  return isMobile ? 'mobile_other' : 'pc'
}

function applyRecommendedSet() {
  // 2026-08-31 - 一键推荐一次写满 5 条：3 非品牌 + 2 品牌问法
  const [a, b, c] = buildNonbrandPromptSet(topicLabel.value)
  const brand = form.value.brand_name.trim() || '品牌'
  form.value.prompts = [a, b, c, `${brand}公司介绍`, `${brand}公司怎么样`]
}

function stopPolling() {
  if (pollTimer != null) {
    window.clearInterval(pollTimer)
    pollTimer = null
  }
  polling.value = false
}

async function pollNativePaid(outTradeNo: string) {
  if (pollTimer != null) {
    window.clearInterval(pollTimer)
    pollTimer = null
  }
  polling.value = true
  pollTimer = window.setInterval(async () => {
    try {
      const status = await fetchH5OrderStatus(outTradeNo)
      if (status.status === 'paid') {
        stopPolling()
        nativeCodeUrl.value = ''
        successText.value = `支付成功，诊断已提交（单号 ${status.lead_diagnosis_id || '处理中'}）`
      }
    } catch {
      /* 轮询失败忽略，继续等 */
    }
  }, 2500)
}

async function bootstrap() {
  loading.value = true
  errorText.value = ''
  payEnv.value = detectPayEnv()
  try {
    config.value = await fetchH5DiagnosisConfig()
    const session = await fetchH5DiagnosisSession()
    sessionReady.value = session.ready
    // 2026-08-31 - B3：仅微信内强制 OAuth；PC/手机浏览器可先看表单
    if (payEnv.value === 'wechat' && !session.ready && config.value.oauth_required) {
      startH5OAuth('apply')
      return
    }
  } catch (error: unknown) {
    errorText.value = error instanceof Error ? error.message : '加载失败'
  } finally {
    loading.value = false
  }
}

function validateForm(): string {
  if (!form.value.brand_name.trim()) return '请填写品牌名称'
  const phone = form.value.contact_phone.trim()
  if (!/^1\d{10}$/.test(phone)) return '请填写正确的手机号'
  const prompts = form.value.prompts.map(v => v.trim()).filter(Boolean)
  if (!prompts.length) return '请至少填写 1 条检测问题'
  return ''
}

async function submitOrder() {
  if (!config.value?.enabled) {
    errorText.value = '活动暂未开放'
    return
  }
  if (payEnv.value === 'mobile_other') {
    errorText.value = '请使用微信打开本页面完成支付'
    return
  }
  const formError = validateForm()
  if (formError) {
    errorText.value = formError
    return
  }
  submitting.value = true
  errorText.value = ''
  successText.value = ''
  try {
    const prompts = form.value.prompts.map(v => v.trim()).filter(Boolean)
    const tradeType = payEnv.value === 'pc' ? 'native' : 'jsapi'
    const result = await createH5DiagnosisOrder({
      contact_phone: form.value.contact_phone.trim(),
      brand_name: form.value.brand_name.trim(),
      prompts,
      brand_aliases: form.value.brand_aliases.trim(),
      industry: form.value.industry.trim(),
      website_url: form.value.website_url.trim(),
      competitors: form.value.competitors.trim(),
      pay_trade_type: tradeType,
      pay_channel: 'wechat',
    })

    if (tradeType === 'native') {
      if (result.dev_auto_paid || result.pay_params?.devAutoPaid) {
        await markH5OrderDevPaid(result.out_trade_no)
        const status = await fetchH5OrderStatus(result.out_trade_no)
        successText.value = `支付成功，诊断已提交（单号 ${status.lead_diagnosis_id || '处理中'}）`
        return
      }
      nativeOutTradeNo.value = result.out_trade_no
      nativeCodeUrl.value = String(result.code_url || '')
      if (!nativeCodeUrl.value) {
        throw new Error('未拿到支付二维码，请稍后重试')
      }
      await pollNativePaid(result.out_trade_no)
      return
    }

    if (result.pay_params?.devAutoPaid) {
      await markH5OrderDevPaid(result.out_trade_no)
      const status = await fetchH5OrderStatus(result.out_trade_no)
      successText.value = `支付成功，诊断已提交（单号 ${status.lead_diagnosis_id || '处理中'}）`
      return
    }
    if (!result.pay_params) {
      throw new Error('支付参数缺失')
    }
    await invokeWechatPay(result.pay_params)
    const status = await fetchH5OrderStatus(result.out_trade_no)
    if (status.status === 'paid') {
      successText.value = `支付成功，诊断已提交（单号 ${status.lead_diagnosis_id || '处理中'}）`
    } else {
      successText.value = '支付处理中，请稍后在微信通知中查看或联系顾问'
    }
  } catch (error: unknown) {
    const raw = error instanceof Error ? error.message : '提交失败'
    // 2026-08-31 - 电脑微信 JSAPI 失败文案难懂，改成人话并引导扫码
    if (/access_denied/i.test(raw)) {
      errorText.value = '当前环境不支持微信内直接付款，请用手机微信扫码，或在电脑浏览器打开本页'
    } else {
      errorText.value = raw
    }
  } finally {
    submitting.value = false
  }
}

onMounted(bootstrap)
onUnmounted(stopPolling)
</script>

<template>
  <div class="h5-page">
    <header class="hero">
      <button type="button" class="back" @click="router.push('/h5/diagnosis')">← 返回</button>
      <p class="eyebrow">填写诊断信息</p>
      <h1>{{ config?.price_yuan ?? '—' }} 元 AI 可见度诊断</h1>
    </header>

    <p v-if="payEnv === 'mobile_other' && !loading" class="warn">
      请使用微信打开本页面完成支付。可复制链接到微信，或扫描落地页二维码进入。
    </p>

    <p v-if="loading" class="hint">加载中…</p>
    <p v-else-if="errorText" class="error">{{ errorText }}</p>
    <p v-else-if="successText" class="success">{{ successText }}</p>

    <div v-if="nativeCodeUrl && !successText" class="native-pay">
      <p class="native-title">请使用微信扫码支付</p>
      <img class="native-qr" :src="nativeQrSrc" alt="微信支付二维码">
      <p class="native-hint">{{ polling ? '等待支付结果…' : '扫码后请勿关闭本页' }}</p>
      <p class="native-no">单号 {{ nativeOutTradeNo }}</p>
    </div>

    <!-- 2026-08-31 - H5 对齐 PC 品牌字段；不展示地区/平台/天数/销售备注 -->
    <form v-if="!loading && !successText && !nativeCodeUrl && config?.enabled" class="form" @submit.prevent="submitOrder">
      <label>
        品牌名称 *
        <input v-model="form.brand_name" required maxlength="100" placeholder="例如：客户品牌全称" />
      </label>
      <label>
        品牌别名 / 露出词（可选）
        <input v-model="form.brand_aliases" maxlength="500" placeholder="多个用逗号分隔，例如：品牌简称, 品牌别称" />
      </label>
      <label>
        官网 URL（强烈建议）
        <input v-model="form.website_url" maxlength="500" placeholder="https://www.example.com" />
      </label>
      <label>
        所属行业
        <input v-model="form.industry" maxlength="200" placeholder="例如：户外广告、蛋白粉、智能体平台" />
      </label>
      <label>
        主要竞品
        <input v-model="form.competitors" maxlength="500" placeholder="多个竞品用逗号分隔，例如：竞品A, 竞品B" />
      </label>
      <label>
        手机号 *
        <input v-model="form.contact_phone" required maxlength="11" inputmode="numeric" pattern="1[0-9]{10}" placeholder="请填写手机号码" />
      </label>

      <div class="prompt-block">
        <div class="prompt-head">
          <strong>检测问题（{{ filledPromptCount }}/5）</strong>
          <button type="button" class="link" @click="applyRecommendedSet">一键推荐</button>
        </div>
        <label v-for="(_, index) in form.prompts" :key="index">
          问题 {{ index + 1 }}
          <input v-model="form.prompts[index]" maxlength="200" :placeholder="index === 0 ? '至少填 1 条' : '可选'" />
        </label>
      </div>

      <button class="submit" type="submit" :disabled="!canSubmit">
        {{ submitting ? '提交中…' : (payEnv === 'pc' ? `扫码支付 ¥${config.price_yuan}` : `支付 ¥${config.price_yuan}`) }}
      </button>
    </form>
  </div>
</template>

<style scoped>
.h5-page {
  max-width: 720px;
  margin: 0 auto;
  padding: 20px 16px 48px;
  font-family: system-ui, -apple-system, 'Segoe UI', sans-serif;
  color: #1f2937;
  background: #f8fafc;
  min-height: 100vh;
}
.hero { margin-bottom: 20px; }
.back {
  border: none;
  background: transparent;
  color: #64748b;
  padding: 0 0 8px;
  font-size: 14px;
}
.eyebrow { color: #64748b; font-size: 13px; margin: 0 0 4px; }
h1 { margin: 0; font-size: 24px; }
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
.link {
  border: none;
  color: #0f766e;
  background: transparent;
  padding: 0;
  font-size: 12px;
}
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
.hint, .error, .success, .warn { padding: 12px; border-radius: 10px; }
.error { background: #fef2f2; color: #b91c1c; }
.success { background: #ecfdf5; color: #047857; }
.warn { background: #fff7ed; color: #c2410c; margin-bottom: 12px; }
.native-pay {
  margin: 12px 0 20px;
  padding: 20px 16px;
  border-radius: 16px;
  background: #fff;
  border: 1px solid #e2e8f0;
  text-align: center;
}
.native-title { margin: 0 0 12px; font-size: 16px; font-weight: 700; }
.native-qr {
  width: 220px;
  height: 220px;
  border-radius: 12px;
  background: #fff;
}
.native-hint { margin: 12px 0 4px; font-size: 13px; color: #64748b; }
.native-no { margin: 0; font-size: 12px; color: #94a3b8; }

@media (min-width: 768px) {
  .h5-page { padding: 32px 24px 64px; }
  h1 { font-size: 30px; }
  .form {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 14px 16px;
  }
  .prompt-block,
  .submit {
    grid-column: 1 / -1;
  }
}
</style>
