<script setup lang="ts">
import { computed, onUnmounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  Building2, Check, Eye, EyeOff, ShieldCheck, UserRound,
} from '@lucide/vue'
import { checkResetApi, resetPasswordApi, sendLoginCodeApi, sendResetCodeApi } from '../services/auth'
import { extractErrorDetail, notifyOperationError } from '../utils/requestError'
import { useAuthStore } from '../stores/auth'

const router = useRouter()
const auth = useAuthStore()
const form = reactive({
  username: localStorage.getItem('geo-last-user') || (import.meta.env.DEV ? 'demo' : ''),
  password: import.meta.env.DEV ? 'Geo@2026' : '',
  remember: true,
})
const loading = ref(false)
const showPassword = ref(false)
const identityDialog = ref(false)
const selectedIdentity = ref<number | null>(null)
const mode = ref<'password' | 'sms' | 'reset'>('password')
const sms = reactive({ phone: '', code: '' })
const reset = reactive({ code: '', newPassword: '', confirm: '' })
const resetUsername = ref('')
const resetPhone = ref('')
const showResetPassword = ref(false)
const codeWait = ref(0)
const RESET_UNBOUND = '该账号尚未绑定手机号, 请联系管理员重置密码'
let codeTimer = 0

function startCodeWait() {
  codeWait.value = 60
  window.clearInterval(codeTimer)
  codeTimer = window.setInterval(() => {
    codeWait.value -= 1
    if (codeWait.value <= 0) window.clearInterval(codeTimer)
  }, 1000)
}

onUnmounted(() => window.clearInterval(codeTimer))

const selected = computed(() => auth.pendingIdentities.find(item => item.id === selectedIdentity.value))
function identityDisplayName(identity: { position_name?: string | null; identity_name?: string }) {
  return identity.position_name || identity.identity_name || '登录身份'
}

async function finishLogin(needsSelection: boolean) {
  if (needsSelection) {
    selectedIdentity.value = auth.pendingIdentities.find(item => item.is_default)?.id || auth.pendingIdentities[0]?.id || null
    identityDialog.value = true
  } else {
    ElMessage.success('登录成功')
    await router.replace(auth.portalPath)
  }
}

async function sendCode() {
  if (loading.value || codeWait.value > 0) return
  if (!/^1\d{10}$/.test(sms.phone.trim())) {
    ElMessage.warning('请填写 11 位手机号')
    return
  }
  loading.value = true
  try {
    const result = await sendLoginCodeApi(sms.phone.trim())
    startCodeWait()
    if (result.dev_code) ElMessage.info(`本地验证码 ${result.dev_code}`)
    else ElMessage.success('验证码已发送')
  } catch (error: unknown) {
    const detail = extractErrorDetail(error, '')
    if (isSoftSmsError(detail)) {
      if (detail === '验证码已发送, 请稍后再试') startCodeWait()
      ElMessage.warning(detail)
      return
    }
    if (detail === '该手机号尚未绑定, 请用账号密码登录, 或联系管理员绑定' || detail === '该手机号未开启验证码登录') {
      ElMessage.warning(detail)
      return
    }
    notifyOperationError(error, '验证码发送失败')
  } finally {
    loading.value = false
  }
}

function isSoftSmsError(detail: string) {
  return detail === '验证码已发送, 请稍后再试'
    || detail.includes('发送次数已达上限')
    || detail === '发送过于频繁, 请稍后再试'
    || detail === '短信发送失败, 请稍后再试'
    || detail === RESET_UNBOUND
}

async function openReset() {
  const username = form.username.trim()
  if (username.length < 3) {
    ElMessage.warning('请先填写账号')
    return
  }
  if (loading.value) return
  loading.value = true
  try {
    const result = await checkResetApi(username)
    if (resetUsername.value !== username) {
      reset.code = ''
      reset.newPassword = ''
      reset.confirm = ''
      codeWait.value = 0
      window.clearInterval(codeTimer)
    }
    resetUsername.value = username
    resetPhone.value = result.phone_masked || ''
    showResetPassword.value = false
    mode.value = 'reset'
  } catch (error: unknown) {
    const detail = extractErrorDetail(error, '')
    if (isSoftSmsError(detail) || detail === '账号已停用，请联系运营人员' || detail === '企业已删除，请联系运营人员') {
      ElMessage.warning(detail)
      return
    }
    notifyOperationError(error, '暂时无法找回密码')
  } finally {
    loading.value = false
  }
}

async function sendResetCode() {
  if (loading.value || codeWait.value > 0) return
  const username = resetUsername.value
  if (username.length < 3) {
    ElMessage.warning('请先填写账号')
    return
  }
  loading.value = true
  try {
    const result = await sendResetCodeApi(username)
    if (result.phone_masked) resetPhone.value = result.phone_masked
    startCodeWait()
    if (result.dev_code) ElMessage.info(`本地验证码 ${result.dev_code}`)
    else ElMessage.success(resetPhone.value ? `验证码已发送到 ${resetPhone.value}` : '验证码已发送')
  } catch (error: unknown) {
    const detail = extractErrorDetail(error, '')
    if (isSoftSmsError(detail)) {
      if (detail === '验证码已发送, 请稍后再试') startCodeWait()
      ElMessage.warning(detail)
      return
    }
    notifyOperationError(error, '验证码发送失败')
  } finally {
    loading.value = false
  }
}

async function submitReset() {
  const username = resetUsername.value
  if (username.length < 3) return ElMessage.warning('请先填写账号')
  if (!/^\d{4}$/.test(reset.code.trim())) return ElMessage.warning('请填写 4 位验证码')
  if (reset.newPassword.trim().length < 6) return ElMessage.warning('新密码至少 6 个字符')
  if (reset.newPassword !== reset.confirm) return ElMessage.warning('两次输入的密码不一致')
  loading.value = true
  try {
    await resetPasswordApi(username, reset.code.trim(), reset.newPassword.trim())
    form.password = ''
    mode.value = 'password'
    ElMessage.success('密码已更新, 请用新密码登录')
  } catch (error: unknown) {
    const detail = extractErrorDetail(error, '')
    if (detail === RESET_UNBOUND || detail === '新密码不能与当前密码相同' || detail === '新密码至少 6 个字符' || detail.includes('验证码')) {
      ElMessage.warning(detail)
      return
    }
    notifyOperationError(error, '修改失败')
  } finally {
    loading.value = false
  }
}

async function submitLogin() {
  if (mode.value === 'reset') {
    await submitReset()
    return
  }
  if (mode.value === 'sms') {
    if (!/^1\d{10}$/.test(sms.phone.trim()) || !/^\d{4}$/.test(sms.code.trim())) {
      ElMessage.warning('请填写手机号和 4 位验证码')
      return
    }
    loading.value = true
    try {
      const needsSelection = await auth.loginBySms(sms.phone.trim(), sms.code.trim())
      await finishLogin(needsSelection)
    } catch (error: any) {
      if (error?.response?.status === 401 && String(error?.config?.url || '').includes('/auth/sms/login')) return
      notifyOperationError(error, '暂时无法登录, 请检查网络后重试')
    } finally {
      loading.value = false
    }
    return
  }
  if (!form.username || !form.password) return ElMessage.warning('请输入账号和密码')
  loading.value = true
  try {
    const needsSelection = await auth.login(form.username.trim(), form.password)

    if (form.remember) localStorage.setItem('geo-last-user', form.username.trim())
    else localStorage.removeItem('geo-last-user')
    await finishLogin(needsSelection)
  } catch (error: any) {
    if (error?.response?.status === 401 && error?.config?.url?.includes('/auth/login')) return
    notifyOperationError(error, '暂时无法登录，请检查网络后重试')
  } finally {
    loading.value = false
  }
}

async function enterWithIdentity() {
  if (!selectedIdentity.value) return
  loading.value = true
  try {
    await auth.selectIdentity(selectedIdentity.value)
    identityDialog.value = false
    ElMessage.success(`已进入${selected.value ? identityDisplayName(selected.value) : '系统'}`)
    await router.replace(auth.portalPath)
  } catch (error: any) {
    notifyOperationError(error, '身份选择失败')
  } finally {
    loading.value = false
  }
}

</script>

<template>
  <!-- 2026-08-20 - 登录方案 A 玻璃卡 - 科技静图底 + 毛玻璃表单，客户向文案 -->
  <main class="auth-page auth-page--glass">
    <div class="auth-glass-bg" aria-hidden="true">
      <div class="auth-glass-base"></div>
      <div class="auth-glass-grid"></div>
      <div class="auth-glass-glow auth-glass-glow-a"></div>
      <div class="auth-glass-glow auth-glass-glow-b"></div>
      <div class="auth-glass-vignette"></div>
    </div>

    <div class="auth-center">
      <form class="auth-form auth-form--glass" @submit.prevent="submitLogin">
        <header class="auth-glass-head">
          <h1>GEO Monitor</h1>
          <p>{{ mode === 'reset' ? `验证码将发到 ${resetPhone}` : '看清品牌在 AI 回答里的提及、排名与信源' }}</p>
        </header>

        <div v-if="mode !== 'reset'" class="auth-mode" role="tablist" aria-label="登录方式">
          <button type="button" :class="{ 'is-on': mode === 'password' }" @click="mode = 'password'">账号密码</button>
          <button type="button" :class="{ 'is-on': mode === 'sms' }" @click="mode = 'sms'">手机验证码</button>
        </div>

        <template v-if="mode === 'password'">
        <label class="auth-field-label" for="username">账号</label>
        <div class="auth-field">
          <input id="username" v-model="form.username" autocomplete="username" placeholder="请输入账号" />
          <UserRound aria-hidden="true" />
        </div>

        <label class="auth-field-label" for="password">密码</label>
        <div class="auth-field">
          <input
            id="password"
            v-model="form.password"
            :type="showPassword ? 'text' : 'password'"
            autocomplete="current-password"
            placeholder="请输入密码"
          />
          <button
            type="button"
            class="auth-field-toggle"
            :title="showPassword ? '隐藏密码' : '显示密码'"
            :aria-label="showPassword ? '隐藏密码' : '显示密码'"
            @click="showPassword = !showPassword"
          >
            <EyeOff v-if="showPassword" />
            <Eye v-else />
          </button>
        </div>

        <div class="auth-remember-row">
          <label class="auth-remember">
            <input v-model="form.remember" type="checkbox" />
            <span class="auth-remember-box" aria-hidden="true">
              <Check />
            </span>
            <span class="auth-remember-text">记住账号</span>
          </label>
          <button type="button" class="auth-forgot" @click="openReset">忘记密码</button>
        </div>
        </template>

        <template v-else-if="mode === 'reset'">
          <div class="auth-reset-account">
            <span class="auth-field-label">账号</span>
            <strong>{{ resetUsername }}</strong>
          </div>
          <label class="auth-field-label" for="reset-code">验证码</label>
          <div class="auth-field auth-field--code">
            <input id="reset-code" v-model="reset.code" inputmode="numeric" maxlength="4" autocomplete="one-time-code" placeholder="4 位验证码" />
            <button type="button" class="auth-code-send" :disabled="loading || codeWait > 0" @click="sendResetCode">
              {{ codeWait > 0 ? `${codeWait}s` : '获取验证码' }}
            </button>
          </div>
          <label class="auth-field-label" for="reset-password">新密码</label>
          <div class="auth-field">
            <input
              id="reset-password"
              v-model="reset.newPassword"
              :type="showResetPassword ? 'text' : 'password'"
              autocomplete="new-password"
              placeholder="至少 6 位"
            />
            <button
              type="button"
              class="auth-field-toggle"
              :title="showResetPassword ? '隐藏密码' : '显示密码'"
              :aria-label="showResetPassword ? '隐藏密码' : '显示密码'"
              @click="showResetPassword = !showResetPassword"
            >
              <EyeOff v-if="showResetPassword" />
              <Eye v-else />
            </button>
          </div>
          <label class="auth-field-label" for="reset-confirm">确认新密码</label>
          <div class="auth-field auth-field--tail">
            <input id="reset-confirm" v-model="reset.confirm" :type="showResetPassword ? 'text' : 'password'" autocomplete="new-password" placeholder="再输入一次" />
          </div>
        </template>

        <div v-else class="auth-sms">
          <label class="auth-field-label" for="login-phone">手机号</label>
          <div class="auth-field">
            <input id="login-phone" v-model="sms.phone" inputmode="numeric" maxlength="11" autocomplete="tel" placeholder="11 位手机号" />
          </div>
          <label class="auth-field-label" for="login-code">验证码</label>
          <div class="auth-field auth-field--code">
            <input id="login-code" v-model="sms.code" inputmode="numeric" maxlength="4" autocomplete="one-time-code" placeholder="4 位验证码" />
            <button type="button" class="auth-code-send" :disabled="loading || codeWait > 0" @click="sendCode">
              {{ codeWait > 0 ? `${codeWait}s` : '获取验证码' }}
            </button>
          </div>
        </div>

        <button class="auth-submit" type="submit" :disabled="loading">
          <span v-if="loading" class="auth-submit-spinner" aria-hidden="true"></span>
          <span>{{ loading ? '请稍候' : (mode === 'reset' ? '确认修改' : '登录') }}</span>
        </button>
        <button v-if="mode === 'reset'" type="button" class="auth-back" @click="mode = 'password'">返回登录</button>
        <p v-else class="auth-help">无法登录？请联系贵司管理员</p>
      </form>
    </div>

    <p class="auth-center-foot">© GEO Monitor</p>

    <el-dialog v-model="identityDialog" width="560px" :close-on-click-modal="false" :show-close="false" class="identity-dialog">
      <template #header>
        <div class="identity-head">
          <span>选择登录身份</span>
          <small>{{ auth.pendingUser?.display_name }} · {{ auth.pendingIdentities.length }} 个可用身份</small>
        </div>
      </template>
      <div class="identity-list">
        <button
          v-for="identity in auth.pendingIdentities"
          :key="identity.id"
          type="button"
          class="identity-option"
          :class="{ selected: selectedIdentity === identity.id }"
          @click="selectedIdentity = identity.id"
        >
          <div class="identity-icon">
            <ShieldCheck v-if="identity.identity_type === 'PLATFORM'" />
            <Building2 v-else />
          </div>
          <div class="identity-copy">
            <strong>{{ identityDisplayName(identity) }}</strong>
            <span>{{ identity.identity_type === 'PLATFORM' ? '平台运营端' : identity.tenant_name }}</span>
          </div>
          <div class="radio-dot"><Check v-if="selectedIdentity === identity.id" /></div>
        </button>
      </div>
      <template #footer>
        <button class="identity-enter" :disabled="!selectedIdentity || loading" @click="enterWithIdentity">
          {{ loading ? '进入中…' : '进入工作空间' }}
        </button>
      </template>
    </el-dialog>
  </main>
</template>
