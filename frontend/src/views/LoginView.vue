<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  ArrowRight, BarChart3, BookOpenCheck, Boxes, Building2, Check, Eye, EyeOff,
  LockKeyhole, MessageSquareWarning, SearchCheck, ShieldCheck, UserRound,
} from '@lucide/vue'
import { useAuthStore } from '../stores/auth'

const router = useRouter()
const auth = useAuthStore()
const form = reactive({
  username: localStorage.getItem('geo-last-user') || 'demo',
  password: 'Geo@2026',
  remember: true,
})
const loading = ref(false)
const showPassword = ref(false)
const identityDialog = ref(false)
const selectedIdentity = ref<number | null>(null)

const selected = computed(() => auth.pendingIdentities.find(item => item.id === selectedIdentity.value))
const platforms = [
  { name: 'DeepSeek', mark: 'D', tone: 'deepseek' },
  { name: '豆包', mark: '豆', tone: 'doubao' },
  { name: 'Kimi', mark: 'K', tone: 'kimi' },
  { name: '百度 AI+', mark: '百', tone: 'baidu' },
  { name: '通义千问', mark: '千', tone: 'qianwen' },
  { name: '元宝', mark: '元', tone: 'yuanbao' },
]
const capabilities = [
  [SearchCheck, '品牌曝光'],
  [BarChart3, '推荐排名'],
  [BookOpenCheck, '引用来源'],
  [MessageSquareWarning, '舆情风险'],
]

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
      await router.replace(auth.portalPath)
    }
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || '登录失败，请稍后重试')
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
    ElMessage.success(`已进入${selected.value?.identity_name || '系统'}`)
    await router.replace(auth.portalPath)
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || '身份切换失败')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <main class="auth-page">
    <section class="auth-visual">
      <header class="auth-brand">
        <div class="auth-brand-mark"><Boxes /></div>
        <div><strong>GEO Monitor</strong><span>AI 平台推广监测系统</span></div>
      </header>

      <div class="auth-visual-content">
        <div class="auth-title">
          <h1>让品牌在 AI 回答中<span>被看见</span></h1>
          <p>覆盖主流 AI 平台，持续洞察品牌曝光、推荐排名与引用表现</p>
        </div>

        <div class="constellation-wrap" aria-label="主流 AI 平台动态接入生态">
          <div class="orbit-grid"></div>
          <div class="orbit-halo orbit-halo-large"></div>
          <div class="orbit-halo orbit-halo-small"></div>
          <div class="orbit-core">
            <span class="core-pulse"></span>
            <div class="core-mark"><Boxes /></div>
            <strong>GEO</strong>
            <small>AI 可见度中枢</small>
          </div>
          <div class="orbit-platforms">
            <div
              v-for="(platform, index) in platforms"
              :key="platform.name"
              class="platform-node"
              :class="[`platform-node-${index + 1}`, `platform-node-${platform.tone}`]"
            >
              <span class="platform-icon">{{ platform.mark }}</span>
              <span class="platform-label"><i></i>{{ platform.name }}</span>
            </div>
          </div>
        </div>

        <div class="capability-row">
          <div v-for="([icon, label]) in capabilities" :key="label as string" class="capability-item">
            <component :is="icon" /><span>{{ label }}</span>
          </div>
        </div>
      </div>
    </section>

    <section class="auth-form-side">
      <div class="auth-orbit"><Boxes /></div>
      <form class="auth-form" @submit.prevent="submitLogin">
        <div class="auth-heading"><span>欢迎回来</span><h2>GEO Monitor</h2><i></i></div>

        <label class="auth-label" for="username">账号</label>
        <div class="auth-input"><UserRound /><input id="username" v-model="form.username" autocomplete="username" placeholder="请输入账号" /></div>

        <label class="auth-label" for="password">密码</label>
        <div class="auth-input"><LockKeyhole /><input id="password" v-model="form.password" :type="showPassword ? 'text' : 'password'" autocomplete="current-password" placeholder="请输入密码" /><button type="button" title="显示或隐藏密码" @click="showPassword = !showPassword"><EyeOff v-if="showPassword" /><Eye v-else /></button></div>

        <div class="auth-options"><label><input v-model="form.remember" type="checkbox" /> 记住账号</label><button type="button">忘记密码</button></div>
        <button class="auth-submit" type="submit" :disabled="loading"><span>{{ loading ? '正在验证...' : '登录系统' }}</span><ArrowRight /></button>
      </form>
    </section>

    <el-dialog v-model="identityDialog" width="620px" :close-on-click-modal="false" :show-close="false" class="identity-dialog dark-identity-dialog">
      <template #header><div class="identity-head"><span>选择本次登录身份</span><small>{{ auth.pendingUser?.display_name }}，检测到 {{ auth.pendingIdentities.length }} 个可用身份</small></div></template>
      <div class="identity-list">
        <button v-for="identity in auth.pendingIdentities" :key="identity.id" type="button" class="identity-option" :class="{ selected: selectedIdentity === identity.id }" @click="selectedIdentity = identity.id">
          <div class="identity-icon"><ShieldCheck v-if="identity.identity_type === 'PLATFORM'" /><Building2 v-else /></div>
          <div class="identity-copy"><strong>{{ identity.identity_name }}</strong><span>{{ identity.identity_type === 'PLATFORM' ? '管理企业、用户、套餐、模型与系统配置' : identity.tenant_name }}</span></div>
          <div class="radio-dot"><Check v-if="selectedIdentity === identity.id" /></div>
        </button>
      </div>
      <template #footer><button class="identity-enter" :disabled="!selectedIdentity || loading" @click="enterWithIdentity">进入工作空间 <ArrowRight /></button></template>
    </el-dialog>
  </main>
</template>
