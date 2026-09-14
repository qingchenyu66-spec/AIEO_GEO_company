<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { ElDrawer } from 'element-plus'
import 'element-plus/es/components/drawer/style/css'
import { ExternalLink } from '@lucide/vue'
import PlatformBadge from '../../../components/PlatformBadge.vue'
import { getMonitorSubtask, type MonitorSubtask } from '../../../services/monitor'
import type { SnapshotBackfillPendingItem } from '../../../services/snapshotBackfill'
import { buildSourceTrackRows } from '../../../utils/sourceSiteLabel'
import { monitorStatusLabelMap, platformLabelMap, sentimentLabelMap } from '../portalMaps'
import { formatDateTime, formatMonitorSubtaskRankDetail } from '../portalUtils'
import { snapshotBackfillBatchLabel, snapshotBackfillRankDisplay } from '../snapshotBackfillDisplay'
import { externalLink } from '../portalUtils'

const props = defineProps<{
  visible: boolean
  loading: boolean
  item: SnapshotBackfillPendingItem | null
  subtask: MonitorSubtask | null
  canSubmit?: boolean
  /** 从「补录前」格子打开：详情优先展示补录前快照 */
  preferBefore?: boolean
}>()

const emit = defineEmits<{
  'update:visible': [value: boolean]
  'update:subtask': [value: MonitorSubtask]
  backfill: []
  undismiss: []
}>()

const drawerVisible = computed({
  get: () => props.visible,
  set: (value: boolean) => emit('update:visible', value),
})

const headline = computed(() => props.item?.tenant_name || props.item?.brand_name || props.item?.monitor_keywords || '快照详情')

const rankDisplay = computed(() => snapshotBackfillRankDisplay(props.item, props.subtask))

const beforeSnap = computed(() => {
  const top = props.subtask?.before_backfill
  if (top && typeof top === 'object') return top
  const raw = props.subtask?.raw_result
  const nested = raw && typeof raw === 'object' ? (raw as { before_backfill?: MonitorSubtask['before_backfill'] }).before_backfill : null
  return nested && typeof nested === 'object' ? nested : null
})

const hasBeforeSnap = computed(() => Boolean(beforeSnap.value))

const viewingBefore = computed(() => Boolean(props.preferBefore && hasBeforeSnap.value))

/** 补录前对照：排名/提及必须以 before 快照为准，不能再用补录后的 subtask */
const displayRank = computed(() => {
  if (!viewingBefore.value || !beforeSnap.value) return rankDisplay.value
  const pos = beforeSnap.value.mention_position
  let mention: number | null = null
  if (pos != null && Number.isFinite(Number(pos))) mention = Number(pos)
  return {
    prompt_intent: rankDisplay.value.prompt_intent,
    mention_position: mention,
    brand_mentioned: mention != null ? true : Boolean(beforeSnap.value.has_answer),
    rank_source: null,
    rank_category: null,
  }
})

const displaySentiment = computed(() => {
  if (viewingBefore.value && beforeSnap.value) {
    return beforeSnap.value.sentiment || null
  }
  return props.subtask?.sentiment || props.item?.sentiment || null
})

const displayTaskStatus = computed(() => {
  if (viewingBefore.value && beforeSnap.value) {
    return beforeSnap.value.status || null
  }
  return props.subtask?.status || null
})

const displayStatusTag = computed(() => {
  if (viewingBefore.value && beforeSnap.value) {
    if (beforeSnap.value.has_answer) return '已有结果'
    const st = String(beforeSnap.value.status || '').toLowerCase()
    if (st === 'failed' || st === 'stopped') return '待补录'
    return beforeSnap.value.status || '—'
  }
  return statusLabel(props.item)
})

const snapshotLink = computed(() => {
  if (viewingBefore.value) {
    return externalLink(beforeSnap.value?.page_screenshot_url || beforeSnap.value?.page_screenshot)
  }
  return externalLink(props.subtask?.page_screenshot)
})

const parsePending = computed(() => String(props.subtask?.backfill_parse_status || '').toLowerCase() === 'pending')

// 2026-09-02 - 解析中/截图未出都不得露旧快照链接
const screenshotPending = computed(() => {
  if (viewingBefore.value) return false
  return Boolean(props.subtask?.screenshot_pending) || parsePending.value
})

const screenshotFailed = computed(() => {
  if (snapshotLink.value || screenshotPending.value) return false
  if (viewingBefore.value) return false
  return props.subtask?.screenshot_ok === false
})

const snapshotEmptyHint = computed(() => {
  // 2026-08-07 - 「暂无快照请填 URL」误导异步截图中的运营 - 按状态分文案
  if (viewingBefore.value) return '补录前无快照'
  if (parsePending.value) return '正文解析中，快照稍后生成'
  if (props.subtask?.screenshot_pending) return '快照生成中，稍后将自动可用'
  if (screenshotFailed.value) return '快照生成失败，可重新补录分享链接'
  return '暂无快照'
})

const isDismissed = computed(() => Boolean(props.item?.backfill_dismissed || props.subtask?.backfill_dismissed))

const pollTimer = ref<ReturnType<typeof setInterval> | null>(null)

function stopShotPoll() {
  if (pollTimer.value) {
    clearInterval(pollTimer.value)
    pollTimer.value = null
  }
}

async function refreshSubtaskOnce() {
  const id = props.subtask?.subtask_id || props.item?.subtask_id
  if (!id) return
  try {
    const next = await getMonitorSubtask(id, { include_ops: true, silentError: true })
    emit('update:subtask', next)
    if (externalLink(next.page_screenshot) || next.screenshot_pending === false) {
      stopShotPoll()
    }
  } catch {
    // silent
  }
}

function startShotPoll() {
  stopShotPoll()
  if (!props.visible || !screenshotPending.value || viewingBefore.value) return
  void refreshSubtaskOnce()
  pollTimer.value = setInterval(() => {
    void refreshSubtaskOnce()
  }, 3000)
}

watch(
  () => [props.visible, screenshotPending.value, props.subtask?.subtask_id, viewingBefore.value] as const,
  () => {
    if (props.visible && screenshotPending.value && !viewingBefore.value) startShotPoll()
    else stopShotPoll()
  },
)

onUnmounted(stopShotPoll)

function showRankNote() {
  if (viewingBefore.value) return false
  if (props.subtask?.prompt_intent !== 'ranking' && props.item?.prompt_intent !== 'ranking') return false
  const raw = props.subtask?.raw_mention_position ?? props.item?.raw_mention_position
  const rank = displayRank.value.mention_position
  return raw != null && raw !== rank
}

function rawRankNote() {
  return props.subtask?.raw_mention_position ?? props.item?.raw_mention_position
}

function sourceLabel(item: SnapshotBackfillPendingItem | null) {
  if (!item) return '—'
  if (item.source === 'lead_diagnosis') return '售前诊断'
  return 'GEO 监测'
}

function statusLabel(item: SnapshotBackfillPendingItem | null) {
  if (!item) return '—'
  if (item.backfill_dismissed) return '已忽略'
  if (item.needs_backfill) return '待补录'
  if (item.has_answer) return '已有结果'
  return item.status || '—'
}

function actionLabel(item: SnapshotBackfillPendingItem | null) {
  if (!item) return '补录'
  if (item.needs_backfill) return '快照补录'
  if (item.has_answer) return '覆盖更正'
  return '补录'
}

const answerPreview = computed(() => {
  const text = (viewingBefore.value
    ? beforeSnap.value?.answer_content
    : props.subtask?.answer_content)?.trim()
  if (!text) return null
  return text.length > 280 ? `${text.slice(0, 280)}…` : text
})

const afterSourceTracks = computed(() =>
  buildSourceTrackRows(props.subtask, { limit: 20, linkOf: externalLink }),
)

const beforeSourceTracks = computed(() =>
  buildSourceTrackRows(beforeSnap.value, { limit: 20, linkOf: externalLink }),
)

const beforeSourcesCaptured = computed(() => {
  const snap = beforeSnap.value
  if (!snap) return false
  if (snap.has_reference_list === false && snap.has_citation_list === false) return false
  if (snap.has_reference_list === true || snap.has_citation_list === true) return true
  // 兼容：字段直接存在时也视为已快照
  return Array.isArray(snap.reference_list) || Array.isArray(snap.citation_list)
})

const beforeSourceCount = computed(
  () => beforeSourceTracks.value.citations.length + beforeSourceTracks.value.references.length,
)
const afterSourceCount = computed(
  () => afterSourceTracks.value.citations.length + afterSourceTracks.value.references.length,
)

const showBeforeSourcesBlock = computed(() => viewingBefore.value && hasBeforeSnap.value)
const showAfterSourcesBlock = computed(() => !viewingBefore.value)
</script>

<template>
  <ElDrawer
    v-model="drawerVisible"
    :title="headline"
    size="520px"
    class="snapshot-backfill-detail-drawer"
  >
    <div v-if="loading" class="snapshot-detail-loading">加载详情中…</div>
    <template v-else-if="item && subtask">
      <div class="snapshot-detail-tags">
        <span class="snapshot-detail-tag">{{ sourceLabel(item) }}</span>
        <span
          class="snapshot-detail-tag"
          :class="{
            pending: item.needs_backfill && !isDismissed && !viewingBefore,
            done: ((viewingBefore && beforeSnap?.has_answer) || (!viewingBefore && item.has_answer && !item.needs_backfill)) && !isDismissed,
            dismissed: isDismissed,
          }"
        >
          {{ displayStatusTag }}
        </span>
      </div>

      <dl class="snapshot-detail-grid">
        <div>
          <dt>企业</dt>
          <dd>{{ item.tenant_name || item.brand_name || '—' }}</dd>
        </div>
        <div>
          <dt>平台</dt>
          <dd><PlatformBadge :code="subtask.platform" size="sm" /> {{ platformLabelMap[subtask.platform] || subtask.platform }}</dd>
        </div>
        <div>
          <dt>监测词</dt>
          <dd>{{ item.monitor_keywords || '—' }}</dd>
        </div>
        <div>
          <dt>词组</dt>
          <dd>{{ item.keyword_group || item.monitor_keywords || '—' }}</dd>
        </div>
        <div v-if="item.region_label && item.region_label !== '全部区域'">
          <dt>监测地区</dt>
          <dd>{{ item.region_label }}</dd>
        </div>
        <div>
          <dt>调度批次</dt>
          <dd>{{ snapshotBackfillBatchLabel(item) }}</dd>
        </div>
        <div>
          <dt>结果更新时间</dt>
          <dd>{{ formatDateTime(subtask.updated_at || item.updated_at) }}</dd>
        </div>
        <div>
          <dt>{{ displayRank.prompt_intent === 'ranking' ? '品牌排名' : '品牌提及' }}</dt>
          <dd>
            <strong>{{ formatMonitorSubtaskRankDetail(displayRank) }}</strong>
            <small v-if="showRankNote()">原始解析排名 {{ rawRankNote() }}</small>
          </dd>
        </div>
        <div>
          <dt>情感</dt>
          <dd>{{ sentimentLabelMap[String(displaySentiment || '').toLowerCase()] || displaySentiment || '—' }}</dd>
        </div>
        <div>
          <dt>任务状态</dt>
          <dd>{{ monitorStatusLabelMap[String(displayTaskStatus || '')] || displayTaskStatus || '—' }}</dd>
        </div>
        <div class="is-wide">
          <dt>监测问题</dt>
          <dd>{{ subtask.prompt }}</dd>
        </div>
        <div class="is-wide">
          <dt>快照链接</dt>
          <dd v-if="snapshotLink && !screenshotPending">
            <a :href="snapshotLink" target="_blank" rel="noopener noreferrer" class="snapshot-detail-link">
              查看快照
              <ExternalLink :size="14" />
            </a>
          </dd>
          <dd v-else class="snapshot-detail-muted">{{ snapshotEmptyHint }}</dd>
        </div>
        <div v-if="answerPreview" class="is-wide">
          <dt>回答摘要</dt>
          <dd class="snapshot-detail-answer">{{ answerPreview }}</dd>
        </div>
        <div v-if="showBeforeSourcesBlock" class="is-wide snapshot-detail-sources">
          <dt>信源 · {{ beforeSourceCount }}</dt>
          <dd>
            <p v-if="!beforeSourcesCaptured" class="snapshot-detail-muted">
              历史补录未快照信源
            </p>
            <template v-else>
              <div v-if="beforeSourceTracks.citations.length" class="snapshot-detail-source-group">
                <div class="snapshot-detail-source-head">正文引用 · {{ beforeSourceTracks.citations.length }}</div>
                <a
                  v-for="row in beforeSourceTracks.citations"
                  :key="`before-${row.key}`"
                  class="snapshot-detail-source-link"
                  :class="{ 'is-plain': !row.href }"
                  :href="row.href || undefined"
                  :target="row.href ? '_blank' : undefined"
                  :rel="row.href ? 'noopener noreferrer' : undefined"
                >
                  <span class="snapshot-detail-source-title">{{ row.title }}</span>
                  <span v-if="row.site" class="snapshot-detail-source-site">{{ row.site }}</span>
                </a>
              </div>
              <div v-if="beforeSourceTracks.references.length" class="snapshot-detail-source-group">
                <div class="snapshot-detail-source-head">参考来源 · {{ beforeSourceTracks.references.length }}</div>
                <a
                  v-for="row in beforeSourceTracks.references"
                  :key="`before-${row.key}`"
                  class="snapshot-detail-source-link"
                  :class="{ 'is-plain': !row.href }"
                  :href="row.href || undefined"
                  :target="row.href ? '_blank' : undefined"
                  :rel="row.href ? 'noopener noreferrer' : undefined"
                >
                  <span class="snapshot-detail-source-title">{{ row.title }}</span>
                  <span v-if="row.site" class="snapshot-detail-source-site">{{ row.site }}</span>
                </a>
              </div>
              <p
                v-if="!beforeSourceTracks.citations.length && !beforeSourceTracks.references.length"
                class="snapshot-detail-muted"
              >
                暂无信源
              </p>
            </template>
          </dd>
        </div>
        <div v-if="showAfterSourcesBlock" class="is-wide snapshot-detail-sources">
          <dt>信源 · {{ afterSourceCount }}</dt>
          <dd>
            <div v-if="afterSourceTracks.citations.length" class="snapshot-detail-source-group">
              <div class="snapshot-detail-source-head">正文引用 · {{ afterSourceTracks.citations.length }}</div>
              <a
                v-for="row in afterSourceTracks.citations"
                :key="`after-${row.key}`"
                class="snapshot-detail-source-link"
                :class="{ 'is-plain': !row.href }"
                :href="row.href || undefined"
                :target="row.href ? '_blank' : undefined"
                :rel="row.href ? 'noopener noreferrer' : undefined"
              >
                <span class="snapshot-detail-source-title">{{ row.title }}</span>
                <span v-if="row.site" class="snapshot-detail-source-site">{{ row.site }}</span>
              </a>
            </div>
            <div v-if="afterSourceTracks.references.length" class="snapshot-detail-source-group">
              <div class="snapshot-detail-source-head">参考来源 · {{ afterSourceTracks.references.length }}</div>
              <a
                v-for="row in afterSourceTracks.references"
                :key="`after-${row.key}`"
                class="snapshot-detail-source-link"
                :class="{ 'is-plain': !row.href }"
                :href="row.href || undefined"
                :target="row.href ? '_blank' : undefined"
                :rel="row.href ? 'noopener noreferrer' : undefined"
              >
                <span class="snapshot-detail-source-title">{{ row.title }}</span>
                <span v-if="row.site" class="snapshot-detail-source-site">{{ row.site }}</span>
              </a>
            </div>
            <p
              v-if="!afterSourceTracks.citations.length && !afterSourceTracks.references.length"
              class="snapshot-detail-muted"
            >
              暂无信源
            </p>
          </dd>
        </div>
        <div class="is-wide">
          <dt>子任务 ID</dt>
          <dd class="snapshot-detail-mono">{{ subtask.subtask_id }}</dd>
        </div>
      </dl>

      <p v-if="item.error_message" class="snapshot-detail-error">{{ item.error_message }}</p>
      <p v-if="isDismissed" class="snapshot-detail-dismiss-hint">
        已忽略待补录提醒，现有答案与排名仍计入客户；可取消忽略以重新纳入待办。
      </p>

      <div v-if="canSubmit !== false" class="snapshot-detail-actions">
        <button
          v-if="!isDismissed"
          type="button"
          class="primary-btn"
          @click="emit('backfill')"
        >
          {{ actionLabel(item) }}
        </button>
        <button
          v-if="isDismissed"
          type="button"
          class="primary-btn"
          @click="emit('undismiss')"
        >
          取消忽略
        </button>
      </div>
    </template>
  </ElDrawer>
</template>

<style scoped>
.snapshot-detail-loading {
  padding: 24px 0;
  color: #64748b;
  text-align: center;
}
.snapshot-detail-tags {
  display: flex;
  gap: 8px;
  margin-bottom: 16px;
}
.snapshot-detail-tag {
  padding: 4px 10px;
  border-radius: 999px;
  background: rgba(45, 108, 223, 0.08);
  color: #2d6cdf;
  font-size: 12px;
  font-weight: 700;
}
.snapshot-detail-tag.pending {
  background: rgba(194, 65, 12, 0.1);
  color: #c2410c;
}
.snapshot-detail-tag.done {
  background: rgba(22, 163, 74, 0.1);
  color: #15803d;
}
.snapshot-detail-tag.dismissed {
  background: rgba(100, 116, 139, 0.12);
  color: #475569;
}
.snapshot-detail-sources {
  margin-top: 2px;
}
.snapshot-detail-source-group + .snapshot-detail-source-group {
  margin-top: 10px;
}
.snapshot-detail-source-head {
  margin: 0 0 6px;
  color: #64748b;
  font-size: 12px;
  font-weight: 700;
}
.snapshot-detail-source-link {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin: 0 0 8px;
  padding: 8px 10px;
  border-radius: 8px;
  background: #f8fbff;
  border: 1px solid #e2eef9;
  text-decoration: none;
  color: inherit;
}
.snapshot-detail-source-link:hover {
  border-color: #93c5fd;
}
.snapshot-detail-source-link.is-plain {
  cursor: default;
}
.snapshot-detail-source-title {
  color: #153052;
  font-size: 13px;
  line-height: 1.45;
  word-break: break-word;
}
.snapshot-detail-source-site {
  color: #64748b;
  font-size: 12px;
}
.snapshot-detail-dismiss-hint {
  margin: 0 0 16px;
  padding: 10px 12px;
  border-radius: 8px;
  background: rgba(100, 116, 139, 0.08);
  color: #475569;
  font-size: 13px;
  line-height: 1.5;
}
.snapshot-detail-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px 16px;
  margin: 0;
}
.snapshot-detail-grid div {
  min-width: 0;
}
.snapshot-detail-grid div.is-wide {
  grid-column: 1 / -1;
}
.snapshot-detail-grid dt {
  margin: 0 0 4px;
  color: #94a3b8;
  font-size: 12px;
  font-weight: 700;
}
.snapshot-detail-grid dd {
  margin: 0;
  color: #153052;
  font-size: 14px;
  line-height: 1.5;
  word-break: break-word;
}
.snapshot-detail-grid dd strong {
  color: #c2410c;
  font-size: 16px;
}
.snapshot-detail-grid dd small {
  display: block;
  margin-top: 4px;
  color: #94a3b8;
  font-size: 12px;
  font-weight: 500;
}
.snapshot-detail-link {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: #2d6cdf;
  text-decoration: none;
}
.snapshot-detail-answer {
  padding: 10px 12px;
  border-radius: 10px;
  background: #f8fafc;
  white-space: pre-wrap;
}
.snapshot-detail-mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
  color: #475569;
}
.snapshot-detail-muted {
  color: #94a3b8;
  font-size: 13px;
}
.snapshot-detail-error {
  margin: 16px 0 0;
  padding: 10px 12px;
  border-radius: 10px;
  background: rgba(194, 65, 12, 0.08);
  color: #c2410c;
  font-size: 13px;
}
.snapshot-detail-actions {
  display: flex;
  justify-content: flex-end;
  margin-top: 20px;
  padding-top: 16px;
  border-top: 1px solid #e2ebf4;
}
</style>
