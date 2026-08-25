export interface SourceCategoryRule {
  id: string
  label: string
  color: string
  keywords?: string[]
  domains?: string[]
  hostSuffixes?: string[]
}

/** 按优先级排列：先命中先返回；official 单独后置。 */
export const SOURCE_CATEGORY_RULES: SourceCategoryRule[] = [
  {
    id: 'encyclopedia',
    label: '百科/知识库',
    color: '#9b7ae7',
    domains: ['baike.baidu.com', 'baike.com', 'baike.sogou.com', 'wikipedia.org', 'wiki'],
  },
  {
    id: 'government',
    label: '政府/公共事业',
    color: '#64748b',
    keywords: ['人民政府', '政务', '公共资源交易'],
    hostSuffixes: ['.gov.cn', '.gov'],
  },
  {
    id: 'enterprise',
    label: '企业库/工商信息',
    color: '#6366f1',
    keywords: ['企查查', '天眼查', '爱企查', '启信宝', '工商信息', '企业信用', '水滴信用'],
    domains: [
      'tianyancha.com',
      'qcc.com',
      'qichacha.com',
      'aiqicha.baidu.com',
      'gsxt.gov.cn',
      'qixin.com',
      'shuidiqiye.com',
      'qimingpian.com',
    ],
  },
  {
    id: 'recruitment',
    label: '招聘/职场',
    color: '#8b5cf6',
    keywords: ['招聘', '直聘', '猎聘', '人才网', '求职', '看准网', '职友集'],
    domains: [
      'zhipin.com',
      'liepin.com',
      '51job.com',
      'zhaopin.com',
      'kanzhun.com',
      'jobui.com',
      'chinahr.com',
      'lagou.com',
      'maimai.cn',
    ],
  },
  {
    id: 'qa',
    label: '问答社区',
    color: '#35c58f',
    keywords: ['问答', '知乎'],
    domains: ['zhihu.com', 'zhidao.baidu.com', 'wukong.com', 'stackoverflow.com'],
  },
  {
    id: 'ranking',
    label: '行业榜单/测评',
    color: '#f59e0b',
    keywords: ['十大品牌', '排行榜', '品牌排行', '选购指南', '横评', '品牌推荐', '口碑排行', '十大品牌网'],
    domains: ['maigoo.com', 'cnpp.cn', 'cnpp100.com', 'chinapp.com', 'top10.cn'],
  },
  {
    id: 'b2b',
    label: 'B2B/黄页/渠道站',
    color: '#0d9488',
    keywords: ['黄页', '电话邦', '查号', '名录', '招商加盟', '供应商', '顺企', '马可波罗'],
    domains: [
      'dianhua.cn',
      'mapbar.com',
      '58.com',
      'ganji.com',
      '11467.com',
      'huicong.com',
      'makepolo.com',
      'chinabidding.com.cn',
      'b2b168.com',
      '51sole.com',
      'gys.cn',
      'hc360.com',
    ],
  },
  {
    id: 'local',
    label: '地图/本地生活',
    color: '#22c55e',
    keywords: ['地图', '大众点评', '美团', '高德地图', '百度地图'],
    domains: ['amap.com', 'gaode.com', 'dianping.com', 'meituan.com', 'map.baidu.com', 'map.qq.com'],
  },
  {
    id: 'ecommerce',
    label: '电商平台',
    color: '#ec4899',
    domains: [
      'taobao.com',
      'tmall.com',
      'jd.com',
      '1688.com',
      'pinduoduo.com',
      'yangkeduo.com',
      'dangdang.com',
      'amazon.cn',
      'amazon.com',
      'youzan.com',
    ],
  },
  {
    id: 'social',
    label: '社交/内容平台',
    color: '#f0b84e',
    keywords: ['微博', '小红书', '公众号', '百家号', '头条号'],
    domains: [
      'weibo.com',
      'weibo.cn',
      'weixin.qq.com',
      'mp.weixin.qq.com',
      'douyin.com',
      'iesdouyin.com',
      'xiaohongshu.com',
      'xhslink.com',
      'bilibili.com',
      'b23.tv',
      'youku.com',
      'iqiyi.com',
      'v.qq.com',
      'toutiao.com',
      'm.toutiao.com',
      'ixigua.com',
      'baijiahao.baidu.com',
    ],
  },
  {
    id: 'media',
    label: '行业媒体/新闻',
    color: '#20b8c9',
    keywords: ['媒体', '新闻', '资讯', '报道', '家居网', '新闻网', '日报', '晚报'],
    domains: [
      'sohu.com',
      '163.com',
      'sina.com.cn',
      'sina.cn',
      'ifeng.com',
      'thepaper.cn',
      '36kr.com',
      'huxiu.com',
      'pchouse.com.cn',
      'yiche.com',
      'autohome.com.cn',
      'jiemian.com',
      'to8to.com',
      'shangyexinzhi.com',
      'cnblogs.com',
      'jianshu.com',
      'csdn.net',
      'zgswcn.com',
      'dzwww.com',
      'lieju.com',
      'liebiao.com',
      'docin.com',
      'doc88.com',
      'bjd.com.cn',
      'bjnews.com.cn',
      'eastmoney.com',
      'stockstar.com',
      'people.com.cn',
      'xinhuanet.com',
      'ce.cn',
      'stcn.com',
      'cnstock.com',
      'pedaily.cn',
    ],
  },
  {
    id: 'forum',
    label: '论坛/经验分享',
    color: '#14b8a6',
    keywords: ['论坛', '贴吧', '值得买', '经验'],
    domains: [
      'tieba.baidu.com',
      'v2ex.com',
      'douban.com',
      'smzdm.com',
      'chiphell.com',
      'club.autohome.com.cn',
      'bbs.',
    ],
  },
  {
    id: 'official',
    label: '官网/自有阵地',
    color: '#326fea',
    keywords: [
      '官网', '官方网站', 'homepage', '企业介绍', '关于我们',
      '公司简介', '企业简介', '集团简介', '欢迎您访问', '欢迎访问',
    ],
    domains: ['dwywood.com'],
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

const LEGACY_CATEGORY_ALIASES: Record<string, SourceCategory> = {
  video: 'social',
}

const PLATFORM_CATEGORY_IDS = new Set(
  SOURCE_CATEGORY_RULES.map(rule => rule.id).filter(id => id !== 'official' && id !== 'other'),
)

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
  const key = LEGACY_CATEGORY_ALIASES[id] || id
  return sourceCategoryLabels[key as SourceCategory] || id
}

export function sourceCategoryColor(id: string) {
  const key = LEGACY_CATEGORY_ALIASES[id] || id
  return sourceCategoryColors[key as SourceCategory] || sourceCategoryColors.official
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

const CORPORATE_HEURISTIC_DENY_SUFFIXES = [
  'baidu.com', 'china.cn', 'sina.com.cn', 'sina.cn', 'sohu.com', '163.com', 'qq.com',
  'eastmoney.com', 'cnstock.com', 'pedaily.cn', 'weibo.com', 'zhihu.com', 'toutiao.com',
  'ixigua.com', 'apple.com', 'google.com', 'ctrip.com', 'mapbar.com', '360.cn',
]

function hostMatchesDomain(host: string, domain: string) {
  if (!host || !domain) return false
  if (domain === 'bbs.') return host.startsWith('bbs.') || host.includes('.bbs.')
  const bare = domain.replace(/^\./, '')
  return host === bare || host.endsWith(`.${bare}`)
}

function hostOnDenyPlatform(host: string) {
  return CORPORATE_HEURISTIC_DENY_SUFFIXES.some(suffix => hostMatchesDomain(host, suffix))
}

function matchRule(rule: SourceCategoryRule, text: string, host: string) {
  if (rule.hostSuffixes?.some(suffix => {
    const bare = suffix.replace(/^\./, '')
    return host === bare || host.endsWith(`.${bare}`)
  })) {
    return true
  }
  if (rule.domains?.some(domain => hostMatchesDomain(host, domain))) {
    return true
  }
  if (rule.keywords?.some(keyword => text.includes(keyword.toLowerCase()))) {
    return true
  }
  return false
}

function looksLikeCorporateSitePage(rawText: string, host: string) {
  if (!host || hostOnDenyPlatform(host)) return false
  const text = rawText.replace(/\s+/g, '')
  if (!text) return false
  if (['公司简介', '企业简介', '集团简介', '企业介绍', '关于我们', '联系我们', '官方网站', '官网']
    .some(token => text.includes(token))) {
    return true
  }
  if (['股份有限公司', '有限责任公司', '有限公司', '集团有限公司'].some(suffix => text.includes(suffix))) {
    if (['|', '_', '｜'].some(sep => text.includes(sep))) return true
    if (['装饰材料', '门店', '专卖', '经销', '贸易'].some(token => text.includes(token))) return true
  }
  return false
}

export function sourceCategory(
  source: { title?: string; url?: string; site?: string | null; category?: string | null },
  options?: { brandOfficialHost?: string | null; brandKnownHosts?: string[] },
): SourceCategory {
  const presetRaw = String(source.category || '').trim()
  const preset = LEGACY_CATEGORY_ALIASES[presetRaw] || presetRaw
  if (preset && preset in sourceCategoryLabels) {
    return preset as SourceCategory
  }
  const text = `${source.title || ''} ${source.site || ''} ${source.url || ''}`.toLowerCase()
  const rawText = `${source.title || ''} ${source.site || ''} ${source.url || ''}`
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

  if (host && looksLikeCorporateSitePage(rawText, host)) return 'official'

  return SOURCE_CATEGORY_FALLBACK
}

export const sourceCategoryIds = SOURCE_CATEGORY_RULES.map(rule => rule.id) as SourceCategory[]

if (!import.meta.env.PROD) {
  const checks: Array<[Parameters<typeof sourceCategory>[0], SourceCategory]> = [
    [{ url: 'https://baike.baidu.com/item/foo' }, 'encyclopedia'],
    [{ url: 'https://www.tianyancha.com/company/1' }, 'enterprise'],
    [{ url: 'https://www.gov.cn/zhengce/' }, 'government'],
    [{ url: 'https://www.zhihu.com/question/1' }, 'qa'],
    [{ url: 'https://m.zhipin.com/job/1' }, 'recruitment'],
    [{ url: 'https://www.maigoo.com/brand/' }, 'ranking'],
    [{ url: 'https://www.dianhua.cn/x', site: '电话邦' }, 'b2b'],
    [{ url: 'https://map.baidu.com/' }, 'local'],
    [{ url: 'https://mp.weixin.qq.com/s/abc' }, 'social'],
    [{ url: 'https://www.bilibili.com/video/1' }, 'social'],
    [{ url: 'https://www.sohu.com/a/1' }, 'media'],
    [{ url: 'https://www.smzdm.com/p/1' }, 'forum'],
    [{ url: 'https://item.taobao.com/1' }, 'ecommerce'],
    [{ title: '品牌官方网站介绍' }, 'official'],
    [{ title: '某行业观察', url: 'https://news.pchouse.com.cn/post' }, 'media'],
    [{ title: '某行业观察', url: 'https://example.org/post' }, 'other'],
    [{
      title: '公司简介_海南装饰材料,海口装饰材料,海南旺顺祥业贸易有限公司',
      url: 'https://www.hkwsxy.com/about.html',
    }, 'official'],
    [{ title: '百科精选帖', url: 'https://m.pchouse.com.cn/post' }, 'media'],
    [{ title: '旗舰店报道', url: 'https://news.bjd.com.cn/a/1', site: '北京日报网' }, 'media'],
    [{ title: '会员商城系统', url: 'https://m.fkw.com/a/1' }, 'other'],
  ]
  for (const [input, expected] of checks) {
    const actual = sourceCategory(input)
    if (actual !== expected) {
      console.warn(`[sourceCategory] expected ${expected} got ${actual}`, input)
    }
  }
}
