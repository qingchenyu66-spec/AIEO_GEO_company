<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { LockKeyhole } from '@lucide/vue'
import { changePasswordApi } from '../services/auth'
import { notifyOperationError } from '../utils/requestError'
import { useAuthStore } from '../stores/auth'

const router = useRouter()
const auth = useAuthStore()
const loading = ref(false)
const forcedChange = computed(() => auth.mustChangePassword)
const form = reactive({
  oldPassword: '',
  newPassword: '',
  confirmPassword: '',
})

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

async function logoutInstead() {
  await auth.logout()
  await router.replace('/login')
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
          <h1>{{ forcedChange ? '设置新密码' : '修改密码' }}</h1>
          <p>{{ forcedChange ? '请先设置自己的密码，再进入工作空间' : '更新当前账号的登录密码' }}</p>
        </header>

        <p class="auth-form-sub">当前账号：{{ auth.session?.user?.username || '—' }}</p>

        <label class="auth-field-label" for="old-password">当前密码</label>
        <div class="auth-field">
          <input
            id="old-password"
            v-model="form.oldPassword"
            type="password"
            autocomplete="current-password"
            :placeholder="forcedChange ? '管理员下发的初始密码' : '当前登录密码'"
          />
          <LockKeyhole aria-hidden="true" />
        </div>

        <label class="auth-field-label" for="new-password">新密码</label>
        <div class="auth-field">
          <input
            id="new-password"
            v-model="form.newPassword"
            type="password"
            autocomplete="new-password"
            placeholder="至少 6 个字符"
          />
          <LockKeyhole aria-hidden="true" />
        </div>

        <label class="auth-field-label" for="confirm-password">确认新密码</label>
        <div class="auth-field">
          <input
            id="confirm-password"
            v-model="form.confirmPassword"
            type="password"
            autocomplete="new-password"
            placeholder="再输入一次"
          />
          <LockKeyhole aria-hidden="true" />
        </div>

        <button type="submit" class="auth-submit" style="margin-top: 22px" :disabled="loading">
          <span>{{ loading ? '提交中…' : '确认修改' }}</span>
        </button>
        <button type="button" class="auth-secondary" :disabled="loading" @click="forcedChange ? logoutInstead() : backToPortal()">
          {{ forcedChange ? '退出登录' : '返回' }}
        </button>
      </form>
    </div>

    <p class="auth-center-foot">© GEO Monitor</p>
  </main>
</template>
