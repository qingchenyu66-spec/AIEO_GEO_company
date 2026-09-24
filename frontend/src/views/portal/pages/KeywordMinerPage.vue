<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useAuthStore } from '../../../stores/auth'
import { readCsrfToken } from '../../../utils/csrf'

const props = withDefaults(defineProps<{ active?: boolean }>(), { active: true })

const auth = useAuthStore()
const iframeRef = ref<HTMLIFrameElement | null>(null)

const minerOrigin = computed(() => {
  const raw = String(import.meta.env.VITE_KEYWORD_MINER_ORIGIN || '').trim()
  if (raw) return raw.replace(/\/$/, '')
  // 同域 /keyword-miner/：生产 nginx，本地 vite proxy，Cookie/CSRF 可直达 GEO API
  if (typeof window !== 'undefined' && window.location?.origin) {
    return `${window.location.origin}/keyword-miner`
  }
  return '/keyword-miner'
})

const iframeSrc = computed(() => `${minerOrigin.value}/?embed=1`)
const healthUrl = computed(() => `${minerOrigin.value}/api/health`)

const canOpen = computed(() => {
  const menu = auth.allowedMenus.find(item => item.menu_code === 'platform.keyword_miner')
  return Boolean(menu?.can_export || menu?.can_update || menu?.can_create)
})

const offline = ref(false)

function postBootstrap() {
  const win = iframeRef.value?.contentWindow
  if (!win) return
  const origin = minerOrigin.value
  let target = '*'
  try {
    target = new URL(origin, window.location.origin).origin
  } catch {
    target = '*'
  }
  win.postMessage(
    {
      type: 'geo-km-bootstrap',
      apiBase: `${window.location.origin}/api/v1`,
      csrf: readCsrfToken() || '',
    },
    target,
  )
}

onMounted(async () => {
  try {
    const res = await fetch(healthUrl.value, { method: 'GET', cache: 'no-store' })
    offline.value = !(res.ok && (await res.json() as { status?: string }).status === 'ok')
  } catch {
    offline.value = true
  }
})

watch(
  () => props.active,
  (active) => {
    if (active) postBootstrap()
  },
)

onUnmounted(() => {
  iframeRef.value = null
})
</script>

<template>
  <div class="km-page" :class="{ 'is-active': active }">
    <div v-if="!canOpen" class="km-empty">当前账号没有 GEO选词 权限。</div>
    <template v-else>
      <div v-if="offline" class="km-warn" role="status">
        选词服务未启动（{{ minerOrigin }}）
      </div>
      <iframe
        ref="iframeRef"
        class="km-frame"
        title="GEO 选词"
        :src="iframeSrc"
        @load="postBootstrap"
      />
    </template>
  </div>
</template>

<style>
html:has(.km-page.is-active),
body:has(.km-page.is-active) {
  overflow: hidden;
  height: 100%;
}

.portal-content-immersive:has(.km-page.is-active) {
  height: calc(100dvh - var(--portal-topbar-height, 74px));
  max-height: calc(100dvh - var(--portal-topbar-height, 74px));
  min-height: 0 !important;
  overflow: hidden;
}
</style>

<style scoped>
.km-page {
  display: none;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  overflow: hidden;
  background: #fff;
}

.km-page.is-active {
  display: flex;
}

.km-empty {
  flex: 1;
  display: grid;
  place-items: center;
  color: #6b7280;
  font-size: 14px;
}

.km-warn {
  flex-shrink: 0;
  padding: 8px 14px;
  background: #fff5f5;
  border-bottom: 1px solid #ffc9c9;
  color: #c92a2a;
  font-size: 12.5px;
}

.km-frame {
  flex: 1;
  width: 100%;
  min-height: 0;
  border: 0;
  display: block;
  background: #fff;
}
</style>
