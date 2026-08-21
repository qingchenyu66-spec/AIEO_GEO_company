<script setup lang="ts">
import { computed, nextTick, reactive, ref, watch } from 'vue'
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
const urlInputRef = ref<HTMLInputElement | null>(null)
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

const hasExistingAnswer = computed(() => Boolean(props.subtask?.answer_content?.trim()))
// 2026-08-21 - 只改排名须已有模力正文或截图；图链不算分享页
const hasExistingSnapshot = computed(() => Boolean((props.subtask?.page_screenshot || '').trim()))
const hasMolResult = computed(() => hasExistingAnswer.value || hasExistingSnapshot.value)
const parsedRank = computed(() => parseSnapshotBackfillMentionPosition(form.mention_position))

/** 分享页链接（排除截图 CDN/代理图） */
function isSharePageUrl(raw: string): boolean {
  const url = raw.trim()
  return Boolean(url) && !isProxiedScreenshotUrl(url)
}

// 2026-08-21 - 粘贴后立刻点提交时 v-model 可能未跟上，提交以输入框 DOM 为准
function readShareUrlFromInput(): string {
  const fromDom = (urlInputRef.value?.value || '').trim()
  const fromForm = form.snapshot_url.trim()
  return fromDom || fromForm
}

const hasShareUrl = computed(() => isSharePageUrl(form.snapshot_url))
const canRankOnly = computed(() => hasMolResult.value && parsedRank.value != null)
const canSubmit = computed(() => hasShareUrl.value || canRankOnly.value || Boolean(form.snapshot_url.trim()))

watch(
  () => props.visible,
  (open) => {
    if (!open) return
    const shot = props.subtask?.page_screenshot || ''
    // 已有模力结果时链接留空便于只改排名；截图 CDN/代理图永不预填进分享链接
    if (hasMolResult.value || isProxiedScreenshotUrl(shot)) {
      form.snapshot_url = ''
    } else {
      form.snapshot_url = isSharePageUrl(shot) ? shot : ''
    }
    // 2026-07-29 - 预填旧名次导致粘贴链接仍锁定 manual_rank、位次看似未变 - 打开时不预填，有链接留空走自动解析
    form.mention_position = ''
  },
)

async function handleSubmit() {
  if (!props.subtask?.subtask_id || submitting.value) return
  await nextTick()
  const url = readShareUrlFromInput()
  if (url !== form.snapshot_url.trim()) {
    form.snapshot_url = url
  }
  const rank = parseSnapshotBackfillMentionPosition(form.mention_position)
  const sharePage = isSharePageUrl(url)
  // 截图 CDN 也传给后端（后端会当成已有快照走只改排名），勿在前端直接丢掉
  const payloadUrl = url || null

  if (!payloadUrl && !hasMolResult.value) {
    notifyOperationError(new Error('当前无可用快照，请粘贴分享链接补录'), '快照补录失败')
    return
  }
  if (!sharePage && rank == null) {
    notifyOperationError(new Error('未填写分享链接时，请填写品牌排名'), '快照补录失败')
    return
  }

  submitting.value = true
  try {
    const result = await submitSnapshotBackfill(props.subtask.subtask_id, {
      snapshot_url: payloadUrl,
      mention_position: rank,
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
        <!-- 2026-08-21 - 不用 type=url：粘贴后未失焦就提交时部分浏览器/v-model 不同步，请求丢了链接却报无快照 -->
        <input
          ref="urlInputRef"
          v-model="form.snapshot_url"
          type="text"
          inputmode="url"
          autocomplete="off"
          placeholder="https://www.doubao.com/thread/... 或其它平台分享页链接"
          @change="form.snapshot_url = ($event.target as HTMLInputElement).value"
        >
      </label>
      <label>
        <span>{{
          hasShareUrl
            ? '品牌排名（可选，清空则自动解析）'
            : hasMolResult
              ? '品牌排名（不填链接时必填）'
              : '品牌排名（须先有模力结果，或粘贴分享链接）'
        }}</span>
        <input v-model="form.mention_position" type="number" min="1" max="100" placeholder="例如 3">
      </label>
    </form>

    <template #footer>
      <button type="button" class="plain-btn" @click="dialogVisible = false">取消</button>
      <button
        type="button"
        class="primary-btn"
        :disabled="submitting"
        @click="handleSubmit"
      >
        {{
          submitting
            ? (hasShareUrl ? '正在解析分享页…' : '提交中…')
            : hasShareUrl && hasExistingAnswer ? '提交并覆盖' : '提交补录'
        }}
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
  color: #0f172a;
  font-weight: 600;
}
.snapshot-backfill-warn {
  margin: 0 0 10px;
  padding: 8px 10px;
  border-radius: 8px;
  background: #fff7ed;
  color: #9a3412;
  font-size: 12px;
  line-height: 1.45;
}
.snapshot-backfill-form {
  margin-top: 8px;
}
.snapshot-backfill-form textarea {
  min-height: 88px;
}
</style>
