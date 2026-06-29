import { ElMessage } from 'element-plus'

type ErrorDetailFormatter = (error: unknown) => string

export function isUserCancelled(error: unknown): boolean {
  return error === 'cancel' || error === 'close'
}

export function extractErrorDetail(error: unknown): string {
  const response = (error as { response?: { data?: { detail?: unknown }; status?: number } })?.response
  const detail = response?.data?.detail
  if (Array.isArray(detail)) {
    return detail
      .map((item: { msg?: string }) => item.msg || '')
      .filter(Boolean)
      .join('；') || '请求失败，请稍后重试'
  }
  if (typeof detail === 'string') return detail
  const status = response?.status
  if (status === 403) return '没有权限执行此操作'
  if (status === 404) return '请求的资源不存在'
  if (status && status >= 500) return '服务器错误，请联系管理员'
  return (error as Error)?.message || '操作失败，请稍后重试'
}

/** Page-level toast with operation context. Skips user-cancelled dialogs. */
export function notifyOperationError(
  error: unknown,
  context: string,
  formatDetail: ErrorDetailFormatter = extractErrorDetail,
) {
  if (isUserCancelled(error)) return
  if (import.meta.env.DEV && error) console.error(context, error)
  ElMessage.error(`${context}：${formatDetail(error)}`)
}
