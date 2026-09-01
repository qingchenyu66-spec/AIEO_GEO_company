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
  rank_source?: string | null
  rank_category?: string | null
  rank_basis?: string | null
  keyword_group?: string | null
  sentiment?: string | null
  page_screenshot?: string | null
  lead_diagnosis_id?: number | null
  schedule_key?: string | null
  schedule_window_key?: string | null
  schedule_label?: string | null
  schedule_source?: string | null
  region_code?: string | null
  region_label?: string | null
  brand_name?: string | null
  backfill_dismissed?: boolean
  needs_backfill_raw?: boolean
}

export interface SnapshotBackfillQuery {
  tenant_id?: number | null
  all_tenants?: boolean
  date?: string
  date_from?: string
  date_to?: string
  source?: 'tenant_monitor' | 'lead_diagnosis' | ''
  platform?: string
  keyword?: string
  keyword_group?: string
  pending_only?: boolean
  offset?: number
  limit?: number
  include_summary?: boolean
  skip_cache?: boolean
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
  summary_partial?: boolean
}

export interface SnapshotBackfillListResult {
  items: SnapshotBackfillPendingItem[]
  summary: SnapshotBackfillListSummary
}

export interface SnapshotBackfillMatrixPlatform {
  id: string
  name: string
  todo: number
  fail: number
  avg: number | null
}

export interface SnapshotBackfillMatrixSlot {
  subtask_id: string | null
  task_id?: string
  schedule_label?: string | null
  schedule_window_key?: string | null
  mention_position?: number | null
  needs_backfill?: boolean
  backfill_dismissed?: boolean
  has_answer?: boolean
  status?: string | null
  error_message?: string | null
  prompt?: string
  platform?: string
  tenant_id?: number | null
  tenant_name?: string | null
  brand_name?: string | null
  source?: string
  monitor_keywords?: string | null
  keyword_group?: string | null
  updated_at?: string | null
  is_gap?: boolean
  /** 是否有补录前快照（仅本功能上线后补录的有） */
  has_before_backfill?: boolean
  before_mention_position?: number | null
  before_has_answer?: boolean | null
  before_status?: string | null
}

export interface SnapshotBackfillMatrixCell {
  platform: string
  word: string
  date: string
  rank: number | null
  has_todo: boolean
  fail_count: number
  sample_count: number
  rank_sample_count: number
  gap_count?: number
  slots: SnapshotBackfillMatrixSlot[]
}

export interface SnapshotBackfillMatrixResult {
  date_from: string
  date_to: string
  dates: string[]
  words: string[]
  platforms: SnapshotBackfillMatrixPlatform[]
  cells: SnapshotBackfillMatrixCell[]
  summary: {
    todo_cells: number
    fail_slots: number
    item_total: number
    scan_capped?: boolean
    gap_cells?: number
  }
}

export async function getPendingSnapshotBackfills(
  query: SnapshotBackfillQuery = {},
  options?: { signal?: AbortSignal },
): Promise<SnapshotBackfillListResult> {
  const response = await http.get('/v1/monitor/snapshot-backfill/pending', {
    signal: options?.signal,
    params: {
      limit: query.limit ?? 40,
      offset: query.offset ?? 0,
      pending_only: query.pending_only ?? false,
      tenant_id: query.tenant_id || undefined,
      all_tenants: query.tenant_id ? undefined : (query.all_tenants ?? true),
      date: query.date || undefined,
      date_from: query.date_from || undefined,
      date_to: query.date_to || undefined,
      source: query.source || undefined,
      platform: query.platform || undefined,
      keyword: query.keyword || undefined,
      keyword_group: query.keyword_group || undefined,
      include_summary: query.include_summary,
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

export async function getSnapshotBackfillMatrix(
  query: SnapshotBackfillQuery = {},
  options?: { signal?: AbortSignal },
): Promise<SnapshotBackfillMatrixResult> {
  const response = await http.get('/v1/monitor/snapshot-backfill/matrix', {
    signal: options?.signal,
    params: {
      tenant_id: query.tenant_id || undefined,
      all_tenants: query.tenant_id ? undefined : (query.all_tenants ?? true),
      date_from: query.date_from || undefined,
      date_to: query.date_to || undefined,
      source: query.source || undefined,
      platform: query.platform || undefined,
      keyword: query.keyword || undefined,
      keyword_group: query.keyword_group || undefined,
      skip_cache: query.skip_cache || undefined,
    },
  })
  return response.data.data as SnapshotBackfillMatrixResult
}

export async function ensureGapBackfillSubtask(payload: {
  tenant_id: number
  platform: string
  prompt: string
  schedule_window_key: string
}): Promise<{ subtask: MonitorSubtask; item: SnapshotBackfillPendingItem }> {
  const response = await http.post('/v1/monitor/snapshot-backfill/gap-subtask', payload)
  invalidateCache('/v1/monitor')
  return response.data.data
}

export async function submitSnapshotBackfill(
  subtaskId: string,
  payload: {
    snapshot_url?: string | null
    answer_content?: string | null
    mention_position?: number | null
    sentiment?: string | null
    reference_urls?: string[]
  },
): Promise<{ subtask: MonitorSubtask }> {
  // 2026-08-17 - 补录默认 30s 被艾迪亚信源重刷拖死；后端已异步，前端仍放宽兜底
  const response = await http.post(`/v1/monitor/subtasks/${subtaskId}/snapshot-backfill`, payload, {
    timeout: 120000,
  })
  invalidateCache('/v1/monitor')
  invalidateCache('/v1/brand/asset')
  return response.data.data
}

export async function dismissSnapshotBackfill(subtaskId: string): Promise<{
  subtask_id: string
  backfill_dismissed: boolean
  item: SnapshotBackfillPendingItem
}> {
  const response = await http.post(`/v1/monitor/subtasks/${subtaskId}/snapshot-backfill/dismiss`)
  invalidateCache('/v1/monitor')
  return response.data.data
}

export interface SnapshotBackfillBatchDismissSlot {
  tenant_id?: number | null
  platform: string
  prompt: string
  schedule_window_key?: string | null
  subtask_id?: string | null
  is_gap?: boolean
}

export async function dismissSnapshotBackfillBatch(
  query: SnapshotBackfillQuery & { todo_only?: boolean; slots?: SnapshotBackfillBatchDismissSlot[] } = {},
): Promise<{ dismissed: number; skipped: number; truncated: boolean; todo_only: boolean }> {
  const response = await http.post(
    '/v1/monitor/snapshot-backfill/dismiss-batch',
    query.slots?.length ? { slots: query.slots } : null,
    {
      params: {
        tenant_id: query.tenant_id || undefined,
        all_tenants: query.tenant_id ? undefined : (query.all_tenants ?? true),
        date_from: query.date_from || undefined,
        date_to: query.date_to || undefined,
        source: query.source || undefined,
        platform: query.platform || undefined,
        keyword: query.keyword || undefined,
        keyword_group: query.keyword_group || undefined,
        todo_only: query.todo_only ?? true,
      },
      timeout: 120000,
    },
  )
  invalidateCache('/v1/monitor')
  return response.data.data
}

export async function undismissSnapshotBackfill(subtaskId: string): Promise<{
  subtask_id: string
  backfill_dismissed: boolean
  item: SnapshotBackfillPendingItem
}> {
  const response = await http.post(`/v1/monitor/subtasks/${subtaskId}/snapshot-backfill/undismiss`)
  invalidateCache('/v1/monitor')
  return response.data.data
}
