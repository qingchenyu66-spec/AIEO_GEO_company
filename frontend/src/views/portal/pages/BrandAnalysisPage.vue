<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { RefreshCw, ChevronLeft, ChevronRight, HelpCircle, Download } from '@lucide/vue'
import { ElDialog, ElTooltip, ElMessage } from 'element-plus'
import { withRetry } from '../../../composables/useRetry'
import { getBrandAsset, type BrandAsset } from '../../../services/brand'
import {
  downloadBrandAnalysisPdf,
  getBrandAnalysis,
  getMonitorSubtask,
  type BrandAnalysisAiDescription,
  type BrandAnalysisAnswer,
  type BrandAnalysisDashboard,
  type BrandComparePeriod,
  type MonitorSubtask,
} from '../../../services/monitor'
import { buildSourceTrackRows } from '../../../utils/sourceSiteLabel'
import { extractErrorDetail, notifyOperationError } from '../../../utils/requestError'
import { useAuthStore } from '../../../stores/auth'
import { parseAnswerBlocks } from '../answerBlocks'
import { parsePreviewTenantId } from '../customerPreview'
import { formatDateTime, externalLink } from '../portalUtils'
import { platformLabelMap, sentimentLabelMap } from '../portalMaps'
import { inferDeviceLabel } from '../composables/useWorkspaceBoardExtras'

const props = defineProps<{
  brandAsset?: BrandAsset | null
  loading?: boolean
}>()

const emit = defineEmits<{ back: []; refresh: [] }>()

const route = useRoute()
const auth = useAuthStore()

const dashboard = ref<BrandAnalysisDashboard | null>(null)
const localBrandAsset = ref<BrandAsset | null>(null)
const localLoading = ref(false)
const loadError = ref('')
const updateTime = ref('')
// 2026-09-07 - B+：环比窗口可选周/月/季/年；比例跟描述筛选数
const comparePeriod = ref<BrandComparePeriod>('month')
const exporting = ref(false)

const canExport = computed(() => {
  const menus = auth.allowedMenus || []
  const row = menus.find(m => m.menu_code === 'customer.brand_analysis')
  if (row) return Boolean(row.can_export)
  return auth.session?.identity?.identity_type === 'PLATFORM'
})

const snapshotVisible = ref(false)
const snapshotLoading = ref(false)
const snapshotSubtask = ref<MonitorSubtask | null>(null)
const snapshotPromptHint = ref('')

const groupVisible = ref(false)
const activeGroup = ref<BrandAnalysisAiDescription | null>(null)

const selfLoaded = computed(() => props.brandAsset === undefined)
const effectiveBrandAsset = computed(() => (
  props.brandAsset !== undefined ? props.brandAsset : localBrandAsset.value
))
const effectiveLoading = computed(() => (
  props.loading ?? (selfLoaded.value ? localLoading.value : false)
))

function stampNow() {
  const d = new Date()
  const pad = (n: number) => String(n).padStart(2, '0')
  updateTime.value = `更新于 ${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}
stampNow()

const brandName = computed(() => (
  effectiveBrandAsset.value?.company_full_name
  || dashboard.value?.company_name
  || dashboard.value?.brand_name
  || '监测品牌'
))

const comparePeriodOptions: Array<{ value: BrandComparePeriod; label: string }> = [
  { value: 'week', label: '周' },
  { value: 'month', label: '月' },
  { value: 'quarter', label: '季' },
  { value: 'year', label: '年' },
]

const overviewShare = computed(() => {
  const share = dashboard.value?.description_share || {}
  return {
    正面: Number(share['正面'] || 0),
    中性: Number(share['中性'] || 0),
    负面: Number(share['负面'] || 0),
  }
})

function resolveTenantId() {
  const isPlatform = auth.session?.identity?.identity_type === 'PLATFORM'
  if (isPlatform) return parsePreviewTenantId(route) ?? undefined
  return undefined
}

function formatPtDelta(value: number | null | undefined) {
  if (value == null || Number.isNaN(Number(value))) return '—'
  const n = Number(value)
  const sign = n > 0 ? '+' : ''
  return `${sign}${n.toFixed(1)} pt`
}

function deltaTone(value: number | null | undefined, lowerIsBetter = false) {
  if (value == null || Number.isNaN(Number(value))) return 'muted'
  const n = Number(value)
  if (Math.abs(n) < 0.05) return 'muted'
  const upIsGood = !lowerIsBetter
  if (n > 0) return upIsGood ? 'ok' : 'bad'
  return upIsGood ? 'bad' : 'ok'
}

function compareDeltaClass(value: number | null | undefined, lowerIsBetter = false) {
  const tone = deltaTone(value, lowerIsBetter)
  if (tone === 'ok') return 'up'
  if (tone === 'bad') return 'down'
  return 'is-muted'
}

function platformShare(
  platform: { sentiment_share?: Record<string, number>; positive?: unknown[]; neutral?: unknown[]; negative?: unknown[] },
  key: '正面' | '中性' | '负面',
) {
  const share = platform.sentiment_share
  if (share && share[key] != null) return Number(share[key] || 0)
  const pos = (platform.positive || []).length
  const neu = (platform.neutral || []).length
  const neg = (platform.negative || []).length
  const labeled = pos + neu + neg
  if (!labeled) return 0
  const map = { 正面: pos, 中性: neu, 负面: neg }
  return Math.round((1000 * map[key]) / labeled) / 10
}

async function loadPageData() {
  localLoading.value = true
  loadError.value = ''
  try {
    const tenantId = resolveTenantId()
    dashboard.value = await withRetry(() => getBrandAnalysis({
      tenant_id: tenantId,
      parse: false,
      compare_period: comparePeriod.value,
    }))
    if (selfLoaded.value) {
      const assetTenantId = dashboard.value?.tenant_id ?? tenantId ?? null
      const response = await withRetry(() => getBrandAsset(assetTenantId))
      localBrandAsset.value = response.asset
    }
    const pending =
      Number(dashboard.value?.parse?.pending_left || 0) +
      Number(dashboard.value?.parse?.description_pending_left || 0)
    if (pending > 0) {
      const grain = comparePeriod.value
      void getBrandAnalysis({
        tenant_id: tenantId,
        parse: true,
        compare_period: grain,
      })
        .then((data) => {
          if (comparePeriod.value !== grain) return
          dashboard.value = data
          const descErrs = data.parse?.description_errors || []
          const sentErrs = data.parse?.errors || []
          if (descErrs.length || sentErrs.length || data.parse?.error) {
            notifyOperationError(
              new Error(String(data.parse?.error || descErrs[0] || sentErrs[0] || '补解析失败')),
              '品牌分析补解析未完成',
            )
          }
        })
        .catch((error: unknown) => {
          notifyOperationError(error, '品牌分析补解析失败')
        })
    }
  } catch (error: unknown) {
    notifyOperationError(error, '品牌分析数据加载失败')
    loadError.value = extractErrorDetail(error)
  } finally {
    localLoading.value = false
  }
}

async function handleRefresh() {
  await loadPageData()
  emit('refresh')
  stampNow()
}

async function handleExportPdf() {
  // 2026-09-07 - D1：导出维度=页面当前 comparePeriod，不另开选择
  if (exporting.value) return
  exporting.value = true
  try {
    const filename = await downloadBrandAnalysisPdf({
      tenant_id: resolveTenantId(),
      compare_period: comparePeriod.value,
    })
    ElMessage.success(`已导出 ${filename}`)
  } catch (error: unknown) {
    notifyOperationError(error, '导出口碑快照失败')
  } finally {
    exporting.value = false
  }
}

async function openAnswer(row: BrandAnalysisAnswer) {
  const subtaskId = String(row.subtask_id || '').trim()
  if (!subtaskId) return
  snapshotVisible.value = true
  snapshotLoading.value = true
  snapshotSubtask.value = null
  snapshotPromptHint.value = row.prompt || ''
  try {
    snapshotSubtask.value = await getMonitorSubtask(subtaskId)
  } catch (error: unknown) {
    notifyOperationError(error, '快照加载失败')
    snapshotVisible.value = false
  } finally {
    snapshotLoading.value = false
  }
}

function closeSnapshot() {
  snapshotVisible.value = false
  snapshotSubtask.value = null
  snapshotPromptHint.value = ''
}

function openDescriptionGroup(row: BrandAnalysisAiDescription) {
  activeGroup.value = row
  groupVisible.value = true
}

function openPlatformSentimentSnaps(platformName: string, sentimentLabel: string) {
  const platform = (dashboard.value?.platforms || []).find(item => item.name === platformName)
  if (!platform) return
  const bucketKey =
    sentimentLabel === '正面' ? 'positive'
      : sentimentLabel === '中性' ? 'neutral'
        : sentimentLabel === '负面' ? 'negative'
          : null
  if (!bucketKey) return
  const answers = platform[bucketKey] || []
  if (!answers.length) return
  activeGroup.value = {
    description: `${platform.name} · ${sentimentLabel}（${answers.length} 条）`,
    sentiment: sentimentLabel,
    sample_count: answers.length,
    platforms: [{ code: platform.code, name: platform.name }],
    answers,
  }
  groupVisible.value = true
}

function closeDescriptionGroup() {
  groupVisible.value = false
  activeGroup.value = null
}

async function openAnswerFromGroup(row: BrandAnalysisAnswer) {
  await openAnswer(row)
}

const snapshotAnswerBlocks = computed(() => parseAnswerBlocks(snapshotSubtask.value?.answer_content || ''))
const snapshotUpdatedAt = computed(() => formatDateTime(snapshotSubtask.value?.updated_at || null))
const snapshotScreenshotUrl = computed(() => externalLink(snapshotSubtask.value?.page_screenshot || '') || '')
const snapshotSourceTracks = computed(() =>
  buildSourceTrackRows(snapshotSubtask.value, { limit: 12, linkOf: externalLink }),
)

function sentimentTone(label: string | undefined) {
  if (label === '正面') return 'ok'
  if (label === '负面') return 'bad'
  if (label === '中性') return 'mid'
  return 'unk'
}

type SentimentFilter = 'all' | '正面' | '中性' | '负面'
const sentimentFilter = ref<SentimentFilter>('正面')
const platformFilter = ref<string>('all')

const sentimentFilterOptions: Array<{ value: SentimentFilter; label: string }> = [
  { value: 'all', label: '全部' },
  { value: '正面', label: '正面' },
  { value: '中性', label: '中性' },
  { value: '负面', label: '负面' },
]

const platformFilterOptions = computed(() => {
  const rows = dashboard.value?.platforms || []
  return [
    { value: 'all', label: '全部' },
    ...rows.map(platform => ({ value: platform.code, label: platform.name })),
  ]
})

const filteredDescriptions = computed(() => {
  const rows = dashboard.value?.ai_descriptions || []
  return rows.filter((row) => {
    if (sentimentFilter.value !== 'all' && row.sentiment !== sentimentFilter.value) return false
    if (platformFilter.value === 'all') return true
    return (row.answers || []).some(answer => answer.platform === platformFilter.value)
      || (row.platforms || []).some(platform => platform.code === platformFilter.value)
  })
})

const descriptionFilterCounts = computed(() => {
  const rows = dashboard.value?.ai_descriptions || []
  const platform = platformFilter.value
  const counts: Record<SentimentFilter, number> = {
    all: 0,
    正面: 0,
    中性: 0,
    负面: 0,
  }
  for (const row of rows) {
    if (platform !== 'all') {
      const hit = (row.answers || []).some(answer => answer.platform === platform)
        || (row.platforms || []).some(platformRow => platformRow.code === platform)
      if (!hit) continue
    }
    counts.all += 1
    const label = row.sentiment
    if (label === '正面' || label === '中性' || label === '负面') {
      counts[label] += 1
    }
  }
  return counts
})

function descriptionFilterCount(option: SentimentFilter) {
  return Number(descriptionFilterCounts.value[option] || 0)
}

const DESC_PAGE_SIZE = 5
const descPage = ref(1)

const descTotalPages = computed(() => (
  Math.max(1, Math.ceil(filteredDescriptions.value.length / DESC_PAGE_SIZE))
))

const pagedDescriptions = computed(() => {
  const page = Math.min(descPage.value, descTotalPages.value)
  const start = (page - 1) * DESC_PAGE_SIZE
  return filteredDescriptions.value.slice(start, start + DESC_PAGE_SIZE)
})

const platformRowsSorted = computed(() => {
  const rows = [...(dashboard.value?.platforms || [])]
  // 2026-09-07 - Brandwatch 渠道图按样本量排；同分再比负面占比
  return rows.sort((a, b) => {
    const vol = (b.sample_count || 0) - (a.sample_count || 0)
    if (vol) return vol
    return platformShare(b, '负面') - platformShare(a, '负面')
  })
})

watch(dashboard, () => {
  platformFilter.value = 'all'
  descPage.value = 1
})

watch([sentimentFilter, platformFilter], () => {
  descPage.value = 1
})

watch(comparePeriod, () => {
  void loadPageData()
})

onMounted(() => {
  void loadPageData()
})
</script>


<template>
  <section class="brand-analysis-page">
    <Teleport to="#portal-page-head-extra" defer>
      <div class="ba-head-actions">
        <button
          v-if="canExport"
          type="button"
          class="ws-board-btn"
          :disabled="effectiveLoading || exporting || !dashboard"
          @click="handleExportPdf"
        >
          <Download :size="16" />
          {{ exporting ? '导出中…' : '导出 PDF' }}
        </button>
        <button type="button" class="ws-board-btn" :disabled="effectiveLoading" @click="handleRefresh">
          <RefreshCw :size="16" :class="{ 'ba-spin': effectiveLoading }" />
          刷新
        </button>
        <span class="ws-board-update">{{ updateTime }}</span>
      </div>
    </Teleport>

    <div v-if="loadError" class="ws-board-error">{{ loadError }}</div>
    <div v-else-if="effectiveLoading && !dashboard" class="ws-board-loading">
      <div v-for="n in 4" :key="n" class="ws-board-skeleton" />
    </div>

    <template v-else-if="dashboard">
      <!-- 2026-09-07 - Brandwatch 式：结论卡 + 独立「平台情感构成」100% 堆叠条 -->
      <div class="ws-board-insight-row ba-insight-row">
        <article class="ws-board-card ws-board-conclusion-card ba-summary">
          <!-- 2026-09-07 - 副文案过长把样本挤到下一行 - 标题行只留品牌+样本，周期单独一行 -->
          <div class="ws-board-conclusion-head ba-summary-top">
            <div class="ws-board-conclusion-title-wrap">
              <h2 class="ws-board-conclusion-title ba-summary-name">{{ brandName }}</h2>
              <p class="ws-board-conclusion-sub">
                {{ dashboard.period_label || '—' }}
                · {{ dashboard.purchased_platforms?.length || 0 }} 个平台
                <template v-if="dashboard.data_as_of">
                  · 截至抓取 {{ dashboard.data_as_of }}
                </template>
              </p>
            </div>
            <div class="ws-board-conclusion-head-aside ba-summary-aside">
              <span class="ws-board-conclusion-badge is-calm">样本 {{ dashboard.sample_count ?? 0 }}</span>
            </div>
          </div>
          <div class="ba-summary-period" role="region" aria-label="环比窗口">
            <div class="ws-board-tabs">
              <button
                v-for="option in comparePeriodOptions"
                :key="option.value"
                type="button"
                class="ws-board-tab"
                :class="{ active: comparePeriod === option.value }"
                @click="comparePeriod = option.value"
              >
                {{ option.label }}
              </button>
            </div>
          </div>

          <div class="ws-board-conclusion-metrics ba-summary-kpis">
            <div class="ws-board-conclusion-metric ba-kpi is-ok">
              <div class="ws-board-conclusion-metric-label">正面</div>
              <div class="ws-board-conclusion-metric-value">{{ overviewShare['正面'].toFixed(1) }}%</div>
              <div
                v-if="!dashboard.description_compare?.insufficient"
                class="ws-board-conclusion-metric-delta"
                :class="compareDeltaClass(dashboard.description_compare?.deltas?.['正面_pt'])"
              >{{ formatPtDelta(dashboard.description_compare?.deltas?.['正面_pt']) }}</div>
              <div v-else class="ws-board-conclusion-metric-delta is-muted">—</div>
            </div>
            <div class="ws-board-conclusion-metric ba-kpi is-mid">
              <div class="ws-board-conclusion-metric-label">中性</div>
              <div class="ws-board-conclusion-metric-value">{{ overviewShare['中性'].toFixed(1) }}%</div>
              <div
                v-if="!dashboard.description_compare?.insufficient"
                class="ws-board-conclusion-metric-delta"
                :class="compareDeltaClass(dashboard.description_compare?.deltas?.['中性_pt'])"
              >{{ formatPtDelta(dashboard.description_compare?.deltas?.['中性_pt']) }}</div>
              <div v-else class="ws-board-conclusion-metric-delta is-muted">—</div>
            </div>
            <div class="ws-board-conclusion-metric ba-kpi is-bad">
              <div class="ws-board-conclusion-metric-label">负面</div>
              <div class="ws-board-conclusion-metric-value">{{ overviewShare['负面'].toFixed(1) }}%</div>
              <div
                v-if="!dashboard.description_compare?.insufficient"
                class="ws-board-conclusion-metric-delta"
                :class="compareDeltaClass(dashboard.description_compare?.deltas?.['负面_pt'], true)"
              >{{ formatPtDelta(dashboard.description_compare?.deltas?.['负面_pt']) }}</div>
              <div v-else class="ws-board-conclusion-metric-delta is-muted">—</div>
            </div>
          </div>

          <div class="ba-share-track" aria-hidden="true">
            <i v-if="overviewShare['正面'] > 0" class="is-ok" :style="{ flexGrow: overviewShare['正面'] }" />
            <i v-if="overviewShare['中性'] > 0" class="is-mid" :style="{ flexGrow: overviewShare['中性'] }" />
            <i v-if="overviewShare['负面'] > 0" class="is-bad" :style="{ flexGrow: overviewShare['负面'] }" />
          </div>
        </article>

        <article class="ws-board-card ba-platform-card">
          <div class="ws-board-card-head">
            <div class="ws-board-card-title" style="margin:0">平台情感构成</div>
            <div class="ba-stack-legend" aria-hidden="true">
              <span class="is-ok">正面</span>
              <span class="is-mid">中性</span>
              <span class="is-bad">负面</span>
            </div>
          </div>
          <p v-if="!platformRowsSorted.length" class="ws-board-mini-empty">暂无平台样本</p>
          <div v-else class="ba-stack-list">
            <div
              v-for="platform in platformRowsSorted"
              :key="platform.code"
              class="ba-stack-row"
            >
              <div class="ba-stack-name">{{ platform.name }}</div>
              <div class="ba-stack-bar" role="img" :aria-label="`${platform.name} 正${platformShare(platform, '正面')}% 中${platformShare(platform, '中性')}% 负${platformShare(platform, '负面')}%`">
                <button
                  v-if="platformShare(platform, '正面') > 0"
                  type="button"
                  class="seg is-ok"
                  :style="{ width: `${platformShare(platform, '正面')}%` }"
                  :disabled="!(platform.positive || []).length"
                  :title="`正面 ${platformShare(platform, '正面')}%`"
                  @click="openPlatformSentimentSnaps(platform.name, '正面')"
                >
                  <em v-if="platformShare(platform, '正面') >= 14">{{ platformShare(platform, '正面').toFixed(0) }}%</em>
                </button>
                <button
                  v-if="platformShare(platform, '中性') > 0"
                  type="button"
                  class="seg is-mid"
                  :style="{ width: `${platformShare(platform, '中性')}%` }"
                  :disabled="!(platform.neutral || []).length"
                  :title="`中性 ${platformShare(platform, '中性')}%`"
                  @click="openPlatformSentimentSnaps(platform.name, '中性')"
                >
                  <em v-if="platformShare(platform, '中性') >= 14">{{ platformShare(platform, '中性').toFixed(0) }}%</em>
                </button>
                <button
                  v-if="platformShare(platform, '负面') > 0"
                  type="button"
                  class="seg is-bad"
                  :style="{ width: `${platformShare(platform, '负面')}%` }"
                  :disabled="!(platform.negative || []).length"
                  :title="`负面 ${platformShare(platform, '负面')}%`"
                  @click="openPlatformSentimentSnaps(platform.name, '负面')"
                >
                  <em v-if="platformShare(platform, '负面') >= 14">{{ platformShare(platform, '负面').toFixed(0) }}%</em>
                </button>
              </div>
            </div>
          </div>
        </article>
      </div>

      <div class="ba-filter-bar">
        <span class="ba-filter-label">
          情感筛选
          <ElTooltip
            placement="top"
            :show-after="200"
            content="角标按 AI 描述归并组数计；右上「样本」是监测回答条数，一条回答可拆出多组，故「全部」常大于样本数。"
          >
            <button type="button" class="ba-filter-help" aria-label="情感筛选数字说明">
              <HelpCircle :size="14" />
            </button>
          </ElTooltip>
        </span>
        <div class="ws-board-tabs ba-filter-tabs">
          <button
            v-for="option in sentimentFilterOptions"
            :key="option.value"
            type="button"
            class="ws-board-tab"
            :class="{ active: sentimentFilter === option.value }"
            @click="sentimentFilter = option.value"
          >
            {{ option.label }}
            <em>{{ descriptionFilterCount(option.value) }}</em>
          </button>
        </div>
        <span class="ba-filter-label">平台筛选</span>
        <div class="ws-board-tabs ba-filter-tabs">
          <button
            v-for="option in platformFilterOptions"
            :key="option.value"
            type="button"
            class="ws-board-tab"
            :class="{ active: platformFilter === option.value }"
            @click="platformFilter = option.value"
          >
            {{ option.label }}
          </button>
        </div>
      </div>

      <article class="ws-board-card ba-desc-card">
        <div class="ws-board-card-head">
          <div class="ws-board-card-title" style="margin:0">AI 描述</div>
          <span class="ws-board-section-period" style="margin:0">
            {{ filteredDescriptions.length }} 组
          </span>
        </div>
        <p v-if="!dashboard.sample_count" class="ws-board-mini-empty">暂无样本</p>
        <p v-else-if="!filteredDescriptions.length" class="ws-board-mini-empty">当前筛选下暂无描述</p>
        <div v-else class="ba-desc-list">
          <button
            v-for="(row, index) in pagedDescriptions"
            :key="`${row.description}-${index}`"
            type="button"
            class="ba-desc"
            :class="`is-${sentimentTone(row.sentiment)}`"
            @click="openDescriptionGroup(row)"
          >
            <span class="ba-desc-top">
              <span class="ba-desc-text">{{ row.description }}</span>
              <span class="ba-desc-count">{{ row.sample_count }} 条</span>
            </span>
            <span class="ba-desc-meta">
              <span class="ba-sent-pill" :class="`is-${sentimentTone(row.sentiment)}`">
                {{ row.sentiment || '未知' }}
              </span>
              <span
                v-for="plat in row.platforms"
                :key="plat.code"
                class="ba-plat-chip"
              >{{ plat.name }}</span>
            </span>
          </button>
        </div>
        <div v-if="filteredDescriptions.length > DESC_PAGE_SIZE" class="ba-pager">
          <button
            type="button"
            class="ba-pager-btn"
            :disabled="descPage <= 1"
            aria-label="上一页"
            @click="descPage = Math.max(1, descPage - 1)"
          >
            <ChevronLeft :size="16" />
            <span>上一页</span>
          </button>
          <span class="ba-pager-chip">
            <em>{{ Math.min(descPage, descTotalPages) }}</em>
            <span>/</span>
            <em>{{ descTotalPages }}</em>
          </span>
          <button
            type="button"
            class="ba-pager-btn"
            :disabled="descPage >= descTotalPages"
            aria-label="下一页"
            @click="descPage = Math.min(descTotalPages, descPage + 1)"
          >
            <span>下一页</span>
            <ChevronRight :size="16" />
          </button>
        </div>
      </article>
    </template>

    <ElDialog
      v-model="groupVisible"
      width="720px"
      align-center
      destroy-on-close
      append-to-body
      class="ws-board-detail-dialog"
      @closed="closeDescriptionGroup"
    >
      <template #header>
        <div class="ws-board-dialog-head">
          <h3>关联快照</h3>
          <p v-if="activeGroup">{{ activeGroup.description }}</p>
        </div>
      </template>
      <div v-if="activeGroup" class="ba-group-list">
        <button
          v-for="row in activeGroup.answers"
          :key="row.subtask_id"
          type="button"
          class="ba-group-snap"
          @click="openAnswerFromGroup(row)"
        >
          <strong>{{ row.platform_name || platformLabelMap[row.platform || ''] || row.platform || '—' }}</strong>
          <span class="ba-group-prompt">{{ row.prompt || '—' }}</span>
          <span class="ba-group-excerpt">{{ row.excerpt || '—' }}</span>
          <span class="ba-group-foot">
            <em :class="`is-${sentimentTone(row.sentiment)}`">{{ row.sentiment || '未知' }}</em>
            <em v-if="row.updated_at">{{ formatDateTime(row.updated_at) }}</em>
          </span>
        </button>
      </div>
    </ElDialog>

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
          <h3>回答详情</h3>
          <p v-if="snapshotPromptHint || snapshotSubtask?.prompt">
            {{ snapshotPromptHint || snapshotSubtask?.prompt }}
          </p>
        </div>
      </template>

      <div v-if="snapshotLoading" class="ws-board-mini-empty">加载详情…</div>
      <template v-else-if="snapshotSubtask">
        <div class="ws-board-drawer-metrics">
          <span class="ws-board-drawer-chip">
            平台 {{ platformLabelMap[snapshotSubtask.platform] || snapshotSubtask.platform || '—' }}
          </span>
          <span class="ws-board-drawer-chip">设备 {{ inferDeviceLabel(snapshotSubtask.platform || '') }}</span>
          <span class="ws-board-drawer-chip">
            情感 {{ sentimentLabelMap[snapshotSubtask.sentiment || ''] || snapshotSubtask.sentiment || '暂无' }}
          </span>
          <span v-if="snapshotUpdatedAt" class="ws-board-drawer-chip">更新 {{ snapshotUpdatedAt }}</span>
          <a
            v-if="snapshotScreenshotUrl"
            :href="snapshotScreenshotUrl"
            target="_blank"
            rel="noopener noreferrer"
            class="ws-board-drawer-chip ws-board-drawer-chip-link"
          >查看页面快照</a>
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
        <div v-if="snapshotSourceTracks.citations.length" class="ws-board-drawer-sources">
          <div class="ws-board-drawer-body-head">正文引用 · {{ snapshotSourceTracks.citations.length }}</div>
          <a
            v-for="row in snapshotSourceTracks.citations"
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
        <div v-if="snapshotSourceTracks.references.length" class="ws-board-drawer-sources">
          <div class="ws-board-drawer-body-head">参考来源 · {{ snapshotSourceTracks.references.length }}</div>
          <a
            v-for="row in snapshotSourceTracks.references"
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
  </section>
</template>

<style scoped>
.brand-analysis-page {
  --ba-ok: #16a34a;
  --ba-mid: #64748b;
  --ba-bad: #dc2626;
  --ba-deep: #0f172a;
  --ba-muted: #64748b;
  --ba-faint: #94a3b8;
  --ba-border: #e2e8f0;
  max-width: 1400px;
  margin: 0 auto;
  padding: 0 0 40px;
  color: #1e293b;
}

.ba-head-actions {
  display: inline-flex;
  align-items: center;
  gap: 12px;
}

.ba-spin {
  animation: ba-spin 1s linear infinite;
}

@keyframes ba-spin {
  to { transform: rotate(360deg); }
}

.ba-summary {
  margin-bottom: 0;
  height: 100%;
}

.ba-summary-top {
  flex-wrap: nowrap;
  align-items: flex-start;
}

.ba-summary-name {
  font-size: 17px;
  letter-spacing: -0.02em;
}

.ba-summary-aside {
  flex-shrink: 0;
  align-items: flex-end;
}

.ba-summary-period {
  margin: 10px 0 12px;
}

.ba-summary-kpis {
  margin: 0;
}

/* 情感色落在指标格上，避免裸数字飘在空里 */
.ba-kpi.is-ok {
  background: linear-gradient(180deg, #ecfdf5 0%, #f8fafc 100%);
  border-color: #d1fae5;
}

.ba-kpi.is-ok .ws-board-conclusion-metric-value {
  color: #15803d;
}

.ba-kpi.is-mid {
  background: linear-gradient(180deg, #f8fafc 0%, #f1f5f9 100%);
  border-color: #e2e8f0;
}

.ba-kpi.is-mid .ws-board-conclusion-metric-value {
  color: #334155;
}

.ba-kpi.is-bad {
  background: linear-gradient(180deg, #fef2f2 0%, #f8fafc 100%);
  border-color: #fecaca;
}

.ba-kpi.is-bad .ws-board-conclusion-metric-value {
  color: #b91c1c;
}

.ba-share-track {
  display: flex;
  gap: 4px;
  height: 8px;
  margin: 2px 0 0;
}

.ba-share-track > i {
  display: block;
  min-width: 0;
  border-radius: 999px;
}

.ba-share-track .is-ok { background: #22c55e; }
.ba-share-track .is-mid { background: #94a3b8; }
.ba-share-track .is-bad { background: #ef4444; }

.ba-platform-card {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-height: 0;
  padding: 18px 18px 16px !important;
}

.ba-stack-legend {
  display: inline-flex;
  align-items: center;
  gap: 12px;
  font-size: 12px;
  font-weight: 600;
  color: #64748b;
}

.ba-stack-legend > span {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.ba-stack-legend > span::before {
  content: '';
  width: 8px;
  height: 8px;
  border-radius: 999px;
}

.ba-stack-legend .is-ok::before { background: #22c55e; }
.ba-stack-legend .is-mid::before { background: #94a3b8; }
.ba-stack-legend .is-bad::before { background: #ef4444; }

.ba-stack-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  flex: 1;
  justify-content: center;
}

.ba-stack-row {
  display: grid;
  grid-template-columns: 76px minmax(0, 1fr);
  gap: 12px;
  align-items: center;
}

.ba-stack-name {
  font-size: 13px;
  font-weight: 650;
  color: #0f172a;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ba-stack-bar {
  display: flex;
  width: 100%;
  height: 22px;
  overflow: hidden;
  border-radius: 6px;
  background: #f1f5f9;
}

.ba-stack-bar .seg {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  margin: 0;
  padding: 0 4px;
  border: 0;
  border-radius: 0;
  cursor: pointer;
  min-width: 0;
  box-sizing: border-box;
}

.ba-stack-bar .seg:disabled {
  cursor: default;
}

.ba-stack-bar .seg:not(:disabled):hover {
  filter: brightness(0.95);
}

.ba-stack-bar .seg em {
  font-style: normal;
  font-size: 11px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  color: #fff;
  text-shadow: 0 1px 1px rgba(15, 23, 42, 0.18);
  line-height: 1;
}

.ba-stack-bar .is-ok { background: #22c55e; }
.ba-stack-bar .is-mid { background: #94a3b8; }
.ba-stack-bar .is-mid em { color: #f8fafc; }
.ba-stack-bar .is-bad { background: #ef4444; }

.ba-filter-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px 14px;
  margin: 0 0 16px;
  padding: 10px 14px;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  background: rgba(248, 250, 252, 0.96);
}

.ba-filter-label {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 13px;
  font-weight: 700;
  color: #0f172a;
}

.ba-filter-help {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  margin: 0;
  padding: 0;
  border: 0;
  background: transparent;
  color: #94a3b8;
  cursor: help;
  line-height: 1;
}

.ba-filter-help:hover {
  color: #64748b;
}

.ba-filter-tabs {
  margin: 0;
}

.ba-filter-tabs .ws-board-tab em {
  margin-left: 4px;
  font-style: normal;
  font-weight: 600;
  color: #94a3b8;
}

.ba-filter-tabs .ws-board-tab.active em {
  color: #2563eb;
}

.ba-desc-card {
  margin-bottom: 20px;
}

.ba-desc-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.ba-desc {
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: 100%;
  margin: 0;
  padding: 14px 16px;
  border: 1px solid #e2e8f0;
  border-left: 3px solid #cbd5e1;
  border-radius: 12px;
  background: #fbfdff;
  text-align: left;
  cursor: pointer;
  font-family: inherit;
}

.ba-desc.is-ok { border-left-color: var(--ba-ok); }
.ba-desc.is-bad { border-left-color: var(--ba-bad); }
.ba-desc.is-mid { border-left-color: #94a3b8; }

.ba-desc:hover {
  border-color: #93c5fd;
  box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.08);
}

.ba-desc-top {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
}

.ba-desc-text {
  font-size: 14px;
  font-weight: 600;
  line-height: 1.5;
  color: #0f172a;
}

.ba-desc-count {
  flex-shrink: 0;
  font-size: 12px;
  font-weight: 700;
  color: #2563eb;
  white-space: nowrap;
}

.ba-desc-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
}

.ba-sent-pill {
  display: inline-flex;
  align-items: center;
  min-height: 24px;
  padding: 0 9px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
  background: #f1f5f9;
  color: var(--ba-mid);
}

.ba-sent-pill.is-ok { background: #ecfdf5; color: var(--ba-ok); }
.ba-sent-pill.is-bad { background: #fef2f2; color: var(--ba-bad); }
.ba-sent-pill.is-mid { background: #f1f5f9; color: var(--ba-mid); }

.ba-plat-chip {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 999px;
  background: #f1f5f9;
  color: #64748b;
}

.ba-group-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 60vh;
  overflow: auto;
}

.ba-group-snap {
  display: flex;
  flex-direction: column;
  gap: 4px;
  width: 100%;
  margin: 0;
  padding: 12px;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  background: #fff;
  text-align: left;
  cursor: pointer;
  font-family: inherit;
}

.ba-group-snap:hover {
  border-color: #93c5fd;
}

.ba-group-snap strong {
  font-size: 13px;
  color: #0f172a;
}

.ba-group-prompt {
  font-size: 12px;
  color: #64748b;
}

.ba-group-excerpt {
  font-size: 13px;
  color: #1e293b;
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.ba-group-foot {
  display: flex;
  gap: 10px;
  margin-top: 2px;
}

.ba-group-foot em {
  font-style: normal;
  font-size: 12px;
  color: #94a3b8;
}

.ba-group-foot em.is-ok { color: var(--ba-ok); }
.ba-group-foot em.is-bad { color: var(--ba-bad); }
.ba-group-foot em.is-mid { color: var(--ba-mid); }

.ba-pager {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  margin-top: 14px;
  padding-top: 14px;
  border-top: 1px solid #edf2f8;
}

.ba-pager-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  min-height: 34px;
  padding: 0 12px;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  background: #fff;
  color: #334155;
  font-size: 13px;
  font-weight: 600;
  font-family: inherit;
  cursor: pointer;
  transition: border-color .15s, background .15s, color .15s, box-shadow .15s;
}

.ba-pager-btn:hover:not(:disabled) {
  border-color: #93c5fd;
  background: #f8fbff;
  color: #2563eb;
  box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.08);
}

.ba-pager-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
  background: #f8fafc;
  color: #94a3b8;
}

.ba-pager-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 34px;
  padding: 0 14px;
  border-radius: 999px;
  background: #f1f5f9;
  color: #64748b;
  font-size: 13px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.ba-pager-chip em {
  font-style: normal;
  color: #0f172a;
}

.ba-pager-chip span {
  color: #94a3b8;
}

@media (max-width: 960px) {
  .ba-stack-row {
    grid-template-columns: 64px minmax(0, 1fr);
    gap: 8px;
  }
}
</style>
