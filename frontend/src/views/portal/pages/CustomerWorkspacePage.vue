<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { AlertTriangle, ChevronDown, ChevronRight, Clock3, HelpCircle, RefreshCw, Search } from '@lucide/vue'
import { useWorkspaceEnter } from '../../../composables/useCountUp'
import WorkspaceCountUp from '../components/WorkspaceCountUp.vue'
import { useCustomerWorkspace } from '../composables/useCustomerWorkspace'
import {
  useWorkspaceCampusCharts,
  watchWorkspaceCampusCharts,
  type WorkspaceCampusChartData,
} from '../composables/useWorkspaceCampusCharts'
import type { WorkspaceTrendPreset } from '../../../utils/customerMonitorDate'

const {
  brief,
  loading,
  loadError,
  alertsExpanded,
  alertsSectionRef,
  alertsFocused,
  heroTone,
  statusBadge,
  primaryAction,
  visibleAlerts,
  hiddenAlertCount,
  loadBrief,
  navigateToMenu,
  focusWorkspaceAlerts,
  openAlertTarget,
  realtimeMenuName,
  canOpenRealtime,
  formatKpiDelta,
  kpiDeltaClass,
  platformLabelMap,
  greetingLabel,
  trendPreset,
  trendStartDate,
  trendEndDate,
  trendMaxDate,
  trendPeriodLabel,
  applyTrendPreset,
  onCustomTrendDateChange,
  platformPeriodLabel,
  healthScore,
  healthScoreExplanation,
  healthScoreSummary,
  workspaceHeadline,
  miniKpis,
  trendBars,
  platformRankList,
  todoItems,
  showTodoStrip,
  activeRound,
  roundSummaryLine,
} = useCustomerWorkspace()

const { enterActive, enterGeneration } = useWorkspaceEnter(() => brief.value)
void alertsSectionRef

const displayName = computed(() => brief.value?.company_name || brief.value?.brand_name || '当前企业')
const showEmptyGuide = computed(() => heroTone.value === 'empty' && !loading.value)

const trendPresetOptions: Array<{ value: WorkspaceTrendPreset; label: string }> = [
  { value: '7d', label: '近7日' },
  { value: 'month', label: '月' },
  { value: 'quarter', label: '季度' },
  { value: 'year', label: '年' },
  { value: 'custom', label: '自定义' },
]

const scheduleLine = computed(() => {
  const active = activeRound.value
  if (!active) return '暂无已完成监测批次'
  const prefix = active.usingPrevious ? '上一轮监测' : '最新监测批次'
  return `${prefix} · 已完成 ${active.completed} 条`
})

const emptyHint = computed(() => {
  if (activeRound.value) return ''
  return '暂无已完成检测结果，请等待监测任务返回。'
})

const sampleTotal = computed(() => activeRound.value?.completed ?? 0)

const rankGaugeScore = computed(() => {
  const rank = brief.value?.kpis.avg_brand_rank
  if (rank == null) return 0
  return Math.max(0, Math.min(100, 100 - (rank - 1) * 20))
})

const trendChartRef = ref<HTMLDivElement | null>(null)
const healthGaugeRef = ref<HTMLDivElement | null>(null)
const platformRankChartRef = ref<HTMLDivElement | null>(null)

const { renderCharts, bindResize } = useWorkspaceCampusCharts({
  trend: trendChartRef,
  intent: ref(null),
  mention: ref(null),
  healthGauge: healthGaugeRef,
  rankGauge: ref(null),
  top3Gauge: ref(null),
  platformRank: platformRankChartRef,
})

const chartData = computed<WorkspaceCampusChartData | null>(() => {
  if (!brief.value) return null
  const activeRanks = platformRankList.value
  return {
    trendLabels: trendBars.value.map(bar => bar.label),
    trendValues: trendBars.value.map(bar => bar.value),
    intentRows: [],
    intentTotal: 0,
    mentionRows: [],
    mentionRate: brief.value.kpis.brand_mention_rate,
    healthScore: healthScore.value,
    rankGaugeScore: rankGaugeScore.value,
    avgBrandRank: brief.value.kpis.avg_brand_rank,
    top3Rate: brief.value.kpis.top3_rate ?? 0,
    platformRankLabels: activeRanks.map(row => platformLabelMap[row.platform] || row.platform),
    platformRankValues: activeRanks.map(row => row.mention_rate),
    platformRankSamples: activeRanks.map(row => row.sample_count),
  }
})

watchWorkspaceCampusCharts(chartData, renderCharts, bindResize)

watch(showEmptyGuide, (empty) => {
  if (!empty && chartData.value) {
    renderCharts(chartData.value).then(() => bindResize())
  }
})
</script>

<template>
  <section class="customer-workspace-page ws-campus">
    <header class="ws-campus-head">
      <div>
        <h1>工作台</h1>
        <p>{{ displayName }} · 监测简报 · {{ scheduleLine }}</p>
      </div>
      <div class="ws-campus-head-actions">
        <button
          v-if="statusBadge.tone === 'warn'"
          type="button"
          class="ws-campus-badge is-clickable"
          :class="`tone-${statusBadge.tone}`"
          title="查看需关注提醒"
          @click="focusWorkspaceAlerts"
        >
          {{ statusBadge.label }}
        </button>
        <span v-else class="ws-campus-badge" :class="`tone-${statusBadge.tone}`">{{ statusBadge.label }}</span>
        <button
          v-if="primaryAction"
          type="button"
          class="ws-campus-primary"
          @click="navigateToMenu(primaryAction.menu)"
        >
          {{ primaryAction.label }}
          <ChevronRight />
        </button>
        <button type="button" class="ws-campus-ghost" :disabled="loading" @click="loadBrief">
          <RefreshCw :class="{ spinning: loading }" />
          刷新
        </button>
      </div>
    </header>

    <div v-if="loadError" class="ws-campus-error">
      {{ loadError }}
      <button type="button" class="ws-campus-ghost" @click="loadBrief">重试</button>
    </div>

    <div v-if="loading && !brief" class="ws-campus-loading">
      <div v-for="n in 6" :key="n" class="ws-campus-skeleton" />
    </div>

    <section v-else-if="showEmptyGuide" class="ws-campus-empty">
      <Clock3 />
      <h3>等待首次监测结果</h3>
      <p>{{ emptyHint }}</p>
      <ul>
        <li>系统会自动发起检测并同步结果，无需手动提交</li>
        <li>结果返回后，这里会展示健康分、平台表现与露出趋势</li>
        <li>可先查看{{ realtimeMenuName }}页了解任务结构，或维护品牌/竞品配置</li>
      </ul>
      <button v-if="canOpenRealtime" type="button" class="ws-campus-primary" @click="navigateToMenu('customer.realtime')">
        <Search />
        查看{{ realtimeMenuName }}
      </button>
    </section>

    <template v-else-if="brief">
      <!-- ① 简报 + ② 露出率趋势（一体） -->
      <article class="ws-campus-hero">
        <section class="ws-campus-hero-summary ws-campus-greet" :class="heroTone">
          <div class="ws-campus-greet-top">
            <div class="ws-campus-greet-copy">
              <div class="ws-campus-greet-hello">{{ greetingLabel() }}，{{ workspaceHeadline }}</div>
            </div>
            <div class="ws-campus-health-block">
              <div ref="healthGaugeRef" class="ws-campus-chart ws-campus-chart-health" />
              <div class="ws-campus-health-label">
                <span>GEO 健康分</span>
                <el-tooltip placement="left" effect="light" :show-after="200">
                  <template #content>
                    <div class="ws-health-score-tip">
                      <p v-for="(line, index) in healthScoreExplanation" :key="index">{{ line }}</p>
                    </div>
                  </template>
                  <button type="button" class="ws-health-score-help" aria-label="健康分计算说明">
                    <HelpCircle :size="13" />
                  </button>
                </el-tooltip>
              </div>
            </div>
          </div>
          <div class="ws-campus-greet-foot">
            <div class="ws-campus-greet-stat">
              <b>
                <WorkspaceCountUp
                  :value="sampleTotal"
                  :active="enterActive"
                  :generation="enterGeneration"
                  :duration="900"
                />
              </b>
              <span>本轮完成样本</span>
            </div>
            <span v-if="healthScoreSummary" class="ws-campus-greet-divider" aria-hidden="true" />
            <div v-if="healthScoreSummary" class="ws-campus-greet-stat is-summary">
              <span>{{ healthScoreSummary }}</span>
            </div>
          </div>
        </section>

        <section class="ws-campus-hero-trend">
          <div class="ws-campus-card-head ws-campus-card-head-trend">
            <h3>露出率趋势</h3>
            <div class="ws-campus-date-filter">
              <div class="ws-campus-date-presets">
                <button
                  v-for="option in trendPresetOptions"
                  :key="option.value"
                  type="button"
                  :class="{ active: trendPreset === option.value }"
                  @click="applyTrendPreset(option.value)"
                >
                  {{ option.label }}
                </button>
              </div>
              <span
                v-if="trendPreset !== 'custom' && trendPeriodLabel"
                class="ws-campus-date-range"
                :title="`${trendStartDate} ~ ${trendEndDate}`"
              >{{ trendPeriodLabel }}</span>
              <div v-if="trendPreset === 'custom'" class="ws-campus-custom-dates">
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
            </div>
          </div>
          <div ref="trendChartRef" class="ws-campus-chart ws-campus-chart-trend" />
          <p v-if="!trendBars.length" class="ws-campus-mini-empty ws-campus-chart-empty">暂无趋势数据</p>
        </section>
      </article>

      <!-- ③ 三 KPI -->
      <div class="ws-campus-kpi-strip">
        <article v-for="kpi in miniKpis" :key="kpi.key" class="ws-campus-kpi-card">
          <span>{{ kpi.label }}</span>
          <b>
            <template v-if="kpi.value != null">
              <WorkspaceCountUp
                :value="kpi.value"
                :active="enterActive"
                :generation="enterGeneration"
                :decimals="kpi.decimals"
                :duration="900"
              />{{ kpi.unit }}
            </template>
            <template v-else>—</template>
          </b>
          <em
            v-if="kpi.delta != null"
            :class="kpiDeltaClass(kpi.delta, kpi.lowerIsBetter)"
          >
            {{ formatKpiDelta(kpi.delta, kpi.unit || '', kpi.lowerIsBetter, kpi.deltaKind || 'default') }}
          </em>
          <em v-else class="is-muted">较上一轮 —</em>
        </article>
      </div>

      <!-- ④ 平台横条 -->
      <article class="ws-campus-card ws-campus-platform-panel">
        <div class="ws-campus-card-head">
          <h3>已购平台表现</h3>
          <span class="ws-campus-chip">{{ platformPeriodLabel }}</span>
        </div>
        <div ref="platformRankChartRef" class="ws-campus-chart ws-campus-chart-rank" />
        <p v-if="!platformRankList.length" class="ws-campus-mini-empty">暂无平台数据</p>
      </article>

      <!-- 待办（仅有数量时显示） -->
      <div v-if="showTodoStrip" class="ws-campus-todo-inline">
        <button
          v-for="item in todoItems.filter(row => row.count > 0)"
          :key="item.key"
          type="button"
          class="ws-campus-todo-chip"
          :class="item.tone"
          @click="navigateToMenu(item.menu)"
        >
          <b>{{ item.count }}</b>
          <span>{{ item.label }}</span>
          <ChevronRight />
        </button>
      </div>

      <!-- ⑤ 本轮监测摘要 -->
      <p class="ws-campus-round-summary">{{ roundSummaryLine }}</p>

      <!-- 告警 -->
      <div
        v-if="visibleAlerts.length"
        ref="alertsSectionRef"
        class="ws-campus-alerts"
        :class="{ 'is-focused': alertsFocused }"
      >
        <button
          v-for="alert in visibleAlerts"
          :key="alert.message"
          type="button"
          class="ws-campus-alert"
          :class="alert.level"
          @click="openAlertTarget(alert)"
        >
          <AlertTriangle v-if="alert.level === 'warn'" />
          <Clock3 v-else />
          <span>{{ alert.message }}</span>
          <ChevronRight />
        </button>
        <button
          v-if="hiddenAlertCount > 0"
          type="button"
          class="ws-campus-alert-toggle"
          @click="alertsExpanded = true"
        >
          展开其余 {{ hiddenAlertCount }} 条提醒
          <ChevronDown />
        </button>
        <button
          v-else-if="alertsExpanded && brief.alerts.length > 2"
          type="button"
          class="ws-campus-alert-toggle"
          @click="alertsExpanded = false"
        >
          收起提醒
          <ChevronDown class="is-flipped" />
        </button>
      </div>
    </template>
  </section>
</template>
