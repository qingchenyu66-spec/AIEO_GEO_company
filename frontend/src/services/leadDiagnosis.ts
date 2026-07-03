import { http } from './http'

export type LeadDiagnosisStatus = 'pending' | 'collecting' | 'ready' | 'failed'

export interface LeadDiagnosisRun {
  id: number
  schedule_key: string
  schedule_label: string
  task_id?: string | null
  status: string
  prompt_count: number
  platform_count: number
  error_message?: string | null
  created_at: string
  updated_at: string
}

export interface LeadDiagnosisItem {
  id: number
  brand_name: string
  contact_name?: string | null
  contact_phone?: string | null
  contact_note?: string | null
  prompts: string[]
  competitors: string[]
  region_code?: string | null
  schedule_times: string[]
  schedule_days?: number
  schedule_total_count?: number
  diagnosis_date: string
  status: LeadDiagnosisStatus
  health_score?: number | null
  mention_rate?: number | null
  avg_rank?: number | null
  run_count: number
  completed_run_count: number
  created_at: string
  updated_at: string
}

export interface LeadDiagnosisDetail extends LeadDiagnosisItem {
  diagnosis_result?: Record<string, unknown> | null
  runs?: LeadDiagnosisRun[]
}

export interface CreateLeadDiagnosisPayload {
  brand_name: string
  prompts: string[]
  competitors?: string[]
  region_code?: string | null
  contact_name?: string
  contact_phone?: string
  contact_note?: string
  diagnosis_date?: string
  start_immediately?: boolean
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

export async function getLeadDiagnosisList(params?: { keyword?: string; status?: string }): Promise<LeadDiagnosisItem[]> {
  const response = await http.get('/v1/lead-diagnosis/list', { params })
  return response.data.data
}

export async function getLeadDiagnosisDetail(leadId: number): Promise<LeadDiagnosisDetail> {
  const response = await http.get(`/v1/lead-diagnosis/${leadId}`)
  return response.data.data
}

export async function createLeadDiagnosis(payload: CreateLeadDiagnosisPayload): Promise<LeadDiagnosisDetail> {
  const response = await http.post('/v1/lead-diagnosis', payload)
  return response.data.data
}

export async function refreshLeadDiagnosis(leadId: number): Promise<LeadDiagnosisDetail> {
  const response = await http.post(`/v1/lead-diagnosis/${leadId}/refresh`)
  return response.data.data
}

export async function submitLeadDiagnosisRun(leadId: number, force = false): Promise<Record<string, unknown>> {
  const response = await http.post(`/v1/lead-diagnosis/${leadId}/submit-run`, null, { params: { force } })
  return response.data.data
}

export async function downloadLeadDiagnosisExport(leadId: number, format: 'pdf' | 'docx' = 'pdf') {
  const response = await http.get(`/v1/lead-diagnosis/${leadId}/export`, {
    params: { format },
    responseType: 'blob',
  })
  const fallback = `lead-diagnosis-${leadId}.${format}`
  const filename = parseExportFilename(response.headers['content-disposition'], fallback)
  const contentType = String(response.headers['content-type'] || 'application/octet-stream')
  const blob = new Blob([response.data], { type: contentType })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  URL.revokeObjectURL(url)
  return filename
}

export const LEAD_STATUS_LABELS: Record<LeadDiagnosisStatus, string> = {
  pending: '待抓取',
  collecting: '抓取中',
  ready: '已完成',
  failed: '失败',
}
