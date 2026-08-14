<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import {
  AlertTriangle,
  BarChart3,
  Cloud,
  Download,
  Globe,
  HeartPulse,
  Info,
  RefreshCw,
  Trophy,
} from '@lucide/vue'
import { ElDialog } from 'element-plus'
import PlatformBadge from '../../../components/PlatformBadge.vue'
import type { WorkspaceTrendPreset } from '../../../utils/customerMonitorDate'
import { buildSourceTrackRows } from '../../../utils/sourceSiteLabel'
import { inferDeviceLabel } from '../composables/useWorkspaceBoardExtras'
import { useBrandInsights, type CompetitorDatePreset } from '../composables/useCompetitorAnalysis'
import { parseAnswerBlocks } from '../answerBlocks'
import { formatDateTime, externalLink } from '../portalUtils'
import { platformLabelMap, sentimentLabelMap } from '../portalMaps'
import '../../../styles/competitor-analysis.css'

const mentionTrendChartRef = ref<HTMLDivElement | null>(null)
const sentimentTrendChartRef = ref<HTMLDivElement | null>(null)
const sentimentWordCloudRef = ref<HTMLDivElement | null>(null)

const {
  isCustomerView,
  trendPreset,
  trendStartDate,
  trendEndDate,
  trendMaxDate,
  trendPeriodLabel,
  applyTrendPreset,
  onCustomTrendDateChange,
  datePreset,
  promptFilter,
  promptOptions,
  selectedPlatforms,
  platformTabs,
  loading,
  keywordsLoading,
  leaderboardRows,
  sentimentLeaderboardRows,
  brandRow,
  brandSentimentRow,
  sampleTotal,
  brandSampleTotal,
  insight,
  sentimentTrendRows,
  sentimentKeywordTab,
  activeSentimentKeywords,
  activeSentimentKeywordSample,
  mentionTrendHiddenCount,
  loadSummary,
  observeWordcloudPanel,
  resetFilters,
  exportCsv,
  togglePlatform,
  closeKeywordSnapshot,
  snapshotVisible,
  snapshotLoading,
  snapshotSubtask,
  snapshotPhrase,
} = useBrandInsights({ mentionTrendChartRef, sentimentTrendChartRef, sentimentWordCloudRef })

const wordcloudPanelRef = ref<HTMLElement | null>(null)

watch([loading, wordcloudPanelRef], () => {
  if (loading.value) return
  observeWordcloudPanel(wordcloudPanelRef.value)
})

const datePresets: Array<{ value: CompetitorDatePreset; label: string }> = [
  { value: '7', label: '近 7 天' },
  { value: '30', label: '近 30 天' },
  { value: '90', label: '近 90 天' },
]

const customerTrendPresetOptions: Array<{ value: WorkspaceTrendPreset; label: string }> = [
  { value: '7d', label: '近7日' },
  { value: 'month', label: '月' },
  { value: 'quarter', label: '季度' },
  { value: 'year', label: '年' },
  { value: 'custom', label: '自定义' },
]

function formatRank(value: number | null | undefined) {
  if (value === null || value === undefined) return '—'
  return Number.isInteger(value) ? String(value) : value.toFixed(1)
}

function isPlatformActive(code: string) {
  return code === 'all' ? selectedPlatforms.value.length === 0 : selectedPlatforms.value.includes(code)
}

const snapshotRankLabel = computed(() => {
  const subtask = snapshotSubtask.value
  const rank = subtask?.brand_rank ?? subtask?.mention_position
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

const snapshotSourceTracks = computed(() =>
  buildSourceTrackRows(snapshotSubtask.value, { limit: 12, linkOf: externalLink }),
)
</script>

<template>
  <section class="competitor-page brand-insights-page">
    <header class="competitor-sticky-bar">
      <div class="competitor-sticky-inner">
        <div v-if="isCustomerView" class="competitor-date-filter">
          <div class="competitor-date-presets">
            <button
              v-for="option in customerTrendPresetOptions"
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
            class="competitor-date-range"
            :title="`${trendStartDate} ~ ${trendEndDate}`"
          >{{ trendPeriodLabel }}</span>
          <div v-if="trendPreset === 'custom'" class="competitor-custom-dates">
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
        <div v-else class="competitor-date-presets">
          <button
            v-for="preset in datePresets"
            :key="preset.value"
            type="button"
            :class="{ active: datePreset === preset.value }"
            @click="datePreset = preset.value"
          >
            {{ preset.label }}
          </button>
        </div>
        <div class="competitor-sticky-filters">
          <select v-model="promptFilter">
            <option value="">全部问题</option>
            <option v-for="prompt in promptOptions" :key="prompt" :value="prompt">{{ prompt }}</option>
          </select>
        </div>
        <div class="competitor-sticky-actions">
          <span v-if="loading" class="competitor-loading-dot">更新中…</span>
          <button type="button" class="filter-reset-btn tiny-btn" @click="resetFilters">重置</button>
          <button type="button" class="filter-reset-btn tiny-btn" :disabled="loading" @click="loadSummary()">
            <RefreshCw />
            刷新
          </button>
          <button type="button" class="primary-btn small-btn" :disabled="!leaderboardRows.length" @click="exportCsv">
            <Download />
            导出
          </button>
        </div>
      </div>
      <div v-if="platformTabs.length > 1" class="brand-insights-platform-chips">
        <button
          v-for="tab in platformTabs"
          :key="tab.code"
          type="button"
          class="brand-insights-platform-chip"
          :class="{ active: isPlatformActive(tab.code) }"
          @click="togglePlatform(tab.code)"
        >
          <PlatformBadge v-if="tab.code !== 'all'" :code="tab.code" size="xs" icon-only />
          <Globe v-else />
          <span>{{ tab.name }}</span>
          <em>{{ tab.count }}</em>
        </button>
      </div>
    </header>

    <div class="brand-insights-kpi-row">
      <article class="brand-insights-kpi">
        <span>本品牌提及率</span>
        <b>{{ brandRow?.mention ?? 0 }}%</b>
        <em>{{ brandRow?.mention_count ?? 0 }} / {{ brandSampleTotal }} 样本</em>
      </article>
      <article class="brand-insights-kpi">
        <span>首位提及率</span>
        <b>{{ brandRow?.first_mention_rate ?? 0 }}%</b>
        <em>推荐列表排名第 1</em>
      </article>
      <article class="brand-insights-kpi">
        <span>平均排名</span>
        <b>{{ formatRank(brandRow?.rank) }}</b>
        <!-- 2026-08-14 - 本品牌与竞品排名口径不同，显式挂有排名样本覆盖 -->
        <em>{{ brandRow?.rank_sample_count ?? 0 }} / {{ brandSampleTotal }} 有排名</em>
      </article>
      <article class="brand-insights-kpi">
        <span>正面情绪占比</span>
        <b>{{ brandSentimentRow?.positive_rate ?? 0 }}%</b>
        <em>{{ brandSentimentRow?.sentiment_sample ?? 0 }} 条有效样本</em>
      </article>
    </div>

    <div class="competitor-insight" :class="`is-${insight.level}`">
      <div class="competitor-insight-icon">
        <AlertTriangle v-if="insight.level === 'config' || insight.level === 'sample'" />
        <Info v-else />
      </div>
      <div>
        <strong>{{ insight.title }}</strong>
        <p>{{ insight.body }}</p>
      </div>
    </div>

    <div v-if="loading && !sampleTotal" class="competitor-empty-state">
      <BarChart3 />
      <h3>洞察数据加载中…</h3>
      <p>正在汇总品牌与竞品提及率，请稍候。</p>
    </div>

    <template v-else-if="sampleTotal > 0">
      <section class="brand-insights-grid">
        <article class="competitor-panel brand-insights-quadrant">
          <div class="competitor-panel-head">
            <div>
              <h3>品牌提及率分析</h3>
              <p>
                <!-- 2026-07-30 - 洞察四宫格下钻意义不大 - 去掉点击下钻文案与查看明细 -->
                本品牌 · 全部配置竞品走势
                <span v-if="mentionTrendHiddenCount > 0" class="brand-insights-trend-note">
                  （另有 {{ mentionTrendHiddenCount }} 个竞品见右侧排行榜）
                </span>
              </p>
            </div>
            <BarChart3 />
          </div>
          <div
            v-if="leaderboardRows.some(row => row.mention > 0)"
            ref="mentionTrendChartRef"
            class="echart-box brand-insights-trend-echart"
          />
          <div v-else class="mini-empty chart-empty">暂无提及趋势数据。</div>
        </article>

        <article class="competitor-panel brand-insights-quadrant">
          <div class="competitor-panel-head">
            <div>
              <h3>品牌提及排行榜</h3>
              <p>提及率 · 首位提及率</p>
            </div>
            <Trophy />
          </div>
          <div class="brand-insights-rank-table">
            <div class="brand-insights-rank-head">
              <span>排名</span>
              <span>品牌</span>
              <span>提及率</span>
              <span>首位提及率</span>
            </div>
            <div
              v-for="(row, index) in leaderboardRows"
              :key="row.name"
              class="brand-insights-rank-row"
              :class="{ 'is-brand': row.is_brand }"
            >
              <span>{{ index + 1 }}</span>
              <div class="brand-insights-rank-name">
                <b>{{ row.name }}</b>
                <i v-if="row.is_brand">本品牌</i>
              </div>
              <strong>{{ row.mention }}%</strong>
              <span>{{ row.first_mention_rate }}%</span>
            </div>
          </div>
        </article>

        <article class="competitor-panel brand-insights-quadrant">
          <div class="competitor-panel-head">
            <div>
              <h3>情绪趋势</h3>
              <p>监测回答情感标签占比</p>
            </div>
            <HeartPulse />
          </div>
          <div
            v-if="sentimentTrendRows.length"
            ref="sentimentTrendChartRef"
            class="echart-box brand-insights-trend-echart"
          />
          <div v-else class="mini-empty chart-empty">暂无情绪趋势数据。</div>
        </article>

        <article class="competitor-panel brand-insights-quadrant">
          <div class="competitor-panel-head">
            <div>
              <h3>情绪指数排行榜</h3>
              <p>各品牌在推荐列表中被提及时的回答情绪分布</p>
            </div>
            <HeartPulse />
          </div>
          <div class="brand-insights-rank-table">
            <div class="brand-insights-rank-head sentiment">
              <span>排名</span>
              <span>品牌</span>
              <span>正面占比</span>
              <span>负面占比</span>
            </div>
            <div
              v-for="(row, index) in sentimentLeaderboardRows"
              :key="`sentiment-${row.name}`"
              class="brand-insights-rank-row"
              :class="{ 'is-brand': row.is_brand }"
            >
              <span>{{ index + 1 }}</span>
              <div class="brand-insights-rank-name">
                <b>{{ row.name }}</b>
                <i v-if="row.is_brand">本品牌</i>
              </div>
              <strong class="is-positive">{{ row.positive_rate }}%</strong>
              <span class="is-negative">{{ row.negative_rate }}%</span>
            </div>
            <div v-if="!sentimentLeaderboardRows.length" class="mini-empty">暂无情绪排行数据。</div>
          </div>
        </article>
      </section>

      <section ref="wordcloudPanelRef" class="competitor-panel brand-insights-wordcloud-panel">
        <div class="competitor-panel-head">
          <div>
            <h3>品牌情绪词</h3>
            <p>
              从品牌邻近评价中提取正/负面短语 · 点击词条直达快照
            </p>
          </div>
          <Cloud />
        </div>
        <div class="brand-insights-sentiment-tabs">
          <button
            type="button"
            :class="{ active: sentimentKeywordTab === 'positive' }"
            @click="sentimentKeywordTab = 'positive'"
          >
            正面关键词
          </button>
          <button
            type="button"
            :class="{ active: sentimentKeywordTab === 'negative' }"
            @click="sentimentKeywordTab = 'negative'"
          >
            负面关键词
          </button>
        </div>
        <div
          v-show="activeSentimentKeywords.length || keywordsLoading"
          ref="sentimentWordCloudRef"
          class="echart-box brand-insights-wordcloud-echart"
          :class="{ 'is-loading': keywordsLoading }"
        />
        <div v-if="keywordsLoading && !activeSentimentKeywords.length" class="mini-empty chart-empty">
          情绪词加载中…
        </div>
        <div v-else-if="!activeSentimentKeywords.length" class="mini-empty chart-empty">
          {{ activeSentimentKeywordSample > 0 ? '暂无可用短语，请稍后刷新。' : `暂无${sentimentKeywordTab === 'positive' ? '正面' : '负面'}情绪样本。` }}
        </div>
      </section>
    </template>

    <div v-else-if="!loading" class="competitor-empty-state">
      <BarChart3 />
      <h3>暂无洞察样本</h3>
      <p>请先完成定时监测并同步结果。若已配置竞品库，数据会在检测完成后自动汇总。</p>
    </div>

    <ElDialog
      v-model="snapshotVisible"
      width="680px"
      align-center
      destroy-on-close
      append-to-body
      class="ws-board-detail-dialog"
      @closed="closeKeywordSnapshot"
    >
      <template #header>
        <div class="ws-board-dialog-head">
          <h3>快照摘要</h3>
          <p v-if="snapshotPhrase || snapshotSubtask?.prompt">
            <template v-if="snapshotPhrase">情绪词「{{ snapshotPhrase }}」</template>
            <template v-if="snapshotPhrase && snapshotSubtask?.prompt"> · </template>
            <template v-if="snapshotSubtask?.prompt">{{ snapshotSubtask.prompt }}</template>
          </p>
        </div>
      </template>

      <div v-if="snapshotLoading" class="ws-board-mini-empty">加载详情…</div>
      <template v-else-if="snapshotSubtask">
        <div class="ws-board-drawer-metrics">
          <span class="ws-board-drawer-chip">
            平台 {{ platformLabelMap[snapshotSubtask.platform] || snapshotSubtask.platform || '—' }}
          </span>
          <span class="ws-board-drawer-chip">排名 {{ snapshotRankLabel }}</span>
          <span class="ws-board-drawer-chip">设备 {{ inferDeviceLabel(snapshotSubtask.platform || '') }}</span>
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
