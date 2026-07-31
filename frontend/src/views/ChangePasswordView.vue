<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowRight, LockKeyhole } from '@lucide/vue'
import { changePasswordApi } from '../services/auth'
import { notifyOperationError } from '../utils/requestError'
import { useAuthStore } from '../stores/auth'
import AppBrandLogo from '../components/AppBrandLogo.vue'

const router = useRouter()
const auth = useAuthStore()
const loading = ref(false)
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
</script>

<template>
  <!-- 2026-07-31 - 改密页黑屏 - 对齐登录页 auth-wrap/form/field，勿用已废弃 auth-card/input -->
  <main class="auth-page">
    <div class="auth-ambient" aria-hidden="true">
      <div class="auth-bg-base"></div>
      <div class="auth-bg-grid"></div>
      <div class="auth-bg-vignette"></div>
      <div class="auth-spotlight"></div>
      <div class="auth-orb auth-orb-a"></div>
      <div class="auth-orb auth-orb-b"></div>
    </div>

    <div class="auth-wrap">
      <header class="auth-hero">
        <AppBrandLogo variant="full" alt="艾迪亚控股集团 · GEO Monitor" />
        <h1>修改登录密码</h1>
        <p class="auth-hero-sub">首次登录或管理员重置后，需设置自己的密码才能继续使用系统</p>
      </header>

      <form class="auth-form" @submit.prevent="submit">
        <h2>设置新密码</h2>
        <p class="auth-hint">当前账号：{{ auth.session?.user?.username || '—' }}</p>

        <label class="auth-field-label" for="old-password">当前密码</label>
        <div class="auth-field">
          <LockKeyhole aria-hidden="true" />
          <input
            id="old-password"
            v-model="form.oldPassword"
            type="password"
            autocomplete="current-password"
            placeholder="管理员下发的初始密码"
          />
        </div>

        <label class="auth-field-label" for="new-password">新密码</label>
        <div class="auth-field">
          <LockKeyhole aria-hidden="true" />
          <input
            id="new-password"
            v-model="form.newPassword"
            type="password"
            autocomplete="new-password"
            placeholder="至少 6 个字符"
          />
        </div>

        <label class="auth-field-label" for="confirm-password">确认新密码</label>
        <div class="auth-field">
          <LockKeyhole aria-hidden="true" />
          <input
            id="confirm-password"
            v-model="form.confirmPassword"
            type="password"
            autocomplete="new-password"
            placeholder="再输入一次"
          />
        </div>

        <button type="submit" class="auth-submit" style="margin-top: 22px" :disabled="loading">
          <span>{{ loading ? '提交中…' : '确认修改' }}</span>
          <ArrowRight v-if="!loading" />
        </button>
        <button type="button" class="auth-secondary" :disabled="loading" @click="logoutInstead">退出登录</button>
      </form>
    </div>
  </main>
</template>
