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
  citation_list: Array<{ title?: string; url?: string; site?: string; index?: number }>
  recommended_questions: string[]
  error_message: string | null
  mention_position: number | null
  mention_context: string | null
  sentiment: string | null
  amount: number | null
}

export interface MonitorTaskDetail {
  task: MonitorTask
  subtasks: MonitorSubtask[]
}

export async function createMonitorTask(payload: MonitorTaskCreatePayload): Promise<MonitorTask> {
  const response = await http.post('/v1/monitor/tasks', payload)
  return response.data.data
}

export async function getMonitorTasks(): Promise<MonitorTask[]> {
  const response = await http.get('/v1/monitor/tasks')
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
