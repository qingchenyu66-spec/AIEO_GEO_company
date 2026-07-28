/** 客户侧监测展示：截至昨日（含）的全部历史，不含今日。 */

function formatLocalDate(date: Date) {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

export function yesterdayDateString(date = new Date()) {
  const copy = new Date(date)
  copy.setDate(copy.getDate() - 1)
  return formatLocalDate(copy)
}

export function todayDateString(date = new Date()) {
  return formatLocalDate(date)
}

export function customerDisplayCutoffDate(date = new Date()) {
  return yesterdayDateString(date)
}

export function customerDisplayDateRange(lookbackDays = 7, date = new Date()) {
  const endDate = customerDisplayCutoffDate(date)
  const start = new Date(`${endDate}T00:00:00`)
  start.setDate(start.getDate() - (lookbackDays - 1))
  return {
    startDate: formatLocalDate(start),
    endDate,
  }
}

/** @deprecated 请使用 customerDisplayDateRange */
export function yesterdayDateRange(date = new Date()) {
  return customerDisplayDateRange(1, date)
}

export function todayScheduleKey(date = new Date()) {
  return todayDateString(date).replace(/-/g, '')
}

export function monitorTaskBeforeToday(task: {
  schedule_key?: string | null
  schedule_window_key?: string | null
  created_at?: string | null
}) {
  const key = String(task.schedule_window_key || task.schedule_key || '').split('-kw')[0]
  const todayKey = todayScheduleKey()
  if (/^\d{8}/.test(key)) {
    return key.slice(0, 8) !== todayKey
  }
  const created = String(task.created_at || '').slice(0, 10).replace(/-/g, '')
  return created !== todayKey
}

export function customerDisplayPeriodLabel() {
  return `数据截至 ${customerDisplayCutoffDate()}`
}

export function customerTrendPeriodLabel(lookbackDays = 7, date = new Date()) {
  const { startDate, endDate } = customerDisplayDateRange(lookbackDays, date)
  return `近${lookbackDays}日 ${startDate} ~ ${endDate}`
}

export type WorkspaceTrendPreset = '7d' | 'month' | 'quarter' | 'year' | 'custom'

export function workspaceTrendDateRange(
  preset: WorkspaceTrendPreset,
  customStart?: string,
  customEnd?: string,
  date = new Date(),
) {
  const endDate = customerDisplayCutoffDate(date)
  const end = new Date(`${endDate}T00:00:00`)

  if (preset === '7d') {
    return customerDisplayDateRange(7, date)
  }
  if (preset === 'month') {
    const start = new Date(end.getFullYear(), end.getMonth(), 1)
    return { startDate: formatLocalDate(start), endDate }
  }
  if (preset === 'quarter') {
    const quarterStartMonth = Math.floor(end.getMonth() / 3) * 3
    const start = new Date(end.getFullYear(), quarterStartMonth, 1)
    return { startDate: formatLocalDate(start), endDate }
  }
  if (preset === 'year') {
    const start = new Date(end.getFullYear(), 0, 1)
    return { startDate: formatLocalDate(start), endDate }
  }
  return {
    startDate: customStart || customerDisplayDateRange(7, date).startDate,
    endDate: customEnd || endDate,
  }
}

export function formatCompactDateRange(startDate: string, endDate: string) {
  if (!startDate || !endDate) return ''
  if (startDate === endDate) return startDate.slice(5)
  const [sy, sm, sd] = startDate.split('-')
  const [ey, em, ed] = endDate.split('-')
  if (sy === ey) return `${sm}-${sd} ~ ${em}-${ed}`
  return `${startDate} ~ ${endDate}`
}

export function workspaceTrendPeriodLabel(
  preset: WorkspaceTrendPreset,
  startDate: string,
  endDate: string,
) {
  const range = formatCompactDateRange(startDate, endDate)
  const names: Record<WorkspaceTrendPreset, string> = {
    '7d': '近7日',
    month: '本月',
    quarter: '本季',
    year: '本年',
    custom: '自定义',
  }
  const name = names[preset] || ''
  // 2026-07-28 - 切周期无体感 - 标签带预设名，避免只看热力误以为没切
  if (!range) return name
  return name ? `${name} ${range}` : range
}

/** 与当前筛选等长的上一期：近7天→再往前7天；本月→上月同期；本季/本年同理；自定义→紧邻前一段。 */
export function workspacePreviousPeriodRange(
  preset: WorkspaceTrendPreset,
  startDate: string,
  endDate: string,
): { startDate: string; endDate: string } | null {
  const start = new Date(`${startDate}T00:00:00`)
  const end = new Date(`${endDate}T00:00:00`)
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime()) || start > end) return null

  if (preset === '7d' || preset === 'custom') {
    const days = Math.round((end.getTime() - start.getTime()) / 86400000) + 1
    const prevEnd = new Date(start)
    prevEnd.setDate(prevEnd.getDate() - 1)
    const prevStart = new Date(prevEnd)
    prevStart.setDate(prevStart.getDate() - (days - 1))
    return { startDate: formatLocalDate(prevStart), endDate: formatLocalDate(prevEnd) }
  }

  if (preset === 'month') {
    const prevMonthLast = new Date(start.getFullYear(), start.getMonth(), 0)
    const prevEndDay = Math.min(end.getDate(), prevMonthLast.getDate())
    const prevEnd = new Date(prevMonthLast.getFullYear(), prevMonthLast.getMonth(), prevEndDay)
    const prevStart = new Date(prevEnd.getFullYear(), prevEnd.getMonth(), 1)
    return { startDate: formatLocalDate(prevStart), endDate: formatLocalDate(prevEnd) }
  }

  if (preset === 'quarter') {
    const qStartMonth = Math.floor(start.getMonth() / 3) * 3
    const thisQStart = new Date(start.getFullYear(), qStartMonth, 1)
    const prevQEnd = new Date(thisQStart)
    prevQEnd.setDate(0)
    const prevQStartMonth = Math.floor(prevQEnd.getMonth() / 3) * 3
    const prevQStart = new Date(prevQEnd.getFullYear(), prevQStartMonth, 1)
    // 与本期相同的「季初 → 相对截止日」对齐
    const dayOffset = Math.round((end.getTime() - thisQStart.getTime()) / 86400000)
    const alignedEnd = new Date(prevQStart)
    alignedEnd.setDate(alignedEnd.getDate() + dayOffset)
    const endClamped = alignedEnd > prevQEnd ? prevQEnd : alignedEnd
    return { startDate: formatLocalDate(prevQStart), endDate: formatLocalDate(endClamped) }
  }

  if (preset === 'year') {
    const y = start.getFullYear() - 1
    const prevStart = new Date(y, 0, 1)
    const prevEnd = new Date(y, end.getMonth(), end.getDate())
    // 闰日等边界：若上一年没有该日，退到月末
    if (prevEnd.getMonth() !== end.getMonth()) {
      prevEnd.setDate(0)
    }
    return { startDate: formatLocalDate(prevStart), endDate: formatLocalDate(prevEnd) }
  }

  return null
}

export function workspacePeriodCompareLabel(preset: WorkspaceTrendPreset) {
  if (preset === '7d') return '较上周'
  if (preset === 'month') return '较上月'
  if (preset === 'quarter') return '较上季'
  if (preset === 'year') return '较上年'
  return '较上期'
}

export function isBeforeCustomerCutoff(isoTime: string | null | undefined, date = new Date()) {
  if (!isoTime) return false
  const cutoffEnd = new Date(`${customerDisplayCutoffDate(date)}T23:59:59.999`)
  return new Date(isoTime).getTime() <= cutoffEnd.getTime()
}
