<script setup lang="ts">
import { computed } from 'vue'
import { BarChart3, ChevronDown, ChevronRight, Download, LayoutGrid, RefreshCw } from '@lucide/vue'
import { ElDrawer } from 'element-plus'
import 'element-plus/es/components/drawer/style/css'
import PlatformBadge from '../../../components/PlatformBadge.vue'
import RankingMatrixChartPanel from '../components/RankingMatrixChartPanel.vue'
import type { RankingMatrixCellSnapshot, MonitorSubtask } from '../../../services/monitor'
import type { WorkspaceTrendPreset } from '../../../utils/customerMonitorDate'
import { citationSourceDisplay } from '../../../utils/sourceSiteLabel'
import { externalLink } from '../portalUtils'
import { useMonitorRealtime } from '../composables/useMonitorRealtime'

function citationRows(list: MonitorSubtask['reference_list'] | undefined) {
  return (list || []).slice(0, 8).map((source, index) => ({
    key: `${source.index ?? index}-${source.url || source.title || index}`,
    href: externalLink(source.url),
    ...citationSourceDisplay(source),
  }))
}

const {
  monitorDetail,
  loadingMonitor,
  loadingMatrix,
  loadingDetail,
  filters,
  datePreset,
  brandCompetitors,
  viewMode,
  rankingMatrix,
  rankingMatrixView,
  matrixChartType,
  activeMatrixPlatform,
  matrixLayoutMode,
  matrixFilterSummary,
  detailVisible,
  detailSubtask,
  detailContext,
  heroMetrics,
  platformCoverage,
  platformOptions,
  scheduleRoundOptions,
  monitorGroupOptions,
  monitorKeywordOptions,
  exposureTermOptions,
  filteredGroupedMonitorTasks,
  scheduleSourceLabel,
  isCustomerView,
  customerTrendPeriodLabel,
  customerTrendMaxDate,
  displayScheduleLabel,
  refreshCurrentView,
  selectMonitorTask,
  switchViewMode,
  openMatrixChartCell,
  toggleMatrixSnapshot,
  matrixDrawerSnapshots,
  isMatrixDrawerMode,
  expandedSnapshotId,
  loadingSnapshotId,
  openListSubtask,
  closeDetail,
  applyDatePreset,
  onCustomDateChange,
  resetFilters,
  exportMatrixCsv,
  formatRank,
  formatExposureLabel,
  formatKeywordGroupDetailHint,
  keywordGroupSelectValue,
  keywordGroupFilterValue,
  formatTaskTitle,
  taskPromptPreview,
  answerExcerpt,
  sentimentToneClass,
  taskPromptCount,
  taskPlatformCount,
  filteredMonitorSubtasks,
  monitorResultPlatformOptions,
  monitorResultStatusOptions,
  platformLabelMap,
  monitorStatusLabelMap,
  sentimentLabelMap,
  formatDateTime,
} = useMonitorRealtime()


const isLoading = computed(() => {
  if (viewMode.value === 'matrix') {
    return loadingMatrix.value && !rankingMatrix.value
  }
  return loadingMonitor.value || loadingMatrix.value
})

const customerDatePresetOptions: Array<{ value: WorkspaceTrendPreset; label: string }> = [
  { value: '7d', label: '近7日' },
  { value: 'month', label: '月' },
  { value: 'quarter', label: '季度' },
  { value: 'year', label: '年' },
  { value: 'custom', label: '自定义' },
]

const drawerAvgRank = computed(() => {
  const cell = detailContext.value?.cell
  if ((cell?.prompt_intent ?? detailSubtask.value?.prompt_intent) !== 'ranking') return null
  if ((cell?.rank_sample_count || cell?.sample_count || 0) > 1) {
    return formatRank(cell?.mention_position)
  }
  return null
})

const drawerRank = computed(() => {
  const subtask = detailSubtask.value
  if (subtask?.prompt_intent === 'ranking') {
    return formatRank(subtask.mention_position)
  }
  const cell = detailContext.value?.cell
  if (cell?.prompt_intent === 'ranking') {
    return formatRank(cell.mention_position)
  }
  return null
})

const drawerExposure = computed(() => {
  const subtask = detailSubtask.value
  const cell = detailContext.value?.cell
  if ((subtask?.prompt_intent ?? cell?.prompt_intent) !== 'ranking') {
    return formatExposureLabel(subtask?.brand_mentioned ?? cell?.brand_mentioned)
  }
  return null
})

const showRankNote = computed(() => {
  const subtask = detailSubtask.value
  if (!subtask) return false
  const intent = subtask.prompt_intent ?? detailContext.value?.cell?.prompt_intent
  const raw = subtask.raw_mention_position
  const rank = subtask.mention_position
  return intent === 'ranking' && raw != null && raw !== rank
})

function snapshotRankNote(snapshot: RankingMatrixCellSnapshot, subtask: MonitorSubtask | null) {
  if (!subtask || subtask.subtask_id !== snapshot.subtask_id) return false
  const intent = subtask.prompt_intent ?? snapshot.prompt_intent
  const raw = subtask.raw_mention_position ?? snapshot.raw_mention_position
  const rank = subtask.mention_position ?? snapshot.mention_position
  return intent === 'ranking' && raw != null && raw !== rank
}
</script>

<template>
  <section class="monitor-page realtime-monitor-page">
    <header class="realtime-sticky-bar">
      <div class="realtime-sticky-inner">
        <div v-if="isCustomerView" class="realtime-date-filter">
          <div class="realtime-date-presets">
            <button
              v-for="option in customerDatePresetOptions"
              :key="option.value"
              type="button"
              :class="{ active: datePreset === option.value }"
              @click="applyDatePreset(option.value)"
            >
              {{ option.label }}
            </button>
          </div>
          <span
            v-if="datePreset !== 'custom' && customerTrendPeriodLabel"
            class="realtime-date-range-chip"
            :title="`${filters.startDate} ~ ${filters.endDate}`"
          >{{ customerTrendPeriodLabel }}</span>
          <div v-if="datePreset === 'custom'" class="realtime-custom-dates">
            <input
              v-model="filters.startDate"
              type="date"
              :max="filters.endDate"
              @change="onCustomDateChange"
            >
            <span>至</span>
            <input
              v-model="filters.endDate"
              type="date"
              :min="filters.startDate"
              :max="customerTrendMaxDate"
              @change="onCustomDateChange"
            >
          </div>
        </div>
        <template v-else>
          <div class="realtime-date-presets">
            <button type="button" :class="{ active: datePreset === '7d' }" @click="applyDatePreset('7d')">近 7 天</button>
            <button type="button" :class="{ active: datePreset === '30d' }" @click="applyDatePreset('30d')">近 30 天</button>
            <button type="button" :class="{ active: datePreset === 'custom' }" @click="datePreset = 'custom'">自定义</button>
          </div>
          <div v-if="datePreset === 'custom'" class="realtime-custom-dates">
            <input v-model="filters.startDate" type="date" @change="onCustomDateChange">
            <span>至</span>
            <input v-model="filters.endDate" type="date" @change="onCustomDateChange">
          </div>
        </template>
        <div class="realtime-sticky-filters">
          <select v-model="filters.platform">
            <option value="">全部平台</option>
            <option v-for="platform in platformOptions" :key="platform" :value="platform">
              {{ platformLabelMap[platform] || platform }}
            </option>
          </select>
          <select v-model="filters.keywordGroup" class="monitor-group-select" title="按监测词组筛选">
            <option value="">全部词组</option>
            <option
              v-for="(group, groupIndex) in monitorGroupOptions"
              :key="`group-${group.id ?? group.sort_order}-${group.name || group.monitor_keyword}`"
              :value="keywordGroupSelectValue(group, groupIndex)"
              :title="formatKeywordGroupDetailHint(group)"
            >
              {{ keywordGroupFilterValue(group, groupIndex) }}
            </option>
          </select>
          <select v-model="filters.monitorKeyword" class="monitor-keyword-select" title="按监测问题筛选">
            <option value="">全部监控词</option>
            <option
              v-for="keyword in monitorKeywordOptions"
              :key="`monitor-kw-${keyword}`"
              :value="keyword"
            >
              {{ keyword }}
            </option>
          </select>
          <select v-model="filters.exposureTerm" class="monitor-exposure-select" title="按露出词筛选">
            <option value="">全部露出词</option>
            <option v-for="term in exposureTermOptions" :key="`exposure-${term}`" :value="term">
              {{ term }}
            </option>
          </select>
          <select v-if="viewMode === 'list'" v-model="filters.scheduleWindowKey">
            <option value="">全部轮次</option>
            <option
              v-for="item in scheduleRoundOptions"
              :key="item.schedule_window_key"
              :value="item.schedule_window_key"
            >
              {{ item.schedule_label }}
            </option>
          </select>
        </div>
        <div class="realtime-view-toggle">
          <button type="button" :class="{ active: viewMode === 'matrix' }" @click="switchViewMode('matrix')">排名矩阵</button>
          <button type="button" :class="{ active: viewMode === 'list' }" @click="switchViewMode('list')">逐条列表</button>
        </div>
        <div class="realtime-sticky-actions">
          <span v-if="isLoading" class="realtime-loading-dot">更新中</span>
          <button type="button" class="filter-reset-btn tiny-btn" @click="resetFilters">重置</button>
          <button type="button" class="filter-reset-btn tiny-btn" :disabled="isLoading" @click="refreshCurrentView">
            <RefreshCw />
            刷新
          </button>
          <button
            type="button"
            class="primary-btn small-btn"
            :disabled="!rankingMatrixView?.rows.length"
            @click="exportMatrixCsv"
          >
            <Download />
            导出矩阵
          </button>
        </div>
        <div class="realtime-filter-summary">
          日期 <b>{{ matrixFilterSummary.date }}</b>
          · 平台 <b>{{ matrixFilterSummary.platform }}</b>
          · 词组 <b>{{ matrixFilterSummary.group }}</b>
          · 监测词 <b>{{ matrixFilterSummary.monitorKeyword }}</b>
          · 露出词 <b>{{ matrixFilterSummary.exposureTerm }}</b>
          · 结果 <b>{{ matrixFilterSummary.columnCount }}</b> 词 · <b>{{ matrixFilterSummary.dayCount }}</b> 天
        </div>
      </div>
    </header>

    <div v-if="viewMode === 'matrix'" class="realtime-matrix-legend-strip">
      <span><i class="legend-top-1" />1</span>
      <span><i class="legend-top-3" />2–3</span>
      <span><i class="legend-mid" />4–6</span>
      <span><i class="legend-none" />未提及</span>
    </div>

    <article class="realtime-hero">
      <div v-if="isLoading && !rankingMatrix && !monitorDetail" class="realtime-hero-skeleton">
        <div /><div /><div /><div />
      </div>
      <div v-else class="realtime-hero-metrics">
        <div class="realtime-hero-metric">
          <span>最近日期</span>
          <b>{{ heroMetrics.latestSchedule || '—' }}</b>
          <em>
            {{ heroMetrics.dayCount }} 天有数据 · {{ heroMetrics.scopeLabel }}
            <template v-if="loadingMatrix"> · 更新中</template>
          </em>
        </div>
        <div class="realtime-hero-metric">
          <span>成功样本</span>
          <b>{{ heroMetrics.sampleCount != null ? heroMetrics.sampleCount : '—' }}</b>
          <em>{{ heroMetrics.columnCount }} 个监测词 · {{ heroMetrics.scopeLabel }}</em>
        </div>
        <div class="realtime-hero-metric">
          <span>平均排名</span>
          <b>{{ heroMetrics.avgRank != null ? formatRank(heroMetrics.avgRank) : '—' }}</b>
          <em v-if="heroMetrics.mentionRate != null">提及率 {{ heroMetrics.mentionRate }}%</em>
          <em v-else>{{ heroMetrics.scopeLabel }}</em>
        </div>
        <div class="realtime-hero-metric">
          <span>Top3 占比</span>
          <b>{{ heroMetrics.top3Rate != null ? `${heroMetrics.top3Rate}%` : '—' }}</b>
          <em>{{ heroMetrics.scopeLabel }}</em>
        </div>
      </div>
    </article>

    <details class="panel realtime-config-panel">
      <summary>
        {{ isCustomerView ? '监测范围' : '监测计划与平台范围' }}
        <ChevronDown />
      </summary>
      <div class="realtime-config-body">
        <div class="realtime-config-grid is-customer-safe">
          <div class="realtime-config-card">
            <span>竞品监测</span>
            <b>{{ brandCompetitors.length }} 个竞品</b>
            <small>{{ brandCompetitors.slice(0, 4).map(item => item.name).join('、') || '暂无' }}</small>
          </div>
          <div class="realtime-config-card">
            <span>平台范围</span>
            <div class="realtime-platform-chips">
              <span
                v-for="item in platformCoverage"
                :key="item.code"
                class="realtime-platform-chip"
                :class="item.status === '已返回' ? 'is-active' : 'is-pending'"
              >
                {{ item.name }}
              </span>
            </div>
          </div>
        </div>
      </div>
    </details>

    <section v-if="viewMode === 'matrix'" class="realtime-matrix-panel realtime-matrix-platform-grid">
      <div class="realtime-chart-mode-bar">
        <div class="realtime-chart-mode-label">
          图表类型
          <small>排名快照：单日=当日排名，区间=均值；走势热力按天对比</small>
        </div>
        <div class="realtime-chart-view-toggle">
          <button
            type="button"
            :class="{ active: matrixChartType === 'bar' }"
            @click="matrixChartType = 'bar'"
          >
            <BarChart3 />
            排名快照
          </button>
          <button
            type="button"
            :class="{ active: matrixChartType === 'heat' }"
            @click="matrixChartType = 'heat'"
          >
            <LayoutGrid />
            走势热力
          </button>
          <!-- 完整矩阵与走势热力功能重叠，暂隐藏
          <button
            type="button"
            :class="{ active: matrixChartType === 'table' }"
            @click="matrixChartType = 'table'"
          >
            <Table2 />
            完整矩阵
          </button>
          -->
        </div>
      </div>

      <div v-if="loadingMatrix" class="mini-empty">排名矩阵加载中…</div>
      <RankingMatrixChartPanel
        v-else-if="rankingMatrixView"
        :matrix="rankingMatrixView"
        :chart-type="matrixChartType"
        :active-platform="activeMatrixPlatform"
        :layout-mode="matrixLayoutMode"
        :purchased-platforms="platformOptions"
        :platform-label-map="platformLabelMap"
        :format-rank="formatRank"
        :display-schedule-label="displayScheduleLabel"
        :filter-start-date="filters.startDate"
        :filter-end-date="filters.endDate"
        @update:active-platform="activeMatrixPlatform = $event"
        @open-cell="openMatrixChartCell"
      />
      <!-- 完整矩阵表视图暂隐藏（与走势热力重叠），代码保留便于恢复
      <template v-else-if="rankingMatrixView?.columns.length && rankingMatrixView.rows.length">
        <div class="realtime-matrix-scroll">
          <table class="realtime-matrix-table">
            <thead>
              <tr>
                <th class="realtime-matrix-time-col">日期</th>
                <th
                  v-for="column in rankingMatrixView!.columns"
                  :key="column.prompt"
                  class="realtime-matrix-prompt-col"
                  :title="column.prompt"
                >
                  <small v-if="column.monitor_keyword">{{ column.monitor_keyword }}</small>
                  <small v-else-if="column.group_name">{{ column.group_name }}</small>
                  <span>{{ column.prompt }}</span>
                </th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="row in rankingMatrixView.rows"
                :key="`${row.schedule_window_key || row.task_id}-${row.keyword_group || ''}-${row.platform || ''}`"
                :class="{ 'realtime-matrix-row-latest': isLatestMatrixRow(row) }"
              >
                <th class="realtime-matrix-time-col">
                  <span>{{ displayScheduleLabel(row.schedule_label || row.snapshot_at || '-') }}{{ isCustomerView ? '' : scheduleSourceLabel(row.schedule_source) }}</span>
                  <small v-if="!isCustomerView && row.keyword_group && !filterScope.keywordGroup && !filterScope.monitorKeyword">{{ row.keyword_group }}</small>
                  <small v-if="rankingMatrixView?.all_platforms && row.platform" class="realtime-matrix-platform">
                    <PlatformBadge :code="row.platform" size="xs" />
                  </small>
                </th>
                <td
                  v-for="column in rankingMatrixView!.columns"
                  :key="`${row.schedule_window_key || row.task_id}-${column.prompt}`"
                  class="realtime-matrix-cell"
                  :class="[
                    matrixCellRankClass(row.cells[column.prompt]?.mention_position),
                    {
                      'is-active': selectedMatrixCell?.taskId === row.task_id
                        && selectedMatrixCell?.prompt === column.prompt
                        && (selectedMatrixCell?.platform || '') === (row.platform || ''),
                    },
                  ]"
                  :title="matrixCellTitle(row.cells[column.prompt])"
                  @click="selectMatrixCell(row.task_id, row.platform, row.snapshot_at, row.schedule_label, column.prompt, row.cells[column.prompt])"
                >
                  {{ formatRank(row.cells[column.prompt]?.mention_position) }}
                  <small
                    v-if="(row.cells[column.prompt]?.rank_sample_count || 0) > 1"
                    class="realtime-matrix-cell-note"
                  >均</small>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>
      -->
      <div v-else class="mini-empty">当前筛选条件下暂无排名数据，请调整日期或平台。</div>
    </section>

    <section v-else class="realtime-list-layout">
      <article class="realtime-task-panel">
        <div class="panel-head compact">
          <h2>检测记录</h2>
          <span>{{ filteredGroupedMonitorTasks.reduce((sum, g) => sum + g.tasks.length, 0) }} 个词组任务</span>
        </div>
        <div v-for="group in filteredGroupedMonitorTasks" :key="group.schedule_window_key" class="realtime-schedule-group">
          <div class="realtime-schedule-group-head">
            <b>{{ displayScheduleLabel(group.schedule_label) }}</b>
            <span>{{ group.tasks.length }} 个词组</span>
          </div>
          <button
            v-for="task in group.tasks"
            :key="task.task_id"
            type="button"
            class="realtime-task-item"
            :class="{ active: monitorDetail?.task.task_id === task.task_id }"
            @click="selectMonitorTask(task.task_id)"
          >
            <b>{{ formatTaskTitle(task) }}</b>
            <span v-if="taskPromptPreview(task)" class="task-prompt-preview">{{ taskPromptPreview(task) }}</span>
            <small>{{ monitorStatusLabelMap[task.status] || task.status }} · {{ task.completed_items }}/{{ task.total_items }}{{ scheduleSourceLabel(task.schedule_source) }} · {{ taskPromptCount(task) }} 问 × {{ taskPlatformCount(task) }} 平台</small>
          </button>
        </div>
        <div v-if="loadingMonitor && !filteredGroupedMonitorTasks.length" class="mini-empty">检测记录加载中…</div>
        <div v-else-if="!loadingMonitor && !filteredGroupedMonitorTasks.length" class="mini-empty">暂无检测批次，等待定时任务返回。</div>
      </article>

      <article class="realtime-result-panel">
        <div class="panel-head compact">
          <div>
            <h2>本轮检测</h2>
            <p>{{ monitorDetail ? '点击卡片查看完整 AI 回答' : '从左侧选择词组任务' }}</p>
          </div>
        </div>

        <template v-if="monitorDetail">
          <div class="realtime-result-summary">
            <span>{{ isCustomerView ? '批次' : '轮次' }} <b>{{ displayScheduleLabel(monitorDetail.task.schedule_label, '—') }}</b></span>
            <span>状态 <b>{{ monitorStatusLabelMap[monitorDetail.task.status] || monitorDetail.task.status }}</b></span>
            <span>完成 <b>{{ monitorDetail.task.completed_items }}/{{ monitorDetail.task.total_items }}</b></span>
            <span v-if="monitorDetail.task.failed_items">失败 <b>{{ monitorDetail.task.failed_items }}</b></span>
          </div>

          <div class="realtime-sticky-filters" style="margin-bottom: 14px;">
            <select v-model="filters.status">
              <option value="all">全部状态</option>
              <option v-for="status in monitorResultStatusOptions" :key="status" :value="status">
                {{ monitorStatusLabelMap[status] || status }}
              </option>
            </select>
            <select v-model="filters.platform">
              <option value="">全部平台</option>
              <option v-for="platform in monitorResultPlatformOptions" :key="platform" :value="platform">
                {{ platformLabelMap[platform] || platform }}
              </option>
            </select>
            <em style="align-self: center; font-style: normal; color: #8aa0ba; font-size: 12px;">
              {{ filteredMonitorSubtasks.length }} / {{ monitorDetail.subtasks.length }} 条
            </em>
          </div>

          <button
            v-for="subtask in filteredMonitorSubtasks"
            :key="subtask.subtask_id"
            type="button"
            class="realtime-subtask-card"
            :class="sentimentToneClass(subtask.sentiment)"
            @click="openListSubtask(subtask)"
          >
            <div class="realtime-subtask-head">
              <PlatformBadge :code="subtask.platform" size="xs" class="realtime-platform-badge" />
              <span
                v-if="subtask.prompt_intent === 'ranking'"
                class="realtime-rank-badge"
                :class="{ 'is-none': subtask.mention_position == null }"
              >
                排名 {{ formatRank(subtask.mention_position) }}
              </span>
              <span v-else class="realtime-rank-badge" :class="{ 'is-none': !subtask.brand_mentioned }">
                {{ formatExposureLabel(subtask.brand_mentioned) }}
              </span>
              <span class="realtime-sentiment-pill" :class="sentimentToneClass(subtask.sentiment)">
                {{ sentimentLabelMap[subtask.sentiment || ''] || subtask.sentiment || '暂无' }}
              </span>
            </div>
            <h4>{{ subtask.prompt }}</h4>
            <p>{{ answerExcerpt(subtask.answer_content) || '暂无回答摘要' }}</p>
            <div class="realtime-subtask-foot">
              <span>{{ monitorStatusLabelMap[subtask.status || ''] || subtask.status }}</span>
              <span>查看详情 <ChevronRight /></span>
            </div>
          </button>
          <div v-if="!filteredMonitorSubtasks.length" class="mini-empty">没有匹配当前筛选的结果。</div>
        </template>
        <div v-else class="mini-empty">选择左侧词组任务后，可浏览各平台检测结果。</div>
      </article>
    </section>

    <ElDrawer
      v-model="detailVisible"
      size="480px"
      destroy-on-close
      class="realtime-detail-drawer"
      @closed="closeDetail"
    >
      <template #header>
        <div class="realtime-drawer-head">
          <h3>{{ detailContext?.prompt || detailSubtask?.prompt || '检测详情' }}</h3>
          <p>
            {{ detailContext?.scheduleLabel || '—' }}
            · <PlatformBadge
              v-if="detailContext?.platform || detailSubtask?.platform"
              :code="detailContext?.platform || detailSubtask?.platform || ''"
              size="xs"
            />
            <template v-else>—</template>
          </p>
        </div>
      </template>

      <div v-if="loadingDetail && !isMatrixDrawerMode" class="mini-empty">加载详情…</div>
      <template v-else-if="isMatrixDrawerMode">
        <div class="realtime-drawer-snapshots-head">
          <b>当日监测快照</b>
          <span>
            {{ matrixDrawerSnapshots.length }} 轮
            <template v-if="drawerAvgRank"> · 均值 {{ drawerAvgRank }}</template>
          </span>
        </div>
        <p class="realtime-drawer-list-hint">点击某一轮展开查看回答与快照，再次点击可收起。</p>
        <div class="realtime-drawer-accordion">
          <article
            v-for="(snapshot, index) in matrixDrawerSnapshots"
            :key="snapshot.subtask_id"
            class="realtime-drawer-accordion-item"
            :class="{ 'is-expanded': expandedSnapshotId === snapshot.subtask_id }"
          >
            <button
              type="button"
              class="realtime-drawer-accordion-trigger"
              @click="toggleMatrixSnapshot(snapshot)"
            >
              <span class="realtime-drawer-snapshot-round">第 {{ index + 1 }} 轮</span>
              <span class="realtime-drawer-accordion-main">
                <strong>{{ snapshot.schedule_label || formatDateTime(snapshot.updated_at) || '—' }}{{ scheduleSourceLabel(snapshot.schedule_source) }}</strong>
                <small>
                  排名 {{ formatRank(snapshot.mention_position) }}
                  · {{ sentimentLabelMap[snapshot.sentiment || ''] || '暂无情感' }}
                  <template v-if="snapshot.page_screenshot"> · 含快照</template>
                </small>
              </span>
              <ChevronDown class="realtime-drawer-accordion-chevron" />
            </button>
            <div
              v-if="expandedSnapshotId === snapshot.subtask_id"
              class="realtime-drawer-accordion-body"
            >
              <div v-if="loadingSnapshotId === snapshot.subtask_id" class="mini-empty compact-empty">加载中…</div>
              <template v-else-if="detailSubtask?.subtask_id === snapshot.subtask_id">
                <div class="realtime-drawer-metrics compact">
                  <span>排名 {{ formatRank(detailSubtask.mention_position) }}</span>
                  <span>情感 {{ sentimentLabelMap[detailSubtask.sentiment || ''] || '暂无' }}</span>
                  <span>状态 {{ monitorStatusLabelMap[detailSubtask.status || ''] || '—' }}</span>
                  <a
                    v-if="externalLink(detailSubtask.page_screenshot || snapshot.page_screenshot)"
                    :href="externalLink(detailSubtask.page_screenshot || snapshot.page_screenshot)!"
                    target="_blank"
                    rel="noopener noreferrer"
                  >打开快照</a>
                </div>
                <p v-if="snapshotRankNote(snapshot, detailSubtask)" class="realtime-drawer-note">
                  回答正文中未出现品牌露出词，矩阵展示「-」；原始检测排名仅供参考，已按正文重新计算。
                </p>
                <pre v-if="detailSubtask.answer_content" class="realtime-drawer-answer">{{ detailSubtask.answer_content }}</pre>
                <p v-else-if="detailSubtask.mention_context" class="realtime-drawer-note">{{ detailSubtask.mention_context }}</p>
                <div v-if="detailSubtask.reference_list?.length" class="realtime-drawer-sources">
                  <b>引用信源</b>
                  <a
                    v-for="row in citationRows(detailSubtask.reference_list)"
                    :key="`${detailSubtask.subtask_id}-${row.key}`"
                    :href="row.href || undefined"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    <span>{{ row.title }}</span>
                    <span v-if="row.site" class="realtime-drawer-source-site"> · {{ row.site }}</span>
                  </a>
                </div>
                <p v-if="detailSubtask.error_message" class="danger-copy">{{ detailSubtask.error_message }}</p>
              </template>
            </div>
          </article>
        </div>
      </template>
      <template v-else-if="detailSubtask || detailContext">
        <div class="realtime-drawer-metrics">
          <span v-if="drawerRank != null">品牌排名 {{ drawerRank }}</span>
          <span v-if="drawerExposure != null">品牌露出 {{ drawerExposure }}</span>
          <span>情感 {{ sentimentLabelMap[detailSubtask?.sentiment || detailContext?.cell?.sentiment || ''] || '暂无' }}</span>
          <span>状态 {{ monitorStatusLabelMap[detailSubtask?.status || detailContext?.cell?.status || ''] || '—' }}</span>
          <a
            v-if="externalLink(detailSubtask?.page_screenshot || detailContext?.cell?.page_screenshot)"
            :href="externalLink(detailSubtask?.page_screenshot || detailContext?.cell?.page_screenshot)!"
            target="_blank"
            rel="noopener noreferrer"
          >打开快照</a>
        </div>

        <p v-if="showRankNote" class="realtime-drawer-note">
          回答正文中未出现品牌露出词，矩阵展示「-」；原始检测排名仅供参考，已按正文重新计算。
        </p>

        <pre v-if="detailSubtask?.answer_content" class="realtime-drawer-answer">{{ detailSubtask.answer_content }}</pre>
        <p v-else-if="detailSubtask?.mention_context" class="realtime-drawer-note">{{ detailSubtask.mention_context }}</p>

        <div v-if="detailSubtask?.reference_list?.length" class="realtime-drawer-sources">
          <b>引用信源</b>
          <a
            v-for="row in citationRows(detailSubtask.reference_list)"
            :key="`${detailSubtask.subtask_id}-${row.key}`"
            :href="row.href || undefined"
            target="_blank"
            rel="noopener noreferrer"
          >
            <span>{{ row.title }}</span>
            <span v-if="row.site" class="realtime-drawer-source-site"> · {{ row.site }}</span>
          </a>
        </div>

        <p v-if="detailSubtask?.error_message" class="danger-copy">{{ detailSubtask.error_message }}</p>
      </template>
    </ElDrawer>
  </section>
</template>
