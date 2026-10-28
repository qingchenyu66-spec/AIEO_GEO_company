import type { SnapshotBackfillPendingItem } from '../../services/snapshotBackfill'

/** 分页刷新时按子任务去重，并让后到的任务状态覆盖旧状态。 */
export function mergeSnapshotBackfillMobilePage(
  current: SnapshotBackfillPendingItem[],
  incoming: SnapshotBackfillPendingItem[],
) {
  const merged = new Map(current.map(item => [item.subtask_id, item]))
  for (const item of incoming) merged.set(item.subtask_id, item)
  return [...merged.values()]
}
