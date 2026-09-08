/** 设置页签 / 书签图标（登录页与门户共用）。 */
export const DEFAULT_FAVICON = '/logo-icon-32.png'

export function applyDocumentFavicon(href: string) {
  let link = document.querySelector<HTMLLinkElement>("link[rel='icon']")
  if (!link) {
    link = document.createElement('link')
    link.rel = 'icon'
    document.head.appendChild(link)
  }
  link.type = 'image/png'
  link.href = href
}

/**
 * 登录页也要跟平台默认 Logo：进应用就拉公开 meta，有自定义则换 favicon。
 * 用 fetch 避开 http 拦截器的全局 loading / 401 踢登录。
 */
export async function applyPlatformFaviconFromServer(): Promise<void> {
  try {
    const res = await fetch('/api/v1/management/platform-brand/logo/meta', {
      credentials: 'include',
      headers: { Accept: 'application/json' },
    })
    if (!res.ok) return
    const body = (await res.json()) as {
      data?: { has_logo?: boolean; logo_updated_at?: string | null }
    }
    const meta = body?.data
    if (!meta?.has_logo) return
    const v = meta.logo_updated_at ? `?v=${encodeURIComponent(meta.logo_updated_at)}` : ''
    applyDocumentFavicon(`/api/v1/management/platform-brand/logo${v}`)
  } catch {
    // 失败保持 index.html 内置标
  }
}
