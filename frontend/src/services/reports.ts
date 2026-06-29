import { http } from './http'

export interface ReportListItem {
  id: number
  tenant_id: number | null
  tenant_name: string
  report_title: string
  report_type: 'diagnosis' | 'weekly' | 'monthly' | 'custom'
  status: 'draft' | 'generated' | 'published'
  health_score: number | null
  mention_rate: number | null
  avg_rank: number | null
  created_at: string
  updated_at: string
}

export interface GenerateReportPayload {
  tenant_id?: number | null
  report_title: string
  report_type: string
  diagnosis_id?: number | null
  include_competitor?: boolean
  include_sentiment?: boolean
  include_sources?: boolean
  platforms?: string[]
}

export async function getReportList(params?: { tenant_id?: number; report_type?: string }): Promise<ReportListItem[]> {
  const response = await http.get('/v1/reports/list', { params })
  return response.data.data
}

export async function createReport(data: GenerateReportPayload): Promise<ReportListItem> {
  const response = await http.post('/v1/reports/generate', data)
  return response.data.data
}
