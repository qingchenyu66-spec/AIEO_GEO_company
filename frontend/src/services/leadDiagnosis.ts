import { http } from './http'
import type { GeoHttpRequestConfig } from './http'

export type LeadDiagnosisStatus = 'pending' | 'collecting' | 'ready' | 'failed'

export interface LeadDiagnosisCreator {
  user_id: number
  display_name: string
  username?: string | null
}

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

export interface LeadDiagnosisSchedulePlanItem {
  day: string
  slot: string
  schedule_key: string
  schedule_label: string
  region_code?: string | null
}

export interface LeadDiagnosisItem {
  id: number
  brand_name: string
  contact_name?: string | null
  contact_phone?: string | null
  contact_note?: string | null
  prompts: string[]
  competitors: string[]
  region_codes?: string[]
  schedule_times: string[]
  schedule_days?: number
  schedule_calendar_days?: number
  plan_end_date?: string
  schedule_total_count?: number
  diagnosis_date: string
  status: LeadDiagnosisStatus
  health_score?: number | null
  mention_rate?: number | null
  avg_rank?: number | null
  run_count: number
  completed_run_count: number
  created_by_user_id?: number | null
  creator?: LeadDiagnosisCreator | null
  created_at: string
  updated_at: string
}

export interface LeadDiagnosisDetail extends LeadDiagnosisItem {
  diagnosis_result?: Record<string, unknown> | null
  runs?: LeadDiagnosisRun[]
  schedule_plan?: LeadDiagnosisSchedulePlanItem[]
}

export interface CreateLeadDiagnosisPayload {
  brand_name: string
  prompts: string[]
  competitors?: string[]
  region_codes?: string[]
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

export async function submitLeadDiagnosisRun(
  leadId: number,
  options: { force?: boolean; scheduleKey?: string } = {},
): Promise<Record<string, unknown>> {
  const response = await http.post(`/v1/lead-diagnosis/${leadId}/submit-run`, null, {
    params: {
      force: options.force ?? false,
      schedule_key: options.scheduleKey,
    },
  })
  return response.data.data
}

export async function downloadLeadDiagnosisExport(
  leadId: number,
  format: 'pdf' | 'docx' | 'html' = 'pdf',
  onProgress?: (label: string, pct?: number | null) => void,
) {
  // 方案 B：异步任务 + 轮询下载（避免长连接卡死）
  onProgress?.('内容写入中…', 0)
  const created = await http.post(`/v1/lead-diagnosis/${leadId}/export-jobs`, null, {
    params: { format },
    timeout: 30000,
  })
  const job = created.data?.data || {}
  const jobId = String(job.job_id || '')
  if (!jobId) throw new Error('创建导出任务失败')

  if (job.status === 'ready') {
    onProgress?.(format === 'pdf' ? 'PDF生成中…' : '生成中…', 100)
  } else {
    const started = Date.now()
    const maxWaitMs = 10 * 60 * 1000
    while (Date.now() - started < maxWaitMs) {
      const statusResp = await http.get(`/v1/lead-diagnosis/export-jobs/${jobId}`, { timeout: 30000 })
      const statusJob = statusResp.data?.data || {}
      const label = String(statusJob.progress || (format === 'pdf' ? 'PDF渲染中…' : '内容写入中…'))
      const pct = typeof statusJob.progress_pct === 'number' ? statusJob.progress_pct : undefined
      onProgress?.(label, pct)
      if (statusJob.status === 'ready') break
      if (statusJob.status === 'failed') throw new Error(String(statusJob.error || '导出失败'))
      await new Promise(resolve => setTimeout(resolve, statusJob.cached ? 200 : 800))
    }
  }

  onProgress?.(format === 'pdf' ? 'PDF生成中…' : '生成中…', 100)
  // 模力风格 PDF 可达数十 MB；nginx/前端需 ≥ 数分钟，409 多为多 worker 瞬时态再试
  const EXPORT_DOWNLOAD_TIMEOUT_MS = 600_000
  let response
  let lastError: unknown
  for (let attempt = 0; attempt < 4; attempt++) {
    try {
      response = await http.get(`/v1/lead-diagnosis/export-jobs/${jobId}/download`, {
        responseType: 'blob',
        timeout: EXPORT_DOWNLOAD_TIMEOUT_MS,
        silentError: attempt < 3,
      } as GeoHttpRequestConfig)
      lastError = undefined
      break
    } catch (error: unknown) {
      lastError = error
      const status = (error as { response?: { status?: number } })?.response?.status
      if (status === 409 && attempt < 3) {
        await new Promise(resolve => setTimeout(resolve, 400 * (attempt + 1)))
        continue
      }
      throw error
    }
  }
  if (!response) throw lastError instanceof Error ? lastError : new Error('导出下载失败')
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
