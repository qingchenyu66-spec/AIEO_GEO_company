<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { AlertTriangle, ChevronDown, ChevronRight, Clock3, RefreshCw, Search } from '@lucide/vue'
import { useWorkspaceEnter } from '../../../composables/useCountUp'
import WorkspaceCountUp from '../components/WorkspaceCountUp.vue'
import { useCustomerWorkspace } from '../composables/useCustomerWorkspace'
import {
  useWorkspaceCampusCharts,
  watchWorkspaceCampusCharts,
  type WorkspaceCampusChartData,
} from '../composables/useWorkspaceCampusCharts'

const {
  brief,
  loading,
  alertsExpanded,
  heroTone,
  statusBadge,
  primaryAction,
  visibleAlerts,
  hiddenAlertCount,
  loadBrief,
  navigateToMenu,
  openSnapshot,
  alertTargetMenu,
  realtimeMenuName,
  formatDateTime,
  formatKpiDelta,
  kpiDeltaClass,
  snapshotMetric,
  snapshotIntentClass,
  snapshotIntentLabel,
  platformLabelMap,
  greetingLabel,
  healthScore,
  workspaceHeadline,
  miniKpis,
  trendBars,
  platformRankList,
  todoItems,
  showTodoStrip,
  latestSnapshot,
} = useCustomerWorkspace()

const { enterActive, enterGeneration } = useWorkspaceEnter(() => brief.value)

const displayName = computed(() => brief.value?.company_name || brief.value?.brand_name || '当前企业')
const showEmptyGuide = computed(() => heroTone.value === 'empty' && !loading.value)

const scheduleLine = computed(() => {
  const latest = brief.value?.latest_schedule
  if (!latest?.completed_subtasks) return '暂无已完成监测批次'
  return `最新监测批次 · 已完成 ${latest.completed_subtasks} 条`
})

const emptyHint = computed(() => {
  if (brief.value?.recent_snapshots?.length) return ''
  return '暂无已完成检测结果，请等待监测任务返回。'
})

const sampleTotal = computed(() => {
  if (!brief.value) return 0
  return brief.value.kpis.ranking_sample_count + brief.value.kpis.exposure_sample_count
})

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
        <p>{{ displayName }} · 近 7 日监测简报 · {{ scheduleLine }}</p>
      </div>
      <div class="ws-campus-head-actions">
        <span class="ws-campus-badge" :class="`tone-${statusBadge.tone}`">{{ statusBadge.label }}</span>
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

    <div v-if="loading && !brief" class="ws-campus-loading">
      <div v-for="n in 6" :key="n" class="ws-campus-skeleton" />
    </div>

    <section v-else-if="showEmptyGuide" class="ws-campus-empty">
      <Clock3 />
      <h3>等待首次监测结果</h3>
      <p>{{ emptyHint }}</p>
      <ul>
        <li>系统会自动发起检测并同步结果，无需手动提交</li>
        <li>结果返回后，这里会展示健康分、平台表现与检测快照</li>
        <li>可先查看{{ realtimeMenuName }}页了解任务结构，或维护品牌/竞品配置</li>
      </ul>
      <button type="button" class="ws-campus-primary" @click="navigateToMenu('customer.realtime')">
        <Search />
        查看{{ realtimeMenuName }}
      </button>
    </section>

    <template v-else-if="brief">
      <!-- ① 结论 + ② 健康分 + 趋势 -->
      <div class="ws-campus-grid-top">
        <article class="ws-campus-card ws-campus-greet" :class="heroTone">
          <div class="ws-campus-greet-main">
            <div class="ws-campus-greet-copy">
              <div class="ws-campus-greet-hello">{{ greetingLabel() }}，{{ workspaceHeadline }}</div>
              <small>数据来自真实监测任务返回</small>
              <div class="ws-campus-greet-sample">
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
            </div>
            <div class="ws-campus-health-block">
              <div ref="healthGaugeRef" class="ws-campus-chart ws-campus-chart-health" />
              <span>GEO 健康分</span>
              <small>可见度 60% + 排名 40%</small>
            </div>
          </div>
        </article>

        <article class="ws-campus-card">
          <div class="ws-campus-card-head">
            <h3>露出率趋势</h3>
            <span class="ws-campus-chip">近 7 日</span>
          </div>
          <div ref="trendChartRef" class="ws-campus-chart ws-campus-chart-trend" />
          <p v-if="!trendBars.length" class="ws-campus-mini-empty ws-campus-chart-empty">暂无趋势数据</p>
        </article>
      </div>

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
          <button type="button" class="ws-campus-link" @click="navigateToMenu('customer.realtime')">
            查看{{ realtimeMenuName }}
          </button>
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

      <!-- ⑤ 最近检测快照 -->
      <article class="ws-campus-card ws-campus-snapshot">
        <div class="ws-campus-card-head">
          <h3>最近检测快照</h3>
          <button type="button" class="ws-campus-link" @click="navigateToMenu('customer.realtime')">
            进入{{ realtimeMenuName }}
          </button>
        </div>
        <template v-if="latestSnapshot">
          <div class="ws-campus-snap-meta">
            <span class="ws-campus-tag" :class="snapshotIntentClass(latestSnapshot)">{{ snapshotIntentLabel(latestSnapshot) }}</span>
            <span>{{ platformLabelMap[latestSnapshot.platform] || latestSnapshot.platform }}</span>
            <span>{{ latestSnapshot.schedule_label || formatDateTime(latestSnapshot.updated_at) }}</span>
          </div>
          <h4>{{ latestSnapshot.prompt }}</h4>
          <p>{{ latestSnapshot.answer_excerpt || '暂无摘要' }}</p>
          <button type="button" class="ws-campus-snap-foot" @click="openSnapshot(latestSnapshot)">
            {{ snapshotMetric(latestSnapshot) }} · 点击查看详情 →
          </button>
        </template>
        <p v-else class="ws-campus-mini-empty">{{ emptyHint }}</p>
      </article>

      <!-- 告警 -->
      <div v-if="visibleAlerts.length" class="ws-campus-alerts">
        <button
          v-for="alert in visibleAlerts"
          :key="alert.message"
          type="button"
          class="ws-campus-alert"
          :class="alert.level"
          @click="navigateToMenu(alertTargetMenu(alert))"
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
