import type { MonitorSubtask } from '../../services/monitor'
import type { SnapshotBackfillPendingItem } from '../../services/snapshotBackfill'
import type { MonitorRankDisplay } from './portalUtils'

/** 子任务详情 API 已附带运营端展示字段，合并进抽屉用的 item。 */
export function mergeSnapshotBackfillItem(
  partial: SnapshotBackfillPendingItem,
  subtask: MonitorSubtask,
): SnapshotBackfillPendingItem {
  return {
    ...partial,
    subtask_id: subtask.subtask_id,
    task_id: subtask.task_id || partial.task_id,
    tenant_id: subtask.tenant_id ?? partial.tenant_id,
    tenant_name: subtask.tenant_name ?? partial.tenant_name,
    platform: subtask.platform || partial.platform,
    prompt: subtask.prompt || partial.prompt,
    error_message: subtask.error_message ?? partial.error_message,
    source: (subtask.source as SnapshotBackfillPendingItem['source']) || partial.source,
    monitor_keywords: subtask.monitor_keywords ?? partial.monitor_keywords,
    keyword_group: subtask.keyword_group ?? partial.keyword_group,
    schedule_label: subtask.schedule_label ?? partial.schedule_label,
    schedule_key: subtask.schedule_key ?? partial.schedule_key,
    schedule_window_key: subtask.schedule_window_key ?? partial.schedule_window_key,
    schedule_source: subtask.schedule_source ?? partial.schedule_source,
    region_code: subtask.region_code ?? partial.region_code,
    region_label: subtask.region_label ?? partial.region_label,
    brand_name: subtask.brand_name ?? partial.brand_name,
    task_created_at: subtask.task_created_at ?? partial.task_created_at,
    updated_at: subtask.updated_at ?? partial.updated_at,
    mention_position: subtask.mention_position ?? partial.mention_position,
    raw_mention_position: subtask.raw_mention_position ?? partial.raw_mention_position,
    brand_rank: subtask.brand_rank ?? partial.brand_rank,
    brand_mentioned: subtask.brand_mentioned ?? partial.brand_mentioned,
    prompt_intent: subtask.prompt_intent ?? partial.prompt_intent,
    rank_source: subtask.rank_source ?? (partial as { rank_source?: string | null }).rank_source,
    rank_category: subtask.rank_category ?? (partial as { rank_category?: string | null }).rank_category,
    sentiment: subtask.sentiment ?? partial.sentiment,
    page_screenshot: subtask.page_screenshot ?? partial.page_screenshot,
    needs_backfill: subtask.needs_backfill ?? partial.needs_backfill,
    has_answer: subtask.has_answer ?? partial.has_answer ?? Boolean(subtask.answer_content),
    status: subtask.status || partial.status,
  }
}

export function snapshotBackfillRankDisplay(
  item: SnapshotBackfillPendingItem | null,
  subtask: MonitorSubtask | null,
): MonitorRankDisplay {
  const fromSub = subtask as MonitorSubtask & MonitorRankDisplay | null
  const fromItem = item as (SnapshotBackfillPendingItem & MonitorRankDisplay) | null
  return {
    prompt_intent: fromSub?.prompt_intent ?? fromItem?.prompt_intent,
    mention_position: fromSub?.mention_position ?? fromItem?.mention_position ?? null,
    brand_mentioned: fromSub?.brand_mentioned ?? fromItem?.brand_mentioned ?? null,
    rank_source: fromSub?.rank_source ?? fromItem?.rank_source ?? null,
    rank_category: fromSub?.rank_category ?? fromItem?.rank_category ?? null,
  }
}

export function snapshotBackfillBatchLabel(item: SnapshotBackfillPendingItem | null) {
  if (!item) return '—'
  return item.schedule_label || '—'
}

/** number 型 input 的 v-model 可能为 number，提交前统一解析为排名或 null。 */
export function parseSnapshotBackfillMentionPosition(value: string | number | null | undefined): number | null {
  const raw = String(value ?? '').trim()
  if (!raw) return null
  const parsed = Number(raw)
  return Number.isFinite(parsed) ? parsed : null
}
