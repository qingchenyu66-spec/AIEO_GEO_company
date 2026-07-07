import { http } from './http'

export interface ApprovalChangeItem {
  field: string
  kind: 'add' | 'update' | 'delete' | 'info' | string
  before?: string
  after?: string
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
  preview?: ApprovalPreview
  status: 'pending' | 'approved' | 'rejected'
  status_label: string
  requester_user_id: number
  requester_name?: string | null
  reviewer_user_id?: number | null
  reviewer_name?: string | null
  review_comment?: string | null
  reviewed_at?: string | null
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

export async function getPendingApprovalCount(): Promise<number> {
  const response = await http.get('/v1/approvals/pending-count')
  return Number(response.data.data?.count ?? 0)
}

export async function listApprovals(params?: { status?: string; mine_only?: boolean }): Promise<OperationApproval[]> {
  const response = await http.get('/v1/approvals', { params })
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
