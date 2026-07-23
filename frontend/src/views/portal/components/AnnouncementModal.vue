<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ackAnnouncement, getPendingAnnouncement, type AnnouncementPending } from '../../../services/announcements'
import { hydrateAnnouncementHtml } from '../../../services/announcementHtml'

const visible = ref(false)
const loading = ref(false)
const acking = ref(false)
const current = ref<AnnouncementPending | null>(null)
const bodyHtml = ref('')

const titleText = computed(() => current.value?.title || '系统公告')

async function renderBody(html: string) {
  bodyHtml.value = await hydrateAnnouncementHtml(html || '')
}

async function loadNext() {
  loading.value = true
  try {
    const item = await getPendingAnnouncement()
    current.value = item
    visible.value = Boolean(item)
    if (item) await renderBody(item.body_html)
    else bodyHtml.value = ''
  } catch {
    current.value = null
    visible.value = false
    bodyHtml.value = ''
  } finally {
    loading.value = false
  }
}

async function confirmAck() {
  if (!current.value || acking.value) return
  acking.value = true
  try {
    const result = await ackAnnouncement(current.value.id)
    if (result.next) {
      current.value = result.next
      visible.value = true
      await renderBody(result.next.body_html)
    } else {
      current.value = null
      visible.value = false
      bodyHtml.value = ''
    }
  } catch {
    /* keep dialog open */
  } finally {
    acking.value = false
  }
}

watch(visible, (open) => {
  if (!open) bodyHtml.value = ''
})

onMounted(() => {
  void loadNext()
})

defineExpose({ reload: loadNext })
</script>

<template>
  <el-dialog
    v-model="visible"
    width="680px"
    :close-on-click-modal="false"
    :close-on-press-escape="false"
    :show-close="false"
    append-to-body
    align-center
    class="announcement-modal-dialog"
  >
    <template #header>
      <div class="announcement-modal-head">
        <span class="announcement-modal-badge">系统公告</span>
        <h3>{{ titleText }}</h3>
      </div>
    </template>

    <div v-if="loading" class="announcement-modal-loading">加载公告中…</div>
    <div v-else-if="current" class="announcement-modal-body" v-html="bodyHtml" />

    <template #footer>
      <div class="announcement-modal-footer">
        <p class="announcement-modal-tip">确认后，当前账号将不再弹出本条公告</p>
        <button type="button" class="announcement-modal-btn" :disabled="acking || !current" @click="confirmAck">
          {{ acking ? '提交中…' : '确认，不再提示' }}
        </button>
      </div>
    </template>
  </el-dialog>
</template>

<style scoped>
.announcement-modal-head {
  display: grid;
  gap: 8px;
  padding-right: 8px;
}
.announcement-modal-badge {
  display: inline-flex;
  width: fit-content;
  padding: 2px 8px;
  border-radius: 999px;
  background: #eff6ff;
  color: #1d4ed8;
  font-size: 12px;
  font-weight: 600;
}
.announcement-modal-head h3 {
  margin: 0;
  font-size: 20px;
  line-height: 1.35;
  color: #0f172a;
  font-weight: 700;
}
.announcement-modal-loading {
  color: #64748b;
  padding: 24px 0;
  text-align: center;
}
.announcement-modal-body {
  line-height: 1.75;
  color: #1e293b;
  max-height: min(58vh, 520px);
  overflow: auto;
  padding: 4px 2px 8px;
  font-size: 14px;
}
.announcement-modal-body :deep(p) {
  margin: 0 0 10px;
}
.announcement-modal-body :deep(img) {
  max-width: 100%;
  height: auto;
  border-radius: 10px;
  margin: 10px 0;
  display: block;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.06);
}
.announcement-modal-body :deep(a) {
  color: #2563eb;
  word-break: break-all;
}
.announcement-modal-body :deep(ul),
.announcement-modal-body :deep(ol) {
  margin: 0 0 10px;
  padding-left: 1.25rem;
}
.announcement-modal-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  width: 100%;
}
.announcement-modal-tip {
  margin: 0;
  color: #94a3b8;
  font-size: 12px;
}
.announcement-modal-btn {
  border: 0;
  border-radius: 10px;
  padding: 10px 18px;
  color: #fff;
  font-weight: 600;
  cursor: pointer;
  background: linear-gradient(90deg, #2563eb, #0ea5e9);
  box-shadow: 0 8px 18px rgba(37, 99, 235, 0.25);
}
.announcement-modal-btn:disabled {
  opacity: 0.65;
  cursor: not-allowed;
  box-shadow: none;
}
</style>

<style>
.announcement-modal-dialog.el-dialog {
  border-radius: 16px;
  overflow: hidden;
  box-shadow: 0 24px 64px rgba(15, 23, 42, 0.28);
}
.announcement-modal-dialog .el-dialog__header {
  margin: 0;
  padding: 18px 22px 8px;
  border-bottom: 1px solid #eef2f7;
}
.announcement-modal-dialog .el-dialog__body {
  padding: 12px 22px 8px;
}
.announcement-modal-dialog .el-dialog__footer {
  padding: 12px 22px 18px;
  border-top: 1px solid #eef2f7;
}
</style>
