<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useAuthStore } from '../../../stores/auth'
import { readCsrfToken } from '../../../utils/csrf'
import {
  KEYWORD_MINER_EXAMPLES_MENU,
  KEYWORD_MINER_MENU,
  KEYWORD_MINER_WORKBENCH_MENU,
} from '../constants'
import KeywordMinerExamplesPage from './KeywordMinerExamplesPage.vue'

const props = withDefaults(defineProps<{
  active?: boolean
  activeTab?: 'workbench' | 'examples'
}>(), {
  active: true,
  activeTab: 'workbench',
})

const emit = defineEmits<{
  switchTab: [tab: 'workbench' | 'examples']
}>()

const auth = useAuthStore()
const iframeRef = ref<HTMLIFrameElement | null>(null)

const minerOrigin = computed(() => {
  const raw = String(import.meta.env.VITE_KEYWORD_MINER_ORIGIN || '').trim()
  if (raw) return raw.replace(/\/$/, '')
  if (typeof window !== 'undefined' && window.location?.origin) {
    return `${window.location.origin}/keyword-miner`
  }
  return '/keyword-miner'
})

const iframeSrc = computed(() => `${minerOrigin.value}/?embed=1`)
const healthUrl = computed(() => `${minerOrigin.value}/api/health`)

function menuOf(code: string) {
  return auth.allowedMenus.find(item => item.menu_code === code)
}

const canWorkbench = computed(() => {
  const parent = menuOf(KEYWORD_MINER_MENU)
  const wb = menuOf(KEYWORD_MINER_WORKBENCH_MENU)
  return Boolean(
    parent?.can_export || parent?.can_update || parent?.can_create
    || wb?.can_export || wb?.can_update || wb?.can_create,
  )
})

const canExamples = computed(() => {
  const ex = menuOf(KEYWORD_MINER_EXAMPLES_MENU)
  const parent = menuOf(KEYWORD_MINER_MENU)
  return Boolean(
    ex?.can_export || ex?.can_update || ex?.can_create
    || parent?.can_export || parent?.can_update || parent?.can_create,
  )
})

const canOpen = computed(() => canWorkbench.value || canExamples.value)

const tab = computed(() => {
  if (props.activeTab === 'examples' && canExamples.value) return 'examples'
  if (canWorkbench.value) return 'workbench'
  return canExamples.value ? 'examples' : 'workbench'
})

const offline = ref(false)

function postBootstrap() {
  const win = iframeRef.value?.contentWindow
  if (!win) return
  // 同源 iframe (经 /keyword-miner 反代); 禁止 fallback '*'
  const target = window.location.origin
  win.postMessage(
    {
      type: 'geo-km-bootstrap',
      apiBase: `${window.location.origin}/api/v1`,
      csrf: readCsrfToken() || '',
    },
    target,
  )
}

async function checkHealth() {
  try {
    const res = await fetch(healthUrl.value, { method: 'GET', cache: 'no-store' })
    offline.value = !(res.ok && (await res.json() as { status?: string }).status === 'ok')
  } catch {
    offline.value = true
  }
}

onMounted(() => {
  void checkHealth()
})

watch(
  () => props.active,
  (active) => {
    if (active && tab.value === 'workbench') postBootstrap()
  },
)

watch(tab, (value) => {
  if (value === 'workbench' && props.active) {
    void checkHealth()
    postBootstrap()
  }
})

onUnmounted(() => {
  iframeRef.value = null
})
</script>

<template>
  <div class="km-page" :class="{ 'is-active': active, 'is-examples': tab === 'examples' }">
    <div v-if="!canOpen" class="km-empty">当前账号没有 GEO选词 权限。</div>
    <template v-else>
      <div class="km-tabs" role="tablist" aria-label="GEO选词分区">
        <button
          v-if="canWorkbench"
          type="button"
          class="km-tab"
          :class="{ active: tab === 'workbench' }"
          role="tab"
          :aria-selected="tab === 'workbench'"
          @click="emit('switchTab', 'workbench')"
        >
          选词台
        </button>
        <button
          v-if="canExamples"
          type="button"
          class="km-tab"
          :class="{ active: tab === 'examples' }"
          role="tab"
          :aria-selected="tab === 'examples'"
          @click="emit('switchTab', 'examples')"
        >
          范例库
        </button>
      </div>

      <template v-if="tab === 'workbench'">
        <div v-if="offline" class="km-warn" role="status">
          选词服务未启动（{{ minerOrigin }}）。本地请在 services/keyword-miner 执行：
          backend\.venv\Scripts\python.exe app.py
        </div>
        <iframe
          ref="iframeRef"
          class="km-frame"
          title="GEO 选词台"
          :src="iframeSrc"
          @load="postBootstrap"
        />
      </template>
      <KeywordMinerExamplesPage v-else />
    </template>
  </div>
</template>

<style>
html:has(.km-page.is-active:not(.is-examples)),
body:has(.km-page.is-active:not(.is-examples)) {
  overflow: hidden;
  height: 100%;
}

.portal-content-immersive:has(.km-page.is-active:not(.is-examples)) {
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

.km-page.is-examples {
  overflow: auto;
}

.km-tabs {
  display: flex;
  gap: 4px;
  padding: 8px 12px 0;
  border-bottom: 1px solid #e8edf5;
  background: #f8fafc;
  flex-shrink: 0;
}

.km-tab {
  border: 0;
  background: transparent;
  color: #6b7280;
  font-size: 13.5px;
  font-weight: 600;
  padding: 8px 12px 10px;
  cursor: pointer;
  border-bottom: 2px solid transparent;
}

.km-tab.active {
  color: #185fa5;
  border-bottom-color: #185fa5;
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
