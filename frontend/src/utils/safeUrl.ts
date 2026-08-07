const ALLOWED_PROTOCOLS = new Set(['http:', 'https:'])

/** 校验外部链接，仅允许 http/https，防止 javascript: 等注入。
 * 同源相对路径（如 /api/v1/media/shot/...）也会解析为当前站点绝对地址。
 */
export function safeExternalUrl(raw: string | null | undefined): string | null {
  const text = (raw || '').trim()
  if (!text) return null
  try {
    const url = new URL(text, window.location.origin)
    if (!ALLOWED_PROTOCOLS.has(url.protocol)) return null
    return url.href
  } catch {
    return null
  }
}

/** 快照代理/补录自截图路径不可当作补录「分享页 URL」回填。 */
export function isProxiedScreenshotUrl(raw: string | null | undefined): boolean {
  const text = (raw || '').trim()
  if (!text) return false
  return /\/api\/v1\/media\/(?:shot|backfill-shot)\//.test(text)
}
