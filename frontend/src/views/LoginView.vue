<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  Building2, Check, Eye, EyeOff, ShieldCheck, UserRound,
} from '@lucide/vue'
import { notifyOperationError } from '../utils/requestError'
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

const selected = computed(() => auth.pendingIdentities.find(item => item.id === selectedIdentity.value))
function identityDisplayName(identity: { position_name?: string | null; identity_name?: string }) {
  return identity.position_name || identity.identity_name || '登录身份'
}

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
          <p>看清品牌在 AI 回答里的提及、排名与信源</p>
        </header>

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

        <label class="auth-remember">
          <input v-model="form.remember" type="checkbox" />
          <span class="auth-remember-box" aria-hidden="true">
            <Check />
          </span>
          <span class="auth-remember-text">记住账号</span>
        </label>

        <button class="auth-submit" type="submit" :disabled="loading">
          <span v-if="loading" class="auth-submit-spinner" aria-hidden="true"></span>
          <span>{{ loading ? '正在验证…' : '登录' }}</span>
        </button>
        <p class="auth-help">无法登录？请联系贵司管理员</p>
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
