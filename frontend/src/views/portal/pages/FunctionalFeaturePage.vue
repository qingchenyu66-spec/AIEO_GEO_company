<script setup lang="ts">
import { computed, inject, onMounted, onUnmounted, ref, watch } from 'vue'
import { BookOpen, HelpCircle, Link2 } from '@lucide/vue'
import { usePortalCharts } from '../../../composables/usePortalCharts'
import { sourceCategoryLabels } from '../composables/useMonitorAnalytics'
import { PortalAnalyticsKey } from '../injectionKeys'
import { monitorStatusLabelMap, platformLabelMap } from '../portalMaps'
import { formatDateTime, formatFileSize } from '../portalUtils'

const emit = defineEmits<{ 'open-menu-config': [] }>()

const analytics = inject(PortalAnalyticsKey)!
const {
  monitorSummary,
  brandAsset,
  brandCompetitors,
  functionalPage,
  sourceStructureRows,
  sourceRanking,
  sourceTrendRows,
  contentPreferenceRows,
  sourcePlatformTabs,
  selectedSourcePlatform,
  sourceKeywordFilter,
  sourceStartDate,
  sourceEndDate,
  resetSourceFilters,
  negativeRate,
  sourceTotalCount,
  diagnosisScore,
  platformCoverage,
  platformRanking,
  competitorCompareRows,
  operationLogs,
  systemSettings,
  loadPlatformSystemData,
  loadingKnowledgeFiles,
  uploadingKnowledgeFile,
  knowledgeFiles,
  handleKnowledgeUpload,
  recentSubtasks,
} = analytics

const diagnosisChartRef = ref<HTMLDivElement | null>(null)
const competitorChartRef = ref<HTMLDivElement | null>(null)
const sourceStructureChartRef = ref<HTMLDivElement | null>(null)
const sourceTrendChartRef = ref<HTMLDivElement | null>(null)

const { renderCharts } = usePortalCharts({
  diagnosis: diagnosisChartRef,
  competitor: competitorChartRef,
  sourceStructure: sourceStructureChartRef,
  sourceTrend: sourceTrendChartRef,
})

const chartData = computed(() => ({
  chartTrend: [],
  platformRanking: platformRanking.value,
  sentimentPieRows: [],
  positiveRate: 0,
  diagnosisScore: diagnosisScore.value,
  competitorCompareRows: competitorCompareRows.value,
  sourceStructureRows: sourceStructureRows.value,
  sourceTrendRows: sourceTrendRows.value,
  sourceCategoryLabels,
}))

async function refreshCharts() {
  await renderCharts(chartData.value)
}

watch([
  platformRanking,
  diagnosisScore,
  competitorCompareRows,
  sourceStructureRows,
  sourceTrendRows,
  selectedSourcePlatform,
  sourceKeywordFilter,
  sourceStartDate,
  sourceEndDate,
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
          <h2>{{ functionalPage.mode === 'diagnosis' ? '品牌健康分' : functionalPage.mode === 'report' ? '报告预览' : functionalPage.mode === 'knowledge' ? '文章文件上传' : functionalPage.mode === 'sources' ? '信源明细' : '业务明细' }}</h2>
        </div>

        <div v-if="functionalPage.mode === 'sources'" class="source-table-workbench">
          <div class="source-tip">
            <HelpCircle />
            <span>AI 大模型结果存在动态变化，不同时间、不同平台的信源结果会有差异；本页展示已同步的真实检测结果。</span>
          </div>
          <div class="source-analytics-grid">
            <section class="source-analysis-card source-structure-card">
              <div class="panel-head"><h2>信源结构对比</h2><span>不同模型引用来源占比</span></div>
              <div v-if="sourceStructureRows.length" ref="sourceStructureChartRef" class="echart-box source-structure-echart"></div>
              <div v-else class="mini-empty chart-empty">暂无信源结构数据。</div>
            </section>
            <section class="source-analysis-card">
              <div class="panel-head"><h2>高频信源排行</h2><span>近30天引用次数</span></div>
              <div v-if="sourceRanking.length" class="source-top-list">
                <div v-for="(source, index) in sourceRanking.slice(0, 5)" :key="source.url">
                  <i>{{ index + 1 }}</i>
                  <b>{{ source.title }}</b>
                  <strong>{{ source.count }}</strong>
                </div>
              </div>
              <div v-else class="mini-empty">暂无高频信源。</div>
            </section>
            <section class="source-analysis-card">
              <div class="panel-head"><h2>信源引用趋势</h2><span>近7日新增引用</span></div>
              <div v-if="sourceTrendRows.some(item => item.value > 0)" ref="sourceTrendChartRef" class="echart-box source-trend-echart"></div>
              <div v-else class="mini-empty chart-empty">暂无信源趋势数据。</div>
            </section>
            <section class="source-analysis-card">
              <div class="panel-head"><h2>内容类型偏好</h2><span>按引用占比</span></div>
              <div class="content-preference-list">
                <div v-for="item in contentPreferenceRows" :key="item.name">
                  <span>{{ item.name }}</span>
                  <i><b :style="{ width: `${item.percent}%` }"></b></i>
                  <em>{{ item.percent }}%</em>
                </div>
              </div>
            </section>
          </div>

          <div v-if="sourcePlatformTabs.length > 1" class="source-platform-cards">
            <button
              v-for="tab in sourcePlatformTabs"
              :key="tab.code"
              :class="{ active: selectedSourcePlatform === tab.code }"
              @click="selectedSourcePlatform = tab.code"
            >
              <Link2 />
              <b>{{ tab.name }}</b>
              <span>{{ tab.count }} 次引用</span>
            </button>
          </div>
          <div class="source-query-bar">
            <input v-model="sourceKeywordFilter" placeholder="输入来源 / 监控词 / 问题关键词搜索" />
            <input v-model="sourceStartDate" type="date" />
            <span>→</span>
            <input v-model="sourceEndDate" type="date" />
            <button class="filter-search-btn">查询</button>
            <button class="filter-reset-btn" @click="resetSourceFilters">重置</button>
          </div>
          <div v-if="sourceRanking.length" class="source-data-table">
            <div class="source-data-head">
              <span>序号</span><span>信源 / 关联问题</span><span>被引用平台</span><span>监控词</span><span>最近检测时间</span><span>引用次数</span><span>操作</span>
            </div>
            <div v-for="(source, index) in sourceRanking" :key="source.url" class="source-data-row">
              <span>{{ index + 1 }}</span>
              <div>
                <b>{{ source.title }}</b>
                <small>{{ (source.questions || []).slice(0, 2).join('；') || '暂无关联问题' }}</small>
              </div>
              <div class="source-table-tags">
                <i v-for="platform in (source.platforms || [])" :key="`${source.url}-${platform}`">{{ platformLabelMap[platform] || platform }}</i>
              </div>
              <div class="source-table-tags muted-tags">
                <i v-for="keyword in (source.keywords || []).slice(0, 4)" :key="`${source.url}-${keyword}`">{{ keyword }}</i>
              </div>
              <span>{{ formatDateTime(source.latest_time) }}</span>
              <strong>{{ source.count }}</strong>
              <div class="source-actions">
                <a :href="source.url" target="_blank">快照凭证</a>
                <a :href="source.url" target="_blank">转到平台</a>
              </div>
            </div>
          </div>
          <div v-else class="mini-empty">暂无符合条件的信源。</div>
        </div>

        <div v-else-if="functionalPage.mode === 'diagnosis'" class="diagnosis-workbench">
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

        <div v-else-if="functionalPage.mode === 'platforms'" class="platform-orbit-card">
          <div class="orbit-center">AI<br />平台矩阵</div>
          <div v-for="(item, index) in platformCoverage.slice(0, 6)" :key="item.code" class="orbit-platform-card" :class="`orbit-pos-${index}`">
            <b>{{ item.name }}</b>
            <span>{{ item.status }} · {{ item.rate }}%</span>
          </div>
        </div>

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

        <div v-else-if="functionalPage.mode === 'competitor'" class="competitor-compare-panel">
          <div v-if="competitorCompareRows.some(row => row.mention > 0)" ref="competitorChartRef" class="echart-box competitor-echart"></div>
          <div v-else class="mini-empty chart-empty">暂无真实竞品排名结果，定时监测完成后展示对比图。</div>
          <div class="gap-cards">
            <div><span>TOP 竞品</span><b>{{ competitorCompareRows[1]?.name || '暂无' }}</b></div>
            <div><span>竞品数量</span><b>{{ brandCompetitors.length }} 个</b></div>
            <div><span>依据来源</span><b>企业竞品库与模力返回排名</b></div>
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

        <div v-else-if="functionalPage.mode === 'knowledge'" class="knowledge-upload">
          <label class="upload-drop" :class="{ disabled: uploadingKnowledgeFile }">
            <input type="file" accept=".pdf,.doc,.docx,.md,.txt" :disabled="uploadingKnowledgeFile" @change="handleKnowledgeUpload" />
            <BookOpen />
            <b>{{ uploadingKnowledgeFile ? '上传中...' : '上传文章类文件' }}</b>
            <span>支持 PDF / Word / Markdown / TXT，只保存原文件和上传记录，不做解析入库。</span>
          </label>
          <div class="knowledge-files">
            <div v-if="loadingKnowledgeFiles" class="mini-empty">文件列表加载中...</div>
            <div v-for="file in knowledgeFiles" :key="file.id">
              <b>{{ file.original_name }}</b>
              <span>{{ file.file_ext.toUpperCase() }} · {{ formatFileSize(file.file_size) }} · 已上传</span>
            </div>
            <div v-if="!loadingKnowledgeFiles && !knowledgeFiles.length" class="mini-empty">暂无上传文件，客户可在这里上传 PDF / Word 等文章资料。</div>
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
