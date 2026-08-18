import { computed, onUnmounted, ref, watch, type Ref } from 'vue'
import type { ECharts } from 'echarts/core'
import { getBrandAsset, keywordGroupMonitorKeywords, type BrandAsset } from '../../../services/brand'
import {
  getRankingMatrix,
  type RankingMatrix,
  type WorkspaceBrief,
  type WorkspaceSnapshot,
} from '../../../services/monitor'
import { extractErrorDetail } from '../../../utils/requestError'
import { platformAccentColor, platformLabelMap, sortPlatformCodes } from '../portalMaps'
import {
  buildMatrixRankScope,
  matrixHeatChartHeight,
  resolveScopedColumnMentionStats,
  sliceMatrixByPlatform,
} from './rankingMatrixChartUtils'
import { loadEchartsRuntime } from '../../../utils/echartsLoader'

export type KeywordChip = { name: string; heat: number | null }

export type KeywordPlatformHeatmap = {
  platforms: string[]
  platformLabels: string[]
  keywords: string[]
  data: Array<[number, number, number]>
  source: 'matrix' | 'snapshots' | 'light'
}

export function formatBoardDateOnly(value?: string | null) {
  if (!value) return '—'
  const text = String(value).trim()
  if (/^\d{4}-\d{2}-\d{2}/.test(text)) return text.slice(0, 10)
  const parsed = new Date(text)
  if (Number.isNaN(parsed.getTime())) return text
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${parsed.getFullYear()}-${pad(parsed.getMonth() + 1)}-${pad(parsed.getDate())}`
}

export function formatBoardDateRange(start?: string | null, end?: string | null) {
  return `${formatBoardDateOnly(start)} ~ ${formatBoardDateOnly(end)}`
}

function collectMonitorKeywords(asset: BrandAsset | null): string[] {
  if (!asset) return []
  const fromGroups = (asset.keyword_groups || [])
    .filter(group => group.status !== false)
    .flatMap(group => keywordGroupMonitorKeywords(group))
  return [...new Set([
    ...(asset.monitor_keywords || []),
    ...fromGroups,
  ].map(item => item.trim()).filter(Boolean))]
}

function columnKeywordLabel(column: RankingMatrix['columns'][number]) {
  return (column.monitor_keyword || column.group_name || column.prompt || '').trim()
}

function snapshotKeyword(row: WorkspaceSnapshot) {
  return (row.keyword_group || row.prompt || '').trim() || '综合'
}

function buildHeatmapFromSnapshots(
  brief: WorkspaceBrief,
  keywordsHint: string[],
): KeywordPlatformHeatmap | null {
  const platforms = sortPlatformCodes(brief.purchased_platforms || [])
  if (!platforms.length) return null
  const snapshots = brief.recent_snapshots || []
  const keywords = [...new Set([
    ...keywordsHint,
    ...snapshots.map(snapshotKeyword),
  ].filter(Boolean))]
  if (!keywords.length) return null

  const bucket = new Map<string, { mentioned: number; total: number }>()
  for (const row of snapshots) {
    const key = `${snapshotKeyword(row)}||${row.platform}`
    const current = bucket.get(key) || { mentioned: 0, total: 0 }
    current.total += 1
    if (row.brand_mentioned || row.brand_rank != null) current.mentioned += 1
    bucket.set(key, current)
  }

  const data: Array<[number, number, number]> = []
  keywords.forEach((keyword, yIndex) => {
    platforms.forEach((platform, xIndex) => {
      const stats = bucket.get(`${keyword}||${platform}`)
      if (!stats?.total) {
        data.push([xIndex, yIndex, -1])
        return
      }
      data.push([xIndex, yIndex, Math.round((stats.mentioned / stats.total) * 1000) / 10])
    })
  })

  return {
    platforms,
    platformLabels: platforms.map(code => platformLabelMap[code] || code),
    keywords,
    data,
    source: 'snapshots',
  }
}

function buildKeywordPlatformHeatmap(
  matrix: RankingMatrix,
  startDate: string,
  endDate: string,
): KeywordPlatformHeatmap {
  const platforms = sortPlatformCodes(matrix.purchased_platforms || [])
  const keywords = [...new Set(matrix.columns.map(columnKeywordLabel).filter(Boolean))]
  const scope = buildMatrixRankScope(matrix.rows, startDate, endDate)
  const data: Array<[number, number, number]> = []

  keywords.forEach((keyword, yIndex) => {
    platforms.forEach((platform, xIndex) => {
      const slice = sliceMatrixByPlatform(matrix, platform)
      const column = matrix.columns.find(item => columnKeywordLabel(item) === keyword)
      if (!column || !slice.rows.length) {
        data.push([xIndex, yIndex, -1])
        return
      }
      const stats = resolveScopedColumnMentionStats(slice.rows, column, scope)
      data.push([xIndex, yIndex, stats.rate ?? -1])
    })
  })

  return {
    platforms,
    platformLabels: platforms.map(code => platformLabelMap[code] || code),
    keywords,
    data,
    source: 'matrix',
  }
}

function keywordHeatFromHeatmap(heatmap: KeywordPlatformHeatmap | null, keywords: string[]) {
  if (!heatmap || !keywords.length) {
    return keywords.map(name => ({ name, heat: null as number | null }))
  }
  const valid = heatmap.data.filter(item => item[2] >= 0).map(item => item[2])
  if (!valid.length) {
    return keywords.map(name => ({ name, heat: null as number | null }))
  }
  const maxHeat = Math.max(1, ...valid)
  return keywords.map(name => {
    const keywordIndex = heatmap.keywords.indexOf(name)
    if (keywordIndex < 0) return { name, heat: 0 }
    const values = heatmap.data
      .filter(item => item[1] === keywordIndex && item[2] >= 0)
      .map(item => item[2])
    const avg = values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : 0
    return { name, heat: Math.round((avg / maxHeat) * 100) }
  })
}

function lightHeatmapFromBrief(brief: WorkspaceBrief | null): KeywordPlatformHeatmap | null {
  const payload = brief?.keyword_platform_heatmap
  if (!payload?.keywords?.length || !payload.platforms?.length) return null
  return {
    platforms: payload.platforms,
    platformLabels: payload.platform_labels?.length
      ? payload.platform_labels
      : payload.platforms.map(code => platformLabelMap[code] || code),
    keywords: payload.keywords,
    data: (payload.data || []) as Array<[number, number, number]>,
    source: 'light',
  }
}

export function formatBoardScheduleLine(asset: BrandAsset | null, brief: WorkspaceBrief | null) {
  const plan = brief?.schedule_plan
  const scheduleType = plan?.schedule_type || asset?.schedule_type
  const times = plan?.schedule_times?.length ? plan.schedule_times : (asset?.schedule_times || [])
  const typeLabels: Record<string, string> = {
    daily_times: '每日',
    fixed_times: '固定时刻',
    weekly: '每周',
    monthly: '每月',
  }
  const prefix = typeLabels[scheduleType || ''] || '监测'
  if (times.length) return `${prefix} ${times.length} 次 · ${times.join(', ')}`
  if (asset?.schedule_frequency) return `${prefix} · 每天 ${asset.schedule_frequency} 次`
  return brief?.next_schedule_hint || '按监测计划执行'
}

export function healthStatusLabel(score: number | null | undefined) {
  if (score == null) return '待评估'
  if (score >= 75) return '良好'
  if (score >= 55) return '一般'
  return '需关注'
}

export function inferDeviceLabel(platformCode: string) {
  const label = platformLabelMap[platformCode] || platformCode
  if (/移动|mobile/i.test(label) || /_m$|mobile/i.test(platformCode)) return '移动端'
  return '桌面端'
}

// 2026-08-17 - 环图/柱用品牌 accent 过跳（Kimi 近黑+多蓝撞车）- 图表专用柔化色，不动 PLATFORM_META
// 2026-08-17 - 首版柔化太贴品牌色看不出差别 - 加大明度/色相分流（仍可辨平台）
const CHART_PLATFORM_COLORS: Record<string, string> = {
  kimi: '#64748b',
  yuanbao: '#34d399',
  doubao: '#fb923c',
  qianwen: '#a78bfa',
  deepseek: '#38bdf8',
  baiduai: '#818cf8',
  wenxinyiyan: '#60a5fa',
  antafu: '#22d3ee',
  quark: '#0ea5e9',
  weibo_zhisou: '#f59e0b',
  chatgpt: '#2dd4bf',
}

export function platformBarColor(platformCode: string) {
  const code = String(platformCode || '').trim()
  const base = code.replace(/_mobile$/i, '')
  return CHART_PLATFORM_COLORS[code]
    || CHART_PLATFORM_COLORS[base]
    || platformAccentColor(platformCode)
    || '#2563eb'
}

export function useWorkspaceBoardExtras(
  brief: Ref<WorkspaceBrief | null>,
  startDate: Ref<string>,
  endDate: Ref<string>,
  enabled: Ref<boolean>,
) {
  const brandAsset = ref<BrandAsset | null>(null)
  const rankingMatrix = ref<RankingMatrix | null>(null)
  const brandLoading = ref(false)
  const matrixLoading = ref(false)
  const matrixError = ref('')
  const matrixRequested = ref(false)
  let matrixAbort: AbortController | null = null
  let matrixSeq = 0
  let brandIdleHandle: number | null = null
  let brandTimer: ReturnType<typeof setTimeout> | null = null

  const monitorKeywords = computed(() => collectMonitorKeywords(brandAsset.value))

  const lightHeatmap = computed(() => lightHeatmapFromBrief(brief.value))

  const snapshotHeatmap = computed(() => (
    brief.value ? buildHeatmapFromSnapshots(brief.value, monitorKeywords.value) : null
  ))

  const keywordPlatformHeatmap = computed<KeywordPlatformHeatmap | null>(() => {
    // summary 轻量热力优先；矩阵太重且需滚到视口，仅作补充
    if (lightHeatmap.value?.keywords.length) return lightHeatmap.value
    if (rankingMatrix.value?.columns.length) {
      return buildKeywordPlatformHeatmap(rankingMatrix.value, startDate.value, endDate.value)
    }
    return snapshotHeatmap.value
  })

  const keywordChips = computed<KeywordChip[]>(() => {
    const heatByName = new Map(
      (brief.value?.keyword_heats || []).map(item => [item.name, item.heat]),
    )
    const keywords = monitorKeywords.value.length
      ? monitorKeywords.value
      : (brief.value?.keyword_heats?.map(item => item.name).filter(Boolean) || [])
    const fallbackKeywords = keywords.length
      ? keywords
      : (keywordPlatformHeatmap.value?.keywords || [])
    if (!fallbackKeywords.length) return []

    // 品牌词表优先（保证 6 词齐全）；热度来自 summary，缺的再按热力图算
    if (heatByName.size) {
      return fallbackKeywords.map(name => {
        if (heatByName.has(name)) {
          const heat = heatByName.get(name)
          return { name, heat: heat == null ? null : heat }
        }
        const fromHeat = keywordHeatFromHeatmap(keywordPlatformHeatmap.value, [name])[0]
        return { name, heat: fromHeat?.heat ?? null }
      })
    }
    return keywordHeatFromHeatmap(keywordPlatformHeatmap.value, fallbackKeywords)
  })

  function cancelDeferredBrandLoad() {
    if (brandIdleHandle != null && typeof cancelIdleCallback === 'function') {
      cancelIdleCallback(brandIdleHandle)
      brandIdleHandle = null
    }
    if (brandTimer != null) {
      clearTimeout(brandTimer)
      brandTimer = null
    }
  }

  async function loadBrandAsset() {
    const tenantId = brief.value?.tenant_id
    if (!tenantId) return
    brandLoading.value = true
    try {
      // no withRetry: brand is non-critical for first paint
      const response = await getBrandAsset(tenantId)
      brandAsset.value = response.asset
    } catch (error: unknown) {
      matrixError.value = extractErrorDetail(error)
    } finally {
      brandLoading.value = false
    }
  }

  /** Schedule brand asset after paint — first screen only needs workspace-brief. */
  function scheduleBrandAssetLoad() {
    cancelDeferredBrandLoad()
    const run = () => {
      brandIdleHandle = null
      brandTimer = null
      void loadBrandAsset()
    }
    if (typeof requestIdleCallback === 'function') {
      brandIdleHandle = requestIdleCallback(run, { timeout: 1200 })
      return
    }
    brandTimer = setTimeout(run, 200)
  }

  async function loadRankingMatrix() {
    const tenantId = brief.value?.tenant_id
    if (!tenantId || !enabled.value) return
    matrixRequested.value = true
    matrixAbort?.abort()
    matrixAbort = new AbortController()
    const seq = ++matrixSeq
    matrixLoading.value = true
    matrixError.value = ''
    try {
      // No withRetry: timeout retries made trend filters feel stuck for ~90s
      const data = await getRankingMatrix(
        {
          start_date: startDate.value || undefined,
          end_date: endDate.value || undefined,
          tenant_id: tenantId,
        },
        {
          timeout: 60000,
          silentError: true,
          signal: matrixAbort.signal,
        },
      )
      if (seq !== matrixSeq) return
      rankingMatrix.value = data
    } catch (error: unknown) {
      if (seq !== matrixSeq) return
      const canceled = (error as { code?: string; name?: string })?.code === 'ERR_CANCELED'
        || (error as { name?: string })?.name === 'CanceledError'
      if (canceled) return
      matrixError.value = extractErrorDetail(error) || '词×平台矩阵加载超时，已改用快照近似'
      rankingMatrix.value = null
    } finally {
      if (seq === matrixSeq) matrixLoading.value = false
    }
  }

  /** Call when heatmap enters viewport — light summary 已够用则跳过重矩阵。 */
  function requestMatrixLoad() {
    if (!enabled.value || !brief.value?.tenant_id) return
    if (brief.value?.keyword_platform_heatmap?.keywords?.length) return
    if (matrixLoading.value) return
    if (rankingMatrix.value) return
    void loadRankingMatrix()
  }

  async function reloadExtras() {
    matrixError.value = ''
    cancelDeferredBrandLoad()
    await loadBrandAsset()
    if (matrixRequested.value) await loadRankingMatrix()
  }

  watch(
    [() => brief.value?.tenant_id, enabled],
    ([tenantId, active]) => {
      if (!active || tenantId == null) return
      // 品牌资产与监测区间无关；切周期不要重复打品牌接口
      if (brandAsset.value) return
      scheduleBrandAssetLoad()
    },
    { immediate: true },
  )

  let matrixDateTimer: ReturnType<typeof setTimeout> | null = null
  watch(
    [startDate, endDate],
    () => {
      if (!enabled.value || !brief.value?.tenant_id) return
      // 切周期不立刻拉矩阵（60s 级接口）；滚到热力图再按需加载
      if (matrixDateTimer != null) clearTimeout(matrixDateTimer)
      matrixDateTimer = null
      matrixAbort?.abort()
      matrixLoading.value = false
      rankingMatrix.value = null
      matrixRequested.value = false
      matrixError.value = ''
    },
  )

  onUnmounted(() => {
    cancelDeferredBrandLoad()
    if (matrixDateTimer != null) clearTimeout(matrixDateTimer)
    matrixAbort?.abort()
  })

  return {
    brandAsset,
    rankingMatrix,
    brandLoading,
    matrixLoading,
    matrixError,
    matrixRequested,
    monitorKeywords,
    keywordChips,
    keywordPlatformHeatmap,
    requestMatrixLoad,
    reloadExtras,
  }
}

export function useKeywordPlatformHeatmapChart(
  container: Ref<HTMLDivElement | null>,
  heatmap: Ref<KeywordPlatformHeatmap | null>,
) {
  let chart: ECharts | null = null

  async function renderHeatmap() {
    const el = container.value
    const payload = heatmap.value
    if (!el || !payload?.keywords.length || !payload.platformLabels.length) {
      chart?.clear()
      return
    }
    const runtime = await loadEchartsRuntime('matrix')
    // 与排名矩阵热力同口径：按词数撑高，外层 wrap 滚动，避免固定 360 只露出约 12 行
    const chartHeight = matrixHeatChartHeight(payload.keywords.length)
    el.style.height = `${chartHeight}px`
    chart = runtime.getInstanceByDom(el) || runtime.init(el)
    chart.setOption({
      animation: false,
      grid: { left: 140, right: 72, top: 20, bottom: 72, containLabel: false },
      tooltip: {
        // heat-wrap 有 overflow:auto；position:top 在首行会被裁成一条白边
        appendTo: 'body',
        extraCssText: 'z-index:40;max-width:280px;white-space:normal;',
        formatter: (params: { data: [number, number, number] }) => {
          const [xIndex, yIndex] = params.data
          const platform = payload.platformLabels[xIndex] || '—'
          const keyword = payload.keywords[yIndex] || '—'
          const raw = payload.data.find(item => item[0] === xIndex && item[1] === yIndex)
          const text = raw == null || raw[2] < 0 ? '暂无样本' : `${raw[2]}`
          return `${keyword} × ${platform}<br/>得分: ${text}`
        },
      },
      xAxis: {
        type: 'category',
        data: payload.platformLabels,
        splitArea: { show: true },
        axisLabel: {
          color: '#64748b',
          fontSize: 12,
          interval: 0,
          rotate: payload.platformLabels.length > 6 ? 30 : 0,
        },
        axisTick: { show: false },
      },
      yAxis: {
        type: 'category',
        data: payload.keywords,
        splitArea: { show: true },
        axisLabel: { color: '#64748b', fontSize: 12, interval: 0 },
        axisTick: { show: false },
      },
      // 2026-08-17 - 工作台热力试色：O 白→品牌蓝；低端勿用纯白（与卡片底糊成「狗啃」）
      visualMap: {
        min: 0,
        max: 100,
        calculable: true,
        orient: 'vertical',
        right: 8,
        top: 'center',
        itemWidth: 12,
        itemHeight: Math.min(140, Math.max(80, Math.floor(chartHeight * 0.35))),
        text: ['高', '低'],
        textStyle: { color: '#64748b', fontSize: 11 },
        inRange: { color: ['#e2e8f0', '#bfdbfe', '#60a5fa', '#2563eb', '#1e3a8a'] },
      },
      series: [{
        type: 'heatmap',
        data: payload.data.map(item => (
          item[2] < 0 ? [item[0], item[1], 0] : item
        )),
        label: {
          show: payload.keywords.length <= 80,
          formatter: (params: { data: [number, number, number] }) => {
            const raw = payload.data.find(item => item[0] === params.data[0] && item[1] === params.data[1])
            if (!raw || raw[2] < 0) return '—'
            return `${raw[2]}`
          },
          fontSize: 12,
          fontWeight: 700,
          color: (params: { data: [number, number, number] }) => {
            const raw = payload.data.find(item => item[0] === params.data[0] && item[1] === params.data[1])
            const value = raw?.[2]
            if (value == null || value < 0) return '#94a3b8'
            if (value >= 50) return '#fff'
            return '#1e3a8a'
          },
        },
        // 2026-08-17 - 热力悬停 emphasis 会丢掉格子数字/字色 - 禁用 emphasis，靠 tooltip
        emphasis: { disabled: true },
      }],
    }, true)
    chart.resize()
  }

  function disposeHeatmap() {
    chart?.dispose()
    chart = null
  }

  watch(heatmap, () => { void renderHeatmap() }, { deep: true, flush: 'post' })

  return { renderHeatmap, disposeHeatmap }
}
