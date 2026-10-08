<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Eye, EyeOff } from '@lucide/vue'
import { changePasswordApi } from '../services/auth'
import { notifyOperationError } from '../utils/requestError'
import { useAuthStore } from '../stores/auth'

const router = useRouter()
const auth = useAuthStore()
const loading = ref(false)
const form = reactive({
  oldPassword: '',
  newPassword: '',
  confirmPassword: '',
})
// 2026-09-07 - 改密页右侧锁图标误导 - 对齐登录页改为显隐眼睛
const showOldPassword = ref(false)
const showNewPassword = ref(false)
const showConfirmPassword = ref(false)

async function submit() {
  if (!form.oldPassword || !form.newPassword) {
    ElMessage.warning('请填写当前密码和新密码')
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
  if (form.oldPassword === form.newPassword) {
    ElMessage.warning('新密码不能与当前密码相同')
    return
  }
  loading.value = true
  try {
    await changePasswordApi(form.oldPassword, form.newPassword)
    await auth.refreshSession()
    ElMessage.success('密码已更新')
    await router.replace(auth.portalPath)
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
  <!-- 2026-08-20 - 改密页对齐玻璃卡方案 A -->
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
          <p>更新当前账号的登录密码</p>
        </header>

        <p class="auth-form-sub">当前账号：{{ auth.session?.user?.username || '—' }}</p>

        <label class="auth-field-label" for="old-password">当前密码</label>
        <div class="auth-field">
          <input
            id="old-password"
            v-model="form.oldPassword"
            :type="showOldPassword ? 'text' : 'password'"
            autocomplete="current-password"
            placeholder="当前登录密码"
          />
          <button
            type="button"
            class="auth-field-toggle"
            :title="showOldPassword ? '隐藏密码' : '显示密码'"
            :aria-label="showOldPassword ? '隐藏密码' : '显示密码'"
            @click="showOldPassword = !showOldPassword"
          >
            <EyeOff v-if="showOldPassword" />
            <Eye v-else />
          </button>
        </div>

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

        <button type="submit" class="auth-submit" style="margin-top: 22px" :disabled="loading">
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
