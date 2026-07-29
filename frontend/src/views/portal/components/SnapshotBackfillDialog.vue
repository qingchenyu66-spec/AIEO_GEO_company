<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import type { MonitorSubtask } from '../../../services/monitor'
import { submitSnapshotBackfill } from '../../../services/snapshotBackfill'
import { notifyOperationError } from '../../../utils/requestError'
import { isProxiedScreenshotUrl } from '../../../utils/safeUrl'
import { platformLabelMap } from '../portalMaps'
import { parseSnapshotBackfillMentionPosition } from '../snapshotBackfillDisplay'

const props = defineProps<{
  visible: boolean
  subtask: MonitorSubtask | null
}>()

const emit = defineEmits<{
  'update:visible': [value: boolean]
  success: [subtask: MonitorSubtask]
}>()

const submitting = ref(false)
const form = reactive({
  snapshot_url: '',
  mention_position: '' as string | number,
})

const dialogVisible = computed({
  get: () => props.visible,
  set: (value: boolean) => emit('update:visible', value),
})

const headline = computed(() => {
  if (!props.subtask) return '快照补录'
  const label = platformLabelMap[props.subtask.platform] || props.subtask.platform
  return `快照补录 · ${label}`
})

const hasExistingAnswer = computed(() => Boolean(props.subtask?.answer_content))
const parsedRank = computed(() => parseSnapshotBackfillMentionPosition(form.mention_position))
const hasShareUrl = computed(() => Boolean(form.snapshot_url.trim()))
const canSubmit = computed(() => hasShareUrl.value || parsedRank.value != null)

watch(
  () => props.visible,
  (open) => {
    if (!open) return
    const shot = props.subtask?.page_screenshot || ''
    // 已有正文时链接默认留空，便于只改排名；失败补录才预填非代理分享链接
    if (props.subtask?.answer_content) {
      form.snapshot_url = ''
    } else {
      form.snapshot_url = isProxiedScreenshotUrl(shot) ? '' : shot
    }
    // 2026-07-29 - 预填旧名次导致粘贴链接仍锁定 manual_rank、位次看似未变 - 打开时不预填，有链接留空走自动解析
    form.mention_position = ''
  },
)

async function handleSubmit() {
  if (!props.subtask?.subtask_id || !canSubmit.value) return
  submitting.value = true
  try {
    const url = form.snapshot_url.trim()
    const result = await submitSnapshotBackfill(props.subtask.subtask_id, {
      snapshot_url: url || null,
      mention_position: parsedRank.value,
    })
    emit('success', result.subtask)
    dialogVisible.value = false
  } catch (error: unknown) {
    notifyOperationError(error, '快照补录失败')
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <el-dialog
    v-model="dialogVisible"
    :title="headline"
    width="640px"
    class="snapshot-backfill-dialog"
    destroy-on-close
  >
    <p v-if="subtask" class="snapshot-backfill-intro">
      可粘贴分享链接解析并<strong>覆盖</strong>正文与信源；不填链接时仅改排名，快照沿用原值。有链接时排名可选手填，留空则按正文自动解析。
    </p>
    <p v-if="hasExistingAnswer && hasShareUrl" class="snapshot-backfill-warn">当前子任务已有抓取内容，填写链接提交后将用本次解析结果完全替换。</p>
    <p v-if="subtask" class="snapshot-backfill-prompt">监测问题：{{ subtask.prompt }}</p>

    <form class="form-grid password-grid snapshot-backfill-form" @submit.prevent="handleSubmit">
      <label class="form-field-full">
        <span>分享链接（可选）</span>
        <input
          v-model="form.snapshot_url"
          type="url"
          placeholder="https://www.doubao.com/thread/... 或其它平台分享页链接"
        >
      </label>
      <label>
        <span>{{ hasShareUrl ? '品牌排名（可选，清空则自动解析）' : '品牌排名（不填链接时必填）' }}</span>
        <input v-model="form.mention_position" type="number" min="1" max="100" placeholder="例如 3">
      </label>
    </form>

    <template #footer>
      <button type="button" class="plain-btn" @click="dialogVisible = false">取消</button>
      <button
        type="button"
        class="primary-btn"
        :disabled="submitting || !canSubmit"
        @click="handleSubmit"
      >
        {{ submitting ? '提交中…' : hasShareUrl && hasExistingAnswer ? '提交并覆盖' : '提交补录' }}
      </button>
    </template>
  </el-dialog>
</template>

<style scoped>
.snapshot-backfill-intro {
  margin: 0 0 10px;
  color: #475569;
  line-height: 1.5;
  font-size: 13px;
}
.snapshot-backfill-prompt {
  margin: 0 0 12px;
  padding: 8px 10px;
  border-radius: 8px;
  background: #f8fafc;
  color: #334155;
  font-size: 13px;
}
.snapshot-backfill-warn {
  margin: 0 0 10px;
  color: #b45309;
  font-size: 13px;
}
.snapshot-backfill-form {
  margin-top: 8px;
}
.snapshot-backfill-form textarea {
  min-height: 180px;
}
.required-mark {
  color: #dc2626;
  font-style: normal;
}
</style>
