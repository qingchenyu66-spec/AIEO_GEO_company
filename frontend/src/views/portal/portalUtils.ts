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

/** 与实时监测矩阵/列表一致的排名数字展示 */
export function formatRank(value: number | null | undefined) {
  if (value === null || value === undefined) return '-'
  return Number.isInteger(value) ? String(value) : value.toFixed(1)
}

export function formatExposureLabel(mentioned?: boolean | null) {
  return mentioned ? '已提及' : '未提及'
}

export interface MonitorRankDisplay {
  prompt_intent?: string | null
  mention_position?: number | null
  brand_mentioned?: boolean | null
}

/** 快照补录卡片等指标区：列头已有「排名」时只展示数字 */
export function formatMonitorSubtaskRank(subtask: MonitorRankDisplay | null | undefined) {
  if (!subtask) return '-'
  if (subtask.prompt_intent === 'ranking') {
    return formatRank(subtask.mention_position)
  }
  return formatExposureLabel(subtask.brand_mentioned)
}

/** 实时监测详情抽屉：第 N 位 / 已提及 / 未提及 */
export function formatMonitorSubtaskRankDetail(subtask: MonitorRankDisplay | null | undefined) {
  if (!subtask) return '—'
  if (subtask.prompt_intent === 'ranking') {
    const rank = formatRank(subtask.mention_position)
    return rank === '-' ? '—' : `第 ${rank} 位`
  }
  return formatExposureLabel(subtask.brand_mentioned)
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
