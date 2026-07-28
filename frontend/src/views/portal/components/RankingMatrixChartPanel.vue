<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import type { ECharts } from 'echarts/core'
import type {
  RankingMatrix,
  RankingMatrixCell,
  RankingMatrixRow,
} from '../../../services/monitor'
import { initChart, loadEchartsRuntime, type EchartsRuntime } from '../../../utils/echartsLoader'
import { platformAccentColor } from '../platformMeta'
import {
  buildKeywordDetailRows,
  buildMatrixBarOption,
  buildMatrixHeatOption,
  buildMatrixRankScope,
  matrixChartHeight,
  matrixPlatformKpi,
  resolveMatrixBarLayoutHint,
  resolveColumnCell,
  resolveColumnRow,
  sliceMatrixByPlatform,
  type MatrixChartType,
  type MatrixHeatDataItem,
  type MatrixLayoutMode,
  type MatrixRankScope,
} from '../composables/rankingMatrixChartUtils'

const props = defineProps<{
  matrix: RankingMatrix | null
  chartType: MatrixChartType
  activePlatform: string
  layoutMode: MatrixLayoutMode
  purchasedPlatforms: string[]
  platformLabelMap: Record<string, string>
  formatRank: (rank: number | null | undefined) => string
  displayScheduleLabel: (label: string | null | undefined, fallback?: string) => string
  filterStartDate: string
  filterEndDate: string
}>()

const emit = defineEmits<{
  'update:activePlatform': [platform: string]
  openCell: [payload: {
    row: RankingMatrixRow
    prompt: string
    cell: RankingMatrixCell | undefined
  }]
}>()

const chartRef = ref<HTMLDivElement | null>(null)
const stageBodyRef = ref<HTMLDivElement | null>(null)
let chartInstance: ECharts | null = null
let runtime: EchartsRuntime | null = null
let renderVersion = 0

function platformHasRows(code: string) {
  if (!props.matrix?.all_platforms) return (props.matrix?.rows.length || 0) > 0
  return props.matrix.rows.some(row => row.platform === code)
}

const availablePlatforms = computed(() => {
  const purchased = props.purchasedPlatforms.length
    ? props.purchasedPlatforms
    : (props.matrix?.purchased_platforms || [])
  if (!props.matrix?.all_platforms) {
    const code = props.matrix?.platform || purchased[0] || ''
    return code ? [code] : purchased.slice(0, 1)
  }
  const withData = purchased.filter(code => platformHasRows(code))
  return withData.length ? withData : purchased
})

const rankScope = computed<MatrixRankScope>(() => (
  buildMatrixRankScope(
    props.matrix?.rows || [],
    props.filterStartDate,
    props.filterEndDate,
  )
))

const platformRailItems = computed(() => {
  const purchased = props.purchasedPlatforms.length
    ? props.purchasedPlatforms
    : (props.matrix?.purchased_platforms || [])
  const scope = rankScope.value
  return purchased.map(code => {
    const slice = props.matrix ? sliceMatrixByPlatform(props.matrix, code) : null
    return {
      code,
      name: props.platformLabelMap[code] || code,
      color: platformAccentColor(code),
      columnCount: slice?.columns.length ?? 0,
      kpi: slice ? matrixPlatformKpi(slice, scope) : { top3: 0, avg: '—', none: 0 },
      hasRows: platformHasRows(code),
    }
  })
})

const PLATFORM_RAIL_LIMIT = 5

const platformRailScrollable = computed(() => platformRailItems.value.length > PLATFORM_RAIL_LIMIT)

const effectivePlatform = computed(() => {
  const current = props.activePlatform.trim()
  if (current) return current
  if (!props.matrix) return ''
  const purchased = props.purchasedPlatforms.length
    ? props.purchasedPlatforms
    : (props.matrix.purchased_platforms || [])
  if (props.matrix.all_platforms) {
    const withRows = purchased.filter(code => platformHasRows(code))
    return withRows[0] || purchased[0] || ''
  }
  return props.matrix.platform || purchased[0] || ''
})

const activeSlice = computed(() => {
  if (!props.matrix || !effectivePlatform.value) return null
  return sliceMatrixByPlatform(props.matrix, effectivePlatform.value)
})

const keywordRows = computed(() => {
  if (!activeSlice.value) return []
  return buildKeywordDetailRows(activeSlice.value, props.formatRank, rankScope.value)
})

const scopeScheduleLabel = computed(() => {
  const scope = rankScope.value
  if (scope.mode === 'period') {
    return `${scope.label} 区间均值 · ${scope.dayCount} 天`
  }
  return props.displayScheduleLabel(scope.dayKey || scope.label, '—')
})

const cardHint = computed(() => {
  if (!activeSlice.value) return ''
  if (props.chartType === 'bar') {
    const scope = rankScope.value
    const prefix = scope.mode === 'day'
      ? scopeScheduleLabel.value
      : `${scope.label} 区间均值`
    return `${prefix} · ${activeSlice.value.columns.length} 个监测词`
  }
  return `${activeSlice.value.rows.length} 天 × ${activeSlice.value.columns.length} 词`
})

const cardHintExtra = computed(() => {
  if (props.layoutMode === 'single') return ' · 单平台视图 · 右侧为词组明细'
  if (props.layoutMode === 'dual') return ' · 双平台视图 · 点击上方切换'
  return ' · 右侧可切换其他已购平台'
})

const platformName = computed(() => (
  props.platformLabelMap[effectivePlatform.value] || effectivePlatform.value || '—'
))

const platformColor = computed(() => platformAccentColor(effectivePlatform.value))

const chartHeight = computed(() => {
  if (!activeSlice.value || props.chartType === 'table') return 420
  return matrixChartHeight(props.chartType, activeSlice.value)
})

const cardKpi = computed(() => matrixPlatformKpi(activeSlice.value || {
  columns: [],
  rows: [],
  platform: '',
}, rankScope.value))

function selectPlatform(code: string) {
  if (!platformHasRows(code)) return
  emit('update:activePlatform', code)
}

function openKeywordRow(row: ReturnType<typeof buildKeywordDetailRows>[number]) {
  if (!row.row) return
  emit('openCell', {
    row: row.row,
    prompt: row.prompt,
    cell: row.cell,
  })
}

function waitForLayout() {
  return new Promise<void>(resolve => {
    requestAnimationFrame(() => requestAnimationFrame(() => resolve()))
  })
}

function measureBarLayoutHint(columnCount: number) {
  if (props.layoutMode === 'dual' || props.chartType !== 'bar') return undefined
  const stage = stageBodyRef.value
  if (!stage) return undefined

  const rail = stage.querySelector('.matrix-platform-rail, .matrix-keyword-rail') as HTMLElement | null
  const card = stage.querySelector('.matrix-chart-card') as HTMLElement | null
  if (!rail || !card) return undefined

  const head = card.querySelector('.matrix-chart-card-head') as HTMLElement | null
  return resolveMatrixBarLayoutHint(columnCount, rail.offsetHeight, head?.offsetHeight ?? 0)
}

async function renderChart() {
  const version = ++renderVersion
  if (props.chartType === 'table' || !activeSlice.value?.columns.length || !activeSlice.value.rows.length) {
    chartInstance?.clear()
    return
  }
  await nextTick()
  await waitForLayout()
  if (!chartRef.value) return

  const slice = activeSlice.value
  if (!runtime) runtime = await loadEchartsRuntime('matrix')
  if (version !== renderVersion) return

  const layoutHint = measureBarLayoutHint(slice.columns.length)
  const built = props.chartType === 'bar'
    ? buildMatrixBarOption(slice, runtime, scopeScheduleLabel.value, rankScope.value, layoutHint)
    : null
  const renderHeight = built?.height ?? chartHeight.value
  chartRef.value.style.height = `${renderHeight}px`

  if (!chartInstance) {
    chartInstance = await initChart(chartRef.value, 'matrix')
  }
  if (version !== renderVersion) return

  const option = built?.option ?? buildMatrixHeatOption(slice, {
    startDate: props.filterStartDate,
    endDate: props.filterEndDate,
  })
  chartInstance.setOption(option, { notMerge: true })
  chartInstance.resize({ width: chartRef.value.clientWidth, height: renderHeight })

  chartInstance.off('click')
  chartInstance.on('click', (params: unknown) => {
    const event = params as {
      componentType?: string
      seriesType?: string
      dataIndex?: number
      data?: { prompt?: string } | [number, number, number]
    }
    if (!slice) return
    if (props.chartType === 'bar' && event.seriesType === 'bar') {
      const seriesData = (option.series as Array<{ data: Array<{ prompt?: string; row?: RankingMatrixRow | null }> }>)[0]?.data || []
      const point = seriesData[event.dataIndex ?? -1]
      const prompt = point?.prompt
      const row = point?.row
      if (!prompt || !row) return
      emit('openCell', {
        row,
        prompt,
        cell: row.cells[prompt] ?? resolveColumnCell(row, slice.columns[event.dataIndex ?? -1] || { prompt, group_name: null }),
      })
      return
    }
    if (props.chartType === 'heat' && event.seriesType === 'heatmap') {
      // 2026-07-28 - 点空日误开别日 / 修完后又点不开 - 用系列 data 上的 dayKey，有 cell 才开抽屉
      const seriesData = (option.series as Array<{ data: MatrixHeatDataItem[] }>)[0]?.data || []
      const point = seriesData[event.dataIndex ?? -1]
        || (event.data as MatrixHeatDataItem | undefined)
      if (!point?.dayKey || !point.prompt) return
      const yIndex = point.value?.[1] ?? -1
      const column = slice.columns[yIndex]
        || slice.columns.find(item => item.prompt === point.prompt)
      if (!column) return
      const row = resolveColumnRow(slice.rows, column, point.dayKey)
      const cell = resolveColumnCell(row, column)
      if (!row || !cell) return
      emit('openCell', {
        row,
        prompt: column.prompt,
        cell,
      })
    }
  })
}

function resizeChart() {
  if (!chartInstance || !chartRef.value) return
  chartInstance.resize({ width: chartRef.value.clientWidth, height: chartRef.value.clientHeight })
}

function disposeChart() {
  chartInstance?.dispose()
  chartInstance = null
}

watch(
  () => [
    props.chartType,
    effectivePlatform.value,
    props.matrix,
    props.layoutMode,
    chartHeight.value,
    props.filterStartDate,
    props.filterEndDate,
  ] as const,
  () => { void renderChart() },
  { deep: true, flush: 'post', immediate: true },
)

watch(effectivePlatform, (code) => {
  if (code && code !== props.activePlatform) {
    emit('update:activePlatform', code)
  }
}, { immediate: true })

function onWindowResize() {
  resizeChart()
}

onMounted(() => {
  window.addEventListener('resize', onWindowResize)
})

onUnmounted(() => {
  window.removeEventListener('resize', onWindowResize)
  disposeChart()
})

defineExpose({ resizeChart })
</script>

<template>
  <div v-if="!matrix?.columns.length || !matrix.rows.length" class="matrix-chart-empty">
    当前筛选条件下暂无数据，请调整日期或关键词筛选。
  </div>
  <template v-else>
    <div
      class="matrix-chart-stage"
      :class="{
        'layout-single': layoutMode === 'single',
        'layout-dual': layoutMode === 'dual',
        'layout-multi': layoutMode === 'multi',
      }"
    >
      <article
        v-if="layoutMode === 'dual'"
        class="matrix-platform-tabs"
      >
        <button
          v-for="code in availablePlatforms"
          :key="`tab-${code}`"
          type="button"
          :class="{ active: code === effectivePlatform }"
          :style="{ '--chip-color': platformAccentColor(code) }"
          :disabled="!platformHasRows(code)"
          @click="selectPlatform(code)"
        >
          <i />
          {{ platformLabelMap[code] || code }}
        </button>
      </article>

      <div
        ref="stageBodyRef"
        class="matrix-chart-stage-body"
        :class="{ 'with-rail': layoutMode !== 'dual' }"
      >
        <article class="matrix-chart-card chart-main" :style="{ '--platform-color': platformColor }">
          <div class="matrix-chart-card-head">
            <div>
              <h2>
                <span class="matrix-platform-badge">{{ platformName.slice(0, 1) }}</span>
                {{ platformName }}
              </h2>
              <p>{{ cardHint }}{{ cardHintExtra }}</p>
            </div>
            <div class="matrix-chart-kpis">
              <div class="matrix-chart-kpi"><span>进前三次数</span><b>{{ cardKpi.top3 }}</b></div>
              <div class="matrix-chart-kpi"><span>均位</span><b>{{ cardKpi.avg }}</b></div>
              <div class="matrix-chart-kpi"><span>未提及</span><b>{{ cardKpi.none }}</b></div>
            </div>
          </div>
          <div class="matrix-chart-wrap">
            <div ref="chartRef" class="matrix-chart-canvas" />
            <p class="matrix-chart-legend">
              <span class="legend-top3">1~3 靠前</span>
              <span class="legend-mid">4+ 待提升</span>
              <span class="legend-none">— 未提及</span>
              <span v-if="chartType === 'bar'" class="legend-axis">条形终点对应排名；右端 1 表示 AI 首推</span>
              <span v-else class="legend-axis">词多时在图内向下滚动即可看全</span>
            </p>
          </div>
        </article>

        <aside
          v-if="layoutMode === 'single'"
          class="matrix-keyword-rail"
        >
          <div class="matrix-keyword-rail-head">
            词组排名明细
            <small>
              {{ rankScope.mode === 'day' ? `${scopeScheduleLabel} · 较昨日变化` : `${scopeScheduleLabel}` }}
            </small>
          </div>
          <div class="matrix-keyword-table-wrap">
            <table class="matrix-keyword-table">
              <thead>
                <tr>
                  <th>监测词</th>
                  <th>{{ rankScope.mode === 'day' ? '当日' : '区间均位' }}</th>
                  <th>{{ rankScope.mode === 'day' ? '较昨日' : '变化' }}</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="row in keywordRows"
                  :key="row.prompt"
                  class="is-clickable"
                  @click="openKeywordRow(row)"
                >
                  <td>{{ row.label }}</td>
                  <td class="rank">
                    <span class="matrix-rank-pill" :class="row.pillCls">{{ row.rankText }}</span>
                  </td>
                  <td class="delta" :class="row.deltaCls">{{ row.deltaText }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </aside>

        <aside
          v-else-if="layoutMode === 'multi'"
          class="matrix-platform-rail"
        >
          <div class="matrix-platform-rail-head">
            全平台对比
            <small>点击切换主图 · 仅展示已购平台</small>
          </div>
          <div
            class="matrix-platform-rail-body"
            :class="{ 'is-scrollable': platformRailScrollable }"
          >
            <button
              v-for="item in platformRailItems"
              :key="`rail-${item.code}`"
              type="button"
              class="matrix-rail-card"
              :class="{
                active: item.code === effectivePlatform,
                disabled: !item.hasRows,
              }"
              :style="{ '--platform-color': item.color }"
              :disabled="!item.hasRows"
              @click="selectPlatform(item.code)"
            >
              <div class="matrix-rail-card-top">
                <b><i class="matrix-rail-dot" />{{ item.name }}</b>
                <span>{{ item.columnCount }} 词</span>
              </div>
              <div class="matrix-rail-kpis">
                <div class="matrix-rail-kpi">
                  <label>进前三次数</label>
                  <strong>{{ item.kpi.top3 }}</strong>
                </div>
                <div class="matrix-rail-kpi">
                  <label>均位</label>
                  <strong>{{ item.kpi.avg }}</strong>
                </div>
                <div class="matrix-rail-kpi">
                  <label>未提及</label>
                  <strong>{{ item.kpi.none }}</strong>
                </div>
              </div>
              <div v-if="!item.hasRows" class="matrix-rail-empty">暂无数据</div>
            </button>
          </div>
        </aside>
      </div>
    </div>
  </template>
</template>
