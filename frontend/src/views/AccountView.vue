<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElDialog, ElMessage } from 'element-plus'
import { ArrowLeft, Copy, Pencil } from '@lucide/vue'
import { bindPhoneApi, changePhoneApi, sendPhoneCodeApi, setPhoneLoginApi, type IdentityInfo } from '../services/auth'
import { extractErrorDetail, notifyOperationError } from '../utils/requestError'
import { useAuthStore } from '../stores/auth'

const router = useRouter()
const auth = useAuthStore()
const loading = ref(false)
const editor = ref<'bind' | 'change' | null>(null)
const bind = reactive({ phone: '', code: '' })
const change = reactive({ oldCode: '', newPhone: '', newCode: '' })
const waits = reactive({ bind: 0, old: 0, next: 0 })
const timers: number[] = []

const user = computed(() => auth.session?.user)
const identities = computed(() => auth.session?.identities || [])
const currentIdentityId = computed(() => auth.session?.identity?.id)
const initial = computed(() => (user.value?.display_name || user.value?.username || '账').slice(0, 1))
const phoneBound = computed(() => Boolean(user.value?.phone_masked))
const canBind = computed(() => user.value?.can_bind_phone !== false)
const phoneLoginOn = computed(() => canBind.value && phoneBound.value && user.value?.phone_login_enabled !== false)
const phoneLoginLabel = computed(() => {
  if (!canBind.value) return '不可用'
  return phoneLoginOn.value ? '已开启' : '未开启'
})
const phoneDialogTitle = computed(() => (editor.value === 'change' ? '更换手机号' : '绑定手机号'))

function identityKind(identity: IdentityInfo) {
  return identity.identity_type === 'PLATFORM' ? '平台运营端' : '客户企业端'
}

function identityTitle(identity: IdentityInfo) {
  return identity.position_name || identity.identity_name || identityKind(identity)
}

function startWait(key: 'bind' | 'old' | 'next') {
  waits[key] = 60
  const timer = window.setInterval(() => {
    waits[key] -= 1
    if (waits[key] <= 0) window.clearInterval(timer)
  }, 1000)
  timers.push(timer)
}

onUnmounted(() => timers.forEach(timer => window.clearInterval(timer)))
onMounted(() => { void auth.refreshSession() })

function noteCode(devCode?: string) {
  if (devCode) ElMessage.info(`本地验证码 ${devCode}`)
  else ElMessage.success('验证码已发送')
}

function noteSendError(error: unknown, key: 'bind' | 'old' | 'next') {
  const detail = extractErrorDetail(error, '')
  if (detail === '验证码已发送, 请稍后再试' || detail.includes('发送次数已达上限') || detail === '发送过于频繁, 请稍后再试' || detail === '短信发送失败, 请稍后再试') {
    if (detail === '验证码已发送, 请稍后再试') startWait(key)
    ElMessage.warning(detail)
    return
  }
  notifyOperationError(error, '验证码发送失败')
}

function openPhoneEditor() {
  if (!canBind.value) return
  editor.value = phoneBound.value ? 'change' : 'bind'
}

async function togglePhoneLogin() {
  if (!canBind.value || !phoneBound.value || loading.value) return
  const next = !phoneLoginOn.value
  loading.value = true
  try {
    await setPhoneLoginApi(next)
    await auth.refreshSession()
    ElMessage.success(next ? '已开启手机号登录' : '已关闭手机号登录')
  } catch (error: unknown) {
    notifyOperationError(error, '设置失败')
  } finally {
    loading.value = false
  }
}

async function copyId() {
  const text = String(user.value?.id || '')
  if (!text) return
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success('已复制账号 ID')
  } catch {
    ElMessage.warning('复制失败, 请手动选择')
  }
}

async function sendBind() {
  if (!/^1\d{10}$/.test(bind.phone.trim())) {
    ElMessage.warning('请填写 11 位手机号')
    return
  }
  loading.value = true
  try {
    const result = await sendPhoneCodeApi('bind', bind.phone.trim())
    startWait('bind')
    noteCode(result.dev_code)
  } catch (error: unknown) {
    noteSendError(error, 'bind')
  } finally {
    loading.value = false
  }
}

async function submitBind() {
  if (!/^1\d{10}$/.test(bind.phone.trim()) || !/^\d{4}$/.test(bind.code.trim())) {
    ElMessage.warning('请填写手机号和 4 位验证码')
    return
  }
  loading.value = true
  try {
    await bindPhoneApi(bind.phone.trim(), bind.code.trim())
    await auth.refreshSession()
    ElMessage.success('手机号已绑定, 可直接用于登录')
    bind.phone = ''
    bind.code = ''
    editor.value = null
  } catch (error: unknown) {
    notifyOperationError(error, '绑定失败')
  } finally {
    loading.value = false
  }
}

async function sendOld() {
  loading.value = true
  try {
    const result = await sendPhoneCodeApi('change_old')
    startWait('old')
    noteCode(result.dev_code)
  } catch (error: unknown) {
    noteSendError(error, 'old')
  } finally {
    loading.value = false
  }
}

async function sendNew() {
  if (!/^1\d{10}$/.test(change.newPhone.trim())) {
    ElMessage.warning('请填写 11 位新手机号')
    return
  }
  loading.value = true
  try {
    const result = await sendPhoneCodeApi('change_new', change.newPhone.trim())
    startWait('next')
    noteCode(result.dev_code)
  } catch (error: unknown) {
    noteSendError(error, 'next')
  } finally {
    loading.value = false
  }
}

async function submitChange() {
  if (!/^\d{4}$/.test(change.oldCode.trim()) || !/^1\d{10}$/.test(change.newPhone.trim()) || !/^\d{4}$/.test(change.newCode.trim())) {
    ElMessage.warning('请填写旧验证码、新手机号和新验证码')
    return
  }
  loading.value = true
  try {
    await changePhoneApi(change.oldCode.trim(), change.newPhone.trim(), change.newCode.trim())
    await auth.refreshSession()
    ElMessage.success('手机号已更换')
    change.oldCode = ''
    change.newPhone = ''
    change.newCode = ''
    editor.value = null
  } catch (error: unknown) {
    notifyOperationError(error, '更换失败')
  } finally {
    loading.value = false
  }
}

function goChangePassword() {
  void router.push('/change-password')
}

async function backToPortal() {
  await router.replace(auth.portalPath)
}
</script>

<template>
  <main class="acct-page">
    <div class="acct-wrap">
      <button type="button" class="acct-back" @click="backToPortal">
        <ArrowLeft />
        返回
      </button>
      <h1>账号与安全</h1>

      <section class="acct-card acct-hero">
        <div>
          <p class="acct-kicker">当前身份</p>
          <h2>{{ auth.session?.identity ? identityTitle(auth.session.identity) : '未选择身份' }}</h2>
          <p class="acct-hero-sub">
            {{ auth.session?.identity ? identityKind(auth.session.identity) : '' }}
            <template v-if="auth.session?.identity?.tenant_name"> · {{ auth.session.identity.tenant_name }}</template>
          </p>
        </div>
      </section>

      <section class="acct-card">
        <header class="acct-card-head">我的账号</header>
        <div class="acct-profile">
          <span class="acct-avatar" aria-hidden="true">{{ initial }}</span>
          <div>
            <p class="acct-login">登录名 <b>{{ user?.username || '—' }}</b></p>
            <p class="acct-id">
              账号 ID {{ user?.id || '—' }}
              <button type="button" class="acct-icon" aria-label="复制账号 ID" @click="copyId">
                <Copy />
              </button>
            </p>
          </div>
        </div>

        <div class="acct-grid">
          <div class="acct-cell">
            <span>登录密码</span>
            <strong class="is-ok">已设置</strong>
            <button type="button" class="acct-icon" aria-label="修改密码" @click="goChangePassword">
              <Pencil />
            </button>
          </div>
          <div class="acct-cell">
            <span>安全手机号</span>
            <strong :class="phoneBound ? '' : 'is-muted'">{{ user?.phone_masked || (canBind ? '未设置' : '不可用') }}</strong>
            <button v-if="canBind" type="button" class="acct-icon" aria-label="设置手机号" @click="openPhoneEditor">
              <Pencil />
            </button>
          </div>
          <div class="acct-cell">
            <span>手机号登录</span>
            <strong :class="phoneLoginOn ? 'is-ok' : 'is-muted'">{{ phoneLoginLabel }}</strong>
            <button
              type="button"
              class="acct-switch"
              :class="{ 'is-on': phoneLoginOn }"
              role="switch"
              :aria-checked="phoneLoginOn"
              aria-label="手机号登录"
              :disabled="!canBind || !phoneBound || loading"
              :title="phoneBound ? '控制能否用该手机号收验证码登录' : '请先设置安全手机号'"
              @click="togglePhoneLogin"
            />
          </div>
          <div class="acct-cell">
            <span>显示名称</span>
            <strong>{{ user?.display_name || '—' }}</strong>
          </div>
          <div class="acct-cell">
            <span>注册时间</span>
            <strong>{{ user?.created_at || '—' }}</strong>
          </div>
        </div>

        <p v-if="!canBind" class="acct-note">观察号不绑定个人手机, 请继续使用账号密码登录.</p>

        <ElDialog
          :model-value="editor !== null"
          :title="phoneDialogTitle"
          width="480px"
          align-center
          append-to-body
          @close="editor = null"
        >
        <form v-if="editor === 'bind'" class="acct-editor" @submit.prevent="submitBind">
          <label>
            手机号
            <input v-model="bind.phone" inputmode="numeric" maxlength="11" placeholder="11 位手机号" />
          </label>
          <label>
            验证码
            <span class="acct-code">
              <input v-model="bind.code" inputmode="numeric" maxlength="4" placeholder="4 位验证码" />
              <button type="button" :disabled="loading || waits.bind > 0" @click="sendBind">
                {{ waits.bind > 0 ? `${waits.bind}s` : '获取验证码' }}
              </button>
            </span>
          </label>
          <div class="acct-editor-actions">
            <button type="submit" class="is-primary" :disabled="loading">绑定</button>
            <button type="button" @click="editor = null">取消</button>
          </div>
        </form>

        <form v-else-if="editor === 'change'" class="acct-editor" @submit.prevent="submitChange">
          <p>当前 {{ user?.phone_masked }}. 旧手机和新手机各收一条验证码. 旧手机丢了, 请联系管理员解绑.</p>
          <label>
            当前手机验证码
            <span class="acct-code">
              <input v-model="change.oldCode" inputmode="numeric" maxlength="4" placeholder="4 位验证码" />
              <button type="button" :disabled="loading || waits.old > 0" @click="sendOld">
                {{ waits.old > 0 ? `${waits.old}s` : '获取验证码' }}
              </button>
            </span>
          </label>
          <label>
            新手机号
            <input v-model="change.newPhone" inputmode="numeric" maxlength="11" placeholder="11 位手机号" />
          </label>
          <label>
            新手机验证码
            <span class="acct-code">
              <input v-model="change.newCode" inputmode="numeric" maxlength="4" placeholder="4 位验证码" />
              <button type="button" :disabled="loading || waits.next > 0" @click="sendNew">
                {{ waits.next > 0 ? `${waits.next}s` : '获取验证码' }}
              </button>
            </span>
          </label>
          <div class="acct-editor-actions">
            <button type="submit" class="is-primary" :disabled="loading">更换</button>
            <button type="button" @click="editor = null">取消</button>
          </div>
        </form>
        </ElDialog>
      </section>

      <section class="acct-card">
        <header class="acct-card-head">登录身份</header>
        <div v-if="!identities.length" class="acct-note">暂无可用身份</div>
        <ul v-else class="acct-identities">
          <li v-for="identity in identities" :key="identity.id" :class="{ 'is-current': identity.id === currentIdentityId }">
            <b>{{ identityTitle(identity) }}</b>
            <span>{{ identityKind(identity) }}</span>
            <span v-if="identity.tenant_name">{{ identity.tenant_name }}</span>
            <em v-if="identity.id === currentIdentityId">当前</em>
          </li>
        </ul>
      </section>
    </div>
  </main>
</template>

<style scoped>
.acct-page {
  min-height: 100vh;
  background: #f3f7fc;
  color: #1e3348;
}
.acct-wrap {
  width: min(1080px, calc(100% - 48px));
  margin: 0 auto;
  padding: 28px 0 64px;
}
.acct-back {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin: 0 0 14px;
  padding: 0;
  border: 0;
  background: transparent;
  color: #5d7590;
  font-size: 13px;
}
.acct-back svg { width: 16px; height: 16px; }
.acct-wrap h1 {
  margin: 0 0 16px;
  font-size: 22px;
  font-weight: 650;
}
.acct-card {
  margin-top: 14px;
  padding: 8px 22px 18px;
  border: 1px solid #dce6f1;
  border-radius: 8px;
  background: #fff;
}
.acct-hero {
  display: flex;
  align-items: center;
  min-height: 108px;
  padding: 22px 24px;
  background: linear-gradient(90deg, #f7fbff 0%, #fff 70%);
}
.acct-kicker {
  margin: 0 0 6px;
  color: #7d93aa;
  font-size: 13px;
}
.acct-hero h2 {
  margin: 0;
  font-size: 20px;
  font-weight: 650;
}
.acct-hero-sub {
  margin: 6px 0 0;
  color: #6d839b;
  font-size: 13px;
}
.acct-card-head {
  padding: 14px 0;
  border-bottom: 1px solid #e7eef6;
  font-size: 15px;
  font-weight: 650;
}
.acct-profile {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 18px 0 8px;
}
.acct-avatar {
  display: grid;
  place-items: center;
  width: 52px;
  height: 52px;
  border-radius: 50%;
  background: #e7f0fb;
  color: #2f6fce;
  font-size: 20px;
  font-weight: 650;
}
.acct-login, .acct-id { margin: 0; color: #5d7590; font-size: 13px; }
.acct-login b { color: #1e3348; font-size: 15px; }
.acct-id { display: flex; align-items: center; gap: 6px; margin-top: 4px; }
.acct-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px 18px;
  padding: 8px 0 4px;
}
.acct-cell {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 56px;
  padding: 8px 0;
}
.acct-cell span { color: #7d93aa; font-size: 13px; }
.acct-cell strong { font-size: 14px; font-weight: 600; }
.acct-cell strong.is-ok { color: #168a69; }
.acct-cell strong.is-muted { color: #8aa0b8; font-weight: 500; }
.acct-icon {
  display: inline-flex;
  padding: 0;
  border: 0;
  background: transparent;
  color: #7d93aa;
}
.acct-icon svg { width: 14px; height: 14px; }
.acct-icon:hover { color: #2f6fce; }
.acct-switch {
  position: relative;
  width: 36px;
  height: 20px;
  padding: 0;
  border: 0;
  border-radius: 999px;
  background: #c5d2e0;
}
.acct-switch::after {
  content: "";
  position: absolute;
  top: 2px;
  left: 2px;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: #fff;
}
.acct-switch.is-on { background: #168a69; }
.acct-switch.is-on::after { transform: translateX(16px); }
.acct-switch:disabled { opacity: 0.45; cursor: not-allowed; }
.acct-note { margin: 8px 0 0; color: #7d93aa; font-size: 13px; }
.acct-editor {
  margin: 0;
  padding: 0;
  border: 0;
  background: transparent;
}
.acct-editor p { margin: 0 0 12px; color: #6d839b; font-size: 13px; }
.acct-editor label {
  display: block;
  margin-top: 10px;
  color: #5d7590;
  font-size: 13px;
}
.acct-editor input {
  display: block;
  width: min(360px, 100%);
  height: 36px;
  margin-top: 6px;
  padding: 0 10px;
  border: 1px solid #d4dfec;
  border-radius: 6px;
  background: #fff;
}
.acct-code { display: flex; gap: 8px; align-items: center; }
.acct-code input { flex: 1; }
.acct-code button, .acct-editor-actions button {
  height: 36px;
  padding: 0 12px;
  border: 1px solid #d4dfec;
  border-radius: 6px;
  background: #fff;
  color: #2f6fce;
}
.acct-editor-actions { display: flex; gap: 8px; margin-top: 14px; }
.acct-editor-actions .is-primary {
  border-color: #2f6fce;
  background: #2f6fce;
  color: #fff;
}
.acct-identities { margin: 0; padding: 0; list-style: none; }
.acct-identities li {
  display: flex;
  align-items: center;
  gap: 16px;
  min-height: 44px;
  font-size: 14px;
}
.acct-identities li + li { border-top: 1px solid #eef3f8; }
.acct-identities span { color: #6d839b; }
.acct-identities em {
  margin-left: auto;
  color: #2f6fce;
  font-style: normal;
  font-size: 12px;
}
@media (max-width: 800px) {
  .acct-wrap { width: min(100% - 28px, 1080px); }
  .acct-grid { grid-template-columns: 1fr 1fr; }
  .acct-identities li { flex-wrap: wrap; gap: 4px 12px; padding: 10px 0; }
  .acct-identities em { margin-left: 0; }
}
</style>
