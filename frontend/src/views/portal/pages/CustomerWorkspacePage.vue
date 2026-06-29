<script setup lang="ts">
import { computed, inject, onMounted, onUnmounted, ref, watch } from 'vue'
import { Activity, HelpCircle } from '@lucide/vue'
import { usePortalCharts } from '../../../composables/usePortalCharts'
import { PortalAnalyticsKey } from '../injectionKeys'
import { platformLabelMap } from '../portalMaps'
import { formatDateTime } from '../portalUtils'

const analytics = inject(PortalAnalyticsKey)!
const {
  loadingSummary,
  syncingMonitorResults,
  stats,
  statTooltipMap,
  chartTrend,
  platformRanking,
  sourcePlatformTabs,
  sourceRanking,
  selectedSourcePlatform,
  recentQuestionGroups,
  customerPlatformServices,
  purchasedPlatformCount,
} = analytics

const trendChartRef = ref<HTMLDivElement | null>(null)
const exposureRankChartRef = ref<HTMLDivElement | null>(null)

const { renderCharts } = usePortalCharts({
  trend: trendChartRef,
  exposureRank: exposureRankChartRef,
})

const chartData = computed(() => ({
  chartTrend: chartTrend.value,
  platformRanking: platformRanking.value,
  sentimentPieRows: [],
  positiveRate: 0,
  diagnosisScore: 0,
  competitorCompareRows: [],
  sourceStructureRows: [],
  sourceTrendRows: [],
  sourceCategoryLabels: {},
}))

async function refreshCharts() {
  await renderCharts(chartData.value)
}

watch([chartTrend, platformRanking], refreshCharts, { deep: true })

onMounted(() => {
  refreshCharts()
  window.addEventListener('resize', refreshCharts)
})

onUnmounted(() => {
  window.removeEventListener('resize', refreshCharts)
})
</script>

<template>
  <section class="portal-hero">
    <div>
      <span class="hero-kicker">品牌监测总览</span>
      <h2>企业 AI 可见度指挥舱</h2>
      <p>汇总品牌曝光、推荐排名、信源分析与风险变化，辅助判断品牌在主流模型中的可见度。</p>
    </div>
    <div class="hero-sync" :class="{ loading: loadingSummary }">
      <Activity />
      <span>{{ syncingMonitorResults ? '远端同步中' : loadingSummary ? '数据更新中' : '数据已校验' }}</span>
    </div>
  </section>

  <section class="customer-service-panel panel">
    <div class="panel-head">
      <div>
        <h2>模型平台覆盖</h2>
        <p>展示当前品牌在主流模型平台中的监测覆盖情况。</p>
      </div>
      <span>{{ purchasedPlatformCount }} / {{ customerPlatformServices.length }} 已购买</span>
    </div>
    <div class="customer-platform-grid">
      <div v-for="platform in customerPlatformServices" :key="platform.code" class="customer-platform-card" :class="{ purchased: platform.purchased }">
        <span>{{ platform.purchased ? '服务中' : '未开通' }}</span>
        <b>{{ platform.name }}</b>
      </div>
    </div>
  </section>

  <section class="portal-stats">
    <article v-for="item in stats" :key="item[0]">
      <span class="stat-title">
        {{ item[0] }}
        <el-tooltip v-if="statTooltipMap[item[0]]" placement="top" effect="light" :content="statTooltipMap[item[0]]">
          <HelpCircle />
        </el-tooltip>
      </span>
      <strong>{{ item[1] }}</strong>
      <small>{{ item[2] }}</small>
    </article>
  </section>

  <section class="portal-main">
    <article class="panel trend-panel">
      <div class="panel-head"><h2>曝光次数趋势</h2><span>最近 7 天品牌被提及次数</span></div>
      <div v-if="chartTrend.length" ref="trendChartRef" class="echart-box trend-echart"></div>
      <div v-else class="mini-empty chart-empty">暂无真实趋势数据，定时任务完成后自动展示。</div>
    </article>

    <article class="panel">
      <div class="panel-head"><h2>曝光率排行图</h2><span>{{ platformRanking.length }} 个平台</span></div>
      <div v-if="platformRanking.length" ref="exposureRankChartRef" class="echart-box exposure-rank-echart"></div>
      <div v-else class="mini-empty">真实任务还在处理中，完成后这里会展示平台曝光排行。</div>
    </article>
  </section>

  <section class="portal-main insight-main">
    <article class="panel source-analysis-panel">
      <div class="panel-head">
        <div><h2>信源分析</h2><p>按平台查看信源、监控词和引用次数</p></div>
        <span>{{ sourceRanking.length }} 条信源</span>
      </div>
      <div v-if="sourcePlatformTabs.length > 1" class="source-platform-tabs">
        <button
          v-for="tab in sourcePlatformTabs"
          :key="tab.code"
          :class="{ active: selectedSourcePlatform === tab.code }"
          @click="selectedSourcePlatform = tab.code"
        >
          {{ tab.name }} <em>{{ tab.count }}</em>
        </button>
      </div>
      <div v-if="sourceRanking.length" class="source-scroll-body">
        <div class="source-rank-grid source-rich-grid">
          <a v-for="source in sourceRanking" :key="source.url" :href="source.url" target="_blank">
            <b>{{ source.title }}</b>
            <span class="source-meta"><strong>{{ source.count }}</strong> 次引用</span>
            <div class="source-chip-row">
              <i v-for="platform in (source.platforms || []).slice(0, 4)" :key="`${source.url}-${platform}`">{{ platformLabelMap[platform] || platform }}</i>
            </div>
            <div class="source-keywords">
              <small v-for="keyword in (source.keywords || []).slice(0, 3)" :key="`${source.url}-${keyword}`">{{ keyword }}</small>
            </div>
          </a>
        </div>
      </div>
      <div v-else class="mini-empty">待模型返回信源后展示，可直接点击跳转。</div>
    </article>

    <article class="panel">
      <div class="panel-head"><h2>最近检测</h2><span>{{ recentQuestionGroups.length }} 组问题</span></div>
      <div v-if="recentQuestionGroups.length" class="recent-check-list grouped-check-list">
        <div v-for="item in recentQuestionGroups" :key="item.prompt">
          <div class="recent-question-head">
            <b>{{ item.prompt }}</b>
            <em>{{ item.platforms.length }}/{{ item.expected_total }} 已返回</em>
          </div>
          <div class="recent-platform-tags">
            <i v-for="platform in item.platforms.slice(0, 6)" :key="`${item.prompt}-${platform}`">{{ platformLabelMap[platform] || platform }}</i>
          </div>
          <div v-if="item.missing_platforms.length" class="recent-missing-platforms">
            待返回：{{ item.missing_platforms.slice(0, 5).map(platform => platformLabelMap[platform] || platform).join('、') }}{{ item.missing_platforms.length > 5 ? '等' : '' }}
          </div>
          <small>{{ item.tenant_name || '当前企业' }} / {{ item.best_rank ? `最佳第${item.best_rank}位` : '未返回排名' }} / {{ formatDateTime(item.latest_time) }}</small>
        </div>
      </div>
      <div v-else class="mini-empty">暂无已完成结果，当前真实任务正在处理中。</div>
    </article>
  </section>
</template>
