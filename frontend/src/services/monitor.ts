import { http, type GeoHttpRequestConfig } from './http'

export interface MonitorPlatformConfig {
  platform: string
  mode: 'standard' | 'reasoning' | 'search' | 'reasoning_search'
  screenshot: 0 | 1 | 2
}

export interface MonitorTaskCreatePayload {
  tenant_id?: number | null
  monitor_keywords?: string | null
  monitor_keyword_aliases?: string[]
  competitors?: Array<{ name: string; aliases: string[] }>
  prompts: string[]
  platforms: MonitorPlatformConfig[]
  region_code?: string[] | null
}

export interface MonitorTask {
  task_id: string
  tenant_id: number | null
  monitor_keywords: string | null
  status: string
  total_items: number
  completed_items: number
  failed_items: number
  prompts: string[]
  platforms: MonitorPlatformConfig[]
  callback_url: string | null
  poll_url: string | null
  last_error: string | null
  created_at: string
  updated_at: string
  schedule_key?: string | null
  schedule_window_key?: string | null
  schedule_label?: string | null
  schedule_run_status?: string | null
  schedule_source?: 'run' | 'inferred' | 'created_at' | null
  keyword_group?: string | null
  prompt_preview?: string | null
}

export interface MonitorSchedulePlan {
  schedule_type: string | null
  schedule_type_label: string | null
  schedule_times: string[]
  schedule_frequency: number
  schedule_weekdays: number[]
  schedule_month_days: number[]
}

export interface MonitorSubtask {
  subtask_id: string
  task_id?: string
  platform: string
  mode: string
  prompt: string
  status: string
  page_screenshot: string | null
  /** 补录后后台截图尚未完成 */
  screenshot_pending?: boolean
  /** 后台截图是否成功；未结束时为 null/undefined */
  screenshot_ok?: boolean | null
  answer_content: string | null
  reference_list: Array<{ title?: string; url?: string; site?: string; index?: number }>
  reference_count?: number
  citation_list: Array<{ title?: string; url?: string; site?: string; index?: number }>
  recommended_questions: string[]
  error_message: string | null
  mention_position: number | null
  mention_context: string | null
  raw_mention_position?: number | null
  brand_rank?: number | null
  brand_mentioned?: boolean
  prompt_intent?: 'ranking' | 'exposure'
  rank_source?: string | null
  rank_confidence?: number | null
  rank_category?: string | null
  rank_basis?: string | null
  sentiment: string | null
  competitor_rankings: Array<Record<string, unknown>>
  all_rankings: Array<Record<string, unknown>>
  amount: number | null
  updated_at?: string | null
  tenant_name?: string | null
  tenant_id?: number | null
  source?: 'tenant_monitor' | 'lead_diagnosis' | string
  monitor_keywords?: string | null
  keyword_group?: string | null
  schedule_label?: string | null
  schedule_key?: string | null
  schedule_window_key?: string | null
  schedule_source?: string | null
  region_code?: string | null
  region_label?: string | null
  brand_name?: string | null
  task_created_at?: string | null
  needs_backfill?: boolean
  needs_backfill_raw?: boolean
  backfill_dismissed?: boolean
  has_answer?: boolean
}

export interface MonitorTaskDetail {
  task: MonitorTask
  subtasks: MonitorSubtask[]
}

export interface MonitorSummary {
  scope: 'PLATFORM' | 'CUSTOMER'
  tenant_id: number | null
  tenant_count: number
  task_count: number
  subtask_count: number
  completed_count: number
  failed_count: number
  total_cost: number
  mention_rate: number
  avg_rank: number
  platform_count: number
  sentiment_counts: Record<string, number>
  platform_stats: Array<{
    platform: string
    total: number
    completed: number
    mention_rate: number
    avg_rank: number | null
  }>
  source_stats: Array<{
    title: string
    url: string
    site?: string | null
    count: number
    platforms?: string[]
    exposure_terms?: string[]
    questions?: string[]
    latest_time?: string | null
    has_exposure?: boolean
  }>
  source_stats_all?: Array<{
    title: string
    url: string
    site?: string | null
    count: number
    platforms?: string[]
    exposure_terms?: string[]
    questions?: string[]
    latest_time?: string | null
    has_exposure?: boolean
  }>
  source_citation_trend?: {
    start_at: string
    end_at: string
    points: Array<{ label: string; day_key: string; value: number }>
  }
  source_citation_trend_by_platform?: Record<string, {
    start_at: string
    end_at: string
    points: Array<{ label: string; day_key: string; value: number }>
  }>
  daily_trend: Array<{ label: string; value: number }>
  daily_labels: string[]
  recent_tasks: Array<MonitorTask & { tenant_name?: string | null }>
  recent_subtasks: Array<MonitorSubtask & { tenant_name?: string | null }>
}

export interface ScheduledMonitorGroupPreview {
  monitor_keyword: string | null
  exposure_terms: string[]
  prompt_limit: number
  prompt_count: number
  prompts: string[]
  subtask_count: number
}

export interface ScheduledMonitorPreview {
  tenant_id: number
  tenant_name: string
  brand_name: string
  schedule_type: string
  schedule_times: string[]
  platforms: MonitorPlatformConfig[]
  max_prompts_total?: number
  max_prompts_per_group?: number
  keyword_group_count?: number
  tasks_per_schedule_window?: number
  platform_count?: number
  prompt_count: number
  subtask_count_per_window?: number
  prompts: string[]
  keyword_groups?: ScheduledMonitorGroupPreview[]
  competitor_count: number
}

export interface RankingMatrixColumn {
  prompt: string
  group_name: string | null
  monitor_keyword?: string | null
  group_id?: number | null
  /** 词组配置的监测平台；切平台 Tab 时据此隐藏未配置词 */
  platforms?: string[]
}

export interface RankingMatrixCellSnapshot {
  subtask_id: string
  task_id?: string | null
  mention_position: number | null
  raw_mention_position?: number | null
  brand_mentioned?: boolean
  monitor_keyword?: string | null
  prompt_intent?: 'ranking' | 'exposure'
  rank_source?: string | null
  rank_confidence?: number | null
  rank_category?: string | null
  rank_basis?: string | null
  schedule_window_key?: string | null
  schedule_label?: string | null
  schedule_source?: 'run' | 'inferred' | 'created_at' | 'lead_diagnosis' | null
  updated_at: string | null
  status: string
  page_screenshot: string | null
  sentiment: string | null
}

export interface RankingMatrixCell {
  subtask_id: string
  mention_position: number | null
  raw_mention_position?: number | null
  brand_mentioned?: boolean
  monitor_keyword?: string | null
  prompt_intent?: 'ranking' | 'exposure'
  rank_source?: string | null
  rank_confidence?: number | null
  rank_category?: string | null
  rank_basis?: string | null
  status: string
  page_screenshot: string | null
  sentiment: string | null
  updated_at: string | null
  sample_count?: number
  rank_sample_count?: number
  snapshots?: RankingMatrixCellSnapshot[]
}

export interface RankingMatrixRow {
  task_id: string
  platform?: string | null
  day_key?: string | null
  schedule_key?: string | null
  schedule_window_key?: string | null
  schedule_label?: string | null
  schedule_source?: 'run' | 'inferred' | 'created_at' | 'daily_avg' | null
  keyword_group?: string | null
  snapshot_at: string | null
  sample_count?: number
  cells: Record<string, RankingMatrixCell>
}

export interface RankingMatrixKeywordGroupOption {
  monitor_keyword: string
  name?: string
  monitor_keywords?: string[]
  exposure_terms: string[]
}

export interface RankingMatrix {
  platform: string | null
  all_platforms?: boolean
  brand_name: string | null
  start_at: string
  end_at: string
  columns: RankingMatrixColumn[]
  rows: RankingMatrixRow[]
  schedule_round_count?: number
  task_count?: number
  schedule_plan?: MonitorSchedulePlan
  prompt_groups: Array<{ name: string; prompts: string[] }>
  keyword_group_options?: RankingMatrixKeywordGroupOption[]
  exposure_term_options?: string[]
  purchased_platforms: string[]
}

export interface MonitorTaskScheduleGroup {
  schedule_window_key: string
  schedule_label: string
  tasks: MonitorTask[]
}

export interface RankingMatrixQuery {
  platform?: string
  start_date?: string
  end_date?: string
  keyword?: string
  monitor_group?: string
  keyword_group?: string
  monitor_keyword?: string
  exposure_term?: string
  limit_rows?: number
  tenant_id?: number
}

export interface WorkspaceBriefSchedule {
  schedule_window_key: string
  schedule_label: string | null
  completed_subtasks: number
  total_subtasks: number
}

export interface WorkspaceBriefKpis {
  ranking_sample_count: number
  mentioned_count?: number
  brand_mention_rate: number
  avg_brand_rank: number | null
  top3_rate: number
  exposure_sample_count: number
  negative_count: number
  negative_rate: number
  source_count: number
  keyword_group_count: number
  competitor_count: number
}

export interface WorkspaceRoundComparison {
  has_previous: boolean
  latest_schedule_label: string | null
  previous_schedule_label: string | null
  avg_brand_rank_delta: number | null
  mention_rate_delta: number | null
  top3_rate_delta: number | null
  negative_count_delta: number | null
}

export interface WorkspacePlatformHighlight {
  platform: string
  mention_rate: number
  avg_rank: number | null
  sample_count: number
  mention_rate_delta?: number | null
  avg_rank_delta?: number | null
}

export interface WorkspaceKpiTrendPoint {
  label: string
  mention_rate: number
  avg_brand_rank: number | null
  top3_rate: number
  negative_count: number
  /** 当日样本数；缺省按旧接口兼容，前端用提及率字段兜底 */
  sample_count?: number
}

export interface WorkspaceSnapshot {
  subtask_id: string
  task_id: string | null
  platform: string
  prompt: string
  keyword_group: string | null
  /** 监控主词（展示用，优先于分组名如「综合」） */
  monitor_keyword?: string | null
  /** 引用文章（收录明细点开跳原文，不是快照） */
  source_articles?: Array<{ title: string; url: string; domain?: string }>
  schedule_label: string | null
  schedule_window_key: string | null
  prompt_intent: 'ranking' | 'exposure'
  brand_rank: number | null
  brand_mentioned: boolean
  sentiment: string
  answer_excerpt: string
  page_screenshot?: string | null
  updated_at: string | null
}

export interface WorkspaceTopSource {
  title: string
  url: string
  count: number
  platforms: string[]
}

export interface WorkspaceAlert {
  level: 'warn' | 'info'
  message: string
}

export interface WorkspaceKeywordHeat {
  name: string
  heat: number | null
}

export interface WorkspaceKeywordPlatformHeatmap {
  platforms: string[]
  platform_labels: string[]
  keywords: string[]
  data: Array<[number, number, number]>
  source?: string
}

export interface WorkspaceBrief {
  tenant_id: number
  brand_name: string | null
  company_name: string | null
  start_at: string
  end_at: string
  trend_start_at?: string
  trend_end_at?: string
  display_period?: string
  display_day?: string | null
  platform_period_label?: string | null
  latest_schedule: WorkspaceBriefSchedule | null
  previous_schedule?: WorkspaceBriefSchedule | null
  round_comparison?: WorkspaceRoundComparison
  kpi_trends?: WorkspaceKpiTrendPoint[]
  next_schedule_hint: string | null
  schedule_plan?: MonitorSchedulePlan
  kpis: WorkspaceBriefKpis
  purchased_platforms: string[]
  platform_highlights: WorkspacePlatformHighlight[]
  top_sources: WorkspaceTopSource[]
  recent_snapshots: WorkspaceSnapshot[]
  alerts: WorkspaceAlert[]
  keyword_heats?: WorkspaceKeywordHeat[]
  keyword_platform_heatmap?: WorkspaceKeywordPlatformHeatmap | null
  service_start_date?: string | null
  service_end_date?: string | null
  health_score?: number
  visibility_score?: number
  rank_score?: number | null
  competitor_score?: number | null
  top_competitor_mention_rate?: number | null
  competitor_lead_delta?: number | null
}

export async function createMonitorTask(payload: MonitorTaskCreatePayload): Promise<MonitorTask> {
  const response = await http.post('/v1/monitor/tasks', payload)
  return response.data.data
}

export async function getMonitorTasks(tenantId?: number | null): Promise<MonitorTask[]> {
  const response = await http.get('/v1/monitor/tasks', {
    params: tenantId ? { tenant_id: tenantId } : {},
  })
  return response.data.data
}

let monitorSummaryCache: { data: MonitorSummary; expiresAt: number; key: string } | null = null
let monitorSummaryInflight: Promise<MonitorSummary> | null = null
let monitorSummaryInflightKey: string | null = null
const MONITOR_SUMMARY_TTL_MS = 60_000

/** 读缓存必须区分账号，否则观察号会吃到同企业主账号的全平台 brief。 */
function portalSessionCacheScope() {
  try {
    const raw = localStorage.getItem('geo-auth-session')
    if (!raw) return 'anon'
    const session = JSON.parse(raw) as {
      user?: { id?: number; username?: string }
      identity?: { id?: number }
    }
    const userId = session?.user?.id ?? ''
    const identityId = session?.identity?.id ?? ''
    const username = String(session?.user?.username || '').trim()
    return `${userId}:${identityId}:${username || '-'}`
  } catch {
    return 'anon'
  }
}

export function invalidateMonitorSummaryCache() {
  monitorSummaryCache = null
  monitorSummaryInflight = null
  monitorSummaryInflightKey = null
}

export async function getMonitorSummary(
  force = false,
  tenantId?: number | null,
  config?: GeoHttpRequestConfig,
): Promise<MonitorSummary> {
  const now = Date.now()
  // 2026-08-07 - summary 缓存按账号隔离，避免观察号串主账号数据
  const cacheKey = `${portalSessionCacheScope()}|${tenantId ? `t:${tenantId}` : 'default'}`
  if (!force && monitorSummaryCache && monitorSummaryCache.key === cacheKey && monitorSummaryCache.expiresAt > now) {
    return monitorSummaryCache.data
  }
  if (!force && !config?.signal && monitorSummaryInflight && monitorSummaryInflightKey === cacheKey) {
    return monitorSummaryInflight
  }
  const request = http.get('/v1/monitor/summary', {
    params: tenantId ? { tenant_id: tenantId } : {},
    ...config,
  }).then(response => {
    const data = response.data.data as MonitorSummary
    monitorSummaryCache = { data, expiresAt: Date.now() + MONITOR_SUMMARY_TTL_MS, key: cacheKey }
    return data
  })
  if (!config?.signal) {
    monitorSummaryInflightKey = cacheKey
    monitorSummaryInflight = request.finally(() => {
      monitorSummaryInflight = null
      monitorSummaryInflightKey = null
    })
    return monitorSummaryInflight
  }
  return request
}

export async function getRankingMatrix(
  params?: RankingMatrixQuery,
  config?: import('./http').GeoHttpRequestConfig,
): Promise<RankingMatrix> {
  const response = await http.get('/v1/monitor/ranking-matrix', { params, ...config })
  let data = response.data.data as RankingMatrix & {
    matrix_status?: string
    job_id?: string
    status?: string
    error?: string
  }
  // 2026-08-21 - 稳定性③：缓存未命中返回 processing 时轮询 job
  if (data?.matrix_status === 'processing' && data.job_id) {
    const jobId = data.job_id
    const started = Date.now()
    const timeoutMs = 90_000
    while (Date.now() - started < timeoutMs) {
      if (config?.signal?.aborted) {
        throw new DOMException('Aborted', 'AbortError')
      }
      await new Promise(r => setTimeout(r, 2500))
      if (config?.signal?.aborted) {
        throw new DOMException('Aborted', 'AbortError')
      }
      const jobResp = await http.get(`/v1/monitor/ranking-matrix/jobs/${encodeURIComponent(jobId)}`, {
        ...config,
      })
      const jobData = jobResp.data.data as typeof data
      if (jobData?.matrix_status === 'ready' && Array.isArray(jobData.rows)) {
        data = jobData
        break
      }
      if (jobData?.matrix_status === 'failed') {
        throw new Error(jobData.error || '排名矩阵计算失败')
      }
      if (jobData?.matrix_status === 'missing') {
        throw new Error('排名矩阵任务已失效，请重试')
      }
    }
    if (data?.matrix_status === 'processing') {
      throw new Error('排名矩阵计算超时，请稍后刷新')
    }
  }
  return data
}

export interface WorkspaceBriefQuery {
  start_date?: string
  end_date?: string
  tenant_id?: number
  record_access?: boolean
  scope?: 'full' | 'summary'
  /** geo=日常 GEO 监测（默认）；brand_word=品牌分析专用 */
  purpose?: 'geo' | 'brand_word'
}

const WORKSPACE_BRIEF_TTL_MS = 45_000
const WORKSPACE_BRIEF_CACHE_MAX = 16
const workspaceBriefCacheMap = new Map<string, { data: WorkspaceBrief; expiresAt: number }>()
let workspaceBriefInflight: Promise<WorkspaceBrief> | null = null
let workspaceBriefInflightKey: string | null = null

function workspaceBriefCacheKey(params?: WorkspaceBriefQuery) {
  // 2026-08-07 - 缓存键缺账号时，观察号会复用同企业主账号 45s 内的全平台数据
  return [
    portalSessionCacheScope(),
    params?.tenant_id ?? 'self',
    params?.start_date || '',
    params?.end_date || '',
    params?.scope || 'full',
    params?.purpose || 'geo',
    params?.record_access ? '1' : '0',
  ].join('|')
}

export function invalidateWorkspaceBriefCache() {
  workspaceBriefCacheMap.clear()
  workspaceBriefInflight = null
  workspaceBriefInflightKey = null
}

/** 登录/切身份/登出时清掉门户读缓存，避免串号。 */
export function invalidatePortalMonitorReadCaches() {
  invalidateMonitorSummaryCache()
  invalidateWorkspaceBriefCache()
}

function readWorkspaceBriefCache(key: string, now: number) {
  const hit = workspaceBriefCacheMap.get(key)
  if (!hit || hit.expiresAt <= now) {
    if (hit) workspaceBriefCacheMap.delete(key)
    return null
  }
  return hit.data
}

function writeWorkspaceBriefCache(key: string, data: WorkspaceBrief, now: number) {
  if (workspaceBriefCacheMap.size >= WORKSPACE_BRIEF_CACHE_MAX) {
    const oldest = workspaceBriefCacheMap.keys().next().value
    if (oldest) workspaceBriefCacheMap.delete(oldest)
  }
  workspaceBriefCacheMap.set(key, { data, expiresAt: now + WORKSPACE_BRIEF_TTL_MS })
}

export async function getWorkspaceBrief(
  params?: WorkspaceBriefQuery,
  options?: { force?: boolean; silentError?: boolean; timeout?: number; signal?: AbortSignal },
): Promise<WorkspaceBrief> {
  const key = workspaceBriefCacheKey(params)
  const now = Date.now()
  if (!options?.force) {
    const cached = readWorkspaceBriefCache(key, now)
    if (cached) return cached
    if (!options?.signal && workspaceBriefInflight && workspaceBriefInflightKey === key) {
      return workspaceBriefInflight
    }
  }
  const request = http.get('/v1/monitor/workspace-brief', {
    params,
    timeout: options?.timeout,
    silentError: options?.silentError,
    signal: options?.signal,
  } as GeoHttpRequestConfig).then(response => {
    const data = response.data.data as WorkspaceBrief
    writeWorkspaceBriefCache(key, data, Date.now())
    return data
  })
  if (!options?.signal) {
    workspaceBriefInflightKey = key
    workspaceBriefInflight = request.finally(() => {
      workspaceBriefInflight = null
      workspaceBriefInflightKey = null
    })
    return workspaceBriefInflight
  }
  return request
}

export interface BrandAnalysisAnswer {
  subtask_id: string
  task_id?: string
  platform?: string
  platform_name?: string
  prompt?: string
  excerpt: string
  sentiment: string
  updated_at?: string | null
  page_screenshot?: string | null
}

export interface BrandAnalysisPlatformBlock {
  code: string
  name: string
  sample_count: number
  positive: BrandAnalysisAnswer[]
  neutral: BrandAnalysisAnswer[]
  negative: BrandAnalysisAnswer[]
  unknown?: BrandAnalysisAnswer[]
}

export interface BrandAnalysisPieSlice {
  name: string
  value: number
  code?: string
}

export interface BrandAnalysisAiDescription {
  description: string
  sentiment: string
  sample_count: number
  platforms: Array<{ code: string; name: string }>
  answers: BrandAnalysisAnswer[]
}

export interface BrandAnalysisDashboard {
  tenant_id: number
  brand_name: string
  company_name?: string
  period_label: string
  purchased_platforms: string[]
  sample_count: number
  sentiment_counts: Record<string, number>
  sentiment_pie: BrandAnalysisPieSlice[]
  platform_pie: BrandAnalysisPieSlice[]
  platforms: BrandAnalysisPlatformBlock[]
  ai_descriptions?: BrandAnalysisAiDescription[]
  parse?: {
    parsed?: number
    pending_left?: number
    errors?: string[]
    error?: string
    description_parsed?: number
    description_pending_left?: number
    description_errors?: string[]
  }
  generated_at?: string
}

export async function getBrandAnalysis(
  params?: { tenant_id?: number; parse?: boolean },
  options?: { timeout?: number },
): Promise<BrandAnalysisDashboard> {
  const response = await http.get('/v1/monitor/brand-analysis', {
    params: {
      tenant_id: params?.tenant_id,
      parse: params?.parse ?? false,
      // 2026-07-28 - 避免中间层/浏览器把旧「1 组」响应当缓存
      _ts: Date.now(),
    },
    timeout: options?.timeout ?? 120_000,
    headers: { 'Cache-Control': 'no-cache', Pragma: 'no-cache' },
  } as GeoHttpRequestConfig)
  return response.data.data as BrandAnalysisDashboard
}

export interface InclusionSnapshotsQuery {
  start_date?: string
  end_date?: string
  tenant_id?: number
  platform?: string
  keyword?: string
  page?: number
  limit?: number
  /** ranked=有位次；all=含未提及 */
  rank_scope?: 'ranked' | 'all'
}

export interface InclusionSnapshotsResult {
  recent_snapshots: WorkspaceSnapshot[]
  purchased_platforms: string[]
  rank_scope?: 'ranked' | 'all'
  total?: number
  page?: number
  page_size?: number
}

export async function getInclusionSnapshots(
  params?: InclusionSnapshotsQuery,
  options?: { silentError?: boolean; timeout?: number },
): Promise<InclusionSnapshotsResult> {
  const response = await http.get('/v1/monitor/inclusion-snapshots', {
    params: {
      ...params,
      platform: params?.platform && params.platform !== 'all' ? params.platform : undefined,
    },
    timeout: options?.timeout,
    silentError: options?.silentError,
  } as GeoHttpRequestConfig)
  return response.data.data
}

export async function getMonitorTaskDetail(taskId: string): Promise<MonitorTaskDetail> {
  const response = await http.get(`/v1/monitor/tasks/${taskId}`)
  return response.data.data
}

export async function getMonitorSubtask(
  subtaskId: string,
  options?: { include_ops?: boolean; silentError?: boolean },
): Promise<MonitorSubtask> {
  const response = await http.get(`/v1/monitor/subtasks/${subtaskId}`, {
    params: options?.include_ops ? { include_ops: true } : undefined,
    silentError: options?.silentError,
  } as GeoHttpRequestConfig)
  return response.data.data
}

export async function syncMonitorTask(taskId: string): Promise<MonitorTaskDetail> {
  const response = await http.post(`/v1/monitor/tasks/${taskId}/sync`)
  invalidateMonitorSummaryCache()
  return response.data.data
}

export async function previewScheduledMonitor(tenantId?: number | null, maxPrompts = 50): Promise<ScheduledMonitorPreview[]> {
  const response = await http.get('/v1/monitor/scheduled/preview', { params: { tenant_id: tenantId || undefined, max_prompts: maxPrompts } })
  return response.data.data
}

export async function runDueScheduledMonitor(params?: { tenant_id?: number | null; limit?: number; max_prompts?: number; force?: boolean }): Promise<Array<Record<string, unknown>>> {
  const response = await http.post('/v1/monitor/scheduled/run-due', null, { params })
  return response.data.data
}
