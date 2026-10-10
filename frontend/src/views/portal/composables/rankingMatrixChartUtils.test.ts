import { describe, expect, it } from 'vitest'

import type { RankingMatrixRow } from '../../../services/monitor'
import { buildMatrixHeatOption, matrixHeatDayKeys } from './rankingMatrixChartUtils'

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

describe('buildMatrixHeatOption long ranges', () => {
  it('keeps every day but opens a readable 31-day window with a time slider', () => {
    const rows = Array.from({ length: 101 }, (_, index) => {
      const value = new Date(Date.UTC(2026, 6, 1 + index)).toISOString().slice(0, 10)
      return row(value)
    })
    const built = buildMatrixHeatOption({
      platform: 'doubao',
      columns: [{ prompt: '测试监测词', group_name: null, monitor_keyword: '测试监测词' }],
      rows,
    }, { startDate: '2026-01-01', endDate: '2026-10-10' })
    const option = built.option as {
      xAxis: { data: string[] }
      dataZoom?: Array<{ startValue: number; endValue: number }>
      series: Array<{ label: { show: boolean } }>
    }

    expect(option.xAxis.data).toHaveLength(101)
    expect(option.dataZoom).toHaveLength(2)
    expect(option.dataZoom?.[0]).toMatchObject({ startValue: 70, endValue: 100 })
    expect(option.series[0]?.label.show).toBe(false)
    expect(built.gridBottom).toBe(52)
  })
})
