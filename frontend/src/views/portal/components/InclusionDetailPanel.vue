<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ChevronLeft, ChevronRight } from '@lucide/vue'
import { ElDialog } from 'element-plus'
import PlatformBadge from '../../../components/PlatformBadge.vue'
import { withRetry } from '../../../composables/useRetry'
import {
  getInclusionSnapshots,
  getMonitorSubtask,
  type MonitorSubtask,
  type WorkspaceSnapshot,
} from '../../../services/monitor'
import { citationSourceDisplay } from '../../../utils/sourceSiteLabel'
import { notifyOperationError } from '../../../utils/requestError'
import { parseAnswerBlocks } from '../answerBlocks'
import { formatDateTime, formatRank, externalLink } from '../portalUtils'
import { platformLabelMap, sentimentLabelMap } from '../portalMaps'

const PAGE_SIZE = 5

const props = defineProps<{
  tenantId?: number | null
  startDate?: string
  endDate?: string
  platformFilter?: string
  keywordFilter?: string
}>()

const loading = ref(false)
const snapshots = ref<WorkspaceSnapshot[]>([])
const page = ref(1)
/** 本格局部筛选：默认只看有位次；「全部」含未提及。切换会重新请求，避免后端 prefer_ranked 把未提及挤掉。 */
const rankScope = ref<'ranked' | 'all'>('ranked')

const snapshotVisible = ref(false)
const snapshotLoading = ref(false)
const snapshotSubtask = ref<MonitorSubtask | null>(null)
const snapshotListRank = ref<number | null>(null)

function snapshotRankLabel(snapshot: WorkspaceSnapshot) {
  if (snapshot.brand_rank != null) return `第 ${formatRank(snapshot.brand_rank)} 位`
  return snapshot.brand_mentioned ? '已提及' : '未提及'
}

function snapshotKeyword(row: WorkspaceSnapshot) {
  return row.monitor_keyword || row.keyword_group || row.prompt || '—'
}

function primaryArticle(row: WorkspaceSnapshot) {
  return (row.source_articles || [])[0] || null
}

function articleTitle(row: WorkspaceSnapshot) {
  const article = primaryArticle(row)
  if (article?.title) return article.title
  return '—'
}

function articleDomain(row: WorkspaceSnapshot) {
  const article = primaryArticle(row)
  if (article?.domain) return article.domain
  const url = article?.url
  if (!url) return ''
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return ''
  }
}

const filteredSnapshots = computed(() => {
  // 平台 / 排名口径已在接口侧按 props + rankScope 拉取，这里只做关键词本地筛
  const query = (props.keywordFilter || '').trim().toLowerCase()
  if (!query) return snapshots.value
  return snapshots.value.filter(row => {
    const haystack = [
      snapshotKeyword(row),
      row.prompt,
      row.keyword_group,
      articleTitle(row),
      articleDomain(row),
      platformLabelMap[row.platform] || row.platform,
    ].join(' ').toLowerCase()
    return haystack.includes(query)
  })
})

const totalPages = computed(() => Math.max(1, Math.ceil(filteredSnapshots.value.length / PAGE_SIZE)))

const pagedSnapshots = computed(() => {
  const start = (page.value - 1) * PAGE_SIZE
  return filteredSnapshots.value.slice(start, start + PAGE_SIZE)
})

const dialogRankLabel = computed(() => {
  // 与列表行一致：优先用点开时带入的列表名次，避免详情重算与列表不一致
  const subtask = snapshotSubtask.value
  const rank = snapshotListRank.value ?? subtask?.brand_rank ?? subtask?.mention_position
  if (rank != null) return `第 ${formatRank(rank)} 位`
  if (subtask?.brand_mentioned) return '已提及'
  return '未提及'
})

const snapshotAnswerBlocks = computed(() => {
  const text = snapshotSubtask.value?.answer_content?.trim()
    || snapshotSubtask.value?.mention_context?.trim()
    || ''
  return text ? parseAnswerBlocks(text) : []
})

const snapshotScreenshotUrl = computed(() => externalLink(snapshotSubtask.value?.page_screenshot))

const snapshotUpdatedAt = computed(() => formatDateTime(snapshotSubtask.value?.updated_at))

const snapshotSourceRows = computed(() => {
  const subtask = snapshotSubtask.value
  const list = subtask?.reference_list?.length ? subtask.reference_list : subtask?.citation_list
  return (list || []).slice(0, 12).map((source, index) => ({
    key: `${source.index ?? index}-${source.url || source.title || index}`,
    href: externalLink(source.url),
    ...citationSourceDisplay(source),
  }))
})

watch(filteredSnapshots, () => {
  page.value = 1
})

watch(totalPages, (total) => {
  if (page.value > total) page.value = total
})

async function openSnapshot(row: WorkspaceSnapshot) {
  const subtaskId = String(row.subtask_id || '').trim()
  if (!subtaskId) return
  snapshotListRank.value = row.brand_rank
  snapshotVisible.value = true
  snapshotLoading.value = true
  snapshotSubtask.value = null
  try {
    snapshotSubtask.value = await withRetry(() => getMonitorSubtask(subtaskId))
  } catch (error: unknown) {
    notifyOperationError(error, '快照加载失败')
    snapshotVisible.value = false
  } finally {
    snapshotLoading.value = false
  }
}

function closeSnapshot() {
  snapshotSubtask.value = null
  snapshotListRank.value = null
}

async function loadSnapshots() {
  loading.value = true
  try {
    const data = await withRetry(() => getInclusionSnapshots({
      tenant_id: props.tenantId ?? undefined,
      start_date: props.startDate || undefined,
      end_date: props.endDate || undefined,
      platform: props.platformFilter || undefined,
      limit: 48,
      rank_scope: rankScope.value,
    }, { silentError: true }))
    snapshots.value = data?.recent_snapshots || []
  } catch (error: unknown) {
    notifyOperationError(error, '收录明细加载失败')
    snapshots.value = []
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  void loadSnapshots()
})

watch(
  () => [props.tenantId, props.startDate, props.endDate, props.platformFilter, rankScope.value] as const,
  () => { void loadSnapshots() },
)
</script>

<template>
  <article class="source-panel source-inclusion-panel">
    <div class="source-panel-head source-inclusion-head">
      <h3>收录明细</h3>
      <div class="source-rank-scope" role="group" aria-label="排名筛选">
        <button
          type="button"
          :class="{ active: rankScope === 'ranked' }"
          @click="rankScope = 'ranked'"
        >
          有排名
        </button>
        <button
          type="button"
          :class="{ active: rankScope === 'all' }"
          @click="rankScope = 'all'"
        >
          全部
        </button>
      </div>
    </div>

    <div v-if="loading && !snapshots.length" class="mini-empty chart-empty">收录明细加载中…</div>
    <div v-else class="source-inclusion-table-wrap">
      <table class="source-inclusion-table">
        <thead>
          <tr>
            <th>关键词</th>
            <th>平台</th>
            <th>排名</th>
            <th>信源</th>
            <th>更新时间</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="!pagedSnapshots.length">
            <td colspan="5" class="source-inclusion-empty">—</td>
          </tr>
          <tr
            v-for="row in pagedSnapshots"
            :key="row.subtask_id"
            class="is-clickable"
            @click="openSnapshot(row)"
          >
            <td>
              <span class="source-keyword-tag">{{ snapshotKeyword(row) }}</span>
            </td>
            <td>
              <span class="source-platform-cell">
                <PlatformBadge :code="row.platform" size="xs" />
              </span>
            </td>
            <td>
              <span class="source-rank-tag">{{ snapshotRankLabel(row) }}</span>
            </td>
            <td class="source-inclusion-source">
              <template v-if="articleTitle(row) !== '—'">
                <span class="source-inclusion-title is-plain">{{ articleTitle(row) }}</span>
                <small v-if="articleDomain(row)" class="source-inclusion-meta">
                  <span class="source-domain-tag is-inline">{{ articleDomain(row) }}</span>
                </small>
              </template>
              <span v-else class="source-inclusion-empty-inline">—</span>
            </td>
            <td class="source-inclusion-time">{{ formatDateTime(row.updated_at) || '—' }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div v-if="filteredSnapshots.length > PAGE_SIZE" class="source-soft-pager">
      <button type="button" class="source-soft-btn" :disabled="page <= 1" @click="page -= 1">
        <ChevronLeft :size="14" />
        上一页
      </button>
      <span>共 {{ filteredSnapshots.length }} 条 · {{ page }} / {{ totalPages }}</span>
      <button type="button" class="source-soft-btn" :disabled="page >= totalPages" @click="page += 1">
        下一页
        <ChevronRight :size="14" />
      </button>
    </div>

    <ElDialog
      v-model="snapshotVisible"
      width="680px"
      align-center
      destroy-on-close
      append-to-body
      class="ws-board-detail-dialog"
      @closed="closeSnapshot"
    >
      <template #header>
        <div class="ws-board-dialog-head">
          <h3>收录快照</h3>
          <p v-if="snapshotSubtask?.prompt">{{ snapshotSubtask.prompt }}</p>
        </div>
      </template>

      <div v-if="snapshotLoading" class="ws-board-mini-empty">加载详情…</div>
      <template v-else-if="snapshotSubtask">
        <div class="ws-board-drawer-metrics">
          <span class="ws-board-drawer-chip">
            平台 {{ platformLabelMap[snapshotSubtask.platform] || snapshotSubtask.platform || '—' }}
          </span>
          <span class="ws-board-drawer-chip">排名 {{ dialogRankLabel }}</span>
          <span class="ws-board-drawer-chip">
            情感 {{ sentimentLabelMap[snapshotSubtask.sentiment || ''] || '暂无' }}
          </span>
          <span v-if="snapshotUpdatedAt" class="ws-board-drawer-chip">更新 {{ snapshotUpdatedAt }}</span>
          <a
            v-if="snapshotScreenshotUrl"
            :href="snapshotScreenshotUrl"
            target="_blank"
            rel="noopener noreferrer"
            class="ws-board-drawer-chip ws-board-drawer-chip-link"
          >查看页面快照</a>
          <span v-else class="ws-board-drawer-chip is-muted">暂无页面快照</span>
        </div>
        <div v-if="snapshotAnswerBlocks.length" class="ws-board-drawer-body">
          <div class="ws-board-drawer-answer">
            <template v-for="(block, index) in snapshotAnswerBlocks" :key="index">
              <h4 v-if="block.type === 'h'" class="ws-board-answer-h">{{ block.text }}</h4>
              <p v-else-if="block.type === 'p'" class="ws-board-answer-p">{{ block.text }}</p>
              <div v-else-if="block.type === 'kv'" class="ws-board-answer-kv">
                <span class="ws-board-answer-kv-label">{{ block.label }}</span>
                <span class="ws-board-answer-kv-value">{{ block.value }}</span>
              </div>
              <ul v-else-if="block.type === 'ul'" class="ws-board-answer-list">
                <li v-for="(item, itemIndex) in block.items" :key="itemIndex">{{ item }}</li>
              </ul>
              <ol v-else-if="block.type === 'ol'" class="ws-board-answer-list is-ordered">
                <li v-for="(item, itemIndex) in block.items" :key="itemIndex">{{ item }}</li>
              </ol>
            </template>
          </div>
        </div>
        <div v-else class="ws-board-mini-empty">暂无回答正文</div>
        <div v-if="snapshotSourceRows.length" class="ws-board-drawer-sources">
          <div class="ws-board-drawer-body-head">引用信源 · {{ snapshotSourceRows.length }}</div>
          <a
            v-for="row in snapshotSourceRows"
            :key="row.key"
            class="ws-board-source-link"
            :class="{ 'is-plain': !row.href }"
            :href="row.href || undefined"
            :target="row.href ? '_blank' : undefined"
            :rel="row.href ? 'noopener noreferrer' : undefined"
          >
            <span class="ws-board-source-title">{{ row.title }}</span>
            <span v-if="row.site" class="ws-board-source-site">{{ row.site }}</span>
          </a>
        </div>
      </template>
    </ElDialog>
  </article>
</template>
