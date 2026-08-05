<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { RefreshCw, ChevronLeft, ChevronRight } from '@lucide/vue'
import { ElDialog } from 'element-plus'
import type { ECharts } from 'echarts/core'
import { withRetry } from '../../../composables/useRetry'
import { getBrandAsset, type BrandAsset } from '../../../services/brand'
import {
  getBrandAnalysis,
  getMonitorSubtask,
  type BrandAnalysisAiDescription,
  type BrandAnalysisAnswer,
  type BrandAnalysisDashboard,
  type BrandAnalysisPlatformBlock,
  type MonitorSubtask,
} from '../../../services/monitor'
import { citationSourceDisplay } from '../../../utils/sourceSiteLabel'
import { extractErrorDetail, notifyOperationError } from '../../../utils/requestError'
import { loadEchartsRuntime } from '../../../utils/echartsLoader'
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
const sentimentChartEl = ref<HTMLElement | null>(null)
const platformChartEl = ref<HTMLElement | null>(null)
let sentimentChart: ECharts | null = null
let platformChart: ECharts | null = null

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

function resolveTenantId() {
  const isPlatform = auth.session?.identity?.identity_type === 'PLATFORM'
  if (isPlatform) return parsePreviewTenantId(route) ?? undefined
  return undefined
}

async function ensureCharts() {
  const runtime = await loadEchartsRuntime('portal')
  await nextTick()
  if (sentimentChartEl.value) {
    sentimentChart = runtime.getInstanceByDom(sentimentChartEl.value) || runtime.init(sentimentChartEl.value)
  }
  if (platformChartEl.value) {
    platformChart = runtime.getInstanceByDom(platformChartEl.value) || runtime.init(platformChartEl.value)
  }
}

const SENTIMENT_ORDER = ['正面', '中性', '负面', '未知'] as const
/** 对齐工作台 success / muted / danger */
const SENTIMENT_COLOR: Record<string, string> = {
  正面: '#16a34a',
  中性: '#94a3b8',
  负面: '#dc2626',
  未知: '#cbd5e1',
}

function sentimentDonutOption(data: Array<{ name: string; value: number }>) {
  const filtered = SENTIMENT_ORDER
    .map(name => ({ name, value: data.find(item => item.name === name)?.value || 0 }))
    .filter(item => item.value > 0)
  const total = filtered.reduce((sum, item) => sum + item.value, 0)
  return {
    animation: false,
    color: filtered.map(item => SENTIMENT_COLOR[item.name] || '#cbd5e1'),
    tooltip: {
      trigger: 'item',
      backgroundColor: 'rgba(15, 23, 42, 0.92)',
      borderWidth: 0,
      padding: [8, 12],
      textStyle: { color: '#fff', fontSize: 12 },
      formatter: (params: { name: string; value: number; percent: number; marker: string }) => (
        params.marker + params.name + '<br/>' + params.value + ' 条 · ' + params.percent + '%'
      ),
    },
    legend: {
      bottom: 0,
      left: 'center',
      itemWidth: 8,
      itemHeight: 8,
      itemGap: 18,
      icon: 'circle',
      textStyle: { color: '#64748b', fontSize: 12 },
      formatter: (name: string) => {
        const row = filtered.find(item => item.name === name)
        if (!row || !total) return name
        return name + ' ' + row.value
      },
    },
    series: [{
      type: 'pie',
      radius: ['46%', '70%'],
      center: ['50%', '44%'],
      padAngle: 1.2,
      minAngle: 4,
      itemStyle: {
        borderRadius: 5,
        borderColor: '#fff',
        borderWidth: 2,
      },
      label: { show: false },
      labelLine: { show: false },
      data: total
        ? filtered
        : [{ name: '暂无', value: 1, itemStyle: { color: '#e2e8f0' } }],
      emphasis: {
        scale: true,
        scaleSize: 6,
        itemStyle: { shadowBlur: 10, shadowColor: 'rgba(15, 23, 42, 0.1)' },
      },
    }],
    graphic: total
      ? [
          {
            type: 'text',
            left: 'center',
            top: '36%',
            style: {
              text: String(total),
              fill: '#0f172a',
              fontSize: 26,
              fontWeight: 700,
              textAlign: 'center',
            },
          },
          {
            type: 'text',
            left: 'center',
            top: '48%',
            style: {
              text: '样本',
              fill: '#94a3b8',
              fontSize: 12,
              textAlign: 'center',
            },
          },
        ]
      : [],
  }
}

function platformSentimentBarOption(platforms: BrandAnalysisPlatformBlock[]) {
  const rows = platforms
    .map(platform => {
      const positive = (platform.positive || []).length
      const neutral = (platform.neutral || []).length
      const negative = (platform.negative || []).length
      const total = positive + neutral + negative
      return {
        name: platform.name,
        positive,
        neutral,
        negative,
        total,
        pPos: total ? (positive / total) * 100 : 0,
        pNeu: total ? (neutral / total) * 100 : 0,
        pNeg: total ? (negative / total) * 100 : 0,
      }
    })
    .filter(item => item.total > 0)
    .sort((a, b) => b.negative - a.negative || b.positive - a.positive || a.name.localeCompare(b.name, 'zh'))

  const names = rows.map(item => item.name).reverse()
  const pos = rows.map(item => Number(item.pPos.toFixed(1))).reverse()
  const neu = rows.map(item => Number(item.pNeu.toFixed(1))).reverse()
  const neg = rows.map(item => Number(item.pNeg.toFixed(1))).reverse()
  const counts = Object.fromEntries(rows.map(item => [item.name, item]))

  return {
    animation: false,
    grid: { left: 108, right: 20, top: 40, bottom: 4 },
    legend: {
      top: 0,
      right: 0,
      itemWidth: 8,
      itemHeight: 8,
      itemGap: 14,
      icon: 'circle',
      textStyle: { color: '#64748b', fontSize: 12 },
      data: ['负面', '中性', '正面'],
    },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow', shadowStyle: { color: 'rgba(37, 99, 235, 0.06)' } },
      backgroundColor: 'rgba(15, 23, 42, 0.92)',
      borderWidth: 0,
      padding: [8, 12],
      textStyle: { color: '#fff', fontSize: 12 },
      formatter: (params: Array<{ axisValue: string }>) => {
        const list = Array.isArray(params) ? params : []
        const name = String(list[0]?.axisValue || '')
        const row = counts[name]
        if (!row) return name
        return [
          name,
          '负面 ' + row.negative + ' 条',
          '中性 ' + row.neutral + ' 条',
          '正面 ' + row.positive + ' 条',
        ].join('<br/>')
      },
    },
    xAxis: {
      type: 'value',
      max: 100,
      min: 0,
      axisLabel: { show: false },
      splitLine: { show: false },
      axisLine: { show: false },
      axisTick: { show: false },
    },
    yAxis: {
      type: 'category',
      data: names.length ? names : ['暂无'],
      axisLabel: {
        color: '#334155',
        fontSize: 12,
        fontWeight: 500,
        width: 96,
        overflow: 'truncate',
      },
      axisLine: { show: false },
      axisTick: { show: false },
    },
    series: [
      {
        name: '负面',
        type: 'bar',
        stack: 'pct',
        data: names.length ? neg : [0],
        barWidth: 14,
        barCategoryGap: '36%',
        cursor: 'pointer',
        itemStyle: { color: SENTIMENT_COLOR['负面'], borderRadius: [7, 0, 0, 7] },
      },
      {
        name: '中性',
        type: 'bar',
        stack: 'pct',
        data: names.length ? neu : [0],
        barWidth: 14,
        cursor: 'pointer',
        itemStyle: { color: SENTIMENT_COLOR['中性'] },
      },
      {
        name: '正面',
        type: 'bar',
        stack: 'pct',
        data: names.length ? pos : [0],
        barWidth: 14,
        cursor: 'pointer',
        itemStyle: {
          color: SENTIMENT_COLOR['正面'],
          borderRadius: [0, 7, 7, 0],
        },
      },
    ],
  }
}

function bindPlatformChartClick() {
  if (!platformChart) return
  // 2026-08-04 - 平台情感色块点击打开该平台×情感全部快照列表
  platformChart.off('click')
  platformChart.on('click', (params: { componentType?: string; seriesName?: string; name?: string }) => {
    if (params.componentType !== 'series') return
    const sentiment = String(params.seriesName || '')
    const platformName = String(params.name || '')
    if (!sentiment || !platformName || platformName === '暂无') return
    openPlatformSentimentSnaps(platformName, sentiment)
  })
}

async function renderCharts() {
  if (!dashboard.value) return
  await ensureCharts()
  sentimentChart?.setOption(sentimentDonutOption(dashboard.value.sentiment_pie || []), true)
  platformChart?.setOption(platformSentimentBarOption(dashboard.value.platforms || []), true)
  bindPlatformChartClick()
  await nextTick()
  sentimentChart?.resize()
  platformChart?.resize()
}

async function loadPageData() {
  localLoading.value = true
  loadError.value = ''
  try {
    const tenantId = resolveTenantId()
    // 先快读（不调 DeepSeek），有待解析再后台补一轮
    dashboard.value = await withRetry(() => getBrandAnalysis({ tenant_id: tenantId, parse: false }))
    if (selfLoaded.value) {
      const assetTenantId = dashboard.value?.tenant_id ?? tenantId ?? null
      const response = await withRetry(() => getBrandAsset(assetTenantId))
      localBrandAsset.value = response.asset
    }
    await renderCharts()
    const pending =
      Number(dashboard.value?.parse?.pending_left || 0) +
      Number(dashboard.value?.parse?.description_pending_left || 0)
    if (pending > 0) {
      void getBrandAnalysis({ tenant_id: tenantId, parse: true })
        .then(async (data) => {
          dashboard.value = data
          await renderCharts()
          const descErrs = data.parse?.description_errors || []
          const sentErrs = data.parse?.errors || []
          // 2026-07-28 - 补解析失败曾被静默吞掉，页面一直停在旧「1 组」
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
  // 复用「关联快照」弹层：展示该平台该情感下全部回答快照
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
const snapshotSourceRows = computed(() => {
  const list = snapshotSubtask.value?.reference_list || []
  return list.map((source, index) => ({
    key: `${index}-${source.url || source.title || ''}`,
    href: externalLink(source.url),
    ...citationSourceDisplay(source),
  }))
})

function sentimentCount(label: string) {
  const counts = dashboard.value?.sentiment_counts || {}
  return Number(counts[label] || 0)
}

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

/** 筛选条数字与 AI 描述「组」对齐（多样本一快照多要点后，不能再用样本数当筛选角标） */
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

function onResize() {
  sentimentChart?.resize()
  platformChart?.resize()
}

watch(dashboard, () => {
  platformFilter.value = 'all'
  descPage.value = 1
  void renderCharts()
})

watch([sentimentFilter, platformFilter], () => {
  descPage.value = 1
})

onMounted(() => {
  void loadPageData()
  window.addEventListener('resize', onResize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  sentimentChart?.dispose()
  platformChart?.dispose()
  sentimentChart = null
  platformChart = null
})
</script>

<template>
  <section class="brand-analysis-page">
    <Teleport to="#portal-page-head-extra" defer>
      <div class="ba-head-actions">
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
      <article class="ws-board-card ws-board-profile-strip ba-profile">
        <div class="ws-board-profile-strip-top">
          <div class="ws-board-profile-strip-main">
            <h2 class="ws-board-profile-name">{{ brandName }}</h2>
            <p class="ws-board-profile-brand">
              {{ dashboard.period_label || '—' }}
              · 已购 {{ dashboard.purchased_platforms?.length || 0 }} 平台
            </p>
          </div>
          <span class="ws-board-profile-status">样本 {{ dashboard.sample_count ?? 0 }}</span>
        </div>
        <div class="ba-profile-meta">
          <div class="ws-board-profile-meta-item">
            <span class="ws-board-profile-meta-label">正面</span>
            <span class="ws-board-profile-meta-value">{{ sentimentCount('正面') }}</span>
          </div>
          <div class="ws-board-profile-meta-item">
            <span class="ws-board-profile-meta-label">中性</span>
            <span class="ws-board-profile-meta-value">{{ sentimentCount('中性') }}</span>
          </div>
          <div class="ws-board-profile-meta-item">
            <span class="ws-board-profile-meta-label">负面</span>
            <span class="ws-board-profile-meta-value">{{ sentimentCount('负面') }}</span>
          </div>
        </div>
      </article>

      <div class="ws-board-hero-row ba-charts">
        <article class="ws-board-card ba-chart-card">
          <div class="ws-board-card-head">
            <div class="ws-board-card-title" style="margin:0">情感分布</div>
          </div>
          <div ref="sentimentChartEl" class="ba-chart-el" />
        </article>
        <article class="ws-board-card ba-chart-card">
          <div class="ws-board-card-head">
            <div class="ws-board-card-title" style="margin:0">平台情感</div>
          </div>
          <div ref="platformChartEl" class="ba-chart-el" />
        </article>
      </div>

      <div class="ba-filter-bar">
        <span class="ba-filter-label">情感筛选</span>
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

.ba-profile {
  margin-bottom: 20px;
}

.ba-profile-meta {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.ba-charts {
  margin-bottom: 20px;
}

.ba-chart-card {
  margin-bottom: 0;
  height: 100%;
  box-sizing: border-box;
}

.ba-chart-el {
  width: 100%;
  height: 300px;
}

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
  font-size: 13px;
  font-weight: 700;
  color: #0f172a;
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
  .ba-profile-meta {
    grid-template-columns: 1fr;
  }

  .ba-charts {
    grid-template-columns: 1fr;
  }

  .ba-chart-el {
    height: 260px;
  }
}
</style>
