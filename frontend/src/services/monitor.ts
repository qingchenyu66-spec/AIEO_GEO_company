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

export interface ScheduledMonitorPreview {
  tenant_id: number
  tenant_name: string
  brand_name: string
  schedule_type: string
  schedule_times: string[]
  platforms: MonitorPlatformConfig[]
  prompt_count: number
  prompts: string[]
  competitor_count: number
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

export async function getMonitorTaskDetail(taskId: string): Promise<MonitorTaskDetail> {
  const response = await http.get(`/v1/monitor/tasks/${taskId}`)
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
