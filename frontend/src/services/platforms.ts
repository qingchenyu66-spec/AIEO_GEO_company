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
  threshold_key: string
  threshold_name: string
  threshold_value: number
  threshold_unit: string
  scope: 'global' | 'tenant'
  tenant_id: number | null
  enabled: boolean
  last_triggered_at: string | null
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
  threshold_value?: number
  enabled?: boolean
}

export type PlatformServiceStatus = 'pending' | 'checking' | 'healthy' | 'degraded' | 'down'

export interface MolizhishuBalance {
  available: boolean
  current_balance: number | null
  current_balance_text: string | null
  fetched_at: string
  error: string | null
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

export async function getMolizhishuBalance(): Promise<MolizhishuBalance> {
  const response = await http.get('/v1/platforms/molizhishu-balance')
  return response.data.data
}

export async function getPlatformMatrix(): Promise<PlatformMatrix> {
  const response = await http.get('/v1/platforms/matrix')
  return response.data.data
}

export async function getPlatforms(): Promise<PlatformInfo[]> {
  const response = await http.get('/v1/platforms')
  return response.data.data
}

export async function updatePlatform(id: number, data: UpdatePlatformPayload): Promise<PlatformInfo> {
  const response = await http.put(`/v1/platforms/${id}`, data)
  return response.data.data
}

export async function getAlertThresholds(): Promise<AlertThreshold[]> {
  const response = await http.get('/v1/alerts/thresholds')
  return response.data.data
}

export async function updateAlertThreshold(id: number, data: UpdateAlertThresholdPayload): Promise<AlertThreshold> {
  const response = await http.put(`/v1/alerts/thresholds/${id}`, data)
  return response.data.data
}
