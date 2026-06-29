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
