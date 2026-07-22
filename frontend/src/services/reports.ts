import { http } from './http'

export type ReportExportFormat = 'pdf' | 'docx' | 'html'

export const HTML_TEMPLATE_REPORT_TYPES = ['weekly', 'monthly', 'quarterly', 'annual', 'diagnosis'] as const

export function isHtmlTemplateReportType(reportType: string | null | undefined) {
  return HTML_TEMPLATE_REPORT_TYPES.includes((reportType || '') as (typeof HTML_TEMPLATE_REPORT_TYPES)[number])
}

/** @deprecated 使用 isHtmlTemplateReportType */
export const PERIOD_HTML_REPORT_TYPES = ['weekly', 'monthly', 'quarterly', 'annual'] as const

export function isPeriodHtmlReportType(reportType: string | null | undefined) {
  return isHtmlTemplateReportType(reportType)
}

export function reportPreviewHtmlUrl(reportId: number) {
  return `/api/v1/reports/${reportId}/preview/html`
}

/** 带登录态拉取 HTML，供 iframe blob 预览（避免裸 src 未带 Cookie/鉴权时整页空白）。 */
export async function fetchReportPreviewHtml(reportId: number): Promise<string> {
  const response = await http.get(`/v1/reports/${reportId}/preview/html`, {
    responseType: 'text',
    timeout: 90000,
    headers: { Accept: 'text/html', 'Content-Type': undefined as unknown as string },
    transformResponse: [(data) => data],
  })
  const html = typeof response.data === 'string' ? response.data : String(response.data ?? '')
  if (!html || html.trimStart().startsWith('{')) {
    throw new Error('报告预览返回非 HTML，请重新登录后重试')
  }
  return html
}

export type ReportType = 'diagnosis' | 'weekly' | 'monthly' | 'quarterly' | 'annual' | 'comparison' | 'periodic'
export type ReportStatus = 'draft' | 'published' | 'archived'

export interface ReportListItem {
  id: number
  tenant_id: number
  tenant_name?: string | null
  report_title: string
  report_type: ReportType
  report_type_label?: string
  status: ReportStatus
  status_label?: string
  data_summary?: string | null
  health_score?: number | null
  mention_rate?: number | null
  avg_rank?: number | null
  report_url?: string | null
  ai_source?: 'deepseek' | 'rule' | null
  created_by?: number | null
  created_at: string
  updated_at: string
}

export interface ReportKpis {
  mention_rate?: number | null
  avg_rank?: number | null
  top3_rate?: number | null
  positive_rate?: number | null
  subtask_count?: number | null
  completed_count?: number | null
  source_count?: number | null
  task_count?: number | null
  health_score?: number | null
}

export interface ReportDiagnosisBlock {
  health_score?: number | null
  sentiment_summary?: string | null
  strength_points?: string | null
  weakness_points?: string | null
  recommendation?: string | null
  diagnosis_title?: string | null
}

export interface ReportPlatformStat {
  platform: string
  total: number
  completed: number
  mention_rate: number
  avg_rank?: number | null
}

export interface ReportSourceItem {
  title: string
  url: string
  count: number
  platforms: string[]
}

export interface ReportAiInsights {
  source?: 'deepseek' | 'rule'
  model?: string | null
  executive_summary?: string | null
  fallback_reason?: string | null
}

export interface ReportContent {
  brand_name?: string | null
  company_name?: string | null
  period_label?: string | null
  generated_at?: string | null
  kpis?: ReportKpis
  diagnosis?: ReportDiagnosisBlock
  ai_insights?: ReportAiInsights
  monitor_snapshot?: {
    sentiment_counts?: Record<string, number>
    platform_stats?: ReportPlatformStat[]
    top_sources?: ReportSourceItem[]
    highlights?: string[]
    competitor_count?: number
    platform_count?: number
  }
}

export interface ReportDetail extends ReportListItem {
  report_content?: ReportContent | null
}

export interface GenerateReportPayload {
  tenant_id?: number | null
  report_title?: string
  report_type?: ReportType
}

/** 运营端手动生成：仅品牌诊断报告 */
export const MANUAL_REPORT_TYPE_OPTIONS: Array<{ value: ReportType; label: string }> = [
  { value: 'diagnosis', label: '品牌诊断报告' },
]

/** @deprecated 使用 MANUAL_REPORT_TYPE_OPTIONS；保留兼容旧引用 */
export const REPORT_TYPE_OPTIONS = MANUAL_REPORT_TYPE_OPTIONS

export async function getReportList(params?: { tenant_id?: number; report_type?: string }): Promise<ReportListItem[]> {
  const response = await http.get('/v1/reports/list', { params })
  return response.data.data
}

export async function getReportDetail(reportId: number): Promise<ReportDetail> {
  const response = await http.get(`/v1/reports/${reportId}`)
  return response.data.data
}

export async function createReport(data: GenerateReportPayload): Promise<ReportListItem> {
  const response = await http.post('/v1/reports/generate', data)
  return response.data.data
}

export async function downloadReportExport(
  reportId: number,
  format: ReportExportFormat,
  onProgress?: (label: string, pct?: number | null) => void,
) {
  onProgress?.('内容写入中…', 0)
  const created = await http.post(`/v1/reports/${reportId}/export-jobs/${format}`, null, {
    timeout: 30000,
  })
  const job = created.data?.data || {}
  const jobId = String(job.job_id || '')
  if (!jobId) throw new Error('创建导出任务失败')

  let filename = String(job.filename || `report-${reportId}.${format}`)
  if (job.status === 'ready') {
    onProgress?.(format === 'pdf' ? 'PDF生成中…' : '生成中…', 100)
  } else {
    const started = Date.now()
    const maxWaitMs = 10 * 60 * 1000
    while (Date.now() - started < maxWaitMs) {
      const statusResp = await http.get(`/v1/reports/export-jobs/${jobId}`, { timeout: 30000 })
      const statusJob = statusResp.data?.data || {}
      const label = String(statusJob.progress || (format === 'pdf' ? 'PDF渲染中…' : '内容写入中…'))
      const pct = typeof statusJob.progress_pct === 'number' ? statusJob.progress_pct : undefined
      onProgress?.(label, pct)
      if (statusJob.filename) filename = String(statusJob.filename)
      if (statusJob.status === 'ready') break
      if (statusJob.status === 'failed') throw new Error(String(statusJob.error || '导出失败'))
      await new Promise(resolve => setTimeout(resolve, statusJob.cached ? 200 : 800))
    }
  }

  onProgress?.('开始下载…', 100)
  const link = document.createElement('a')
  link.href = `/api/v1/reports/export-jobs/${encodeURIComponent(jobId)}/download`
  link.rel = 'noopener'
  document.body.appendChild(link)
  link.click()
  link.remove()
  return filename
}
