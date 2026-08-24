import { http } from './http'

export type LeadDiagnosisStatus = 'pending' | 'collecting' | 'ready' | 'failed' | 'canceled'

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

export interface LeadContext {
  website_url?: string
  industry?: string
  product_focus?: string
  purchase_scenario?: string
  source?: string
}

export interface LeadDiagnosisItem {
  id: number
  brand_name: string
  contact_name?: string | null
  contact_phone?: string | null
  contact_note?: string | null
  lead_context?: LeadContext | null
  brand_aliases?: string[]
  prompts: string[]
  competitors: string[]
  platforms?: string[]
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
  brand_aliases?: string[]
  platforms: string[]
  region_codes?: string[]
  contact_name?: string
  contact_phone?: string
  contact_note?: string
  lead_context?: LeadContext
  diagnosis_date?: string
  schedule_days?: number
  start_immediately?: boolean
}

export async function getLeadDiagnosisList(params?: { keyword?: string; status?: string }): Promise<LeadDiagnosisItem[]> {
  const response = await http.get('/v1/lead-diagnosis/list', { params })
  return response.data.data
}

export async function getLeadDiagnosisDetail(leadId: number): Promise<LeadDiagnosisDetail> {
  const response = await http.get(`/v1/lead-diagnosis/${leadId}`)
  return response.data.data
}

export async function createLeadDiagnosis(
  payload: CreateLeadDiagnosisPayload,
): Promise<LeadDiagnosisDetail | (import('./approvals').OperationApproval & { pending_approval: true })> {
  const response = await http.post('/v1/lead-diagnosis', payload)
  return response.data.data
}

export async function cancelLeadDiagnosis(leadId: number): Promise<LeadDiagnosisDetail> {
  const response = await http.post(`/v1/lead-diagnosis/${leadId}/cancel`)
  return response.data.data
}

export async function finalizeLeadDiagnosisEarly(leadId: number): Promise<LeadDiagnosisDetail> {
  const response = await http.post(`/v1/lead-diagnosis/${leadId}/finalize-early`)
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

export async function fetchLeadDiagnosisPreviewHtml(leadId: number): Promise<string> {
  // 2026-08-12 - 售前详情驾驶舱 iframe - 带鉴权拉 HTML，避免裸 src 空白
  const response = await http.get(`/v1/lead-diagnosis/${leadId}/preview/html`, {
    responseType: 'text',
    timeout: 90000,
    headers: { Accept: 'text/html', 'Content-Type': undefined as unknown as string },
    transformResponse: [(data) => data],
  })
  const html = typeof response.data === 'string' ? response.data : String(response.data ?? '')
  if (!html || html.trimStart().startsWith('{')) {
    throw new Error('诊断预览返回非 HTML，请重新登录后重试')
  }
  return html
}

export async function downloadLeadDiagnosisExport(
  leadId: number,
  format: 'html' = 'html',
  onProgress?: (label: string, pct?: number | null) => void,
) {
  // 异步任务 + 轮询；就绪后走浏览器原生下载（避免 XHR 整包进内存干等）
  onProgress?.('内容写入中…', 0)
  const created = await http.post(`/v1/lead-diagnosis/${leadId}/export-jobs`, null, {
    params: { format },
    timeout: 30000,
  })
  const job = created.data?.data || {}
  const jobId = String(job.job_id || '')
  if (!jobId) throw new Error('创建导出任务失败')

  let filename = String(job.filename || `lead-diagnosis-${leadId}.${format}`)
  if (job.status === 'ready') {
    onProgress?.('生成中…', 100)
  } else {
    const started = Date.now()
    const maxWaitMs = 10 * 60 * 1000
    while (Date.now() - started < maxWaitMs) {
      const statusResp = await http.get(`/v1/lead-diagnosis/export-jobs/${jobId}`, { timeout: 30000 })
      const statusJob = statusResp.data?.data || {}
      const label = String(statusJob.progress || '内容写入中…')
      const pct = typeof statusJob.progress_pct === 'number' ? statusJob.progress_pct : undefined
      onProgress?.(label, pct)
      if (statusJob.filename) filename = String(statusJob.filename)
      if (statusJob.status === 'ready') break
      if (statusJob.status === 'failed') throw new Error(String(statusJob.error || '导出失败'))
      await new Promise(resolve => setTimeout(resolve, statusJob.cached ? 200 : 800))
    }
  }

  onProgress?.('开始下载…', 100)
  const anchor = document.createElement('a')
  anchor.href = `/api/v1/lead-diagnosis/export-jobs/${encodeURIComponent(jobId)}/download`
  anchor.rel = 'noopener'
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  return filename
}

export const LEAD_STATUS_LABELS: Record<LeadDiagnosisStatus, string> = {
  pending: '待抓取',
  collecting: '抓取中',
  ready: '已完成',
  failed: '失败',
  canceled: '已取消',
}
