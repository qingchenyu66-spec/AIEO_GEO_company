<script setup lang="ts">
import { computed, nextTick, onUnmounted, ref, watch } from 'vue'
import {
  BarChart3,
  ChevronDown,
  Clock3,
  FileText,
  Search,
  Tag,
  TrendingUp,
} from '@lucide/vue'
import type { ECharts } from 'echarts/core'
import WorkspaceCountUp from '../components/WorkspaceCountUp.vue'
import { useWorkspaceEnter } from '../../../composables/useCountUp'
import { loadEchartsRuntime } from '../../../utils/echartsLoader'
import { useCustomerWorkspace } from '../composables/useCustomerWorkspace'
import {
  useWorkspaceCampusCharts,
  watchWorkspaceCampusCharts,
  type WorkspaceCampusChartData,
} from '../composables/useWorkspaceCampusCharts'
import {
  formatBoardDateRange,
  formatBoardScheduleLine,
  platformBarColor,
  useKeywordPlatformHeatmapChart,
  useWorkspaceBoardExtras,
} from '../composables/useWorkspaceBoardExtras'
import { getPlatformMeta } from '../platformMeta'
import type { WorkspaceTrendPreset } from '../../../utils/customerMonitorDate'

const boardEnabled = ref(true)

const {
  brief,
  loading,
  periodSwitching,
  loadError,
  loadBrief,
  navigateToMenu,
  canOpenRealtime,
  realtimeMenuName,
  formatKpiDelta,
  kpiDeltaClass,
  trendPreset,
  trendStartDate,
  trendEndDate,
  trendMaxDate,
  applyTrendPreset,
  onCustomTrendDateChange,
  trendPeriodLabel,
  periodCompareLabel,
  platformPeriodLabel,
  miniKpis,
  trendBars,
  platformRankList,
} = useCustomerWorkspace()

const {
  brandAsset,
  matrixLoading,
  matrixError,
  keywordChips,
  keywordPlatformHeatmap,
  requestMatrixLoad,
  reloadExtras,
} = useWorkspaceBoardExtras(brief, trendStartDate, trendEndDate, boardEnabled)

const { enterActive, enterGeneration } = useWorkspaceEnter(() => (
  // 只在「从无到有」时触发入场；切周期 brief 一直存在，避免 KPI 连跳三次
  brief.value ? 'ready' : null
))

async function refreshAll() {
  await loadBrief({ force: true })
  await reloadExtras()
}

/** Below-fold sections mount after first paint so hero/KPI/trend paint first. */
const belowFoldReady = ref(false)
let belowFoldTimer: ReturnType<typeof setTimeout> | null = null

function scheduleBelowFold() {
  if (belowFoldReady.value) return
  if (belowFoldTimer != null) clearTimeout(belowFoldTimer)
  belowFoldTimer = setTimeout(() => {
    belowFoldReady.value = true
    belowFoldTimer = null
  }, 0)
}

const showEmptyGuide = computed(() => {
  if (loading.value || !brief.value) return false
  const data = brief.value
  return data.kpis.ranking_sample_count === 0
    && data.kpis.exposure_sample_count === 0
    && !data.recent_snapshots.length
})

const displayName = computed(() => (
  brief.value?.company_name || brandAsset.value?.company_full_name || brief.value?.brand_name || '当前企业'
))

const monitorKeywordLabels = computed(() => (
  keywordChips.value.map(chip => chip.name).filter(Boolean)
))

const brandLine = computed(() => {
  const keywordCount = monitorKeywordLabels.value.length || brief.value?.kpis.keyword_group_count || 0
  const platformCount = brief.value?.purchased_platforms.length || 0
  return `${keywordCount} 个监控词 · 已购 ${platformCount} 个平台`
})

const monitorPeriod = computed(() => {
  if (!brief.value) return '—'
  return formatBoardDateRange(brief.value.start_at, brief.value.end_at)
})

/** 企业合同/服务起止（档案信息，不随数据周期筛选变化） */
const servicePeriod = computed(() => {
  const start = brief.value?.service_start_date?.trim() || ''
  const end = brief.value?.service_end_date?.trim() || ''
  if (!start && !end) return '未配置'
  return `${start || '未开始'} ~ ${end || '长期'}`
})

const selectedPeriodRange = computed(() => (
  formatBoardDateRange(trendStartDate.value, trendEndDate.value)
))

const scheduleLine = computed(() => formatBoardScheduleLine(brandAsset.value, brief.value))

const platformInsightNote = computed(() => {
  const leader = [...(brief.value?.platform_highlights || [])]
    .filter(row => row.sample_count > 0)
    .sort((a, b) => b.mention_rate - a.mention_rate)[0]
  const weak = [...(brief.value?.platform_highlights || [])]
    .filter(row => row.sample_count > 0)
    .sort((a, b) => a.mention_rate - b.mention_rate)[0]
  const parts: string[] = []
  if (leader) {
    parts.push(`${getPlatformMeta(leader.platform).name} 提及率最高（${leader.mention_rate.toFixed(1)}%）`)
  }
  if (weak && weak.platform !== leader?.platform) {
    parts.push(`${getPlatformMeta(weak.platform).name} 相对偏弱（${weak.mention_rate.toFixed(1)}%）`)
  }
  const warn = brief.value?.alerts.find(alert => alert.level === 'warn')
  if (warn) parts.push(warn.message)
  return parts.join('；') || '持续跟踪各平台提及率与排名变化'
})

const conclusionBadge = computed(() => {
  const zeroPlatforms = (brief.value?.platform_highlights || [])
    .filter(row => row.sample_count > 0 && row.mention_rate <= 0)
  if (zeroPlatforms.length >= 2) return { label: '需关注', calm: false }
  const mention = miniKpis.value.find(kpi => kpi.key === 'mention')?.value
  if (mention != null && mention < 25) return { label: '需关注', calm: false }
  if (brief.value?.alerts.some(alert => alert.level === 'warn')) {
    return { label: '需关注', calm: false }
  }
  return { label: '持续跟踪', calm: true }
})

const trendPresetOptions: Array<{ value: WorkspaceTrendPreset; label: string }> = [
  { value: '7d', label: '近7天' },
  { value: 'month', label: '本月' },
  { value: 'quarter', label: '本季' },
  { value: 'year', label: '本年' },
  { value: 'custom', label: '自定义' },
]

const selectedPeriodPresetLabel = computed(() => (
  trendPresetOptions.find(item => item.value === trendPreset.value)?.label || '自定义'
))

const exposureStats = computed(() => {
  const rows = platformRankList.value.filter(row => row.sample_count > 0)
  const totalSamples = rows.reduce((sum, row) => sum + row.sample_count, 0)
  const platformCount = rows.length
  const byRate = [...rows].sort((a, b) => b.mention_rate - a.mention_rate)
  return {
    totalSamples,
    platformCount,
    highest: byRate[0] ?? null,
    lowest: byRate.length ? byRate[byRate.length - 1] : null,
  }
})

const exposureDonutRef = ref<HTMLDivElement | null>(null)
let exposureDonutChart: ECharts | null = null

// 2026-07-29 - 用户要保留环图；只修平台中文名（勿改成柱图）
const exposureDonutRows = computed(() => (
  [...platformRankList.value.filter(row => row.sample_count > 0)]
    .sort((a, b) => b.mention_rate - a.mention_rate)
    .map(row => ({
      name: getPlatformMeta(row.platform).name,
      value: Math.max(0, row.mention_rate),
      color: platformBarColor(row.platform),
    }))
))

async function renderExposureDonut() {
  const el = exposureDonutRef.value
  if (!el || !exposureDonutRows.value.length) {
    exposureDonutChart?.clear()
    return
  }
  const runtime = await loadEchartsRuntime('portal')
  exposureDonutChart = runtime.getInstanceByDom(el) || runtime.init(el)
  const mentionRate = brief.value?.kpis.brand_mention_rate ?? 0
  const centerMain = `${Number(mentionRate).toFixed(1)}%`
  exposureDonutChart.setOption({
    animation: false,
    color: exposureDonutRows.value.map(row => row.color),
    tooltip: {
      trigger: 'item',
      formatter: (params: { name: string; value: number; marker: string }) => (
        `${params.marker}${params.name}<br/>露出率 ${Number(params.value).toFixed(1)}%`
      ),
    },
    series: [{
      type: 'pie',
      radius: ['46%', '70%'],
      center: ['50%', '50%'],
      padAngle: 1.2,
      minShowLabelAngle: 4,
      itemStyle: {
        borderRadius: 5,
        borderColor: '#fff',
        borderWidth: 2,
      },
      label: {
        show: true,
        formatter: (params: { name: string; value: number }) => (
          `${params.name}  ${Number(params.value).toFixed(1)}%`
        ),
        color: '#475569',
        fontSize: 12,
        lineHeight: 16,
      },
      labelLine: {
        show: true,
        length: 16,
        length2: 12,
        smooth: 0.2,
        lineStyle: { width: 1, color: '#cbd5e1' },
      },
      emphasis: {
        scale: true,
        scaleSize: 6,
        label: {
          fontWeight: 650,
          color: '#0f172a',
        },
      },
      data: exposureDonutRows.value.map(row => ({
        name: row.name,
        value: row.value,
        itemStyle: { color: row.color },
      })),
    }],
    graphic: [
      {
        type: 'text',
        left: 'center',
        top: '44%',
        style: {
          text: centerMain,
          fill: '#0f172a',
          fontSize: 26,
          fontWeight: 700,
          textAlign: 'center',
        },
      },
      {
        type: 'text',
        left: 'center',
        top: '56%',
        style: {
          text: '综合露出',
          fill: '#94a3b8',
          fontSize: 12,
          textAlign: 'center',
        },
      },
    ],
  }, true)
  exposureDonutChart.resize()
}

watch([exposureDonutRows, platformRankList, belowFoldReady], () => {
  if (!belowFoldReady.value) return
  void renderExposureDonut()
}, { flush: 'post' })

const trendChartRef = ref<HTMLDivElement | null>(null)
const heatmapChartRef = ref<HTMLDivElement | null>(null)
const heatmapSectionRef = ref<HTMLElement | null>(null)

const { renderCharts, bindResize } = useWorkspaceCampusCharts({
  trend: trendChartRef,
  intent: ref(null),
  mention: ref(null),
  healthGauge: ref(null),
  rankGauge: ref(null),
  top3Gauge: ref(null),
  platformRank: ref(null),
})

const chartData = computed<WorkspaceCampusChartData | null>(() => {
  if (!brief.value) return null
  return {
    trendLabels: trendBars.value.map(bar => bar.label),
    trendValues: trendBars.value.map(bar => bar.value),
    trendEmptyFlags: trendBars.value.map(bar => bar.empty),
    intentRows: [],
    intentTotal: 0,
    mentionRows: [],
    mentionRate: brief.value.kpis.brand_mention_rate,
    healthScore: null,
    rankGaugeScore: 0,
    avgBrandRank: brief.value.kpis.avg_brand_rank,
    top3Rate: brief.value.kpis.top3_rate ?? 0,
    platformRankLabels: [],
    platformRankValues: [],
    platformRankSamples: [],
  }
})

watchWorkspaceCampusCharts(chartData, renderCharts, bindResize)

const { renderHeatmap, disposeHeatmap } = useKeywordPlatformHeatmapChart(heatmapChartRef, keywordPlatformHeatmap)

const showHeatmapLoading = computed(() => (
  matrixLoading.value && !keywordPlatformHeatmap.value?.keywords.length
))

let heatmapObserver: IntersectionObserver | null = null

function setupHeatmapObserver() {
  if (heatmapObserver) return
  const section = heatmapSectionRef.value
  if (!section) return
  if (typeof IntersectionObserver === 'undefined') {
    requestMatrixLoad()
    return
  }
  heatmapObserver = new IntersectionObserver((entries) => {
    if (entries.some(entry => entry.isIntersecting)) {
      requestMatrixLoad()
      heatmapObserver?.disconnect()
      heatmapObserver = null
    }
  }, { rootMargin: '80px 0px' })
  heatmapObserver.observe(section)
}

watch(keywordPlatformHeatmap, () => {
  if (!belowFoldReady.value) return
  void renderHeatmap()
}, { flush: 'post' })

watch(showEmptyGuide, (empty) => {
  if (!empty && chartData.value) {
    renderCharts(chartData.value).then(() => bindResize())
  }
})

watch([belowFoldReady, boardEnabled], () => {
  if (belowFoldReady.value && boardEnabled.value) void renderHeatmap()
}, { flush: 'post' })

watch(() => brief.value, async (data) => {
  if (!data) return
  void loadEchartsRuntime('portal')
  scheduleBelowFold()
  await nextTick()
}, { immediate: true })

watch(belowFoldReady, async (ready) => {
  if (!ready || !brief.value) return
  await nextTick()
  setupHeatmapObserver()
  void renderExposureDonut()
})

onUnmounted(() => {
  if (belowFoldTimer != null) clearTimeout(belowFoldTimer)
  heatmapObserver?.disconnect()
  disposeHeatmap()
  exposureDonutChart?.dispose()
  exposureDonutChart = null
})
</script>

<template>
  <section class="customer-workspace-page ws-board">
    <div v-if="loadError" class="ws-board-error">
      {{ loadError }}
      <button type="button" class="ws-board-btn" @click="refreshAll">重试</button>
    </div>

    <div v-if="loading && !brief" class="ws-board-loading">
      <div v-for="n in 6" :key="n" class="ws-board-skeleton" />
    </div>

    <section v-else-if="showEmptyGuide" class="ws-board-empty">
      <Clock3 :size="32" />
      <h3>等待首次监测结果</h3>
      <p>暂无已完成检测结果，请等待监测任务返回。</p>
      <button
        v-if="canOpenRealtime"
        type="button"
        class="ws-board-btn ws-board-btn-primary"
        @click="navigateToMenu('customer.realtime')"
      >
        <Search :size="16" />
        查看{{ realtimeMenuName }}
      </button>
    </section>

    <template v-else-if="brief">
      <div class="ws-board-insight-row" :class="{ 'is-period-switching': periodSwitching }">
        <article class="ws-board-card ws-board-conclusion-card">
          <div class="ws-board-conclusion-head">
            <div class="ws-board-conclusion-title-wrap">
              <div class="ws-board-conclusion-title">本期结论</div>
              <p v-if="trendPeriodLabel" class="ws-board-conclusion-sub">
                {{ trendPeriodLabel }} · 区间汇总 · {{ periodCompareLabel }}
              </p>
            </div>
            <div class="ws-board-conclusion-head-aside">
              <span class="ws-board-conclusion-badge" :class="{ 'is-calm': conclusionBadge.calm }">
                {{ conclusionBadge.label }}
              </span>
              <div class="ws-board-period-inline" role="region" aria-label="数据周期">
                <div class="ws-board-tabs" :aria-busy="periodSwitching">
                  <button
                    v-for="option in trendPresetOptions"
                    :key="option.value"
                    type="button"
                    class="ws-board-tab"
                    :class="{ active: trendPreset === option.value }"
                    @click="applyTrendPreset(option.value)"
                  >
                    {{ option.label }}
                  </button>
                </div>
                <span v-if="periodSwitching" class="ws-board-period-bar-hint">正在切换…</span>
              </div>
            </div>
          </div>
          <div v-if="trendPreset === 'custom'" class="ws-board-date-inputs ws-board-date-inputs--inline">
            <input
              v-model="trendStartDate"
              type="date"
              :max="trendEndDate"
              @change="onCustomTrendDateChange"
            >
            <span>至</span>
            <input
              v-model="trendEndDate"
              type="date"
              :min="trendStartDate"
              :max="trendMaxDate"
              @change="onCustomTrendDateChange"
            >
          </div>
          <div class="ws-board-conclusion-metrics">
            <div
              v-for="kpi in miniKpis"
              :key="kpi.key"
              class="ws-board-conclusion-metric"
              :class="{ 'is-primary': kpi.key === 'mention' }"
            >
              <div class="ws-board-conclusion-metric-label">{{ kpi.label }}</div>
              <div class="ws-board-conclusion-metric-value">
                <template v-if="kpi.value != null">
                  <WorkspaceCountUp
                    :value="kpi.value"
                    :active="enterActive"
                    :generation="enterGeneration"
                    :decimals="kpi.decimals"
                  />{{ kpi.unit }}
                </template>
                <template v-else>—</template>
              </div>
              <div
                v-if="kpi.delta != null"
                class="ws-board-conclusion-metric-delta"
                :class="kpiDeltaClass(kpi.delta, kpi.lowerIsBetter)"
              >
                {{ formatKpiDelta(
                  kpi.delta,
                  kpi.unit || '',
                  kpi.lowerIsBetter,
                  kpi.deltaKind || 'default',
                  kpi.compareLabel || (kpi.periodMode ? periodCompareLabel : '较上一轮'),
                ) }}
              </div>
              <div v-else class="ws-board-conclusion-metric-delta is-muted">
                {{ kpi.compareLabel || periodCompareLabel }} —
              </div>
              <div v-if="kpi.sampleHint" class="ws-board-conclusion-metric-delta is-muted">
                {{ kpi.sampleHint }}
              </div>
            </div>
          </div>
        </article>

        <article class="ws-board-card ws-board-trend-card">
          <div class="ws-board-card-head">
            <div class="ws-board-card-title" style="margin:0">
              <TrendingUp :size="18" />
              提及率趋势
            </div>
            <span class="ws-board-section-period">{{ selectedPeriodPresetLabel }} · {{ selectedPeriodRange }}</span>
          </div>
          <div ref="trendChartRef" class="ws-board-chart-trend ws-board-chart-trend-hero" />
          <p v-if="!trendBars.length" class="ws-board-mini-empty">暂无趋势数据</p>
        </article>
      </div>

      <!-- 2026-08-20 - 首屏让结论上移 - 公司/监控词默认折叠，摘要行仍露企业名 -->
      <details class="ws-board-service-info">
        <summary class="ws-board-service-summary">
          <span class="ws-board-service-summary-label">
            服务信息
            <em>{{ displayName }}</em>
          </span>
          <ChevronDown class="ws-board-service-chevron" :size="16" aria-hidden="true" />
        </summary>
        <div class="ws-board-profile-row">
          <article class="ws-board-card ws-board-profile-strip">
            <div class="ws-board-profile-strip-top">
              <div class="ws-board-profile-strip-main">
                <h2 class="ws-board-profile-name">{{ displayName }}</h2>
                <p class="ws-board-profile-brand">{{ brandLine }}</p>
              </div>
              <span class="ws-board-profile-status">正常运行 · {{ platformPeriodLabel }}</span>
            </div>
            <div class="ws-board-profile-strip-meta">
              <div class="ws-board-profile-meta-item">
                <span class="ws-board-profile-meta-label">监测节奏</span>
                <span class="ws-board-profile-meta-value">{{ scheduleLine }}</span>
              </div>
              <div class="ws-board-profile-meta-item">
                <span class="ws-board-profile-meta-label">服务周期</span>
                <span class="ws-board-profile-meta-value">{{ servicePeriod }}</span>
              </div>
              <div class="ws-board-profile-meta-item">
                <span class="ws-board-profile-meta-label">官网</span>
                <a
                  v-if="brandAsset?.official_url"
                  class="ws-board-profile-meta-value is-link"
                  :href="brandAsset.official_url"
                  target="_blank"
                  rel="noopener"
                >{{ brandAsset.official_url }}</a>
                <span v-else class="ws-board-profile-meta-value is-muted">未配置</span>
              </div>
            </div>
          </article>

          <article class="ws-board-card ws-board-keywords-card">
            <div class="ws-board-card-head">
              <div class="ws-board-card-title" style="margin:0">
                <Tag :size="18" />
                监控词
              </div>
              <span class="ws-board-section-period">{{ monitorKeywordLabels.length }} 个</span>
            </div>
            <div v-if="monitorKeywordLabels.length" class="ws-board-keywords-wrap">
              <div class="ws-board-keywords-metrics">
                <div
                  v-for="name in monitorKeywordLabels"
                  :key="name"
                  class="ws-board-keyword-metric"
                  :title="name"
                >
                  <div class="ws-board-keyword-metric-value">{{ name }}</div>
                </div>
              </div>
            </div>
            <p v-else class="ws-board-mini-empty">暂无监控词配置</p>
          </article>
        </div>
      </details>

      <template v-if="belowFoldReady">
      <article class="ws-board-card ws-board-exposure-card">
        <div class="ws-board-exposure-head">
          <div class="ws-board-card-title" style="margin:0">
            <FileText :size="18" />
            平台露出率
          </div>
          <p v-if="platformInsightNote" class="ws-board-exposure-note">{{ platformInsightNote }}</p>
        </div>
        <div v-if="platformRankList.length" class="ws-board-exposure-body">
          <div class="ws-board-exposure-stats">
            <div class="ws-board-stat-mini">
              <div
                class="ws-board-stat-mini-label"
                title="当前数据周期内，各平台监测样本量合计（推荐类样本条数）"
              >监测样本</div>
              <div class="ws-board-stat-mini-value">{{ exposureStats.totalSamples }}</div>
            </div>
            <div class="ws-board-stat-mini">
              <div class="ws-board-stat-mini-label">覆盖平台</div>
              <div class="ws-board-stat-mini-value">{{ exposureStats.platformCount }}</div>
            </div>
            <div v-if="exposureStats.highest" class="ws-board-stat-mini">
              <div class="ws-board-stat-mini-label">最高露出</div>
              <div class="ws-board-stat-mini-value is-sm">
                {{ getPlatformMeta(exposureStats.highest.platform).name }}
              </div>
              <div class="ws-board-stat-mini-delta is-up">
                {{ exposureStats.highest.mention_rate.toFixed(1) }}%
              </div>
            </div>
            <div v-if="exposureStats.lowest" class="ws-board-stat-mini">
              <div class="ws-board-stat-mini-label">最低露出</div>
              <div class="ws-board-stat-mini-value is-sm">
                {{ getPlatformMeta(exposureStats.lowest.platform).name }}
              </div>
              <div class="ws-board-stat-mini-delta">
                {{ exposureStats.lowest.mention_rate.toFixed(1) }}%
              </div>
            </div>
          </div>
          <div ref="exposureDonutRef" class="ws-board-chart-donut" />
        </div>
        <p v-else class="ws-board-mini-empty">暂无平台数据</p>
      </article>

      <article ref="heatmapSectionRef" class="ws-board-card">
        <div class="ws-board-card-title">
          <BarChart3 :size="18" />
          词 × 平台提及率
          <span
            class="ws-board-title-tip"
            tabindex="0"
            data-tip="格子分数 = 该监控词在该平台样本中品牌提及率 × 100（与综合露出同口径：有效排名非空才计提及）。— 表示该词×平台暂无样本。"
          >?</span>
        </div>
        <div v-if="showHeatmapLoading" class="ws-board-mini-empty">热力图加载中…</div>
        <div v-else-if="keywordPlatformHeatmap?.keywords.length" class="ws-board-chart-heat-wrap">
          <div ref="heatmapChartRef" class="ws-board-chart-heat" />
        </div>
        <p v-else class="ws-board-mini-empty">暂无词×平台矩阵数据</p>
        <p v-if="matrixError && keywordPlatformHeatmap?.keywords.length" class="ws-board-matrix-hint">
          {{ matrixError }}
        </p>
      </article>
      </template>
      <div v-else class="ws-board-below-fold-placeholder">
        <div class="ws-board-skeleton" />
        <div class="ws-board-skeleton" />
      </div>

      <footer class="ws-board-foot">
        监测周期 {{ monitorPeriod }} · 已购 {{ brief.purchased_platforms.length }} 平台 · GEO Monitor
      </footer>
    </template>
  </section>
</template>
