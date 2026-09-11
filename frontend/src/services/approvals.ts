import { http } from './http'

export interface ApprovalChangeItem {
  field: string
  kind: 'add' | 'update' | 'delete' | 'info' | string
  before?: string
  after?: string
  before_image_url?: string
  after_image_url?: string
}

export interface ApprovalPreview {
  changes: ApprovalChangeItem[]
  change_count: number
}

export interface OperationApproval {
  id: number
  operation_key: string
  module: string
  module_label: string
  action: string
  action_label: string
  summary: string
  tenant_id?: number | null
  tenant_name?: string | null
  target_id?: number | null
  payload?: Record<string, unknown>
  lead_original_body?: Record<string, unknown> | null
  lead_adopted_body?: Record<string, unknown> | null
  preview?: ApprovalPreview
  status: 'pending' | 'approved' | 'rejected'
  status_label: string
  requester_user_id: number
  requester_name?: string | null
  reviewer_user_id?: number | null
  reviewer_name?: string | null
  review_comment?: string | null
  reviewed_at?: string | null
  resubmit_count?: number
  rejection_history?: Array<Record<string, unknown>>
  resubmitted?: boolean
  created_at: string
  pending_approval?: boolean
  duplicate_merged?: boolean
  message?: string
}

export function isPendingApproval(data: unknown): data is OperationApproval & { pending_approval: true } {
  return Boolean(data && typeof data === 'object' && (data as OperationApproval).pending_approval)
}

/** 销售提交审批后的提示文案；重复提交会合并到原待审单。 */
export function pendingApprovalMessage(data: OperationApproval, fallback: string): string {
  return data.message || fallback
}

export function isDuplicateMergedApproval(data: OperationApproval): boolean {
  return Boolean(data.duplicate_merged)
}

export function isResubmittedApproval(data: OperationApproval): boolean {
  return Boolean(data.resubmitted)
}

export async function getApproval(approvalId: number): Promise<OperationApproval> {
  const response = await http.get(`/v1/approvals/${approvalId}`)
  return response.data.data
}

export async function resubmitApproval(
  approvalId: number,
  payload: { body: Record<string, unknown> },
): Promise<OperationApproval> {
  const response = await http.post(`/v1/approvals/${approvalId}/resubmit`, payload)
  return response.data.data
}

/** 驳回单跳回原业务表单预填修改。 */
export function resubmitTargetForApproval(row: OperationApproval): { menu: string; query: Record<string, string> } | null {
  const id = String(row.id)
  if (row.operation_key === 'lead_diagnosis.create') {
    return { menu: 'platform.lead_diagnosis', query: { resubmit_approval_id: id } }
  }
  if (row.operation_key === 'management.tenant.create') {
    return { menu: 'platform.audit', query: { resubmit_approval_id: id } }
  }
  if (row.operation_key === 'brand.asset.upsert') {
    const query: Record<string, string> = { resubmit_approval_id: id }
    if (row.tenant_id) query.tenant_id = String(row.tenant_id)
    return { menu: 'platform.audit', query }
  }
  return null
}

export async function getPendingApprovalCount(): Promise<number> {
  const response = await http.get('/v1/approvals/pending-count')
  return Number(response.data.data?.count ?? 0)
}

export type ApprovalListResult = {
  items: OperationApproval[]
  total: number
  page: number
  page_size: number
}

export async function listApprovals(params?: {
  status?: string
  mine_only?: boolean
  page?: number
  page_size?: number
}): Promise<ApprovalListResult> {
  const response = await http.get('/v1/approvals', { params })
  const data = response.data.data
  // 兼容旧版直接返回数组的响应
  if (Array.isArray(data)) {
    return { items: data, total: data.length, page: 1, page_size: data.length || 20 }
  }
  return {
    items: Array.isArray(data?.items) ? data.items : [],
    total: Number(data?.total ?? 0),
    page: Number(data?.page ?? 1),
    page_size: Number(data?.page_size ?? 20),
  }
}

export async function reviseLeadDiagnosisApproval(
  approvalId: number,
  body: {
    competitors?: string[]
    platforms?: string[]
    region_codes?: string[]
    schedule_datetimes?: string[]
    prompts?: string[]
    contact_note?: string | null
  },
): Promise<OperationApproval> {
  const response = await http.post(`/v1/approvals/${approvalId}/revise-lead-diagnosis`, body)
  return response.data.data
}

export async function approveOperation(approvalId: number, comment?: string): Promise<OperationApproval> {
  const response = await http.post(`/v1/approvals/${approvalId}/approve`, comment ? { comment } : {})
  return response.data.data
}

export async function rejectOperation(approvalId: number, comment?: string): Promise<OperationApproval> {
  const response = await http.post(`/v1/approvals/${approvalId}/reject`, comment ? { comment } : {})
  return response.data.data
}
