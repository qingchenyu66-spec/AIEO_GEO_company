<script setup lang="ts">
import { computed } from 'vue'
import { useMonitorRealtime } from '../composables/useMonitorRealtime'

const {
  monitorTasks,
  monitorDetail,
  loadingMonitor,
  filters,
  matrixFilters,
  brandAsset,
  brandCompetitors,
  viewMode,
  rankingMatrix,
  loadingMatrix,
  loadingMatrixDetail,
  selectedMatrixCell,
  selectedMatrixSubtask,
  loadMonitorTasks,
  loadRankingMatrix,
  selectMonitorTask,
  switchViewMode,
  selectMatrixCell,
  clearMatrixCellSelection,
  resetMatrixFilters,
  formatRank,
  formatExposureLabel,
  formatTaskTime,
  taskPromptCount,
  taskPlatformCount,
  filteredMonitorSubtasks,
  monitorResultPlatformOptions,
  monitorResultStatusOptions,
  matrixPlatformOptions,
  platformCoverage,
  monitorGroupOptions,
  formatMonitorGroupLabel,
  groupedMonitorTasks,
  schedulePlanDisplay,
  scheduleSourceLabel,
  platformLabelMap,
  monitorStatusLabelMap,
  monitorModeLabelMap,
  sentimentLabelMap,
} = useMonitorRealtime()

const matrixDetailVisible = computed({
  get: () => selectedMatrixCell.value !== null,
  set: (open: boolean) => {
    if (!open) clearMatrixCellSelection()
  },
})
</script>

<template>
  <section class="monitor-page">
    <article class="panel monitor-submit-panel">
      <div class="panel-head">
        <div><h2>定时监测结果</h2><p>系统按平台端配置自动检测，客户侧只查看结果、快照和趋势，不开放手动提交。</p></div>
        <span>平台自动巡检</span>
      </div>
      <div class="monitor-brand-card">
        <div>
          <span>当前监测企业</span>
          <b>{{ brandAsset?.company_full_name || '未配置品牌资产' }}</b>
          <small>主品牌：{{ brandAsset?.brand_name || '-' }} · 简称：{{ brandAsset?.brand_short_name || '-' }}</small>
        </div>
        <div>
          <span>自动带入</span>
          <b>{{ brandCompetitors.length }} 个竞品</b>
          <small>{{ brandCompetitors.slice(0, 4).map(item => item.name).join(' / ') || '请先维护竞品库' }}</small>
        </div>
      </div>
      <div class="monitor-schedule-grid">
        <div>
          <b>{{ schedulePlanDisplay?.typeLabel || '监测计划' }}</b>
          <span>按企业配置的监测频率执行</span>
        </div>
        <div v-for="time in schedulePlanDisplay?.times || []" :key="time">
          <b>{{ time }}</b>
          <span>计划检测时刻</span>
        </div>
        <div v-if="!(schedulePlanDisplay?.times || []).length">
          <b>待配置</b>
          <span>尚未设置具体检测时刻</span>
        </div>
        <div><b>平台范围</b><span>{{ platformCoverage.map(item => item.name).join(' / ') || '-' }}</span></div>
      </div>
    </article>

    <div class="monitor-view-tabs">
      <button type="button" :class="{ active: viewMode === 'list' }" @click="switchViewMode('list')">列表视图</button>
      <button type="button" :class="{ active: viewMode === 'matrix' }" @click="switchViewMode('matrix')">排名矩阵</button>
    </div>

    <section v-if="viewMode === 'matrix'" class="panel ranking-matrix-panel">
      <div class="panel-head">
        <div>
          <h2>排名矩阵</h2>
          <p>每行对应一次<strong>调度轮次</strong>（按企业配置时刻，如 14:30）下的检测结果；列为监测问题。单元格数字为<strong>品牌在 AI 推荐列表中的排名</strong>（越小越靠前，「-」表示未提及）。</p>
        </div>
        <button class="filter-search-btn" :disabled="loadingMatrix" @click="loadRankingMatrix">刷新矩阵</button>
      </div>

      <div class="ranking-matrix-filters">
        <label>
          <span>平台</span>
          <select v-model="matrixFilters.platform">
            <option value="">全部平台</option>
            <option v-for="platform in matrixPlatformOptions" :key="platform" :value="platform">{{ platformLabelMap[platform] || platform }}</option>
          </select>
        </label>
        <label>
          <span>开始日期</span>
          <input v-model="matrixFilters.startDate" type="date" />
        </label>
        <label>
          <span>结束日期</span>
          <input v-model="matrixFilters.endDate" type="date" />
        </label>
        <label class="monitor-filter-keyword">
          <span>监测词组</span>
          <select v-model="matrixFilters.monitorGroup">
            <option value="">全部词组</option>
            <option v-for="group in monitorGroupOptions" :key="group.monitor_keyword" :value="group.monitor_keyword">
              {{ formatMonitorGroupLabel(group) }}
            </option>
          </select>
        </label>
        <button type="button" :disabled="loadingMatrix" @click="loadRankingMatrix">查询</button>
        <button type="button" @click="resetMatrixFilters">重置</button>
      </div>

      <div v-if="rankingMatrix" class="ranking-matrix-meta">
        <span>平台 <b>{{ rankingMatrix.all_platforms ? '全部' : (platformLabelMap[rankingMatrix.platform || ''] || rankingMatrix.platform || '-') }}</b></span>
        <span>品牌 <b>{{ rankingMatrix.brand_name || '-' }}</b></span>
        <span>调度轮次 <b>{{ rankingMatrix.schedule_round_count ?? '-' }}</b></span>
        <span>词组任务 <b>{{ rankingMatrix.task_count ?? rankingMatrix.rows.length }}</b></span>
        <span>监测问题 <b>{{ rankingMatrix.columns.length }}</b></span>
      </div>

      <div v-if="loadingMatrix" class="mini-empty">排名矩阵加载中…</div>
      <div v-else-if="rankingMatrix && rankingMatrix.columns.length && rankingMatrix.rows.length" class="ranking-matrix-scroll">
        <table class="ranking-matrix-table">
          <thead>
            <tr>
              <th class="ranking-matrix-time-col">调度轮次</th>
              <th v-for="column in rankingMatrix.columns" :key="column.prompt" class="ranking-matrix-prompt-col" :title="column.prompt">
                <small v-if="column.group_name">{{ column.group_name }}</small>
                <span>{{ column.prompt }}</span>
              </th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in rankingMatrix.rows" :key="`${row.schedule_window_key || row.task_id}-${row.keyword_group || ''}-${row.platform || ''}`">
              <th class="ranking-matrix-time-col">
                <span>{{ row.schedule_label || row.snapshot_at || '-' }}{{ scheduleSourceLabel(row.schedule_source) }}</span>
                <small v-if="row.keyword_group && !matrixFilters.monitorGroup">{{ row.keyword_group }}</small>
                <small v-if="rankingMatrix.all_platforms && row.platform">{{ platformLabelMap[row.platform] || row.platform }}</small>
              </th>
              <td
                v-for="column in rankingMatrix.columns"
                :key="`${row.schedule_window_key || row.task_id}-${row.keyword_group || ''}-${row.platform || ''}-${column.prompt}`"
                class="ranking-matrix-cell"
                :class="{
                  'has-rank': row.cells[column.prompt]?.mention_position != null,
                  active: selectedMatrixCell?.taskId === row.task_id
                    && selectedMatrixCell?.prompt === column.prompt
                    && (selectedMatrixCell?.platform || '') === (row.platform || ''),
                }"
                @click="selectMatrixCell(row.task_id, row.platform, row.snapshot_at, row.schedule_label, column.prompt, row.cells[column.prompt])"
              >
                {{ formatRank(row.cells[column.prompt]?.mention_position) }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-else-if="rankingMatrix" class="mini-empty">当前筛选条件下暂无排名数据，请调整平台或日期范围。</div>
    </section>

    <section v-else class="monitor-layout">
      <article class="panel monitor-task-list">
        <div class="panel-head"><h2>检测记录</h2><span>{{ monitorTasks.length }} 个词组任务</span></div>
        <div v-for="group in groupedMonitorTasks" :key="group.schedule_window_key" class="monitor-schedule-group">
          <div class="monitor-schedule-group-head">
            <b>{{ group.schedule_label }}</b>
            <span>{{ group.tasks.length }} 个词组任务</span>
          </div>
          <button
            v-for="task in group.tasks"
            :key="task.task_id"
            class="monitor-task-item"
            :class="{ active: monitorDetail?.task.task_id === task.task_id }"
            @click="selectMonitorTask(task.task_id)"
          >
            <b>{{ task.keyword_group || task.monitor_keywords || '未填词组' }}</b>
            <small>{{ monitorStatusLabelMap[task.status] || task.status }} · {{ task.completed_items }}/{{ task.total_items }} 子任务{{ scheduleSourceLabel(task.schedule_source) }}</small>
            <em>{{ taskPromptCount(task) }} 问 × {{ taskPlatformCount(task) }} 平台 · {{ task.platforms.map(item => platformLabelMap[item.platform] || item.platform).join('、') }}</em>
          </button>
        </div>
        <div v-if="!loadingMonitor && !monitorTasks.length" class="mini-empty">暂无检测批次，等待定时任务运行后会出现在这里。</div>
      </article>

      <article class="panel monitor-result-panel">
        <div class="panel-head">
          <div><h2>批次详情</h2><p>{{ monitorDetail ? '查看本次提交的问题、平台与检测结果' : '从左侧选择一次检测批次' }}</p></div>
          <button class="filter-search-btn" :disabled="loadingMonitor" @click="loadMonitorTasks">刷新列表</button>
        </div>
        <template v-if="monitorDetail">
          <details class="monitor-task-prompts" open>
            <summary>
              <span>本次检测问题（{{ taskPromptCount(monitorDetail.task) }} 问 × {{ taskPlatformCount(monitorDetail.task) }} 平台 = {{ monitorDetail.task.total_items || monitorDetail.subtasks.length }} 子任务）</span>
              <em>调度轮次：{{ monitorDetail.task.schedule_label || formatTaskTime(monitorDetail.task.created_at) }}{{ scheduleSourceLabel(monitorDetail.task.schedule_source) }} · 词组：{{ monitorDetail.task.keyword_group || monitorDetail.task.monitor_keywords || '-' }}</em>
            </summary>
            <ol>
              <li v-for="prompt in monitorDetail.task.prompts" :key="prompt">{{ prompt }}</li>
            </ol>
          </details>
          <div class="monitor-result-filters">
            <label>
              <span>平台</span>
              <select v-model="filters.platform">
                <option value="all">全部平台</option>
                <option v-for="platform in monitorResultPlatformOptions" :key="platform" :value="platform">{{ platformLabelMap[platform] || platform }}</option>
              </select>
            </label>
            <label>
              <span>状态</span>
              <select v-model="filters.status">
                <option value="all">全部状态</option>
                <option v-for="status in monitorResultStatusOptions" :key="status" :value="status">{{ monitorStatusLabelMap[status] || status }}</option>
              </select>
            </label>
            <label class="monitor-filter-keyword">
              <span>监测词组</span>
              <select v-model="filters.monitorGroup">
                <option value="">全部词组</option>
                <option v-for="group in monitorGroupOptions" :key="`list-${group.monitor_keyword}`" :value="group.monitor_keyword">
                  {{ formatMonitorGroupLabel(group) }}
                </option>
              </select>
            </label>
            <button type="button" @click="filters.platform = 'all'; filters.status = 'all'; filters.monitorGroup = ''">重置</button>
            <em>{{ filteredMonitorSubtasks.length }} / {{ monitorDetail.subtasks.length }} 条</em>
          </div>
          <div class="monitor-summary">
            <span>状态 <b>{{ monitorStatusLabelMap[monitorDetail.task.status] || monitorDetail.task.status }}</b></span>
            <span>完成 <b>{{ monitorDetail.task.completed_items }}/{{ monitorDetail.task.total_items }}</b></span>
            <span>失败 <b>{{ monitorDetail.task.failed_items }}</b></span>
            <span v-if="monitorDetail.task.last_error">错误 <b>{{ monitorDetail.task.last_error }}</b></span>
          </div>
          <div v-for="subtask in filteredMonitorSubtasks" :key="subtask.subtask_id" class="monitor-subtask-card">
            <div class="subtask-head">
              <div><b>{{ platformLabelMap[subtask.platform || ''] || subtask.platform || '-' }} / {{ monitorModeLabelMap[subtask.mode || ''] || subtask.mode || '-' }}</b><small>{{ subtask.prompt }}</small></div>
              <span>{{ monitorStatusLabelMap[subtask.status || ''] || subtask.status || '-' }}</span>
            </div>
            <div class="subtask-metrics">
              <span v-if="subtask.prompt_intent === 'ranking'">品牌排名：{{ formatRank(subtask.mention_position) }}</span>
              <span v-else>品牌露出：{{ formatExposureLabel(subtask.brand_mentioned) }}</span>
              <span v-if="subtask.prompt_intent === 'ranking' && subtask.raw_mention_position != null && subtask.raw_mention_position !== subtask.mention_position">
                模力原始排名：{{ formatRank(subtask.raw_mention_position) }}
              </span>
              <span>情感：{{ sentimentLabelMap[subtask.sentiment || ''] || '暂无' }}</span>
              <span>费用：{{ subtask.amount ?? '待返回' }}</span>
              <a v-if="subtask.page_screenshot" :href="subtask.page_screenshot" target="_blank">打开快照</a>
              <span v-else class="muted-metric">快照：未返回</span>
            </div>
            <p v-if="subtask.prompt_intent === 'ranking' && subtask.raw_mention_position != null && subtask.raw_mention_position !== subtask.mention_position" class="mention-context ranking-matrix-rank-note">
              回答正文中未出现本公司品牌/露出词，已忽略模力返回的原始排名 {{ formatRank(subtask.raw_mention_position) }}。
            </p>
            <p v-if="subtask.mention_context" class="mention-context">{{ subtask.mention_context }}</p>
            <pre v-if="subtask.answer_content" class="answer-preview">{{ subtask.answer_content }}</pre>
            <div v-if="subtask.reference_list.length" class="source-list">
              <b>信源列表</b>
              <a v-for="source in subtask.reference_list.slice(0, 6)" :key="`${subtask.subtask_id}-${source.index}-${source.url}`" :href="source.url" target="_blank">{{ source.title || source.site || source.url }}</a>
            </div>
            <p v-if="subtask.error_message" class="danger-copy">{{ subtask.error_message }}</p>
          </div>
          <div v-if="!filteredMonitorSubtasks.length" class="mini-empty">没有匹配当前筛选条件的检测结果。</div>
        </template>
        <div v-else class="mini-empty">选择左侧检测批次后，可先查看本次提交的问题列表，再浏览各平台检测结果。</div>
      </article>
    </section>

    <el-dialog v-model="matrixDetailVisible" width="860px" class="ranking-matrix-detail-dialog" align-center destroy-on-close>
      <template #header>
        <div class="ranking-matrix-dialog-head">
          <h3>单元格详情</h3>
          <p v-if="selectedMatrixCell">{{ selectedMatrixCell.scheduleLabel || selectedMatrixCell.snapshotAt }} · {{ selectedMatrixCell.prompt }}</p>
        </div>
      </template>

      <div v-if="loadingMatrixDetail" class="mini-empty">子任务详情加载中…</div>
      <template v-else-if="selectedMatrixSubtask && selectedMatrixCell">
        <div class="subtask-head">
          <div>
            <b>{{ platformLabelMap[selectedMatrixSubtask.platform || ''] || selectedMatrixSubtask.platform || '-' }} / {{ monitorModeLabelMap[selectedMatrixSubtask.mode || ''] || selectedMatrixSubtask.mode || '-' }}</b>
            <small>{{ selectedMatrixSubtask.prompt }}</small>
          </div>
          <span>{{ monitorStatusLabelMap[selectedMatrixSubtask.status || ''] || selectedMatrixSubtask.status || '-' }}</span>
        </div>
        <div class="subtask-metrics">
          <span v-if="(selectedMatrixSubtask.prompt_intent ?? selectedMatrixCell.cell.prompt_intent) === 'ranking'">
            品牌排名：{{ formatRank(selectedMatrixSubtask.mention_position ?? selectedMatrixCell.cell.mention_position) }}
          </span>
          <span v-else>
            品牌露出：{{ formatExposureLabel(selectedMatrixSubtask.brand_mentioned ?? selectedMatrixCell.cell.brand_mentioned) }}
          </span>
          <span v-if="(selectedMatrixSubtask.prompt_intent ?? selectedMatrixCell.cell.prompt_intent) === 'ranking' && (selectedMatrixSubtask.raw_mention_position ?? selectedMatrixCell.cell.raw_mention_position) != null && (selectedMatrixSubtask.raw_mention_position ?? selectedMatrixCell.cell.raw_mention_position) !== (selectedMatrixSubtask.mention_position ?? selectedMatrixCell.cell.mention_position)">
            原始提及排名：{{ formatRank(selectedMatrixSubtask.raw_mention_position ?? selectedMatrixCell.cell.raw_mention_position) }}
          </span>
          <span v-if="selectedMatrixCell.cell.monitor_keyword">监控词：{{ selectedMatrixCell.cell.monitor_keyword }}</span>
          <span>情感：{{ sentimentLabelMap[selectedMatrixSubtask.sentiment || ''] || '暂无' }}</span>
          <span>费用：{{ selectedMatrixSubtask.amount ?? '待返回' }}</span>
          <a v-if="selectedMatrixSubtask.page_screenshot" :href="selectedMatrixSubtask.page_screenshot" target="_blank">打开快照</a>
          <span v-else class="muted-metric">快照：未返回</span>
        </div>
        <p
          v-if="(selectedMatrixSubtask.prompt_intent ?? selectedMatrixCell.cell.prompt_intent) === 'ranking' && (selectedMatrixSubtask.raw_mention_position ?? selectedMatrixCell.cell.raw_mention_position) != null && (selectedMatrixSubtask.mention_position ?? selectedMatrixCell.cell.mention_position) == null"
          class="mention-context ranking-matrix-rank-note"
        >
          说明：本次检测监控词为「{{ selectedMatrixCell.cell.monitor_keyword || '未知' }}」。模力指数原始提及排名为 {{ formatRank(selectedMatrixSubtask.raw_mention_position ?? selectedMatrixCell.cell.raw_mention_position) }}，但该排名对应的是监控词本身（如行业词），并非本公司在推荐列表中的品牌排名，已忽略。
        </p>
        <p
          v-else-if="(selectedMatrixSubtask.prompt_intent ?? selectedMatrixCell.cell.prompt_intent) === 'ranking' && (selectedMatrixSubtask.raw_mention_position ?? selectedMatrixCell.cell.raw_mention_position) != null && (selectedMatrixSubtask.raw_mention_position ?? selectedMatrixCell.cell.raw_mention_position) !== (selectedMatrixSubtask.mention_position ?? selectedMatrixCell.cell.mention_position)"
          class="mention-context ranking-matrix-rank-note"
        >
          说明：模力指数原始提及排名为 {{ formatRank(selectedMatrixSubtask.raw_mention_position ?? selectedMatrixCell.cell.raw_mention_position) }}，与品牌实际排名 {{ formatRank(selectedMatrixSubtask.mention_position ?? selectedMatrixCell.cell.mention_position) }} 不一致，已按回答正文中的品牌露出重新计算。
        </p>
        <p v-if="selectedMatrixSubtask.mention_context" class="mention-context">{{ selectedMatrixSubtask.mention_context }}</p>
        <pre v-if="selectedMatrixSubtask.answer_content" class="answer-preview">{{ selectedMatrixSubtask.answer_content }}</pre>
        <div v-if="selectedMatrixSubtask.reference_list.length" class="source-list">
          <b>信源列表</b>
          <a v-for="source in selectedMatrixSubtask.reference_list.slice(0, 8)" :key="`${selectedMatrixSubtask.subtask_id}-${source.index}-${source.url}`" :href="source.url" target="_blank">{{ source.title || source.site || source.url }}</a>
        </div>
        <p v-if="selectedMatrixSubtask.error_message" class="danger-copy">{{ selectedMatrixSubtask.error_message }}</p>
      </template>
      <template v-else-if="selectedMatrixCell">
        <div class="subtask-metrics">
          <span>品牌排名：{{ formatRank(selectedMatrixCell.cell.mention_position) }}</span>
          <span v-if="selectedMatrixCell.cell.raw_mention_position != null && selectedMatrixCell.cell.raw_mention_position !== selectedMatrixCell.cell.mention_position">
            原始提及排名：{{ formatRank(selectedMatrixCell.cell.raw_mention_position) }}
          </span>
          <span v-if="selectedMatrixCell.cell.monitor_keyword">监控词：{{ selectedMatrixCell.cell.monitor_keyword }}</span>
          <span>情感：{{ sentimentLabelMap[selectedMatrixCell.cell.sentiment || ''] || '暂无' }}</span>
          <span>状态：{{ monitorStatusLabelMap[selectedMatrixCell.cell.status] || selectedMatrixCell.cell.status }}</span>
          <a v-if="selectedMatrixCell.cell.page_screenshot" :href="selectedMatrixCell.cell.page_screenshot" target="_blank">打开快照</a>
          <span v-else class="muted-metric">快照：未返回</span>
        </div>
        <p
          v-if="selectedMatrixCell.cell.raw_mention_position != null && selectedMatrixCell.cell.raw_mention_position !== selectedMatrixCell.cell.mention_position"
          class="mention-context ranking-matrix-rank-note"
        >
          品牌在 AI 回答中未实际出现，矩阵不展示原始排名 {{ formatRank(selectedMatrixCell.cell.raw_mention_position) }}。
        </p>
      </template>
    </el-dialog>
  </section>
</template>
