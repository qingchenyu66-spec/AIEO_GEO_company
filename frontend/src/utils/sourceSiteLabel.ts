/** 引用信源展示：从 site / url 解析站名，供实时监测抽屉标题后缀使用。 */

const SITE_LABELS: Record<string, string> = {
  'docin.com': '豆丁网',
  'qcc.com': '企查查',
  'aiqicha.baidu.com': '爱企查',
  'tianyancha.com': '天眼查',
  'zhipin.com': 'BOSS直聘',
  'maigoo.com': '买购APP',
  'zhihu.com': '知乎',
  'baike.baidu.com': '百度百科',
  'zh.wikipedia.org': '维基百科',
  'douban.com': '豆瓣',
  'baijiahao.baidu.com': '百家号',
  'sohu.com': '搜狐',
  '163.com': '网易',
  'weibo.com': '微博',
}

/** 与后端 `_is_valid_citation_source` 对齐：静态资源/CDN 不当引用展示。 */
const STATIC_EXTS = [
  '.css', '.js', '.mjs', '.map', '.json',
  '.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.ico',
  '.woff', '.woff2', '.ttf', '.eot',
] as const

const ASSET_HOST_BITS = [
  'byteimg.com',
  'lf3-static',
  'lf-flow',
  'ibytedapm',
  'cdn.jsdelivr',
  'unpkg.com',
  'googleapis.com',
  'gstatic.com',
  'cloudflare.com/ajax',
  'fe-static.deepseek.com',
  'cdn.deepseek.com',
  // 2026-08-14 - 阿里系 CDN 裸域无后缀
  'alicdn.com',
  'taobaocdn.com',
  'tbcdn.cn',
] as const

const NOISY_TOKENS = [
  'window._',
  'search.quark.cn',
  'by2=news',
  'docin.com',
  'haokan.baidu.com',
  'quanmin.baidu.com',
  'aiqicha.baidu.com/details/ranklist',
  'cnpp.cn',
  'cnblogs.com',
] as const

export type CitationSourceLike = {
  title?: string
  url?: string
  site?: string
  index?: number
}

// 2026-08-14 - A：抽屉过滤 css/png；与 monitor_service._is_valid_citation_source 同口径
export function isValidCitationSource(source: CitationSourceLike): boolean {
  const titleSite = `${source.title || ''} ${source.site || ''}`.toLowerCase()
  const url = String(source.url || source.site || '').toLowerCase()
  if (!titleSite.trim() && !url.trim()) return false
  if (NOISY_TOKENS.some(token => titleSite.includes(token) || url.includes(token))) return false
  const path = url.split('?', 1)[0]
  if (STATIC_EXTS.some(ext => path.endsWith(ext))) return false
  if (ASSET_HOST_BITS.some(bit => url.includes(bit))) return false
  return true
}

export function filterCitationSources<T extends CitationSourceLike>(list: T[] | undefined | null): T[] {
  return (list || []).filter(isValidCitationSource)
}

function hostnameFromUrl(raw?: string): string | null {
  const text = (raw || '').trim()
  if (!/^https?:\/\//i.test(text)) return null
  try {
    return new URL(text).hostname.replace(/^www\./, '').toLowerCase()
  } catch {
    return null
  }
}

function labelFromHost(host: string): string {
  if (SITE_LABELS[host]) return SITE_LABELS[host]
  for (const [domain, name] of Object.entries(SITE_LABELS)) {
    if (host === domain || host.endsWith(`.${domain}`)) return name
  }
  return host
}

/** site 像可读站名（中文或无域名点的短品牌），而非裸域名片段。 */
function looksLikeSiteName(site: string): boolean {
  const text = site.trim()
  if (!text || text.length > 32) return false
  if (/[\u4e00-\u9fff]/.test(text)) return true
  return !text.includes('.') && text.length >= 2
}

export function citationSourceTitle(source: CitationSourceLike): string {
  return (source.title || source.site || source.url || '未命名信源').trim()
}

function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

/** 标题末尾已带站名（-BOSS直聘 / ->买购APP），或正文含 hostname 时视为已展示。 */
function titleAlreadyShowsSite(title: string, label: string, host: string | null): boolean {
  const text = title.trim()
  if (!text) return false
  if (text.toLowerCase() === label.toLowerCase()) return true
  const trailing = new RegExp(`(?:->|[-–—>|·~])\\s*${escapeRegExp(label)}\\s*$`, 'i')
  if (trailing.test(text)) return true
  if (host && text.toLowerCase().includes(host.toLowerCase())) return true
  return false
}

/** 标题后展示的来源站名；标题末尾已带站名时返回 null，避免重复。 */
export function citationSourceSiteLabel(source: CitationSourceLike): string | null {
  const title = (source.title || '').trim()
  const site = (source.site || '').trim()
  const host = hostnameFromUrl(source.url)

  let label: string | null = null
  if (site && looksLikeSiteName(site)) {
    label = site
  } else if (host) {
    label = labelFromHost(host)
  } else if (site) {
    label = site
  }
  if (!label) return null
  if (title && titleAlreadyShowsSite(title, label, host)) return null
  return label
}

export function citationSourceDisplay(source: CitationSourceLike): { title: string; site: string | null } {
  return {
    title: citationSourceTitle(source),
    site: citationSourceSiteLabel(source),
  }
}

/** 2026-08-14 - 正文引用 / 参考来源双轨，禁止混称「引用信源」 */
export type SourceTrackRows = {
  citations: Array<{ key: string; href: string | null; title: string; site: string | null }>
  references: Array<{ key: string; href: string | null; title: string; site: string | null }>
}

export function buildSourceTrackRows(
  subtask: { citation_list?: CitationSourceLike[] | null; reference_list?: CitationSourceLike[] | null } | null | undefined,
  options?: {
    limit?: number
    linkOf?: (url: string | null | undefined) => string | null
  },
): SourceTrackRows {
  const limit = options?.limit ?? 12
  const linkOf = options?.linkOf ?? ((url: string | null | undefined) => (url ? String(url) : null))
  const mapRows = (list: CitationSourceLike[] | undefined | null, prefix: string) =>
    filterCitationSources(list)
      .slice(0, limit)
      .map((source, index) => ({
        key: `${prefix}-${source.index ?? index}-${source.url || source.title || index}`,
        href: linkOf(source.url),
        ...citationSourceDisplay(source),
      }))
  return {
    citations: mapRows(subtask?.citation_list, 'cite'),
    references: mapRows(subtask?.reference_list, 'ref'),
  }
}
