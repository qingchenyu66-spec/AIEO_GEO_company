<script setup lang="ts">
import { computed, inject, onMounted, onUnmounted, ref, watch } from 'vue'
import { usePortalCharts } from '../../../composables/usePortalCharts'
import { PortalAnalyticsKey } from '../injectionKeys'
import { monitorStatusLabelMap, platformLabelMap } from '../portalMaps'
import PlatformMatrixPanel from '../components/PlatformMatrixPanel.vue'
import '../../../styles/platform-matrix.css'

const emit = defineEmits<{ 'open-menu-config': [] }>()

const analytics = inject(PortalAnalyticsKey)!
const {
  monitorSummary,
  brandAsset,
  brandCompetitors,
  functionalPage,
  negativeRate,
  sourceTotalCount,
  sourceRanking,
  diagnosisScore,
  platformCoverage,
  platformMatrix,
  loadingPlatformMatrix,
  loadPlatformMatrix,
  platformRanking,
  operationLogs,
  systemSettings,
  loadPlatformSystemData,
  recentSubtasks,
} = analytics

const diagnosisChartRef = ref<HTMLDivElement | null>(null)

const { renderCharts } = usePortalCharts({
  diagnosis: diagnosisChartRef,
})

const chartData = computed(() => ({
  chartTrend: [],
  platformRanking: platformRanking.value,
  sentimentPieRows: [],
  positiveRate: 0,
  diagnosisScore: diagnosisScore.value,
  competitorCompareRows: [],
  sourceStructureRows: [],
  sourceTrendRows: [],
  sourceCategoryLabels: {},
}))

async function refreshCharts() {
  await renderCharts(chartData.value)
}

watch([
  platformRanking,
  diagnosisScore,
], refreshCharts, { deep: true })

onMounted(() => {
  refreshCharts()
  window.addEventListener('resize', refreshCharts)
})

onUnmounted(() => {
  window.removeEventListener('resize', refreshCharts)
})
</script>

<template>
  <section class="feature-page">
    <section class="feature-grid">
      <article class="panel feature-primary">
        <div class="panel-head">
          <h2>{{ functionalPage.mode === 'diagnosis' ? '品牌健康分' : functionalPage.mode === 'report' ? '报告预览' : '业务明细' }}</h2>
        </div>

        <div v-if="functionalPage.mode === 'diagnosis'" class="diagnosis-workbench">
          <div v-if="diagnosisScore" ref="diagnosisChartRef" class="echart-box diagnosis-echart"></div>
          <div v-else class="mini-empty chart-empty">暂无可诊断的真实结果。</div>
          <div class="diagnosis-bars">
            <div><span>品牌提及率</span><i><b :style="{ width: `${monitorSummary?.mention_rate || 0}%` }"></b></i><em>{{ monitorSummary?.mention_rate || 0 }}%</em></div>
            <div><span>平均排名</span><i><b :style="{ width: `${monitorSummary?.avg_rank ? Math.max(12, 100 - monitorSummary.avg_rank * 12) : 0}%` }"></b></i><em>{{ monitorSummary?.avg_rank || '-' }}</em></div>
            <div><span>负面风险</span><i><b class="warn-bar" :style="{ width: `${negativeRate}%` }"></b></i><em>{{ negativeRate }}%</em></div>
            <div><span>信源数量</span><i><b :style="{ width: `${Math.min(100, (sourceTotalCount || sourceRanking.length) * 10)}%` }"></b></i><em>{{ sourceTotalCount || sourceRanking.length }}</em></div>
          </div>
          <div class="diagnosis-basis">
            <h3>诊断依据</h3>
            <p>依据已配置监测平台、品牌词、竞品库、模型回答排名、信源数量、情感倾向和历史任务完成情况综合判断。</p>
            <div><span>诊断平台</span><b>{{ platformCoverage.map(item => item.name).join('、') }}</b></div>
            <div><span>纳入竞品</span><b>{{ brandCompetitors.map(item => item.name).join('、') || '暂未配置竞品' }}</b></div>
          </div>
        </div>

        <PlatformMatrixPanel
          v-else-if="functionalPage.mode === 'platforms'"
          :matrix="platformMatrix"
          :loading="loadingPlatformMatrix"
          @refresh="loadPlatformMatrix()"
        />

        <div v-else-if="functionalPage.mode === 'report'" class="report-preview">
          <h3>{{ brandAsset?.brand_name || '艾迪亚' }} GEO 监测诊断报告</h3>
          <p>本周期共完成 {{ monitorSummary?.subtask_count || 0 }} 个检测子任务，品牌提及率 {{ monitorSummary?.mention_rate || 0 }}%，平均推荐排名 {{ monitorSummary?.avg_rank || '-' }}。主要优化方向集中在高权威信源、竞品对比内容和移动端结果稳定性。</p>
          <div class="report-table">
            <span>平台</span><span>提及率</span><span>平均排名</span><span>建议动作</span>
            <template v-for="item in platformRanking.slice(0, 4)" :key="item.platform">
              <b>{{ platformLabelMap[item.platform] || item.platform }}</b><b>{{ item.mention_rate }}%</b><b>{{ item.avg_rank || '-' }}</b><b>补充可引用内容</b>
            </template>
          </div>
        </div>

        <div v-else-if="functionalPage.mode === 'logs'" class="ops-table">
          <div class="settings-header-actions">
            <button class="primary-btn small-btn" @click="loadPlatformSystemData">刷新日志</button>
          </div>
          <div class="ops-head"><span>时间</span><span>操作人</span><span>类型</span><span>描述</span><span>风险</span></div>
          <div v-for="row in operationLogs" :key="row.join('-')" class="ops-row">
            <span>{{ row[0] }}</span><b>{{ row[1] }}</b><span>{{ row[2] }}</span><em>{{ row[3] }}</em><i>{{ row[4] }}</i>
          </div>
        </div>

        <div v-else-if="functionalPage.mode === 'settings'" class="ops-table settings-table">
          <div class="settings-header-actions">
            <button class="primary-btn small-btn" @click="emit('open-menu-config')">菜单配置管理</button>
          </div>
          <div class="ops-head"><span>配置项</span><span>当前值</span><span>作用范围</span><span>状态</span></div>
          <div v-for="row in systemSettings" :key="row[0]" class="ops-row">
            <b>{{ row[0] }}</b><span>{{ row[1] }}</span><em>{{ row[2] }}</em><i>{{ row[3] }}</i>
          </div>
        </div>

        <div v-else class="feature-table">
          <div class="feature-table-head"><span>平台</span><span>问题</span><span>排名</span><span>状态</span><span>快照</span></div>
          <div v-for="item in recentSubtasks.slice(0, 8)" :key="item.subtask_id" class="feature-table-row">
            <span>{{ platformLabelMap[item.platform] || item.platform }}</span>
            <b>{{ item.prompt }}</b>
            <span>{{ item.mention_position ? `第${item.mention_position}位` : '-' }}</span>
            <em>{{ monitorStatusLabelMap[item.status || ''] || item.status || '-' }}</em>
            <a v-if="item.page_screenshot" :href="item.page_screenshot" target="_blank">打开</a>
            <span v-else>待返回</span>
          </div>
          <div v-if="!recentSubtasks.length" class="mini-empty">暂无检测明细，真实任务完成后自动显示。</div>
        </div>
      </article>
    </section>
  </section>
</template>
