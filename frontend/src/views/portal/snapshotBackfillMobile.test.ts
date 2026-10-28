import { describe, expect, it } from 'vitest'
import type { SnapshotBackfillPendingItem } from '../../services/snapshotBackfill'
import { mergeSnapshotBackfillMobilePage } from './snapshotBackfillMobile'

function item(subtaskId: string, status: string): SnapshotBackfillPendingItem {
  return {
    subtask_id: subtaskId,
    task_id: `task-${subtaskId}`,
    tenant_id: 1,
    tenant_name: '测试企业',
    platform: 'deepseek',
    prompt: '测试问题',
    error_message: null,
    source: 'tenant_monitor',
    monitor_keywords: '测试词',
    task_status: status,
    updated_at: '2026-10-28T10:00:00',
    status,
  }
}

describe('mergeSnapshotBackfillMobilePage', () => {
  it('keeps page order while appending new tasks', () => {
    const result = mergeSnapshotBackfillMobilePage(
      [item('a', 'failed')],
      [item('b', 'completed')],
    )
    expect(result.map(row => row.subtask_id)).toEqual(['a', 'b'])
  })

  it('deduplicates overlapping pages and applies the newest state', () => {
    const result = mergeSnapshotBackfillMobilePage(
      [item('a', 'failed'), item('b', 'failed')],
      [item('b', 'completed'), item('c', 'failed')],
    )
    expect(result.map(row => row.subtask_id)).toEqual(['a', 'b', 'c'])
    expect(result[1]?.status).toBe('completed')
  })
})
