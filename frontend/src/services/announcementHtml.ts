import { http, type GeoHttpRequestConfig } from './http'

const MEDIA_PATH_RE = /\/(?:api\/)?v1\/announcements\/media\/(\d+)/i

/** 保存前：把 blob: 预览地址还原为可持久化的媒体路径。 */
export function persistAnnouncementHtml(html: string): string {
  if (!html) return ''
  const doc = new DOMParser().parseFromString(`<div id="root">${html}</div>`, 'text/html')
  const root = doc.getElementById('root')
  if (!root) return html
  root.querySelectorAll('img').forEach((img) => {
    const persistent = img.getAttribute('data-media-src')
    if (persistent) {
      img.setAttribute('src', persistent)
      img.removeAttribute('data-media-src')
    }
  })
  return root.innerHTML
}

/** 展示前：公告媒体走鉴权拉取，换成 blob URL，避免 img 裸请求失败。 */
export async function hydrateAnnouncementHtml(html: string): Promise<string> {
  if (!html) return ''
  const doc = new DOMParser().parseFromString(`<div id="root">${html}</div>`, 'text/html')
  const root = doc.getElementById('root')
  if (!root) return html

  const imgs = Array.from(root.querySelectorAll('img'))
  await Promise.all(
    imgs.map(async (img) => {
      const src = img.getAttribute('src') || ''
      if (src.startsWith('blob:') || src.startsWith('data:')) return
      const match = src.match(MEDIA_PATH_RE)
      if (!match) return
      const mediaId = match[1]
      try {
        const response = await http.get(`/v1/announcements/media/${mediaId}`, {
          responseType: 'blob',
          silentError: true,
        } as GeoHttpRequestConfig)
        const blobUrl = URL.createObjectURL(response.data as Blob)
        img.setAttribute('data-media-src', `/api/v1/announcements/media/${mediaId}`)
        img.setAttribute('src', blobUrl)
      } catch {
        /* keep original src */
      }
    }),
  )
  return root.innerHTML
}

export function isAnnouncementMediaUrl(url: string): boolean {
  return MEDIA_PATH_RE.test(url || '')
}
