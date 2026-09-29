<script setup lang="ts">
import { computed, nextTick, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import type { MonitorSubtask } from '../../../services/monitor'
import {
  listSnapshotBackfillHistoryCandidates,
  submitSnapshotBackfill,
  type SnapshotBackfillHistoryCandidate,
} from '../../../services/snapshotBackfill'
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
  /** 慢路径已入队：关窗后由页面后台轮询，勿窗内干等 */
  'parse-queued': [subtask: MonitorSubtask]
}>()

type BackfillMode = 'link' | 'history'

const submitting = ref(false)
const urlInputRef = ref<HTMLInputElement | null>(null)
const mode = ref<BackfillMode>('link')
const historyLoading = ref(false)
const historyItems = ref<SnapshotBackfillHistoryCandidate[]>([])
const selectedHistoryId = ref('')
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

async function loadHistoryCandidates() {
  if (!props.subtask?.subtask_id) return
  historyLoading.value = true
  try {
    historyItems.value = await listSnapshotBackfillHistoryCandidates(props.subtask.subtask_id)
    if (!historyItems.value.some(item => item.subtask_id === selectedHistoryId.value)) {
      selectedHistoryId.value = historyItems.value[0]?.subtask_id || ''
    }
  } catch (error: unknown) {
    historyItems.value = []
    selectedHistoryId.value = ''
    notifyOperationError(error, '加载历史场次失败')
  } finally {
    historyLoading.value = false
  }
}

watch(
  () => props.visible,
  async (open) => {
    if (!open) return
    mode.value = 'link'
    selectedHistoryId.value = ''
    historyItems.value = []
    const shot = props.subtask?.page_screenshot || ''
    // 已有模力结果时链接留空便于只改排名；截图 CDN/代理图永不预填进分享链接
    if (hasMolResult.value || isProxiedScreenshotUrl(shot)) {
      form.snapshot_url = ''
    } else {
      form.snapshot_url = isSharePageUrl(shot) ? shot : ''
    }
    // 2026-07-29 - 预填旧名次导致粘贴链接仍锁定 manual_rank、位次看似未变 - 打开时不预填，有链接留空走自动解析
    form.mention_position = ''
    // 2026-09-02 - A：解析中不窗内干等 - 仅提示可关窗等矩阵
    if (String(props.subtask?.backfill_parse_status || '').toLowerCase() === 'pending') {
      ElMessage.info('该条正在后台解析，可关闭窗口稍后看矩阵')
    }
  },
)

watch(mode, (next) => {
  if (next === 'history' && props.visible) {
    void loadHistoryCandidates()
  }
})

async function handleSubmit() {
  if (!props.subtask?.subtask_id || submitting.value) return

  if (mode.value === 'history') {
    if (!selectedHistoryId.value) {
      notifyOperationError(new Error('请选择一条历史成功场次'), '快照补录失败')
      return
    }
    submitting.value = true
    try {
      const rank = parseSnapshotBackfillMentionPosition(form.mention_position)
      const result = await submitSnapshotBackfill(props.subtask.subtask_id, {
        reuse_from_subtask_id: selectedHistoryId.value,
        mention_position: rank,
      })
      dialogVisible.value = false
      emit('success', result.subtask)
    } catch (error: unknown) {
      notifyOperationError(error, '快照补录失败')
    } finally {
      submitting.value = false
    }
    return
  }

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
    const subtask = result.subtask
    dialogVisible.value = false
    // 2026-09-02 - A：慢路径立刻关窗，页面后台轮询
    if (result.parse_async) {
      ElMessage.success('已提交后台解析，完成后矩阵会更新')
      emit('parse-queued', subtask)
      return
    }
    emit('success', subtask)
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
    <div class="snapshot-backfill-modes" role="tablist" aria-label="补录方式">
      <button
        type="button"
        class="snapshot-backfill-mode"
        :class="{ active: mode === 'link' }"
        @click="mode = 'link'"
      >
        分享链接
      </button>
      <button
        type="button"
        class="snapshot-backfill-mode"
        :class="{ active: mode === 'history' }"
        @click="mode = 'history'"
      >
        选用历史
      </button>
    </div>

    <p v-if="subtask" class="snapshot-backfill-prompt">监测问题：{{ subtask.prompt }}</p>

    <template v-if="mode === 'link'">
      <p class="snapshot-backfill-intro">
        可粘贴分享链接解析并<strong>覆盖</strong>正文与信源；不填链接时仅改排名，快照沿用原值。有链接时排名可选手填，留空则按正文自动解析。
      </p>
      <p v-if="hasExistingAnswer && hasShareUrl" class="snapshot-backfill-warn">当前子任务已有抓取内容，填写链接提交后将用本次解析结果完全替换。</p>

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
                : '品牌排名（须先有监测结果，或粘贴分享链接）'
          }}</span>
          <input v-model="form.mention_position" type="number" min="1" max="100" placeholder="例如 3">
        </label>
      </form>
    </template>

    <template v-else>
      <p v-if="historyLoading" class="snapshot-backfill-intro">加载历史场次…</p>
      <p v-else-if="!historyItems.length" class="snapshot-backfill-intro">暂无同词同平台的历史成功场次</p>
      <template v-else>
        <p class="snapshot-backfill-intro">
          同条件按监测完成时间取最早最多 30 条，当前 {{ historyItems.length }} 条
        </p>
        <div class="snapshot-history-list" role="listbox" aria-label="历史成功场次">
          <label
            v-for="item in historyItems"
            :key="item.subtask_id"
            class="snapshot-history-item"
            :class="{ active: selectedHistoryId === item.subtask_id }"
          >
            <input
              v-model="selectedHistoryId"
              type="radio"
              name="snapshot-history"
              :value="item.subtask_id"
            >
            <span class="snapshot-history-body">
              <strong>{{ item.remote_time_label || item.schedule_label || item.updated_at || item.subtask_id }}</strong>
              <em>
                排名 {{ item.mention_position ?? '—' }}
                · {{ item.sample_chars }} 字
                <template v-if="item.has_screenshot"> · 含截图</template>
              </em>
              <small v-if="item.answer_excerpt">{{ item.answer_excerpt }}</small>
            </span>
          </label>
        </div>
        <label class="snapshot-history-rank">
          <span>品牌排名（可选，留空用历史场次原排名）</span>
          <input v-model="form.mention_position" type="number" min="1" max="100" placeholder="例如 3">
        </label>
      </template>
    </template>

    <template #footer>
      <button type="button" class="plain-btn" @click="dialogVisible = false">取消</button>
      <button
        type="button"
        class="primary-btn"
        :disabled="submitting || (mode === 'history' && (!selectedHistoryId || historyLoading))"
        @click="handleSubmit"
      >
        {{
          submitting
            ? '提交中…'
            : mode === 'history'
              ? '选用并补录'
              : hasShareUrl && hasExistingAnswer ? '提交并覆盖' : '提交补录'
        }}
      </button>
    </template>
  </el-dialog>
</template>

<style scoped>
.snapshot-backfill-modes {
  display: flex;
  gap: 8px;
  margin: 0 0 12px;
}

.snapshot-backfill-mode {
  border: 1px solid #e2e8f0;
  background: #f8fafc;
  color: #475569;
  border-radius: 999px;
  padding: 6px 12px;
  font-size: 13px;
  cursor: pointer;
}

.snapshot-backfill-mode.active {
  background: #eff6ff;
  border-color: #93c5fd;
  color: #1d4ed8;
  font-weight: 600;
}

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
  font-size: 13px;
  line-height: 1.45;
}

.snapshot-history-list {
  display: grid;
  gap: 8px;
  max-height: min(52vh, 420px);
  overflow: auto;
  margin: 0 0 12px;
}

.snapshot-history-item {
  display: grid;
  grid-template-columns: 18px minmax(0, 1fr);
  gap: 8px;
  align-items: start;
  padding: 10px 12px;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  background: #fff;
  cursor: pointer;
}

.snapshot-history-item.active {
  border-color: #93c5fd;
  background: #f8fbff;
}

.snapshot-history-body {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.snapshot-history-body strong {
  color: #0f172a;
  font-size: 13px;
}

.snapshot-history-body em {
  font-style: normal;
  color: #64748b;
  font-size: 12px;
}

.snapshot-history-body small {
  color: #94a3b8;
  font-size: 12px;
  line-height: 1.4;
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.snapshot-history-rank {
  display: grid;
  gap: 6px;
  font-size: 13px;
  color: #334155;
}

.snapshot-history-rank input {
  width: 100%;
  box-sizing: border-box;
}
</style>
