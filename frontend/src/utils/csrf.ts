/** 从 document.cookie 读取 CSRF token（双提交 Cookie 模式）。 */
export function readCsrfToken(): string | null {
  if (typeof document === 'undefined') return null
  const match = document.cookie.match(/(?:^|;\s*)geo_csrf_token=([^;]+)/)
  return match ? decodeURIComponent(match[1]) : null
}
