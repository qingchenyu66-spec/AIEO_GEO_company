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
    keywords?: string[]
    questions?: string[]
    latest_time?: string | null
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
}

export interface RankingMatrixRow {
  task_id: string
  platform?: string | null
  schedule_key?: string | null
  schedule_window_key?: string | null
  schedule_label?: string | null
  schedule_source?: 'run' | 'inferred' | 'created_at' | null
  keyword_group?: string | null
  snapshot_at: string | null
  cells: Record<string, RankingMatrixCell>
}

export interface RankingMatrixKeywordGroupOption {
  monitor_keyword: string
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
  limit_rows?: number
}

export interface SentimentOverviewItem {
  subtask_id: string
  platform: string
  prompt: string
  keyword_group: string | null
  schedule_label: string | null
  schedule_window_key: string | null
  schedule_source?: 'run' | 'inferred' | 'created_at' | null
  sentiment: string
  sentiment_raw: string | null
  brand_mentioned: boolean
  prompt_intent: 'exposure'
  answer_excerpt: string
  updated_at: string | null
}

export interface SentimentPlatformStat {
  platform: string
  sample_count: number
  positive_rate: number
  negative_rate: number
  neutral_rate: number
  negative_count: number
}

export interface SentimentTrendPoint {
  label: string
  positive: number
  neutral: number
  negative: number
  unknown?: number
}

export interface SentimentScheduleOption {
  schedule_window_key: string
  schedule_label: string
}

export interface SentimentOverview {
  tenant_id: number
  brand_name: string | null
  start_at: string
  end_at: string
  sample_count: number
  recognized_count: number
  unknown_count: number
  negative_count: number
  sentiment_counts: Record<string, number>
  positive_rate: number
  negative_rate: number
  neutral_rate: number
  platform_stats: SentimentPlatformStat[]
  sentiment_trend: SentimentTrendPoint[]
  schedule_options: SentimentScheduleOption[]
  keyword_group_options: RankingMatrixKeywordGroupOption[]
  purchased_platforms: string[]
  schedule_plan?: MonitorSchedulePlan
  items: SentimentOverviewItem[]
}

export interface SentimentOverviewQuery {
  platform?: string
  start_date?: string
  end_date?: string
  monitor_group?: string
  schedule_window_key?: string
  sentiment?: 'all' | 'negative' | 'positive' | 'neutral'
  tenant_id?: number
  item_limit?: number
}

export async function createMonitorTask(payload: MonitorTaskCreatePayload): Promise<MonitorTask> {
  const response = await http.post('/v1/monitor/tasks', payload)
  return response.data.data
}

export async function getMonitorTasks(): Promise<MonitorTask[]> {
  const response = await http.get('/v1/monitor/tasks')
  return response.data.data
}

export async function getMonitorSummary(): Promise<MonitorSummary> {
  const response = await http.get('/v1/monitor/summary')
  return response.data.data
}

export async function getRankingMatrix(params?: RankingMatrixQuery): Promise<RankingMatrix> {
  const response = await http.get('/v1/monitor/ranking-matrix', { params })
  return response.data.data
}

export async function getSentimentOverview(params?: SentimentOverviewQuery): Promise<SentimentOverview> {
  const response = await http.get('/v1/monitor/sentiment-overview', { params })
  return response.data.data
}

export async function getMonitorTaskDetail(taskId: string): Promise<MonitorTaskDetail> {
  const response = await http.get(`/v1/monitor/tasks/${taskId}`)
  return response.data.data
}

export async function getMonitorSubtask(subtaskId: string): Promise<MonitorSubtask> {
  const response = await http.get(`/v1/monitor/subtasks/${subtaskId}`)
  return response.data.data
}

export async function syncMonitorTask(taskId: string): Promise<MonitorTaskDetail> {
  const response = await http.post(`/v1/monitor/tasks/${taskId}/sync`)
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
