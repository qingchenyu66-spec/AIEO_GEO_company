import { describe, expect, it } from 'vitest'

import type { RankingMatrixRow } from '../../../services/monitor'
import { matrixHeatDayKeys } from './rankingMatrixChartUtils'

function row(dayKey: string): RankingMatrixRow {
  return {
    task_id: `task-${dayKey}`,
    platform: 'doubao',
    day_key: dayKey,
    schedule_window_key: dayKey,
    schedule_label: dayKey.slice(5),
    snapshot_at: dayKey,
    cells: {},
  }
}

describe('matrixHeatDayKeys', () => {
  it('fills missing calendar days for a short selected range', () => {
    expect(matrixHeatDayKeys(
      [row('2026-10-01'), row('2026-10-03')],
      { startDate: '2026-10-01', endDate: '2026-10-03' },
    )).toEqual(['2026-10-01', '2026-10-02', '2026-10-03'])
  })

  it('uses actual monitoring days across a long selected range instead of truncating at the range start', () => {
    expect(matrixHeatDayKeys(
      [row('2026-01-01'), row('2026-06-15'), row('2026-10-10')],
      { startDate: '2026-01-01', endDate: '2026-10-10' },
    )).toEqual(['2026-01-01', '2026-06-15', '2026-10-10'])
  })

  it('keeps long-range data outside the selected range off the axis', () => {
    expect(matrixHeatDayKeys(
      [row('2025-12-31'), row('2026-03-20'), row('2026-11-01')],
      { startDate: '2026-01-01', endDate: '2026-10-10' },
    )).toEqual(['2026-03-20'])
  })
})
