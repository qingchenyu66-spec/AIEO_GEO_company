<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
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
type PayChannel = 'wechat' | 'alipay'

const router = useRouter()
const route = useRoute()
const loading = ref(true)
const submitting = ref(false)
const errorText = ref('')
const successText = ref('')
const config = ref<H5DiagnosisConfig | null>(null)
const sessionReady = ref(false)
const payEnv = ref<PayEnv>('pc')
const payChannel = ref<PayChannel>('wechat')
const nativeCodeUrl = ref('')
const nativeOutTradeNo = ref('')
const nativePayChannel = ref<PayChannel>('wechat')
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
// 2026-09-01 - 手机其他浏览器微信 H5 未开通，仅展示不可选
const wechatMobileBrowserReady = false
const showPayChannelPicker = computed(() => payEnv.value === 'pc' || payEnv.value === 'mobile_other')
const canSubmit = computed(() => {
  if (!config.value?.enabled || submitting.value) return false
  if (payEnv.value === 'wechat') return sessionReady.value
  if (payEnv.value === 'mobile_other' && payChannel.value === 'wechat' && !wechatMobileBrowserReady) {
    return false
  }
  return true
})
const payButtonLabel = computed(() => {
  if (submitting.value) return '提交中…'
  const price = config.value?.price_yuan ?? '—'
  if (payChannel.value === 'alipay') {
    if (payEnv.value === 'pc') return `支付宝扫码支付 ¥${price}`
    return `支付宝支付 ¥${price}`
  }
  if (payEnv.value === 'pc') return `微信扫码支付 ¥${price}`
  return `微信支付 ¥${price}`
})
const nativeQrTitle = computed(() =>
  nativePayChannel.value === 'alipay' ? '请使用支付宝扫码支付' : '请使用微信扫码支付',
)
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

function defaultPayChannel(env: PayEnv): PayChannel {
  // 2026-09-01 - 手机其他默认支付宝；PC 默认微信；微信内固定微信
  if (env === 'mobile_other') return 'alipay'
  return 'wechat'
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

async function goResult(outTradeNo: string) {
  // 2026-09-01 - 支付成功进自助结果页看进度
  await router.push({ path: '/h5/diagnosis/result', query: { out_trade_no: outTradeNo } })
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
        await goResult(outTradeNo)
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
  payChannel.value = defaultPayChannel(payEnv.value)
  try {
    config.value = await fetchH5DiagnosisConfig()
    const session = await fetchH5DiagnosisSession()
    sessionReady.value = session.ready
    // 2026-08-31 - B3：仅微信内强制 OAuth；PC/手机浏览器可先看表单
    if (payEnv.value === 'wechat' && !session.ready && config.value.oauth_required) {
      startH5OAuth('apply')
      return
    }
    // 2026-09-01 - 支付宝回跳带 out_trade_no，轮询后进结果页
    const returnedNo = String(route.query.out_trade_no || '').trim()
    if (returnedNo) {
      loading.value = false
      successText.value = '正在确认支付结果…'
      await pollNativePaid(returnedNo)
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
  const formError = validateForm()
  if (formError) {
    errorText.value = formError
    return
  }
  const channel: PayChannel = payEnv.value === 'wechat' ? 'wechat' : payChannel.value
  // 2026-09-01 - 手机其他选微信：等微信 H5 开通；当前拦截
  if (payEnv.value === 'mobile_other' && channel === 'wechat' && !wechatMobileBrowserReady) {
    errorText.value = '微信手机浏览器支付即将开通，请先选支付宝，或用微信打开本页'
    return
  }
  submitting.value = true
  errorText.value = ''
  successText.value = ''
  try {
    const prompts = form.value.prompts.map(v => v.trim()).filter(Boolean)
    let tradeType: 'jsapi' | 'native' | 'wap' | 'precreate' | 'mweb' = 'jsapi'
    if (channel === 'alipay') {
      tradeType = payEnv.value === 'pc' ? 'precreate' : 'wap'
    } else if (payEnv.value === 'pc') {
      tradeType = 'native'
    } else if (payEnv.value === 'mobile_other') {
      tradeType = 'mweb'
    } else {
      tradeType = 'jsapi'
    }
    const result = await createH5DiagnosisOrder({
      contact_phone: form.value.contact_phone.trim(),
      brand_name: form.value.brand_name.trim(),
      prompts,
      brand_aliases: form.value.brand_aliases.trim(),
      industry: form.value.industry.trim(),
      website_url: form.value.website_url.trim(),
      competitors: form.value.competitors.trim(),
      pay_trade_type: tradeType,
      pay_channel: channel,
    })

    if (channel === 'alipay' && tradeType === 'wap') {
      if (result.dev_auto_paid) {
        await markH5OrderDevPaid(result.out_trade_no)
        await goResult(result.out_trade_no)
        return
      }
      const payUrl = String(result.pay_url || '').trim()
      if (!payUrl) throw new Error('未拿到支付宝收银台链接')
      window.location.href = payUrl
      return
    }

    if (tradeType === 'native' || tradeType === 'precreate') {
      if (result.dev_auto_paid || result.pay_params?.devAutoPaid) {
        await markH5OrderDevPaid(result.out_trade_no)
        await goResult(result.out_trade_no)
        return
      }
      nativeOutTradeNo.value = result.out_trade_no
      nativePayChannel.value = channel
      nativeCodeUrl.value = String(result.code_url || '')
      if (!nativeCodeUrl.value) {
        throw new Error('未拿到支付二维码，请稍后重试')
      }
      await pollNativePaid(result.out_trade_no)
      return
    }

    if (result.pay_params?.devAutoPaid) {
      await markH5OrderDevPaid(result.out_trade_no)
      await goResult(result.out_trade_no)
      return
    }
    if (!result.pay_params) {
      throw new Error('支付参数缺失')
    }
    await invokeWechatPay(result.pay_params)
    const status = await fetchH5OrderStatus(result.out_trade_no)
    if (status.status === 'paid') {
      await goResult(result.out_trade_no)
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
  <!-- 2026-08-31 - 申请页对齐落地页蓝系；单卡片分区，避免灰底散表单 -->
  <div class="h5-page">
    <div class="orb orb-a" aria-hidden="true" />
    <div class="orb orb-b" aria-hidden="true" />

    <div class="shell">
      <header class="hero">
        <div class="hero-nav">
          <button type="button" class="back" @click="router.push('/h5/diagnosis')">← 返回</button>
          <button type="button" class="result-link" @click="router.push('/h5/diagnosis/result')">查看报告</button>
        </div>
        <div class="hero-main">
          <span class="price-pill">¥{{ config?.price_yuan ?? '—' }}</span>
          <h1>AI 可见度诊断</h1>
        </div>
      </header>

      <p v-if="loading" class="banner hint">加载中…</p>
      <p v-else-if="errorText" class="banner error">{{ errorText }}</p>
      <p v-else-if="successText" class="banner success">{{ successText }}</p>

      <div v-if="nativeCodeUrl && !successText" class="native-pay">
        <p class="native-title">{{ nativeQrTitle }}</p>
        <img class="native-qr" :src="nativeQrSrc" :alt="nativeQrTitle">
        <p class="native-hint">{{ polling ? '等待支付结果…' : '扫码后请勿关闭本页' }}</p>
        <p class="native-no">单号 {{ nativeOutTradeNo }}</p>
      </div>

      <!-- 2026-08-31 - H5 对齐 PC 品牌字段；不展示地区/平台/天数/销售备注 -->
      <form
        v-if="!loading && !successText && !nativeCodeUrl && config?.enabled"
        class="card"
        @submit.prevent="submitOrder"
      >
        <section class="section">
          <h2 class="section-title">品牌信息</h2>
          <div class="fields">
            <label class="field">
              <span class="field-label">品牌名称 <em>*</em></span>
              <input v-model="form.brand_name" required maxlength="100" placeholder="例如：客户品牌全称">
            </label>
            <label class="field">
              <span class="field-label">品牌别名 / 露出词</span>
              <input v-model="form.brand_aliases" maxlength="500" placeholder="多个用逗号分隔">
            </label>
            <label class="field">
              <span class="field-label">官网 URL</span>
              <input v-model="form.website_url" maxlength="500" placeholder="https://www.example.com">
            </label>
            <label class="field">
              <span class="field-label">所属行业</span>
              <input v-model="form.industry" maxlength="200" placeholder="例如：户外广告、蛋白粉">
            </label>
            <label class="field">
              <span class="field-label">主要竞品</span>
              <input v-model="form.competitors" maxlength="500" placeholder="多个竞品用逗号分隔">
            </label>
            <label class="field">
              <span class="field-label">手机号 <em>*</em></span>
              <input
                v-model="form.contact_phone"
                required
                maxlength="11"
                inputmode="numeric"
                pattern="1[0-9]{10}"
                placeholder="11 位手机号"
              >
            </label>
          </div>
        </section>

        <section class="section prompts">
          <div class="section-head">
            <h2 class="section-title">
              检测问题
              <span class="count">{{ filledPromptCount }}/5</span>
            </h2>
            <button type="button" class="recommend" @click="applyRecommendedSet">一键推荐</button>
          </div>
          <div class="prompt-list">
            <label v-for="(_, index) in form.prompts" :key="index" class="prompt-row">
              <span class="prompt-no">{{ index + 1 }}</span>
              <input
                v-model="form.prompts[index]"
                maxlength="200"
                :placeholder="index === 0 ? '至少填 1 条，如：XX 哪家好' : '可选'"
              >
            </label>
          </div>
        </section>

        <!-- 2026-09-02 - 支付方式放表单底部、提交按钮上方 -->
        <section v-if="showPayChannelPicker" class="section pay-section">
          <h2 class="section-title">支付方式</h2>
          <div class="pay-channel">
            <label
              class="pay-opt"
              :class="{ active: payChannel === 'wechat', disabled: payEnv === 'mobile_other' && !wechatMobileBrowserReady }"
            >
              <input
                v-model="payChannel"
                type="radio"
                value="wechat"
                :disabled="payEnv === 'mobile_other' && !wechatMobileBrowserReady"
              >
              <span class="pay-opt-text">
                微信支付
                <em v-if="payEnv === 'mobile_other' && !wechatMobileBrowserReady" class="pay-opt-note">即将开通</em>
              </span>
            </label>
            <label class="pay-opt" :class="{ active: payChannel === 'alipay' }">
              <input v-model="payChannel" type="radio" value="alipay">
              <span class="pay-opt-text">支付宝</span>
            </label>
          </div>
        </section>

        <div class="submit-bar">
          <button class="submit" type="submit" :disabled="!canSubmit">
            {{ payButtonLabel }}
          </button>
        </div>
      </form>
    </div>
  </div>
</template>

<style scoped>
.h5-page {
  position: relative;
  isolation: isolate;
  min-height: 100vh;
  padding: 20px 16px 40px;
  color: #0f172a;
  background: #f8fbff;
  font-family: system-ui, -apple-system, 'PingFang SC', 'Segoe UI', sans-serif;
  overflow-x: hidden;
}

.orb {
  position: absolute;
  border-radius: 50%;
  filter: blur(48px);
  pointer-events: none;
  z-index: 0;
}
.orb-a {
  top: -80px;
  right: -40px;
  width: 220px;
  height: 220px;
  background: rgba(37, 99, 235, 0.16);
}
.orb-b {
  top: 40%;
  left: -80px;
  width: 180px;
  height: 180px;
  background: rgba(59, 130, 246, 0.10);
}

.shell {
  position: relative;
  z-index: 1;
  width: min(640px, 100%);
  margin: 0 auto;
  display: grid;
  gap: 14px;
}

.hero {
  display: grid;
  gap: 12px;
}
.back {
  justify-self: start;
  border: none;
  background: transparent;
  color: #64748b;
  padding: 0;
  font-size: 14px;
  cursor: pointer;
}
.back:hover { color: #2563eb; }
.hero-nav {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.result-link {
  border: none;
  background: transparent;
  color: #2563eb;
  padding: 0;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
}
.hero-main {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.price-pill {
  display: inline-flex;
  align-items: center;
  min-height: 28px;
  padding: 0 10px;
  border-radius: 999px;
  background: #eff6ff;
  color: #2563eb;
  font-size: 13px;
  font-weight: 700;
}
h1 {
  margin: 0;
  font-size: clamp(22px, 5vw, 28px);
  font-weight: 780;
  letter-spacing: -0.02em;
  color: #0f172a;
}

.banner {
  margin: 0;
  padding: 12px 14px;
  border-radius: 12px;
  font-size: 14px;
  line-height: 1.45;
}
.error { background: #fef2f2; color: #b91c1c; }
.success { background: #ecfdf5; color: #047857; }
.warn { background: #fff7ed; color: #c2410c; }
.hint { background: #fff; color: #64748b; border: 1px solid #e2e8f0; }

.card {
  display: grid;
  gap: 22px;
  padding: 18px 16px 16px;
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.96);
  border: 1px solid #e2e8f0;
  box-shadow: 0 10px 30px rgba(15, 23, 42, 0.05);
}

.section { display: grid; gap: 12px; }
.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}
.section-title {
  margin: 0;
  font-size: 15px;
  font-weight: 700;
  color: #0f172a;
  display: inline-flex;
  align-items: center;
  gap: 8px;
}
.count {
  min-width: 36px;
  padding: 2px 8px;
  border-radius: 999px;
  background: #f1f5f9;
  color: #64748b;
  font-size: 12px;
  font-weight: 650;
  text-align: center;
}
.recommend {
  border: 1px solid #bfdbfe;
  background: #eff6ff;
  color: #2563eb;
  border-radius: 999px;
  padding: 6px 12px;
  font-size: 12px;
  font-weight: 650;
  cursor: pointer;
}
.recommend:hover { background: #dbeafe; }

.fields {
  display: grid;
  gap: 12px;
}
.field {
  display: grid;
  gap: 6px;
}
.field-label {
  font-size: 13px;
  font-weight: 600;
  color: #475569;
}
.field-label em {
  color: #ef4444;
  font-style: normal;
  margin-left: 2px;
}
input {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid #dbe3ef;
  border-radius: 12px;
  padding: 12px 14px;
  font-size: 16px;
  color: #0f172a;
  background: #f8fafc;
  outline: none;
  transition: border-color 0.15s ease, box-shadow 0.15s ease, background 0.15s ease;
}
input::placeholder { color: #94a3b8; }
input:focus {
  border-color: #93c5fd;
  background: #fff;
  box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.12);
}

.prompts {
  padding-top: 4px;
  border-top: 1px solid #f1f5f9;
}
.prompt-list {
  display: grid;
  gap: 8px;
}
.prompt-row {
  display: grid;
  grid-template-columns: 28px minmax(0, 1fr);
  gap: 8px;
  align-items: center;
}
.prompt-no {
  width: 28px;
  height: 28px;
  border-radius: 8px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: #eff6ff;
  color: #2563eb;
  font-size: 12px;
  font-weight: 700;
}

.submit-bar { padding-top: 2px; }
.pay-section { padding-top: 2px; }
.pay-channel {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}
.pay-opt {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0;
  min-width: 0;
  padding: 12px 14px;
  border: 1px solid #dbe3f0;
  border-radius: 12px;
  background: #fff;
  cursor: pointer;
  font-size: 14px;
  color: #0f172a;
  user-select: none;
}
.pay-opt.active {
  border-color: #2563eb;
  background: #eff6ff;
  box-shadow: inset 0 0 0 1px rgba(37, 99, 235, 0.08);
}
.pay-opt.disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
.pay-opt input {
  flex-shrink: 0;
  margin: 0;
  width: 16px;
  height: 16px;
  accent-color: #2563eb;
}
.pay-opt-text {
  flex: 1;
  min-width: 0;
  line-height: 1.35;
  white-space: nowrap;
}
.pay-opt-note {
  display: block;
  margin-top: 2px;
  font-style: normal;
  font-size: 11px;
  font-weight: 500;
  color: #64748b;
  white-space: nowrap;
}
.submit {
  width: 100%;
  border: none;
  border-radius: 14px;
  min-height: 50px;
  padding: 14px 16px;
  font-size: 16px;
  font-weight: 700;
  color: #fff;
  background: #2563eb;
  box-shadow: 0 10px 22px rgba(37, 99, 235, 0.22);
  cursor: pointer;
}
.submit:hover:not(:disabled) { filter: brightness(1.04); }
.submit:active:not(:disabled) { transform: translateY(1px); }
.submit:disabled {
  opacity: 0.55;
  cursor: not-allowed;
  box-shadow: none;
}

.native-pay {
  padding: 24px 16px;
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.96);
  border: 1px solid #e2e8f0;
  box-shadow: 0 10px 30px rgba(15, 23, 42, 0.05);
  text-align: center;
}
.native-title { margin: 0 0 14px; font-size: 16px; font-weight: 700; }
.native-qr {
  width: 220px;
  height: 220px;
  border-radius: 14px;
  background: #fff;
  border: 1px solid #e2e8f0;
}
.native-hint { margin: 14px 0 4px; font-size: 13px; color: #64748b; }
.native-no { margin: 0; font-size: 12px; color: #94a3b8; }

@media (min-width: 720px) {
  .h5-page { padding: 36px 24px 56px; }
  .card { padding: 24px 24px 20px; gap: 24px; }
  .fields {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 14px 16px;
  }
}
</style>
