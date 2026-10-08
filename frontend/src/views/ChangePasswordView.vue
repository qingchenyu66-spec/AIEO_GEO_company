<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Eye, EyeOff } from '@lucide/vue'
import { changePasswordApi, sendPhoneCodeApi } from '../services/auth'
import { extractErrorDetail, notifyOperationError } from '../utils/requestError'
import { useAuthStore } from '../stores/auth'

const router = useRouter()
const auth = useAuthStore()
const loading = ref(false)
const codeWait = ref(0)
let codeTimer = 0
const form = reactive({
  code: '',
  newPassword: '',
  confirmPassword: '',
})
const showNewPassword = ref(false)
const showConfirmPassword = ref(false)
const phoneMasked = computed(() => auth.session?.user?.phone_masked || '')
const canChange = computed(() => Boolean(phoneMasked.value) && auth.session?.user?.can_bind_phone !== false)

function startCodeWait() {
  codeWait.value = 60
  window.clearInterval(codeTimer)
  codeTimer = window.setInterval(() => {
    codeWait.value -= 1
    if (codeWait.value <= 0) window.clearInterval(codeTimer)
  }, 1000)
}

onMounted(() => { void auth.refreshSession() })
onUnmounted(() => window.clearInterval(codeTimer))

async function sendCode() {
  if (!canChange.value || loading.value || codeWait.value > 0) return
  loading.value = true
  try {
    const result = await sendPhoneCodeApi('password')
    startCodeWait()
    if (result.dev_code) ElMessage.info(`本地验证码 ${result.dev_code}`)
    else ElMessage.success('验证码已发送')
  } catch (error: unknown) {
    const detail = extractErrorDetail(error, '')
    if (detail === '验证码已发送, 请稍后再试' || detail.includes('发送次数已达上限') || detail === '发送过于频繁, 请稍后再试' || detail === '短信发送失败, 请稍后再试') {
      if (detail === '验证码已发送, 请稍后再试') startCodeWait()
      ElMessage.warning(detail)
      return
    }
    notifyOperationError(error, '验证码发送失败')
  } finally {
    loading.value = false
  }
}

async function submit() {
  if (!canChange.value) return
  if (!/^\d{4}$/.test(form.code.trim()) || !form.newPassword) {
    ElMessage.warning('请填写验证码和新密码')
    return
  }
  if (form.newPassword.length < 6) {
    ElMessage.warning('新密码至少 6 个字符')
    return
  }
  if (form.newPassword !== form.confirmPassword) {
    ElMessage.warning('两次输入的新密码不一致')
    return
  }
  loading.value = true
  try {
    await changePasswordApi(form.code.trim(), form.newPassword)
    auth.clearLocalSession()
    ElMessage.success('密码已更新, 请重新登录')
    await router.replace('/login')
  } catch (error: unknown) {
    notifyOperationError(error, '修改密码失败')
  } finally {
    loading.value = false
  }
}

async function backToPortal() {
  await router.replace(auth.portalPath)
}
</script>

<template>
  <main class="auth-page auth-page--glass">
    <div class="auth-glass-bg" aria-hidden="true">
      <div class="auth-glass-base"></div>
      <div class="auth-glass-grid"></div>
      <div class="auth-glass-glow auth-glass-glow-a"></div>
      <div class="auth-glass-glow auth-glass-glow-b"></div>
      <div class="auth-glass-vignette"></div>
    </div>

    <div class="auth-center">
      <form class="auth-form auth-form--glass" @submit.prevent="submit">
        <header class="auth-glass-head">
          <h1>修改密码</h1>
          <p>验证码发到已绑定的手机</p>
        </header>

        <p class="auth-form-sub">当前账号: {{ auth.session?.user?.username || '—' }}</p>

        <p v-if="!canChange" class="auth-form-sub">尚未绑定手机号, 请先到账号与安全绑定, 或联系管理员重置密码.</p>

        <template v-else>
          <label class="auth-field-label" for="password-code">验证码</label>
          <div class="auth-field auth-field--code">
            <input id="password-code" v-model="form.code" inputmode="numeric" maxlength="4" autocomplete="one-time-code" placeholder="4 位验证码" />
            <button type="button" class="auth-code-send" :disabled="loading || codeWait > 0" @click="sendCode">
              {{ codeWait > 0 ? `${codeWait}s` : '获取验证码' }}
            </button>
          </div>
          <p class="auth-form-sub">将发送到 {{ phoneMasked }}</p>

          <label class="auth-field-label" for="new-password">新密码</label>
          <div class="auth-field">
            <input
              id="new-password"
              v-model="form.newPassword"
              :type="showNewPassword ? 'text' : 'password'"
              autocomplete="new-password"
              placeholder="至少 6 个字符"
            />
            <button
              type="button"
              class="auth-field-toggle"
              :title="showNewPassword ? '隐藏密码' : '显示密码'"
              :aria-label="showNewPassword ? '隐藏密码' : '显示密码'"
              @click="showNewPassword = !showNewPassword"
            >
              <EyeOff v-if="showNewPassword" />
              <Eye v-else />
            </button>
          </div>

          <label class="auth-field-label" for="confirm-password">确认新密码</label>
          <div class="auth-field">
            <input
              id="confirm-password"
              v-model="form.confirmPassword"
              :type="showConfirmPassword ? 'text' : 'password'"
              autocomplete="new-password"
              placeholder="再输入一次"
            />
            <button
              type="button"
              class="auth-field-toggle"
              :title="showConfirmPassword ? '隐藏密码' : '显示密码'"
              :aria-label="showConfirmPassword ? '隐藏密码' : '显示密码'"
              @click="showConfirmPassword = !showConfirmPassword"
            >
              <EyeOff v-if="showConfirmPassword" />
              <Eye v-else />
            </button>
          </div>
        </template>

        <button v-if="canChange" type="submit" class="auth-submit" style="margin-top: 22px" :disabled="loading">
          <span>{{ loading ? '提交中…' : '确认修改' }}</span>
        </button>
        <button type="button" class="auth-secondary" :disabled="loading" @click="backToPortal()">
          返回
        </button>
      </form>
    </div>

    <p class="auth-center-foot">© GEO Monitor</p>
  </main>
</template>
