import { http } from './http'

export interface OperationLogRecord {
  id: number
  operator_name: string
  action_type: string
  description: string
  ip_address: string | null
  risk_level: string
  target_module: string | null
  tenant_id: number | null
  tenant_name?: string | null
  created_at: string
}

export interface OperationLogPage {
  items: OperationLogRecord[]
  total: number
  page: number
  page_size: number
}

export interface SystemConfigRecord {
  id: number
  config_key: string
  config_value: string
  description: string | null
  updated_by: string | null
  status: boolean
  updated_at: string
}

export async function getOperationLogs(params?: {
  days?: number
  action_type?: string
  keyword?: string
  tenant_id?: number
  page?: number
  page_size?: number
}): Promise<OperationLogPage> {
  const response = await http.get('/v1/ops/logs', { params })
  return response.data.data
}

export async function getSystemConfigs(): Promise<SystemConfigRecord[]> {
  const response = await http.get('/v1/management/system-configs')
  return response.data.data
}

export async function updateSystemConfig(configId: number, configValue: string): Promise<void> {
  await http.put(`/v1/management/system-configs/${configId}`, { config_value: configValue })
}
