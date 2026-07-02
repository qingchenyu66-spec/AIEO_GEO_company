import { http } from './http'

export interface SystemNotification {
  id: number
  audience_type: string
  tenant_id: number | null
  category: string
  level: 'info' | 'warning' | 'critical' | string
  title: string
  message: string
  payload: Record<string, unknown> | null
  source_key: string
  is_read: boolean
  created_at: string
  updated_at: string
}

export async function getNotifications(params?: { unread_only?: boolean; limit?: number }): Promise<SystemNotification[]> {
  const response = await http.get('/v1/notifications', { params })
  return response.data.data
}

export async function getUnreadNotificationCount(): Promise<number> {
  const response = await http.get('/v1/notifications/unread-count')
  return Number(response.data.data?.count || 0)
}

export async function markNotificationRead(id: number): Promise<void> {
  await http.post(`/v1/notifications/${id}/read`)
}

export async function markAllNotificationsRead(): Promise<number> {
  const response = await http.post('/v1/notifications/read-all')
  return Number(response.data.data?.marked || 0)
}

export async function syncGeoPlatforms(forceRefresh = false): Promise<{ created: number; updated: number; total: number }> {
  const response = await http.post('/v1/platforms/sync-catalog', null, { params: { force_refresh: forceRefresh } })
  return response.data.data
}
