export function formatFileSize(size: number) {
  if (size >= 1024 * 1024) return `${(size / 1024 / 1024).toFixed(1)}MB`
  if (size >= 1024) return `${(size / 1024).toFixed(1)}KB`
  return `${size}B`
}

export function formatDateTime(value?: string | null) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  const pad = (num: number) => String(num).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

/** 客户端展示：去掉具体调度时刻，只保留批次/日期语义 */
export function sanitizeCustomerScheduleLabel(value?: string | null, fallback = '监测批次') {
  const text = String(value || '').trim()
  if (!text) return fallback
  const cleaned = text
    .replace(/\d{1,2}:\d{2}(:\d{2})?/g, '')
    .replace(/[·•]\s*(每天|定时|固定|调度|计划).*/g, '')
    .replace(/\s{2,}/g, ' ')
    .replace(/[·•]\s*$/g, '')
    .trim()
  if (!cleaned || cleaned === '—' || cleaned === '-') return fallback
  return cleaned.replace(/^调度轮次[·•\s]*/i, '监测批次 · ')
}
