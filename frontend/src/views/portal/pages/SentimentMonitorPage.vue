<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { AlertTriangle, ChevronRight, Download, Info } from '@lucide/vue'
import { usePortalCharts } from '../../../composables/usePortalCharts'
import { useMonitorSentiment } from '../composables/useMonitorSentiment'

const {
  brandAsset,
  overview,
  loading,
  filters,
  datePreset,
  listTab,
  monitorGroupOptions,
  platformOptions,
  heroStackSegments,
  warnPlatformStats,
  heroCalm,
  listItems,
  tabCounts,
  selectedItem,
  selectedSubtask,
  loadingDetail,
  detailVisible,
  resetFilters,
  applyDatePreset,
  onCustomDateChange,
  switchListTab,
  switchTabFromHero,
  openDetail,
  closeDetail,
  scrollToList,
  filterByPlatform,
  exportCsv,
  formatMonitorGroupLabel,
  formatDateTime,
  sentimentClass,
  cardToneClass,
  platformLabelMap,
  sentimentLabelMap,
} = useMonitorSentiment()

const sentimentTrendChartRef = ref<HTMLDivElement | null>(null)

const { renderCharts } = usePortalCharts({
  sentimentTrend: sentimentTrendChartRef,
})

const chartData = computed(() => ({
  chartTrend: [],
  sentimentTrendRows: overview.value?.sentiment_trend || [],
  platformRanking: [],
  sentimentPieRows: [],
  positiveRate: overview.value?.positive_rate || 0,
  diagnosisScore: 0,
  competitorCompareRows: [],
  sourceStructureRows: [],
  sourceTrendRows: [],
  sourceCategoryLabels: {},
}))

const brandDisplayName = computed(() => brandAsset.value?.brand_name || overview.value?.brand_name || '未配置品牌')

async function refreshCharts() {
  await renderCharts(chartData.value)
}

watch(overview, refreshCharts, { deep: true })

onMounted(() => {
  refreshCharts()
  window.addEventListener('resize', refreshCharts)
})

onUnmounted(() => {
  window.removeEventListener('resize', refreshCharts)
})
</script>

<template>
  <section class="monitor-page sentiment-monitor-page">
    <header class="sentiment-sticky-bar">
      <div class="sentiment-sticky-inner">
        <div class="sentiment-date-presets">
          <button type="button" :class="{ active: datePreset === '7d' }" @click="applyDatePreset('7d')">近 7 天</button>
          <button type="button" :class="{ active: datePreset === '30d' }" @click="applyDatePreset('30d')">近 30 天</button>
          <button type="button" :class="{ active: datePreset === 'custom' }" @click="datePreset = 'custom'">自定义</button>
        </div>
        <div v-if="datePreset === 'custom'" class="sentiment-custom-dates">
          <input v-model="filters.startDate" type="date" @change="onCustomDateChange">
          <span>至</span>
          <input v-model="filters.endDate" type="date" @change="onCustomDateChange">
        </div>
        <div class="sentiment-sticky-filters">
          <select v-model="filters.platform">
            <option value="all">全部平台</option>
            <option v-for="platform in platformOptions" :key="platform" :value="platform">
              {{ platformLabelMap[platform] || platform }}
            </option>
          </select>
          <select v-model="filters.monitorGroup">
            <option value="">全部词组</option>
            <option v-for="group in monitorGroupOptions" :key="group.monitor_keyword" :value="group.monitor_keyword">
              {{ formatMonitorGroupLabel(group) }}
            </option>
          </select>
          <select v-model="filters.scheduleWindowKey">
            <option value="">全部轮次</option>
            <option v-for="item in overview?.schedule_options || []" :key="item.schedule_window_key" :value="item.schedule_window_key">
              {{ item.schedule_label }}
            </option>
          </select>
        </div>
        <div class="sentiment-sticky-actions">
          <span v-if="loading" class="sentiment-loading-dot">更新中</span>
          <button type="button" class="filter-reset-btn tiny-btn" @click="resetFilters">重置</button>
          <button type="button" class="primary-btn small-btn" :disabled="!overview?.sample_count" @click="exportCsv">
            <Download />
            导出报告
          </button>
        </div>
      </div>
    </header>

    <article
      class="sentiment-hero panel"
      :class="{ 'is-calm': heroCalm, 'is-risk': (overview?.negative_count || 0) > 0 }"
    >
      <div class="sentiment-hero-top">
        <div>
          <span class="sentiment-hero-eyebrow">口碑舆情监测</span>
          <h2>{{ brandDisplayName }}</h2>
          <p class="sentiment-hero-note">
            <Info />
            仅统计介绍、口碑、对比类问题，不含排名推荐类
          </p>
        </div>
        <button
          v-if="(overview?.negative_count || 0) > 0"
          type="button"
          class="sentiment-hero-cta"
          @click="scrollToList"
        >
          查看负面内容
          <ChevronRight />
        </button>
      </div>

      <div v-if="loading && !overview" class="sentiment-hero-skeleton">
        <div /><div /><div />
      </div>
      <template v-else>
        <div class="sentiment-hero-metrics">
          <div class="sentiment-hero-metric primary-metric">
            <span>负面条数</span>
            <b>{{ overview?.negative_count || 0 }}</b>
          </div>
          <div class="sentiment-hero-metric">
            <span>负面占比</span>
            <b>{{ overview?.negative_rate || 0 }}%</b>
          </div>
          <div class="sentiment-hero-metric">
            <span>有效样本</span>
            <b>{{ overview?.recognized_count || 0 }}</b>
            <em>/ {{ overview?.sample_count || 0 }} 口碑类</em>
          </div>
        </div>

        <div v-if="heroStackSegments.length" class="sentiment-stack-bar" role="group" aria-label="情感占比">
          <button
            v-for="segment in heroStackSegments"
            :key="segment.key"
            type="button"
            class="sentiment-stack-segment"
            :class="`segment-${segment.key}`"
            :style="{ width: `${Math.max(segment.rate, 0)}%` }"
            :title="`${segment.label} ${segment.rate}%（${segment.count} 条）`"
            @click="switchTabFromHero(segment.key)"
          />
        </div>
        <div v-if="heroStackSegments.length" class="sentiment-stack-legend">
          <button
            v-for="segment in heroStackSegments"
            :key="`legend-${segment.key}`"
            type="button"
            class="sentiment-stack-legend-item"
            @click="switchTabFromHero(segment.key)"
          >
            <i :class="`segment-${segment.key}`" />
            {{ segment.label }} {{ segment.rate }}%
            <em>{{ segment.count }} 条</em>
          </button>
        </div>

        <p v-if="heroCalm" class="sentiment-hero-calm-copy">本期暂无负面内容，品牌口碑表现稳定。</p>
        <p v-else-if="warnPlatformStats.length" class="sentiment-hero-warn-copy">
          <AlertTriangle />
          {{ warnPlatformStats.map(row => platformLabelMap[row.platform] || row.platform).join('、') }}
          负面率偏高，建议优先查看明细。
        </p>
      </template>
    </article>

    <section class="sentiment-analytics-grid">
      <article class="panel sentiment-trend-panel">
        <div class="panel-head">
          <h2>情感趋势</h2>
          <span>按日正 / 中 / 负</span>
        </div>
        <div v-if="overview?.sentiment_trend?.length" ref="sentimentTrendChartRef" class="echart-box sentiment-trend-echart sentiment-trend-full" />
        <div v-else class="mini-empty chart-empty">暂无趋势数据。</div>
      </article>

      <article v-if="overview?.platform_stats?.length" class="panel sentiment-platform-panel">
        <div class="panel-head">
          <h2>平台对比</h2>
          <span>点击筛选平台</span>
        </div>
        <div class="sentiment-platform-stack-list">
          <button
            v-for="row in overview.platform_stats"
            :key="row.platform"
            type="button"
            class="sentiment-platform-stack-row"
            :class="{ warn: row.negative_rate >= 15 && row.negative_count > 0 }"
            @click="filterByPlatform(row.platform)"
          >
            <b>{{ platformLabelMap[row.platform] || row.platform }}</b>
            <div class="sentiment-platform-stack-track">
              <i
                class="segment-positive"
                :style="{ width: `${row.positive_rate}%` }"
                :title="`正面 ${row.positive_rate}%`"
              />
              <i
                class="segment-neutral"
                :style="{ width: `${row.neutral_rate}%` }"
                :title="`中性 ${row.neutral_rate}%`"
              />
              <i
                class="segment-negative"
                :style="{ width: `${row.negative_rate}%` }"
                :title="`负面 ${row.negative_rate}%`"
              />
            </div>
            <em>{{ row.negative_count }} 条负面 · {{ row.sample_count }} 样本</em>
          </button>
        </div>
      </article>
    </section>

    <article id="sentiment-sample-list" class="panel sentiment-list-panel">
      <div class="panel-head">
        <div>
          <h2>舆情样本</h2>
          <p>点击卡片查看完整回答与引用信源</p>
        </div>
        <span>{{ listItems.length }} 条</span>
      </div>

      <div class="sentiment-segmented-tabs">
        <button type="button" :class="{ active: listTab === 'negative' }" @click="switchListTab('negative')">
          负面内容 <i>{{ tabCounts.negative }}</i>
        </button>
        <button type="button" :class="{ active: listTab === 'all' }" @click="switchListTab('all')">
          全部样本 <i>{{ tabCounts.all }}</i>
        </button>
        <button type="button" :class="{ active: listTab === 'positive' }" @click="switchListTab('positive')">
          正面亮点 <i>{{ tabCounts.positive }}</i>
        </button>
      </div>

      <div v-if="loading" class="sentiment-card-skeleton-list">
        <div v-for="n in 3" :key="n" class="sentiment-card-skeleton" />
      </div>
      <div v-else-if="!listItems.length" class="mini-empty sentiment-list-empty">
        {{ listTab === 'negative' ? '当前筛选条件下暂无负面内容。' : '暂无符合条件的口碑样本。' }}
      </div>
      <div v-else class="sentiment-card-list">
        <button
          v-for="item in listItems"
          :key="item.subtask_id"
          type="button"
          class="sentiment-sample-card"
          :class="cardToneClass(item.sentiment)"
          @click="openDetail(item)"
        >
          <div class="sentiment-sample-card-head">
            <i :class="sentimentClass(item.sentiment)">{{ item.sentiment }}</i>
            <span>{{ platformLabelMap[item.platform] || item.platform }}</span>
            <span v-if="item.keyword_group">{{ item.keyword_group }}</span>
            <span>{{ item.schedule_label || formatDateTime(item.updated_at) }}</span>
          </div>
          <h3>{{ item.prompt }}</h3>
          <p>{{ item.answer_excerpt || '暂无回答摘要' }}</p>
          <div class="sentiment-sample-card-foot">
            <span>{{ item.brand_mentioned ? '品牌已提及' : '品牌未提及' }}</span>
            <em>查看详情 <ChevronRight /></em>
          </div>
        </button>
      </div>
    </article>

    <el-dialog
      v-model="detailVisible"
      width="760px"
      destroy-on-close
      class="monitor-detail-dialog"
      :title="selectedSubtask?.prompt || selectedItem?.prompt || '舆情详情'"
      @closed="closeDetail"
    >
      <div v-if="loadingDetail" class="mini-empty">加载详情…</div>
      <template v-else-if="selectedSubtask || selectedItem">
        <div class="subtask-metrics">
          <span v-if="selectedItem">平台：{{ platformLabelMap[selectedItem.platform] || selectedItem.platform }}</span>
          <span v-if="selectedItem">调度：{{ selectedItem.schedule_label || '-' }}</span>
          <span v-if="selectedItem">词组：{{ selectedItem.keyword_group || '-' }}</span>
          <span>情感：{{ sentimentLabelMap[(selectedSubtask?.sentiment || selectedItem?.sentiment) || ''] || selectedSubtask?.sentiment || selectedItem?.sentiment || '暂无' }}</span>
          <span>品牌提及：{{ (selectedSubtask?.brand_mentioned ?? selectedItem?.brand_mentioned) ? '已提及' : '未提及' }}</span>
          <a v-if="selectedSubtask?.page_screenshot" :href="selectedSubtask.page_screenshot" target="_blank">打开快照</a>
        </div>
        <pre v-if="selectedSubtask?.answer_content" class="answer-preview">{{ selectedSubtask?.answer_content }}</pre>
        <p v-else-if="selectedItem?.answer_excerpt" class="mention-context">{{ selectedItem.answer_excerpt }}</p>
        <div v-if="selectedSubtask?.reference_list?.length" class="source-list">
          <b>信源列表</b>
          <a
            v-for="source in (selectedSubtask?.reference_list || []).slice(0, 8)"
            :key="`${selectedSubtask?.subtask_id}-${source.index}-${source.url}`"
            :href="source.url"
            target="_blank"
          >{{ source.title || source.site || source.url }}</a>
        </div>
      </template>
    </el-dialog>
  </section>
</template>
