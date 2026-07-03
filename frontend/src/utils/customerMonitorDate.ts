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

export function isBeforeCustomerCutoff(isoTime: string | null | undefined, date = new Date()) {
  if (!isoTime) return false
  const cutoffEnd = new Date(`${customerDisplayCutoffDate(date)}T23:59:59.999`)
  return new Date(isoTime).getTime() <= cutoffEnd.getTime()
}
