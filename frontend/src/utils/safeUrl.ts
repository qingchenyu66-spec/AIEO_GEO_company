const ALLOWED_PROTOCOLS = new Set(['http:', 'https:'])

/** 校验外部链接，仅允许 http/https，防止 javascript: 等注入。 */
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
