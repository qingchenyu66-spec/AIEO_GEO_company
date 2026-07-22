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
  answer_content: '',
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

watch(
  () => props.visible,
  (open) => {
    if (!open) return
    const shot = props.subtask?.page_screenshot || ''
    // 代理 URL 不能当作模力分享链接回填
    form.snapshot_url = isProxiedScreenshotUrl(shot) ? '' : shot
    form.answer_content = props.subtask?.answer_content || ''
    form.mention_position = props.subtask?.mention_position != null ? String(props.subtask.mention_position) : ''
  },
)

async function handleSubmit() {
  if (!props.subtask?.subtask_id) return
  submitting.value = true
  try {
    const result = await submitSnapshotBackfill(props.subtask.subtask_id, {
      snapshot_url: form.snapshot_url.trim(),
      answer_content: form.answer_content.trim(),
      mention_position: parseSnapshotBackfillMentionPosition(form.mention_position),
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
      请粘贴该平台会话分享链接，并填写 AI 回答正文。提交后将<strong>覆盖</strong>该条原有抓取结果，并重新参与排名与健康分计算。
    </p>
    <p v-if="hasExistingAnswer" class="snapshot-backfill-warn">当前子任务已有抓取内容，提交后将用本次补录完全替换。</p>
    <p v-if="subtask" class="snapshot-backfill-prompt">监测问题：{{ subtask.prompt }}</p>

    <form class="form-grid password-grid snapshot-backfill-form" @submit.prevent="handleSubmit">
      <label class="form-field-full">
        <span>分享链接 <em class="required-mark">*</em></span>
        <input
          v-model="form.snapshot_url"
          type="url"
          placeholder="https://www.doubao.com/thread/... 或 Kimi 分享页链接"
        >
      </label>
      <label class="form-field-full">
        <span>回答正文 <em class="required-mark">*</em></span>
        <textarea
          v-model="form.answer_content"
          rows="10"
          placeholder="从 AI 页面复制完整回答内容，粘贴到这里"
        />
      </label>
      <label>
        <span>品牌排名（可选，不填则自动解析）</span>
        <input v-model="form.mention_position" type="number" min="1" max="100" placeholder="例如 3">
      </label>
    </form>

    <template #footer>
      <button type="button" class="plain-btn" @click="dialogVisible = false">取消</button>
      <button
        type="button"
        class="primary-btn"
        :disabled="submitting || !form.snapshot_url.trim() || !form.answer_content.trim()"
        @click="handleSubmit"
      >
        {{ submitting ? '提交中…' : hasExistingAnswer ? '提交并覆盖' : '提交补录' }}
      </button>
    </template>
  </el-dialog>
</template>

<style scoped>
.snapshot-backfill-intro {
  margin: 0 0 8px;
  color: var(--portal-muted, #64748b);
  font-size: 13px;
  line-height: 1.6;
}
.snapshot-backfill-prompt {
  margin: 0 0 16px;
  padding: 10px 12px;
  border-radius: 10px;
  background: rgba(15, 23, 42, 0.04);
  font-size: 13px;
  line-height: 1.5;
  color: #153052;
}
.snapshot-backfill-warn {
  margin: 0 0 12px;
  padding: 8px 12px;
  border-radius: 8px;
  background: rgba(194, 65, 12, 0.08);
  color: #c2410c;
  font-size: 13px;
}
.snapshot-backfill-form {
  margin-top: 4px;
}
.snapshot-backfill-form textarea {
  width: 100%;
  min-height: 220px;
  padding: 12px;
  border: 1px solid #d8e3f0;
  border-radius: 10px;
  background: #fff;
  color: #153052;
  font-size: 14px;
  line-height: 1.6;
  resize: vertical;
  box-sizing: border-box;
}
.snapshot-backfill-form textarea:focus {
  outline: none;
  border-color: #4288e8;
  box-shadow: 0 0 0 3px rgba(66, 136, 232, 0.1);
}
.required-mark {
  color: #c2410c;
  font-style: normal;
}
</style>
