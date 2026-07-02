import { http } from './http'

export interface PlatformInfo {
  id: number
  platform_code: string
  platform_name: string
  platform_type: 'web' | 'mobile'
  is_enabled: boolean
  mode_options: string[]
  default_mode: string
  api_endpoint: string | null
  created_at: string
  updated_at: string
}

export interface AlertThreshold {
  id: number
  tenant_id: number | null
  metric_type: string
  metric_label?: string
  threshold_name: string
  warning_value: string
  critical_value: string
  unit: string
  enabled: boolean
  updated_by: string | null
  updated_at: string
}

export interface UpdatePlatformPayload {
  platform_name?: string
  is_enabled?: boolean
  mode_options?: string[]
  default_mode?: string
  api_endpoint?: string | null
}

export interface UpdateAlertThresholdPayload {
  threshold_name?: string
  warning_value?: string
  critical_value?: string
  unit?: string
  metric_type?: string
  enabled?: boolean
}

export interface CelerySyncPlatformBreakdown {
  code: string
  name: string
  total: number
  completed: number
  pending: number
  processing: number
  failed: number
  pending_prompts?: string[]
}

export interface CelerySyncTaskDetail {
  task_id: string
  task_id_short: string
  tenant_id?: number | null
  tenant_name?: string | null
  monitor_keywords?: string | null
  status: string
  total_items: number
  completed_items: number
  failed_items: number
  progress_text: string
  prompt_count: number
  prompts: string[]
  prompts_preview?: string | null
  platform_count: number
  platform_codes: string[]
  platform_breakdown: CelerySyncPlatformBreakdown[]
  pending_platforms: string[]
  processing_platforms: string[]
  schedule_label?: string | null
  keyword_group?: string | null
  updated_at?: string | null
  sync_error?: string
  phase?: string
}

export interface CeleryMonitorData {
  checked_at: string
  queues: Array<{
    key: string
    name: string
    pending: number
    warning_threshold: number
    critical_threshold: number
    status: string
    status_level: 'normal' | 'warning' | 'critical'
    usage_percent: number
  }>
  workers: {
    online_count: number
    active_tasks: number
    reserved_tasks: number
    status: string
    items: Array<{ name: string; role: string }>
  }
  alerts: Array<{ queue: string; level: string; title: string; message: string; queued: number; threshold: number }>
  alert_count: number
  flower_url?: string | null
  tips: string[]
  scheduler: {
    submit_scan: string
    sync_scan: string
    backlog_check: string
  }
  runtime_tasks?: {
    active: CeleryRuntimeTask[]
    reserved: CeleryRuntimeTask[]
    total: number
  }
  beat_history?: CeleryBeatHistoryItem[]
  ops_insights?: {
    scheduler_ok: boolean
    scheduler_status: string
    pending_sync_tasks: number
    today_scan_count: number
    today_enqueued_tasks: number
    last_due_scan?: {
      at?: string | null
      status_label?: string | null
      summary?: string | null
    } | null
  }
  pending_sync_details?: CelerySyncTaskDetail[]
  sync_live?: CelerySyncTaskDetail | null
}

export interface CeleryRuntimeTask {
  task_id?: string
  task_key: string
  label: string
  detail: string
  worker: string
  worker_role: string
  phase: 'active' | 'reserved'
  phase_label: string
  started_at?: string | null
}

export interface CeleryBeatHistoryItem {
  task_key: string
  label: string
  status: string
  status_label: string
  checked_at: string
  enqueued?: number
  skipped?: number
  alert_count?: number
  summary?: string
  message?: string | null
  sync_details?: CelerySyncTaskDetail[]
}

export type PlatformServiceStatus = 'pending' | 'checking' | 'healthy' | 'degraded' | 'down'

export interface MolizhishuBalance {
  available: boolean
  current_balance: number | null
  current_balance_text: string | null
  fetched_at: string
  error: string | null
}

export interface DeepseekBalance extends MolizhishuBalance {
  currency?: string | null
  is_available?: boolean | null
  display_value?: string | null
}

export interface PlatformMatrixItem {
  code: string
  name: string
  channel: 'web' | 'mobile'
  channel_label: string
  supported: boolean
  status: PlatformServiceStatus
  status_label: string
  status_hint: string
  probe_total: number
  probe_success: number
  probe_failed: number
  checked_at: string | null
}

export interface PlatformMatrix {
  snapshot_date: string
  supported_count: number
  healthy_count: number
  checking_count: number
  pending_count: number
  issue_count: number
  first_schedule_at: string | null
  updated_at: string
  catalog_source?: string
  catalog_source_url?: string
  catalog_fetched_at?: string | null
  molizhishu_balance?: MolizhishuBalance
  platforms: PlatformMatrixItem[]
}

let platformMatrixCache: { data: PlatformMatrix; at: number } | null = null
let platformListCache: { data: PlatformInfo[]; at: number } | null = null
const PLATFORM_CACHE_TTL = 60 * 1000

export async function getMolizhishuBalance(): Promise<MolizhishuBalance> {
  const response = await http.get('/v1/platforms/molizhishu-balance')
  return response.data.data
}

export async function getDeepseekBalance(): Promise<DeepseekBalance> {
  const response = await http.get('/v1/platforms/deepseek-balance')
  return response.data.data
}

export async function getPlatformMatrix(force = false): Promise<PlatformMatrix> {
  if (!force && platformMatrixCache && Date.now() - platformMatrixCache.at < PLATFORM_CACHE_TTL) {
    return platformMatrixCache.data
  }
  const response = await http.get('/v1/platforms/matrix')
  platformMatrixCache = { data: response.data.data, at: Date.now() }
  return platformMatrixCache.data
}

export async function getPlatforms(): Promise<PlatformInfo[]> {
  if (platformListCache && Date.now() - platformListCache.at < PLATFORM_CACHE_TTL) {
    return platformListCache.data
  }
  const response = await http.get('/v1/platforms')
  platformListCache = { data: response.data.data, at: Date.now() }
  return platformListCache.data
}

export async function updatePlatform(id: number, data: UpdatePlatformPayload): Promise<PlatformInfo> {
  const response = await http.put(`/v1/platforms/${id}`, data)
  platformListCache = null
  platformMatrixCache = null
  return response.data.data
}

export async function getAlertThresholds(scope: 'business' | 'technical' | 'all' = 'business'): Promise<AlertThreshold[]> {
  const response = await http.get('/v1/alerts/thresholds', { params: { scope } })
  return response.data.data
}

export async function getCeleryMonitor(): Promise<CeleryMonitorData> {
  const response = await http.get('/v1/alerts/celery-monitor')
  return response.data.data
}

export async function updateAlertThreshold(id: number, data: UpdateAlertThresholdPayload): Promise<AlertThreshold> {
  const response = await http.put(`/v1/alerts/thresholds/${id}`, data)
  return response.data.data
}
