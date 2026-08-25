export interface SourceCategoryRule {
  id: string
  label: string
  color: string
  keywords?: string[]
  domains?: string[]
  hostSuffixes?: string[]
}

/** 按优先级排列：先命中先返回；未识别平台类站点默认归官网/企业站点。 */
export const SOURCE_CATEGORY_RULES: SourceCategoryRule[] = [
  {
    id: 'encyclopedia',
    label: '百科',
    color: '#9b7ae7',
    keywords: ['百科'],
    domains: ['baike.baidu.com', 'wikipedia.org', 'wiki'],
  },
  {
    id: 'government',
    label: '政府/事业',
    color: '#64748b',
    keywords: ['人民政府', '政务', 'gov.cn'],
    hostSuffixes: ['.gov.cn', '.gov'],
  },
  {
    id: 'enterprise',
    label: '企业库/工商',
    color: '#6366f1',
    keywords: ['企查查', '天眼查', '爱企查', '工商信息', '企业信用', '电话邦', '黄页', '查号', '名录'],
    domains: [
      'tianyancha.com',
      'qcc.com',
      'qichacha.com',
      'aiqicha.baidu.com',
      'gsxt.gov.cn',
      'dianhua.cn',
      'mapbar.com',
      '58.com',
      'ganji.com',
      'chinahr.com',
      'jobui.com',
      '11467.com',
    ],
  },
  {
    id: 'qa',
    label: '问答社区',
    color: '#35c58f',
    keywords: ['问答', '知乎'],
    domains: ['zhihu.com', 'zhidao.baidu.com', 'stackoverflow.com'],
  },
  {
    id: 'social',
    label: '社交媒体',
    color: '#f0b84e',
    keywords: ['微博', '小红书'],
    domains: [
      'weibo.com',
      'weixin.qq.com',
      'mp.weixin.qq.com',
      'douyin.com',
      'xiaohongshu.com',
      'xhslink.com',
    ],
  },
  {
    id: 'forum',
    label: '论坛社区',
    color: '#14b8a6',
    keywords: ['论坛', '贴吧'],
    domains: ['tieba.baidu.com', 'v2ex.com', 'douban.com', 'bbs.'],
  },
  {
    id: 'video',
    label: '视频平台',
    color: '#f97316',
    keywords: ['视频', 'bilibili', 'b站'],
    domains: ['bilibili.com', 'b23.tv', 'youku.com', 'iqiyi.com', 'v.qq.com'],
  },
  {
    id: 'media',
    label: '行业媒体',
    color: '#20b8c9',
    keywords: ['媒体', '新闻', '资讯', '报道', '家居网', '汽车之家'],
    domains: [
      'sohu.com',
      '163.com',
      'sina.com.cn',
      'ifeng.com',
      'thepaper.cn',
      '36kr.com',
      'huxiu.com',
      // 2026-08-25 - 垂直行业媒体补规则，与后端 source_category_service 对齐
      'pchouse.com.cn',
      'yiche.com',
      'autohome.com.cn',
      'maigoo.com',
      'smzdm.com',
      'jiemian.com',
      'to8to.com',
      'shangyexinzhi.com',
      'cnblogs.com',
      'jianshu.com',
      'csdn.net',
      'toutiao.com',
      'ixigua.com',
      'zgswcn.com',
      'dzwww.com',
      'lieju.com',
      'liebiao.com',
      'docin.com',
      'doc88.com',
    ],
  },
  {
    id: 'ecommerce',
    label: '电商/交易',
    color: '#ec4899',
    keywords: ['旗舰店', '商城', '店铺'],
    domains: ['taobao.com', 'tmall.com', 'jd.com', '1688.com'],
  },
  {
    id: 'official',
    label: '官网/企业站点',
    color: '#326fea',
    keywords: ['官网', '官方网站', 'homepage', '企业介绍', '关于我们'],
  },
  {
    id: 'other',
    label: '其他',
    color: '#94a3b8',
    keywords: ['未知来源'],
  },
]

export type SourceCategory = (typeof SOURCE_CATEGORY_RULES)[number]['id']

export const SOURCE_CATEGORY_FALLBACK: SourceCategory = 'other'

const PLATFORM_CATEGORY_IDS = new Set([
  'encyclopedia', 'government', 'enterprise', 'qa', 'social', 'forum', 'video', 'media', 'ecommerce',
])

export const sourceCategoryLabels: Record<SourceCategory, string> = Object.fromEntries(
  SOURCE_CATEGORY_RULES.map(rule => [rule.id, rule.label]),
) as Record<SourceCategory, string>

export const sourceCategoryColors: Record<SourceCategory, string> = Object.fromEntries(
  SOURCE_CATEGORY_RULES.map(rule => [rule.id, rule.color]),
) as Record<SourceCategory, string>

export function createEmptyCategoryBucket(): Record<SourceCategory, number> {
  return Object.fromEntries(SOURCE_CATEGORY_RULES.map(rule => [rule.id, 0])) as Record<SourceCategory, number>
}

export function sourceCategoryLabel(id: string) {
  return sourceCategoryLabels[id as SourceCategory] || id
}

export function sourceCategoryColor(id: string) {
  return sourceCategoryColors[id as SourceCategory] || sourceCategoryColors.official
}

export function collectBrandKnownHosts(brand?: {
  official_url?: string | null
  product_keywords?: string[]
  keyword_groups?: Array<{ exposure_terms?: string[] }>
} | null): string[] {
  const hosts = new Set<string>()
  const add = (raw?: string | null) => {
    const host = normalizeHost(raw || '')
    if (host) hosts.add(host)
  }
  add(brand?.official_url)
  for (const term of brand?.product_keywords || []) {
    if (term.includes('.')) add(term)
  }
  for (const group of brand?.keyword_groups || []) {
    for (const term of group.exposure_terms || []) {
      if (term.includes('.')) add(term)
    }
  }
  return [...hosts]
}

function normalizeHost(input: string) {
  const raw = (input || '').trim().toLowerCase()
  if (!raw) return ''
  try {
    const url = raw.includes('://') ? raw : `https://${raw}`
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return raw.replace(/^https?:\/\//, '').replace(/^www\./, '').split('/')[0]
  }
}

function hostsMatch(left: string, right: string) {
  if (!left || !right) return false
  return left === right || left.endsWith(`.${right}`) || right.endsWith(`.${left}`)
}

function matchRule(rule: SourceCategoryRule, text: string, host: string) {
  if (rule.hostSuffixes?.some(suffix => {
    const bare = suffix.replace(/^\./, '')
    return host === bare || host.endsWith(`.${bare}`)
  })) {
    return true
  }
  if (rule.domains?.some(domain => host === domain || host.endsWith(`.${domain}`) || text.includes(domain))) {
    return true
  }
  if (rule.keywords?.some(keyword => text.includes(keyword.toLowerCase()))) {
    return true
  }
  return false
}

export function sourceCategory(
  source: { title?: string; url?: string; site?: string | null; category?: string | null },
  options?: { brandOfficialHost?: string | null; brandKnownHosts?: string[] },
): SourceCategory {
  const preset = String(source.category || '').trim()
  if (preset && preset in sourceCategoryLabels) {
    return preset as SourceCategory
  }
  const text = `${source.title || ''} ${source.site || ''} ${source.url || ''}`.toLowerCase()
  const host = normalizeHost(source.url || '')

  const knownHosts = [
    ...(options?.brandKnownHosts || []),
    ...(options?.brandOfficialHost ? [options.brandOfficialHost] : []),
  ]
    .map(item => normalizeHost(item))
    .filter(Boolean)
  for (const knownHost of knownHosts) {
    if (host && hostsMatch(host, knownHost)) return 'official'
  }

  for (const rule of SOURCE_CATEGORY_RULES) {
    if (!PLATFORM_CATEGORY_IDS.has(rule.id)) continue
    if (matchRule(rule, text, host)) return rule.id as SourceCategory
  }

  const officialRule = SOURCE_CATEGORY_RULES.find(rule => rule.id === 'official')
  if (officialRule && matchRule(officialRule, text, host)) return 'official'

  return SOURCE_CATEGORY_FALLBACK
}

export const sourceCategoryIds = SOURCE_CATEGORY_RULES.map(rule => rule.id) as SourceCategory[]

// ponytail: self-check — import 时校验规则表与分类入口
if (!import.meta.env.PROD) {
  const checks: Array<[Parameters<typeof sourceCategory>[0], SourceCategory]> = [
    [{ url: 'https://baike.baidu.com/item/foo' }, 'encyclopedia'],
    [{ url: 'https://www.tianyancha.com/company/1' }, 'enterprise'],
    [{ url: 'https://www.gov.cn/zhengce/' }, 'government'],
    [{ url: 'https://www.zhihu.com/question/1' }, 'qa'],
    [{ url: 'https://mp.weixin.qq.com/s/abc' }, 'social'],
    [{ url: 'https://tieba.baidu.com/f?kw=1' }, 'forum'],
    [{ url: 'https://www.bilibili.com/video/1' }, 'video'],
    [{ url: 'https://www.sohu.com/a/1' }, 'media'],
    [{ url: 'https://item.taobao.com/1' }, 'ecommerce'],
    [{ title: '品牌官方网站介绍' }, 'official'],
    [{ title: '某行业观察', url: 'https://news.pchouse.com.cn/post' }, 'media'],
    [{ title: '某行业观察', url: 'https://example.org/post' }, 'other'],
    [{ title: '大王椰板材店', url: 'https://www.dianhua.cn/x', site: '电话邦' }, 'enterprise'],
  ]
  for (const [input, expected] of checks) {
    const actual = sourceCategory(input)
    if (actual !== expected) {
      console.warn(`[sourceCategory] expected ${expected} got ${actual}`, input)
    }
  }
}
