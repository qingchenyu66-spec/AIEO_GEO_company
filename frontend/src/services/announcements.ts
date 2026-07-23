import { http, invalidateCache, type GeoHttpRequestConfig } from './http'

export type AnnouncementTarget = 'platform_all' | 'customer_all' | 'customer_tenants'
export type AnnouncementAction = 'draft' | 'publish_now' | 'schedule'
export type AnnouncementStatus = 'draft' | 'scheduled' | 'published' | 'off'

export interface AnnouncementItem {
  id: number
  title: string
  body_html: string
  targets: AnnouncementTarget[]
  tenant_ids: number[]
  status: AnnouncementStatus
  publish_at?: string | null
  expire_at?: string | null
  created_at?: string | null
  updated_at?: string | null
}

export interface AnnouncementPending {
  id: number
  title: string
  body_html: string
  publish_at?: string | null
}

export interface AnnouncementUpsertPayload {
  title: string
  body_html: string
  targets: AnnouncementTarget[]
  tenant_ids?: number[]
  publish_at?: string | null
  expire_at?: string | null
  action: AnnouncementAction
}

export async function listAnnouncements(): Promise<AnnouncementItem[]> {
  const response = await http.get('/v1/announcements/list')
  return (response.data.data || []) as AnnouncementItem[]
}

export async function createAnnouncement(payload: AnnouncementUpsertPayload): Promise<AnnouncementItem> {
  const response = await http.post('/v1/announcements/', payload)
  invalidateCache('/v1/announcements')
  return response.data.data as AnnouncementItem
}

export async function updateAnnouncement(id: number, payload: AnnouncementUpsertPayload): Promise<AnnouncementItem> {
  const response = await http.put(`/v1/announcements/${id}`, payload)
  invalidateCache('/v1/announcements')
  return response.data.data as AnnouncementItem
}

export async function offlineAnnouncement(id: number): Promise<AnnouncementItem> {
  const response = await http.post(`/v1/announcements/${id}/offline`)
  invalidateCache('/v1/announcements')
  return response.data.data as AnnouncementItem
}

export async function deleteAnnouncement(id: number): Promise<void> {
  await http.delete(`/v1/announcements/${id}`)
  invalidateCache('/v1/announcements')
}

export async function getPendingAnnouncement(): Promise<AnnouncementPending | null> {
  const response = await http.get('/v1/announcements/pending', { silentError: true } as GeoHttpRequestConfig)
  return (response.data.data || null) as AnnouncementPending | null
}

export async function ackAnnouncement(id: number): Promise<{ acked_id: number; next: AnnouncementPending | null }> {
  const response = await http.post(`/v1/announcements/${id}/ack`)
  return response.data.data as { acked_id: number; next: AnnouncementPending | null }
}

export async function uploadAnnouncementMedia(file: File, kind: 'auto' | 'image' | 'file' = 'auto') {
  const form = new FormData()
  form.append('file', file)
  form.append('kind', kind)
  // 勿手写 multipart Content-Type，否则缺 boundary，上传会失败/无响应
  const response = await http.post('/v1/announcements/media', form, {
    headers: { 'Content-Type': undefined as unknown as string },
  })
  return response.data.data as { id: number; kind: string; original_name: string; url: string }
}
