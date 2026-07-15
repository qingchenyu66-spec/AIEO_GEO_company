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

export type RankSource =
  | 'structured'
  | 'appearance'
  | 'api'
  | 'manual'
  | 'llm'
  | 'none'
  | 'exposure'
  | string

/** 排名解析来源（矩阵 tooltip / 详情抽屉） */
export function formatRankSourceLabel(source?: RankSource | null, category?: string | null) {
  const map: Record<string, string> = {
    structured: '分段/表格解析',
    appearance: '章节露出序',
    api: 'API 位次',
    manual: '人工补录',
    llm: 'AI 解析',
    none: '无排名',
    exposure: '曝光监测',
  }
  const label = map[String(source || '').trim()] || ''
  if (!label) return ''
  const section = String(category || '').trim()
  return section ? `${label} · ${section}` : label
}

export function formatExposureLabel(mentioned?: boolean | null) {
  return mentioned ? '已提及' : '未提及'
}

export interface MonitorRankDisplay {
  prompt_intent?: string | null
  mention_position?: number | null
  brand_mentioned?: boolean | null
  rank_source?: RankSource | null
  rank_category?: string | null
}

/** 快照补录卡片等指标区：列头已有「排名」时只展示数字 */
export function formatMonitorSubtaskRank(subtask: MonitorRankDisplay | null | undefined) {
  if (!subtask) return '-'
  if (subtask.prompt_intent === 'ranking') {
    return formatRank(subtask.mention_position)
  }
  return formatExposureLabel(subtask.brand_mentioned)
}

/** 实时监测详情抽屉：第 N 位 · 段名 / 已提及 / 未提及 */
export function formatMonitorSubtaskRankDetail(subtask: MonitorRankDisplay | null | undefined) {
  if (!subtask) return '—'
  if (subtask.prompt_intent === 'ranking') {
    const rank = formatRank(subtask.mention_position)
    if (rank === '-') return '—'
    const section = String(subtask.rank_category || '').trim()
    return section ? `第 ${rank} 位 · ${section}` : `第 ${rank} 位`
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

/** 客户报告中心：去掉标题中的企业名前缀（如「某某公司 · GEO 监测月报」） */
export function stripReportCompanyPrefix(
  title: string,
  names: Array<string | null | undefined> = [],
) {
  const text = (title || '').trim()
  if (!text) return text
  for (const name of names) {
    const company = (name || '').trim()
    if (!company) continue
    for (const sep of [' · ', '·', ' - ', '－']) {
      const prefix = `${company}${sep}`
      if (text.startsWith(prefix)) return text.slice(prefix.length).trim()
    }
  }
  return text
}

const DIAGNOSIS_COVER_TITLE = 'GEO企业诊断报告'
const TITLE_PAREN_MARKERS = ['（', ' (', '('] as const

function stripDiagnosisTitleSuffix(text: string): string {
  let cut = text.length
  for (const marker of TITLE_PAREN_MARKERS) {
    const pos = text.indexOf(marker)
    if (pos !== -1) cut = Math.min(cut, pos)
  }
  if (cut < text.length) {
    return text.slice(0, cut).trim()
  }
  return text
}

/** 报告中心展示用标题：诊断报告去掉括号内的周期/抓取说明（详情区单独展示）。 */
export function formatReportDisplayTitle(item: {
  report_title: string
  report_type?: string | null
  tenant_name?: string | null
}) {
  let text = stripReportCompanyPrefix(item.report_title, [item.tenant_name])
  if (item.report_type === 'diagnosis') {
    text = stripDiagnosisTitleSuffix(text) || DIAGNOSIS_COVER_TITLE
  }
  return text || item.report_title.trim()
}

export { safeExternalUrl as externalLink } from '../../utils/safeUrl'
