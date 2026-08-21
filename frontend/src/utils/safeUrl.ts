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

/** 快照图（代理路径 / 模力 CDN / 常见图片后缀）不可当作补录「分享页 URL」回填。 */
export function isProxiedScreenshotUrl(raw: string | null | undefined): boolean {
  const text = (raw || '').trim()
  if (!text) return false
  if (/\/api\/v1\/media\/(?:shot|backfill-shot)\//.test(text)) return true
  const low = text.toLowerCase()
  // 2026-08-21 - 模力截图 CDN 曾被预填进分享链接，提交走解析失败或清空后误报无快照
  if (low.includes('img.molizhishu')) return true
  return /\.(png|jpe?g|webp|gif)(\?|#|$)/i.test(text)
}
