import { http, invalidateCache } from './http'
import type { MonitorSubtask } from './monitor'

export interface SnapshotBackfillPendingItem {
  subtask_id: string
  task_id: string
  tenant_id: number | null
  tenant_name: string | null
  platform: string
  prompt: string
  error_message: string | null
  source: 'lead_diagnosis' | 'tenant_monitor' | string
  monitor_keywords: string | null
  task_status: string | null
  updated_at: string | null
  task_created_at?: string | null
  needs_backfill?: boolean
  has_answer?: boolean
  status?: string | null
  mention_position?: number | null
  raw_mention_position?: number | null
  brand_rank?: number | null
  brand_mentioned?: boolean | null
  prompt_intent?: string | null
  keyword_group?: string | null
  sentiment?: string | null
  page_screenshot?: string | null
  lead_diagnosis_id?: number | null
  schedule_key?: string | null
  schedule_label?: string | null
  schedule_source?: string | null
  brand_name?: string | null
}

export interface SnapshotBackfillQuery {
  tenant_id?: number | null
  date?: string
  source?: 'tenant_monitor' | 'lead_diagnosis' | ''
  platform?: string
  keyword?: string
  keyword_group?: string
  pending_only?: boolean
  offset?: number
  limit?: number
}

export function subtaskNeedsSnapshotBackfill(subtask: { answer_content?: string | null; status?: string; error_message?: string | null }) {
  if (subtask.answer_content) return false
  if (subtask.status === 'failed' || subtask.status === 'stopped') return true
  return Boolean(subtask.error_message)
}

export interface SnapshotBackfillListSummary {
  total: number
  pending: number
  overwrite: number
  shown: number
  offset: number
  limit: number
  has_more: boolean
  scan_capped?: boolean
}

export interface SnapshotBackfillListResult {
  items: SnapshotBackfillPendingItem[]
  summary: SnapshotBackfillListSummary
}

export async function getPendingSnapshotBackfills(query: SnapshotBackfillQuery = {}): Promise<SnapshotBackfillListResult> {
  const response = await http.get('/v1/monitor/snapshot-backfill/pending', {
    params: {
      limit: query.limit ?? 40,
      offset: query.offset ?? 0,
      pending_only: query.pending_only ?? false,
      tenant_id: query.tenant_id || undefined,
      date: query.date || undefined,
      source: query.source || undefined,
      platform: query.platform || undefined,
      keyword: query.keyword || undefined,
      keyword_group: query.keyword_group || undefined,
    },
  })
  const data = response.data.data
  if (Array.isArray(data)) {
    const items = data as SnapshotBackfillPendingItem[]
    const pending = items.filter(item => item.needs_backfill).length
    const overwrite = items.filter(item => item.has_answer && !item.needs_backfill).length
    return {
      items,
      summary: {
        total: items.length,
        pending,
        overwrite,
        shown: items.length,
        offset: 0,
        limit: query.limit ?? 40,
        has_more: false,
      },
    }
  }
  return data as SnapshotBackfillListResult
}

export async function submitSnapshotBackfill(
  subtaskId: string,
  payload: {
    snapshot_url: string
    answer_content: string
    mention_position?: number | null
    sentiment?: string | null
    reference_urls?: string[]
  },
): Promise<{ subtask: MonitorSubtask }> {
  const response = await http.post(`/v1/monitor/subtasks/${subtaskId}/snapshot-backfill`, payload)
  invalidateCache('/v1/monitor')
  invalidateCache('/v1/brand/asset')
  return response.data.data
}
