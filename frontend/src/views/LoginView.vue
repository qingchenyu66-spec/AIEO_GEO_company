<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  ArrowRight, Building2, Check, Eye, EyeOff, LockKeyhole, ShieldCheck, UserRound,
} from '@lucide/vue'
import { notifyOperationError } from '../utils/requestError'
import { useAuthStore } from '../stores/auth'
import AppBrandLogo from '../components/AppBrandLogo.vue'
import PlatformBadge from '../components/PlatformBadge.vue'
import { supportedPlatforms } from '../views/portal/platformMeta'
import { comparePlatformCodes } from './portal/platformOrder'

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

const selected = computed(() => auth.pendingIdentities.find(item => item.id === selectedIdentity.value))
function identityDisplayName(identity: { position_name?: string | null; identity_name?: string }) {
  return identity.position_name || identity.identity_name || '登录身份'
}
// 2026-08-17 - 登录页监测平台条不展示移动端 - 仅滤展示，不动 supportedPlatforms 业务勾选
// 2026-08-18 - 展示序走市场排序；PLATFORM_META 对象键序不影响本条
const platforms = supportedPlatforms
  .filter(item => !item.code.endsWith('_mobile'))
  .slice()
  .sort((left, right) => comparePlatformCodes(left.code, right.code))
  .map(item => ({ code: item.code, name: item.name }))

async function submitLogin() {
  if (!form.username || !form.password) return ElMessage.warning('请输入账号和密码')
  loading.value = true
  try {
    const needsSelection = await auth.login(form.username.trim(), form.password)

    if (form.remember) localStorage.setItem('geo-last-user', form.username.trim())
    else localStorage.removeItem('geo-last-user')
    if (needsSelection) {
      selectedIdentity.value = auth.pendingIdentities.find(item => item.is_default)?.id || auth.pendingIdentities[0]?.id || null
      identityDialog.value = true
    } else {
      ElMessage.success('登录成功')
      await router.replace(auth.mustChangePassword ? '/change-password' : auth.portalPath)
    }
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
    await router.replace(auth.mustChangePassword ? '/change-password' : auth.portalPath)
  } catch (error: any) {
    notifyOperationError(error, '身份选择失败')
  } finally {
    loading.value = false
  }
}

</script>

<template>
  <main class="auth-page">
    <div class="auth-ambient" aria-hidden="true">
      <div class="auth-bg-base"></div>
      <div class="auth-bg-grid"></div>
      <div class="auth-bg-vignette"></div>
      <div class="auth-spotlight"></div>
      <div class="auth-orb auth-orb-a"></div>
      <div class="auth-orb auth-orb-b"></div>
      <div class="auth-orb auth-orb-c"></div>
      <div class="auth-orb auth-orb-d"></div>
    </div>

    <div class="auth-wrap">
      <header class="auth-hero">
        <AppBrandLogo variant="full" alt="艾迪亚控股集团 · GEO Monitor" />
        <h1>GEO Monitor</h1>
        <p class="auth-hero-sub">AI 平台推广监测</p>
      </header>

      <form class="auth-form" @submit.prevent="submitLogin">
        <h2>欢迎回来</h2>

        <label class="auth-field-label" for="username">账号</label>
        <div class="auth-field">
          <UserRound aria-hidden="true" />
          <input id="username" v-model="form.username" autocomplete="username" placeholder="请输入账号" />
        </div>

        <label class="auth-field-label" for="password">密码</label>
        <div class="auth-field">
          <LockKeyhole aria-hidden="true" />
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

        <label class="auth-remember">
          <input v-model="form.remember" type="checkbox" />
          <span class="auth-remember-box" aria-hidden="true">
            <Check />
          </span>
          <span class="auth-remember-text">记住账号</span>
        </label>

        <button class="auth-submit" type="submit" :disabled="loading">
          <span v-if="loading" class="auth-submit-spinner" aria-hidden="true"></span>
          <span>{{ loading ? '正在验证' : '登录系统' }}</span>
          <ArrowRight v-if="!loading" />
        </button>
      </form>

      <div class="auth-platform-strip" aria-label="已接入监测平台">
        <div class="auth-platform-strip-head">
          <span class="auth-platform-strip-title">
            <span class="auth-platform-dot" aria-hidden="true"></span>
            监测平台
          </span>
          <span class="auth-platform-count">{{ platforms.length }} 个已接入</span>
        </div>
        <div class="auth-platform-grid">
          <div v-for="platform in platforms" :key="platform.code" class="auth-platform-item">
            <PlatformBadge
              :code="platform.code"
              size="sm"
              icon-only
              :show-label="false"
            />
            <span>{{ platform.name }}</span>
          </div>
        </div>
      </div>
    </div>

    <el-dialog v-model="identityDialog" width="620px" :close-on-click-modal="false" :show-close="false" class="identity-dialog dark-identity-dialog">
      <template #header><div class="identity-head"><span>选择本次登录身份</span><small>{{ auth.pendingUser?.display_name }}，检测到 {{ auth.pendingIdentities.length }} 个可用身份</small></div></template>
      <div class="identity-list">
        <button v-for="identity in auth.pendingIdentities" :key="identity.id" type="button" class="identity-option" :class="{ selected: selectedIdentity === identity.id }" @click="selectedIdentity = identity.id">
          <div class="identity-icon"><ShieldCheck v-if="identity.identity_type === 'PLATFORM'" /><Building2 v-else /></div>
          <div class="identity-copy"><strong>{{ identityDisplayName(identity) }}</strong><span>{{ identity.identity_type === 'PLATFORM' ? '管理企业、用户、套餐、模型与系统配置' : identity.tenant_name }}</span></div>
          <div class="radio-dot"><Check v-if="selectedIdentity === identity.id" /></div>
        </button>
      </div>
      <template #footer><button class="identity-enter" :disabled="!selectedIdentity || loading" @click="enterWithIdentity">进入工作空间 <ArrowRight /></button></template>
    </el-dialog>
  </main>
</template>
