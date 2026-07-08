import { http } from './http'

export type ReportExportFormat = 'pdf' | 'docx'

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

export interface UpdateReportPayload {
  report_title?: string
  data_summary?: string
  executive_summary?: string
  highlights?: string[] | string
  diagnosis?: Partial<ReportDiagnosisBlock>
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

export async function updateReport(reportId: number, data: UpdateReportPayload): Promise<ReportDetail> {
  const response = await http.put(`/v1/reports/${reportId}`, data)
  return response.data.data
}

export async function publishReport(reportId: number): Promise<ReportListItem> {
  const response = await http.post(`/v1/reports/${reportId}/publish`)
  return response.data.data
}

function parseExportFilename(contentDisposition: string | undefined, fallback: string) {
  if (!contentDisposition) return fallback
  const utfMatch = contentDisposition.match(/filename\*=UTF-8''([^;]+)/i)
  if (utfMatch?.[1]) {
    try {
      return decodeURIComponent(utfMatch[1])
    } catch {
      return utfMatch[1]
    }
  }
  const plainMatch = contentDisposition.match(/filename="?([^";]+)"?/i)
  return plainMatch?.[1] || fallback
}

export async function downloadReportExport(reportId: number, format: ReportExportFormat) {
  const response = await http.get(`/v1/reports/${reportId}/export/${format}`, {
    responseType: 'blob',
  })
  const fallback = `report-${reportId}.${format}`
  const filename = parseExportFilename(response.headers['content-disposition'], fallback)
  const blob = response.data instanceof Blob ? response.data : new Blob([response.data])
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}
