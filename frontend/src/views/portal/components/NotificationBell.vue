<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { Bell, CheckCheck } from '@lucide/vue'
import {
  getNotifications,
  getUnreadNotificationCount,
  markAllNotificationsRead,
  markNotificationRead,
  type SystemNotification,
} from '../../../services/notifications'
import { extractErrorDetail } from '../../../utils/requestError'

const emit = defineEmits<{
  openAlerts: []
}>()

const open = ref(false)
const loading = ref(false)
const unreadCount = ref(0)
const items = ref<SystemNotification[]>([])
const errorText = ref('')
let timer: number | undefined

const badgeText = computed(() => {
  if (unreadCount.value <= 0) return ''
  return unreadCount.value > 99 ? '99+' : String(unreadCount.value)
})

function levelClass(level: string) {
  if (level === 'critical') return 'is-critical'
  if (level === 'warning') return 'is-warning'
  return 'is-info'
}

function formatTime(raw: string) {
  const date = new Date(raw)
  if (Number.isNaN(date.getTime())) return raw
  return date.toLocaleString('zh-CN', { hour12: false })
}

async function refreshSummary() {
  try {
    unreadCount.value = await getUnreadNotificationCount()
  } catch {
    /* ignore polling errors */
  }
}

async function loadPanel() {
  loading.value = true
  errorText.value = ''
  try {
    const [rows, count] = await Promise.all([
      getNotifications({ limit: 20 }),
      getUnreadNotificationCount(),
    ])
    items.value = rows
    unreadCount.value = count
  } catch (error: unknown) {
    errorText.value = extractErrorDetail(error)
  } finally {
    loading.value = false
  }
}

async function onOpenChange(visible: boolean) {
  open.value = visible
  if (visible) {
    await loadPanel()
  }
}

async function handleRead(item: SystemNotification) {
  if (!item.is_read) {
    await markNotificationRead(item.id)
    item.is_read = true
    unreadCount.value = Math.max(0, unreadCount.value - 1)
  }
  if (item.category === 'celery_queue') {
    emit('openAlerts')
    open.value = false
  }
}

async function handleReadAll() {
  await markAllNotificationsRead()
  items.value = items.value.map(item => ({ ...item, is_read: true }))
  unreadCount.value = 0
}

onMounted(() => {
  void refreshSummary()
  timer = window.setInterval(() => void refreshSummary(), 60000)
})

onUnmounted(() => {
  if (timer) window.clearInterval(timer)
})
</script>

<template>
  <el-dropdown trigger="click" @visible-change="onOpenChange">
    <button type="button" class="icon-action notification-bell" title="系统通知" aria-label="系统通知">
      <Bell />
      <span v-if="badgeText" class="notification-badge">{{ badgeText }}</span>
    </button>
    <template #dropdown>
      <div class="notification-panel">
        <div class="notification-panel-head">
          <strong>系统通知</strong>
          <button type="button" class="notification-read-all" :disabled="!unreadCount" @click.stop="handleReadAll">
            <CheckCheck /> 全部已读
          </button>
        </div>
        <div v-if="errorText" class="ops-error compact">{{ errorText }}</div>
        <div v-else-if="loading" class="notification-empty">加载中…</div>
        <div v-else-if="!items.length" class="notification-empty">暂无通知</div>
        <ul v-else class="notification-list">
          <li
            v-for="item in items"
            :key="item.id"
            class="notification-item"
            :class="[levelClass(item.level), { unread: !item.is_read }]"
            @click="handleRead(item)"
          >
            <div class="notification-item-head">
              <b>{{ item.title }}</b>
              <time>{{ formatTime(item.created_at) }}</time>
            </div>
            <p>{{ item.message }}</p>
          </li>
        </ul>
      </div>
    </template>
  </el-dropdown>
</template>
