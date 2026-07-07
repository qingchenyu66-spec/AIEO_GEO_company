import { http } from './http'

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
  schedule_source?: string | null
  brand_name?: string | null
  task_created_at?: string | null
  needs_backfill?: boolean
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
    count: number
    platforms?: string[]
    exposure_terms?: string[]
    questions?: string[]
    latest_time?: string | null
  }>
  source_citation_trend?: {
    start_at: string
    end_at: string
    points: Array<{ label: string; day_key: string; value: number }>
  }
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
}

export interface RankingMatrixCellSnapshot {
  subtask_id: string
  task_id?: string | null
  mention_position: number | null
  raw_mention_position?: number | null
  brand_mentioned?: boolean
  monitor_keyword?: string | null
  prompt_intent?: 'ranking' | 'exposure'
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
}

export interface WorkspaceBriefSchedule {
  schedule_window_key: string
  schedule_label: string | null
  completed_subtasks: number
  total_subtasks: number
}

export interface WorkspaceBriefKpis {
  ranking_sample_count: number
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
}

export interface WorkspaceSnapshot {
  subtask_id: string
  task_id: string | null
  platform: string
  prompt: string
  keyword_group: string | null
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

export async function getMonitorTasks(): Promise<MonitorTask[]> {
  const response = await http.get('/v1/monitor/tasks')
  return response.data.data
}

let monitorSummaryCache: { data: MonitorSummary; expiresAt: number } | null = null
let monitorSummaryInflight: Promise<MonitorSummary> | null = null
const MONITOR_SUMMARY_TTL_MS = 15_000

export function invalidateMonitorSummaryCache() {
  monitorSummaryCache = null
}

export async function getMonitorSummary(force = false): Promise<MonitorSummary> {
  const now = Date.now()
  if (!force && monitorSummaryCache && monitorSummaryCache.expiresAt > now) {
    return monitorSummaryCache.data
  }
  if (!force && monitorSummaryInflight) {
    return monitorSummaryInflight
  }
  monitorSummaryInflight = http.get('/v1/monitor/summary').then(response => {
    const data = response.data.data as MonitorSummary
    monitorSummaryCache = { data, expiresAt: Date.now() + MONITOR_SUMMARY_TTL_MS }
    return data
  }).finally(() => {
    monitorSummaryInflight = null
  })
  return monitorSummaryInflight
}

export async function getRankingMatrix(params?: RankingMatrixQuery): Promise<RankingMatrix> {
  const response = await http.get('/v1/monitor/ranking-matrix', { params })
  return response.data.data
}

export interface WorkspaceBriefQuery {
  start_date?: string
  end_date?: string
}

export async function getWorkspaceBrief(params?: WorkspaceBriefQuery): Promise<WorkspaceBrief> {
  const response = await http.get('/v1/monitor/workspace-brief', { params })
  return response.data.data
}

export async function getMonitorTaskDetail(taskId: string): Promise<MonitorTaskDetail> {
  const response = await http.get(`/v1/monitor/tasks/${taskId}`)
  return response.data.data
}

export async function getMonitorSubtask(subtaskId: string, options?: { include_ops?: boolean }): Promise<MonitorSubtask> {
  const response = await http.get(`/v1/monitor/subtasks/${subtaskId}`, {
    params: options?.include_ops ? { include_ops: true } : undefined,
  })
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
