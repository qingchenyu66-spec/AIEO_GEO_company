import { ElMessage } from 'element-plus'

type ErrorDetailFormatter = (error: unknown) => string

export function isUserCancelled(error: unknown): boolean {
  return error === 'cancel' || error === 'close'
}

/** Axios / fetch AbortController 取消：不是业务失败，不应弹 toast。 */
export function isRequestCanceled(error: unknown): boolean {
  if (error == null || typeof error !== 'object') return false
  const e = error as {
    code?: string
    name?: string
    message?: string
    __CANCEL__?: boolean
  }
  if (e.__CANCEL__) return true
  if (e.code === 'ERR_CANCELED') return true
  if (e.name === 'CanceledError' || e.name === 'AbortError') return true
  const msg = String(e.message || '').toLowerCase()
  return msg === 'canceled' || msg === 'cancelled'
}

export function extractErrorDetail(error: unknown, fallback = '操作失败，请稍后重试'): string {
  const response = (error as { response?: { data?: { detail?: unknown }; status?: number } })?.response
  const detail = response?.data?.detail
  if (Array.isArray(detail)) {
    return detail
      .map((item: { msg?: string }) => item.msg || '')
      .filter(Boolean)
      .join('；') || fallback || '请求失败，请稍后重试'
  }
  if (typeof detail === 'string') return detail
  const status = response?.status
  if (status === 403) return '没有权限执行此操作'
  if (status === 404) return '请求的资源不存在'
  if (status && status >= 500) return '服务器错误，请联系管理员'
  return (error as Error)?.message || fallback
}

/** Page-level toast with operation context. Skips user-cancelled dialogs. */
export function notifyOperationError(
  error: unknown,
  context: string,
  formatDetail: ErrorDetailFormatter = extractErrorDetail,
) {
  if (isUserCancelled(error) || isRequestCanceled(error)) return
  if (import.meta.env.DEV && error) console.error(context, error)
  ElMessage.error(`${context}：${formatDetail(error)}`)
}
