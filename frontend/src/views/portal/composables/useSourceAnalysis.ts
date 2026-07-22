import { computed, inject, onMounted, onUnmounted, ref, watch, type Ref } from 'vue'
import { ElMessage } from 'element-plus'
import { usePortalCharts } from '../../../composables/usePortalCharts'
import type { MonitorSummary } from '../../../services/monitor'
import { useAuthStore } from '../../../stores/auth'
import {
  customerDisplayDateRange,
  customerDisplayPeriodLabel,
  customerTrendPeriodLabel,
} from '../../../utils/customerMonitorDate'
import { PortalAnalyticsKey } from '../injectionKeys'
import { platformLabelMap } from '../portalMaps'
import { resolvePurchasedPlatformCodes, sortPlatformRows, sortPlatformTabs } from '../platformOrder'
import {
  createEmptyCategoryBucket,
  collectBrandKnownHosts,
  sourceCategory,
  sourceCategoryIds,
  sourceCategoryLabel,
  sourceCategoryLabels,
  type SourceCategory,
} from '../sourceCategory'
import { isCustomerPreviewActive } from '../customerPreview'
import { useRoute } from 'vue-router'

export type { SourceCategory }
export { sourceCategoryLabels, sourceCategory, sourceCategoryLabel }

export type SourceDatePreset = '7' | '30' | 'all'
export type SourceRankTab = 'branded' | 'all'

export type SourceRow = MonitorSummary['source_stats'][number] & {
  category: SourceCategory
  has_exposure: boolean
}

export type WebsiteRankRow = {
  /** 注册域，如 163.com（已合并 m.163.com / c.m.163.com） */
  domain: string
  /** 发布方名称（域名词典优先；不可靠时退回域名） */
  displayName: string
  /** 文中主体（露出词 / 被引用串里的品牌向站点名） */
  subjectHint: string
  count: number
  articleCount: number
  category: SourceCategory
  platforms: string[]
  exposure_terms: string[]
  has_exposure: boolean
  sampleUrl: string
  questions: string[]
}

const RANK_PAGE_SIZE = 20

/** 多段公共后缀：取 eTLD+1 时多拿一级 */
const MULTI_PART_TLDS = new Set([
  'com.cn', 'net.cn', 'org.cn', 'gov.cn', 'edu.cn', 'co.uk', 'com.hk', 'com.tw',
])

/** 注册域 → 发布方（方案 A 主路径） */
const KNOWN_SITE_LABELS: Record<string, string> = {
  '163.com': '网易',
  'toutiao.com': '今日头条',
  'sohu.com': '搜狐',
  'sina.com.cn': '新浪',
  'qq.com': '腾讯',
  'weibo.com': '微博',
  'zhihu.com': '知乎',
  'douyin.com': '抖音',
  'iesdouyin.com': '抖音',
  'xiaohongshu.com': '小红书',
  'bilibili.com': '哔哩哔哩',
  'baidu.com': '百度',
  'baike.baidu.com': '百度百科',
  'ifeng.com': '凤凰网',
  'smzdm.com': '什么值得买',
  'to8to.com': '土巴兔装修网',
  'shangyexinzhi.com': '商业新知',
  'lieju.com': '济南列举网',
  'liebiao.com': '列表网',
  'dzwww.com': '大众网',
  'zgswcn.com': '中国商报网',
  'pchouse.com.cn': 'PChouse太平洋家居网',
  'tianyancha.com': '天眼查',
  'qcc.com': '企查查',
}

const PUBLISHER_NAME_HINT = /网|新闻|日报|晚报|时报|媒体|资讯|头条|百科|论坛|博客|视频|电台|电视|客户端|周刊|杂志|值得买/

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : String(error)
}

function domainFromUrl(url: string) {
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return url.replace(/^https?:\/\//, '').split('/')[0]?.replace(/^www\./, '') || url
  }
}

/** m.163.com / c.m.163.com → 163.com；m.pchouse.com.cn → pchouse.com.cn */
function registrableDomain(hostOrUrl: string) {
  const host = (hostOrUrl.includes('://') ? domainFromUrl(hostOrUrl) : hostOrUrl)
    .replace(/^www\./i, '')
    .toLowerCase()
    .trim()
  if (!host) return ''
  const parts = host.split('.').filter(Boolean)
  if (parts.length <= 2) return host
  const last2 = parts.slice(-2).join('.')
  if (MULTI_PART_TLDS.has(last2) && parts.length >= 3) {
    return parts.slice(-3).join('.')
  }
  return last2
}

function isChineseSiteLabel(value: string) {
  return /[\u4e00-\u9fff]/.test(value) && !/^https?:\/\//i.test(value.trim())
}

function knownPublisherLabel(domain: string) {
  if (KNOWN_SITE_LABELS[domain]) return KNOWN_SITE_LABELS[domain]
  // 兼容历史子域词条
  for (const [key, label] of Object.entries(KNOWN_SITE_LABELS)) {
    if (domain === key || domain.endsWith(`.${key}`)) return label
  }
  return ''
}

function normalizeSiteCandidate(raw: string) {
  return (raw || '').trim().split(/[,，/|、]/)[0]?.trim() || ''
}

function isBrandLikeName(name: string, brandTokens: string[]) {
  const text = name.trim()
  if (!text) return false
  if (/集团|有限公司|股份有限|广告投放|控股/.test(text)) return true
  const lower = text.toLowerCase()
  for (const token of brandTokens) {
    const t = token.trim().toLowerCase()
    if (t.length < 2) continue
    if (lower.includes(t) || t.includes(lower)) return true
  }
  return false
}

function looksLikePublisherName(name: string, brandTokens: string[]) {
  if (!isChineseSiteLabel(name)) return false
  if (isBrandLikeName(name, brandTokens)) return false
  if (PUBLISHER_NAME_HINT.test(name)) return true
  // 短名且不像公司主体时，谨慎采信（如「博客园」）
  return name.length <= 10 && !/公司|集团|投放|传媒$/.test(name)
}

function resolvePublisherAndSubject(
  domain: string,
  siteVotes: Array<[string, number]>,
  exposureTerms: string[],
  brandTokens: string[],
) {
  const known = knownPublisherLabel(domain)
  const publisherFromVotes = siteVotes
    .map(([name]) => normalizeSiteCandidate(name))
    .filter(name => looksLikePublisherName(name, brandTokens))
  const displayName = known || publisherFromVotes[0] || domain

  const subjectFromExposure = exposureTerms.map(t => t.trim()).filter(Boolean)
  const subjectFromVotes = siteVotes
    .map(([name]) => normalizeSiteCandidate(name))
    .filter(name => (
      name
      && name !== displayName
      && isChineseSiteLabel(name)
      && (isBrandLikeName(name, brandTokens) || !looksLikePublisherName(name, brandTokens))
    ))
  const subjects = [...subjectFromExposure, ...subjectFromVotes]
    .filter((name, index, arr) => arr.indexOf(name) === index)
    .filter(name => name !== displayName)
    .slice(0, 3)
  return {
    displayName,
    subjectHint: subjects.join('、'),
  }
}

function sliceTrendPoints<T extends { label: string; value: number }>(points: T[], days: number) {
  if (!points.length || days >= points.length) return points
  return points.slice(points.length - days)
}

function mapSourceRows(
  rows: MonitorSummary['source_stats'],
  brandOfficialHost: string | null | undefined,
  brandKnownHosts: string[],
): SourceRow[] {
  return rows.map(item => ({
    ...item,
    has_exposure: item.has_exposure ?? (item.exposure_terms || []).length > 0,
    category: sourceCategory(item, {
      brandOfficialHost,
      brandKnownHosts,
    }),
  }))
}

function aggregateByWebsite(rows: SourceRow[], brandTokens: string[] = []): WebsiteRankRow[] {
  type Acc = WebsiteRankRow & {
    categoryCounts: Record<string, number>
    topArticleCount: number
    siteVotes: Map<string, number>
  }
  const map = new Map<string, Acc>()
  for (const row of rows) {
    const host = domainFromUrl(row.url || '')
    const domain = registrableDomain(host)
    if (!domain) continue
    let entry = map.get(domain)
    if (!entry) {
      entry = {
        domain,
        displayName: domain,
        subjectHint: '',
        count: 0,
        articleCount: 0,
        category: row.category,
        platforms: [],
        exposure_terms: [],
        has_exposure: false,
        sampleUrl: row.url,
        questions: [],
        categoryCounts: {},
        topArticleCount: row.count,
        siteVotes: new Map(),
      }
      map.set(domain, entry)
    }
    entry.count += row.count
    entry.articleCount += 1
    entry.has_exposure = entry.has_exposure || row.has_exposure
    entry.categoryCounts[row.category] = (entry.categoryCounts[row.category] || 0) + row.count
    // 方案 A：仅采信引用 site 字段投票；标题尾部不再充当发布方
    const siteLabel = normalizeSiteCandidate(row.site || '')
    if (siteLabel && isChineseSiteLabel(siteLabel)) {
      entry.siteVotes.set(siteLabel, (entry.siteVotes.get(siteLabel) || 0) + row.count)
    }
    if (row.count > entry.topArticleCount) {
      entry.topArticleCount = row.count
      entry.sampleUrl = row.url
    }
    for (const platform of row.platforms || []) {
      if (!entry.platforms.includes(platform)) entry.platforms.push(platform)
    }
    for (const term of row.exposure_terms || []) {
      if (!entry.exposure_terms.includes(term)) entry.exposure_terms.push(term)
    }
    for (const question of row.questions || []) {
      if (entry.questions.length < 8 && !entry.questions.includes(question)) {
        entry.questions.push(question)
      }
    }
  }
  return Array.from(map.values())
    .map(({ categoryCounts, topArticleCount: _top, siteVotes, ...row }) => {
      const bestCategory = Object.entries(categoryCounts).sort((a, b) => b[1] - a[1])[0]?.[0]
      const voted = Array.from(siteVotes.entries()).sort((a, b) => b[1] - a[1])
      const naming = resolvePublisherAndSubject(
        row.domain,
        voted,
        row.exposure_terms,
        brandTokens,
      )
      return {
        ...row,
        displayName: naming.displayName,
        subjectHint: naming.subjectHint,
        category: (bestCategory as SourceCategory) || row.category,
        exposure_terms: row.exposure_terms.slice(0, 8),
        platforms: row.platforms.slice(0, 6),
      }
    })
    .sort((a, b) => b.count - a.count || b.articleCount - a.articleCount)
}

export function useSourceAnalysis(options?: {
  structureChartRef?: Ref<HTMLDivElement | null>
  categoryChartRef?: Ref<HTMLDivElement | null>
  trendChartRef?: Ref<HTMLDivElement | null>
}) {
  const analytics = inject(PortalAnalyticsKey)!
  const auth = useAuthStore()
  const route = useRoute()
  const isCustomerView = computed(() => (
    auth.session?.identity?.identity_type === 'CUSTOMER'
    || isCustomerPreviewActive(route, auth.session?.identity?.identity_type === 'PLATFORM')
  ))
  const customerPeriodLabel = computed(() => customerDisplayPeriodLabel())
  const brandAsset = analytics.brandAsset

  const loading = ref(false)
  const monitorSummary = analytics.monitorSummary
  // 客户/运营共用周期；运营默认近 30 天，客户默认全部（截至昨日）
  const datePreset = ref<SourceDatePreset>('all')
  if (!isCustomerView.value) datePreset.value = '30'

  const inclusionDateRange = computed(() => {
    if (datePreset.value === 'all') {
      // brief 无日期时后端默认近 7 天；「全部」显式拉宽到近 365 天
      return customerDisplayDateRange(365)
    }
    return customerDisplayDateRange(Number(datePreset.value))
  })

  const trendPeriodLabel = computed(() => {
    if (datePreset.value === 'all') return '全部周期引用趋势'
    const days = Number(datePreset.value)
    if (isCustomerView.value) return customerTrendPeriodLabel(days)
    return `近 ${days} 日引用趋势`
  })
  const platformFilter = ref('all')
  const categoryFilter = ref<'all' | SourceCategory>('all')
  const keywordFilter = ref('')
  const domainFilter = ref('')
  const rankTab = ref<SourceRankTab>('branded')
  const rankPage = ref(1)

  const structureChartRef = options?.structureChartRef ?? ref<HTMLDivElement | null>(null)
  const categoryChartRef = options?.categoryChartRef ?? ref<HTMLDivElement | null>(null)
  const trendChartRef = options?.trendChartRef ?? ref<HTMLDivElement | null>(null)
  const { renderCharts } = usePortalCharts({
    sourceStructure: structureChartRef,
    sourceCategoryDistribution: categoryChartRef,
    sourceTrend: trendChartRef,
  })

  const brandKnownHosts = computed(() => collectBrandKnownHosts(brandAsset.value))

  const brandedSources = computed<SourceRow[]>(() => (
    mapSourceRows(
      (monitorSummary.value?.source_stats || []).filter(item => (item.exposure_terms || []).length > 0),
      brandAsset.value?.official_url,
      brandKnownHosts.value,
    )
  ))

  const allCitationSources = computed<SourceRow[]>(() => (
    mapSourceRows(
      monitorSummary.value?.source_stats_all || monitorSummary.value?.source_stats || [],
      brandAsset.value?.official_url,
      brandKnownHosts.value,
    )
  ))

  // 图表 / Hero / 平台 chips 仍用品牌相关口径
  const allSources = brandedSources

  const platformRanking = computed(() => sortPlatformRows(monitorSummary.value?.platform_stats || []))

  const structurePlatformCodes = computed(() => resolvePurchasedPlatformCodes(
    brandAsset.value?.monitored_platforms,
    platformRanking.value.map(item => item.platform),
  ))

  function applySourceFilters(rows: SourceRow[], options?: { ignoreCategory?: boolean }) {
    const keyword = keywordFilter.value.trim().toLowerCase()
    const now = Date.now()
    const dayMs = 86400000
    const rangeDays = datePreset.value === 'all' ? null : Number(datePreset.value)
    const rangeStart = rangeDays ? now - rangeDays * dayMs : null
    const ignoreCategory = options?.ignoreCategory === true
    return rows.filter(source => {
      const platformMatched = platformFilter.value === 'all'
        || (source.platforms || []).includes(platformFilter.value)
      const categoryMatched = ignoreCategory
        || categoryFilter.value === 'all'
        || source.category === categoryFilter.value
      const text = `${source.title || ''} ${(source.exposure_terms || []).join(' ')} ${(source.questions || []).join(' ')} ${source.url || ''}`.toLowerCase()
      const keywordMatched = !keyword || text.includes(keyword)
      const sourceTime = source.latest_time ? new Date(source.latest_time).getTime() : null
      const dateMatched = !rangeStart || (sourceTime != null && sourceTime >= rangeStart)
      return platformMatched && categoryMatched && keywordMatched && dateMatched
    }).sort((a, b) => b.count - a.count)
  }

  const filteredSources = computed(() => applySourceFilters(brandedSources.value))
  const filteredAllSources = computed(() => applySourceFilters(allCitationSources.value))

  const brandNameTokens = computed(() => {
    const asset = brandAsset.value
    const tokens = new Set<string>()
    for (const key of ['brand_name', 'brand_short_name', 'company_full_name'] as const) {
      const text = String(asset?.[key] || '').trim()
      if (text) tokens.add(text)
    }
    for (const alias of asset?.aliases || []) {
      const text = String(alias || '').trim()
      if (text) tokens.add(text)
    }
    for (const group of asset?.keyword_groups || []) {
      for (const term of group.exposure_terms || []) {
        const text = String(term || '').trim()
        if (text) tokens.add(text)
      }
    }
    return Array.from(tokens)
  })

  const brandedWebsites = computed(() => aggregateByWebsite(filteredSources.value, brandNameTokens.value))
  const allWebsites = computed(() => aggregateByWebsite(filteredAllSources.value, brandNameTokens.value))

  const activeRankWebsites = computed(() => (
    rankTab.value === 'all' ? allWebsites.value : brandedWebsites.value
  ))

  const activeRankArticles = computed(() => {
    const rows = rankTab.value === 'all' ? filteredAllSources.value : filteredSources.value
    const domain = domainFilter.value.trim().toLowerCase()
    if (!domain) return rows
    return rows.filter(source => registrableDomain(domainFromUrl(source.url || '')).toLowerCase() === domain)
  })

  const articlePage = ref(1)
  const articleTotalPages = computed(() => Math.max(1, Math.ceil(activeRankArticles.value.length / RANK_PAGE_SIZE)))
  const pagedRankArticles = computed(() => {
    const page = Math.min(Math.max(articlePage.value, 1), articleTotalPages.value)
    const start = (page - 1) * RANK_PAGE_SIZE
    return activeRankArticles.value.slice(start, start + RANK_PAGE_SIZE)
  })

  const rankTotalPages = computed(() => Math.max(1, Math.ceil(activeRankWebsites.value.length / RANK_PAGE_SIZE)))
  const pagedRankWebsites = computed(() => {
    const page = Math.min(Math.max(rankPage.value, 1), rankTotalPages.value)
    const start = (page - 1) * RANK_PAGE_SIZE
    return activeRankWebsites.value.slice(start, start + RANK_PAGE_SIZE)
  })

  const sourceTotalCount = computed(() => filteredSources.value.reduce((sum, item) => sum + item.count, 0))
  const uniqueSourceCount = computed(() => filteredSources.value.length)
  const brandedWebsiteCount = computed(() => brandedWebsites.value.length)
  const allCitationTotalCount = computed(() => filteredAllSources.value.reduce((sum, item) => sum + item.count, 0))
  const allCitationUniqueCount = computed(() => filteredAllSources.value.length)
  const allWebsiteCount = computed(() => allWebsites.value.length)
  const brandedCitationShare = computed(() => {
    if (!allCitationTotalCount.value) return 0
    return Math.round((sourceTotalCount.value / allCitationTotalCount.value) * 100)
  })

  const platformWithSourcesCount = computed(() => {
    const allowed = new Set(structurePlatformCodes.value)
    const codes = new Set<string>()
    filteredSources.value.forEach(source => {
      ;(source.platforms || []).forEach(code => {
        if (allowed.size && !allowed.has(code)) return
        codes.add(code)
      })
    })
    return codes.size
  })

  const platformTabs = computed(() => {
    const allowed = new Set(structurePlatformCodes.value)
    const scopeSources = allSources.value
    const counts = new Map<string, number>()
    scopeSources.forEach(source => {
      ;(source.platforms || []).forEach(platform => {
        if (allowed.size && !allowed.has(platform)) return
        counts.set(platform, (counts.get(platform) || 0) + source.count)
      })
    })
    const platformEntries = allowed.size
      ? structurePlatformCodes.value.map(code => ({
        code,
        name: platformLabelMap[code] || code,
        count: counts.get(code) || 0,
      }))
      : Array.from(counts.entries()).map(([code, count]) => ({
        code,
        name: platformLabelMap[code] || code,
        count,
      }))
    const totalCount = platformEntries.reduce((sum, item) => sum + item.count, 0)
    return sortPlatformTabs([
      { code: 'all', name: '全部平台', count: totalCount },
      ...platformEntries,
    ])
  })

  const categoryStats = computed(() => {
    const bucket = createEmptyCategoryBucket()
    filteredSources.value.forEach(source => {
      bucket[source.category] = (bucket[source.category] || 0) + source.count
    })
    const total = Object.values(bucket).reduce((sum, value) => sum + value, 0) || 1
    return sourceCategoryIds.map(key => ({
      key,
      name: sourceCategoryLabels[key],
      count: bucket[key] || 0,
      percent: Math.round((bucket[key] || 0) / total * 100),
    }))
      .filter(item => item.count > 0)
      .sort((a, b) => b.count - a.count)
  })

  /** 引用网站全量列表（与下方排行同数据源；面板内滚动） */
  const websiteShortList = computed(() => {
    const rows = activeRankWebsites.value
    const total = rows.reduce((sum, item) => sum + item.count, 0) || 1
    return rows.map(item => ({
      ...item,
      percent: Math.round((item.count / total) * 10000) / 100,
    }))
  })

  function selectSourceCategory(key: 'all' | SourceCategory) {
    categoryFilter.value = key
    domainFilter.value = ''
    rankPage.value = 1
    articlePage.value = 1
  }

  function selectWebsiteDomain(domain: string) {
    domainFilter.value = domain
    articlePage.value = 1
  }

  function clearWebsiteDomain() {
    domainFilter.value = ''
    articlePage.value = 1
  }

  const activeCategoryKeys = computed(() => categoryStats.value.map(item => item.key))

  const activeSourceCategoryLabels = computed(() => (
    Object.fromEntries(categoryStats.value.map(item => [item.key, item.name]))
  ))

  const categorySummaryLabel = computed(() => {
    const names = categoryStats.value.map(item => item.name)
    if (!names.length) return '—'
    if (names.length <= 3) return names.join(' / ')
    return `共 ${names.length} 类`
  })

  const topCategory = computed(() => categoryStats.value.find(item => item.count > 0) || null)
  const officialRate = computed(() => categoryStats.value.find(item => item.key === 'official')?.percent ?? 0)

  const sourceStructureRows = computed(() => {
    const platforms = platformFilter.value === 'all'
      ? structurePlatformCodes.value
      : structurePlatformCodes.value.filter(code => code === platformFilter.value)
    return platforms.map(platform => {
    const platformSources = filteredSources.value.filter(source => (source.platforms || []).includes(platform))
    const total = platformSources.reduce((sum, source) => sum + source.count, 0)
    const categoryMap = platformSources.reduce((map, source) => {
      map[source.category] = (map[source.category] || 0) + source.count
      return map
    }, {} as Record<string, number>)
    const denom = total || 1
    return {
      platform,
      total,
      categories: activeCategoryKeys.value.map(type => ({
        type,
        value: total ? Math.round(((categoryMap[type] || 0) / denom) * 100) : 0,
      })),
    }
  })
  })

  const sourceTrendRows = computed(() => {
    const trendByPlatform = monitorSummary.value?.source_citation_trend_by_platform
    const selected = platformFilter.value !== 'all' ? platformFilter.value : null
    const backendTrend = selected
      ? trendByPlatform?.[selected]
      : monitorSummary.value?.source_citation_trend
    const backendPoints = backendTrend?.points || []
    if (backendPoints.length) {
      const points = datePreset.value === 'all'
        ? backendPoints
        : sliceTrendPoints(
          backendPoints,
          datePreset.value === '7' ? 7 : 30,
        )
      return points.map(point => ({
        label: point.label,
        value: point.value,
      }))
    }
    return []
  })

  const structureChartRows = computed(() => {
    if (platformFilter.value === 'all') return sourceStructureRows.value
    const active = sourceStructureRows.value.filter(row => row.total > 0)
    return active.length ? active : sourceStructureRows.value
  })

  const analyticsPairMinHeight = computed(() => {
    const rows = Math.max(structureChartRows.value.length, 1)
    return Math.max(280, rows * 36 + 56)
  })

  const hasStructurePanel = computed(() => (
    platformFilter.value === 'all'
      ? sourceStructureRows.value.length > 0
      : sourceStructureRows.value.some(row => row.total > 0)
  ))

  const hasPageContent = computed(() => (
    hasStructurePanel.value
    || filteredSources.value.length > 0
    || filteredAllSources.value.length > 0
  ))

  const insight = computed(() => {
    if (!hasPageContent.value) {
      return {
        level: 'empty' as const,
        title: '暂无信源引用',
        body: '当前筛选下没有可展示的 AI 引用。请完成更多监测或放宽筛选条件。',
      }
    }
    return {
      level: 'ok' as const,
      title: '数据口径说明',
      body: '图表按含露出词的引用文章统计；左侧「引用网站」按域名聚合，点击后右侧「信源明细」仅展示该站文章；可用 Tab 切换品牌相关 / 全部引用。',
    }
  })

  async function loadSummary(force = false) {
    loading.value = true
    try {
      await analytics.loadMonitorSummary(force)
    } catch (error: unknown) {
      ElMessage.error(`信源数据加载失败：${errorMessage(error)}`)
    } finally {
      loading.value = false
    }
  }

  async function refreshCharts() {
    await renderCharts({
      chartTrend: [],
      platformRanking: [],
      sentimentPieRows: [],
      positiveRate: 0,
      diagnosisScore: 0,
      competitorCompareRows: [],
      sourceStructureRows: structureChartRows.value,
      sourceTrendRows: sourceTrendRows.value,
      sourceCategoryLabels: activeSourceCategoryLabels.value,
      sourceCategoryStats: categoryStats.value,
      onSourceCategoryClick: (key: string) => {
        selectSourceCategory(key as SourceCategory)
        requestAnimationFrame(() => {
          document.getElementById('source-article-section')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
        })
      },
    })
  }

  function resetFilters() {
    platformFilter.value = 'all'
    categoryFilter.value = 'all'
    keywordFilter.value = ''
    domainFilter.value = ''
    datePreset.value = isCustomerView.value ? 'all' : '30'
    rankPage.value = 1
    articlePage.value = 1
  }

  function setRankTab(tab: SourceRankTab) {
    rankTab.value = tab
    domainFilter.value = ''
    rankPage.value = 1
    articlePage.value = 1
  }

  function exportCsv() {
    const rows = activeRankWebsites.value
    if (!rows.length) {
      ElMessage.warning('暂无可导出数据')
      return
    }
    const tabLabel = rankTab.value === 'all' ? '全部网站' : '品牌相关网站'
    const lines = [
      ['网站', '引用次数', '文章数', '类型', '露出词', '含露出词', '平台'].join(','),
      ...rows.map(site => [
        `"${site.domain.replace(/"/g, '""')}"`,
        site.count,
        site.articleCount,
        `"${sourceCategoryLabels[site.category] || site.category}"`,
        `"${site.exposure_terms.join('、')}"`,
        site.has_exposure ? '是' : '否',
        `"${site.platforms.map(code => platformLabelMap[code] || code).join('、')}"`,
      ].join(',')),
    ]
    const blob = new Blob([`\uFEFF${lines.join('\n')}`], { type: 'text/csv;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `${brandAsset.value?.brand_name || '信源'}-${tabLabel}.csv`
    link.click()
    URL.revokeObjectURL(url)
    ElMessage.success('已导出 CSV')
  }

  watch([filteredSources, structureChartRows, sourceTrendRows, activeSourceCategoryLabels, hasStructurePanel, loading], () => { void refreshCharts() }, { deep: true })
  watch([platformFilter, categoryFilter, keywordFilter, datePreset, rankTab], () => {
    rankPage.value = 1
    articlePage.value = 1
    if (domainFilter.value) domainFilter.value = ''
  })
  watch(rankTotalPages, pages => {
    if (rankPage.value > pages) rankPage.value = pages
  })
  watch(articleTotalPages, pages => {
    if (articlePage.value > pages) articlePage.value = pages
  })

  onMounted(() => {
    void loadSummary()
    window.addEventListener('resize', refreshCharts)
  })

  onUnmounted(() => {
    window.removeEventListener('resize', refreshCharts)
  })

  return {
    brandAsset,
    isCustomerView,
    customerPeriodLabel,
    trendPeriodLabel,
    loading,
    datePreset,
    inclusionDateRange,
    platformFilter,
    categoryFilter,
    keywordFilter,
    domainFilter,
    rankTab,
    rankPage,
    rankPageSize: RANK_PAGE_SIZE,
    rankTotalPages,
    articlePage,
    articleTotalPages,
    platformTabs,
    filteredSources,
    filteredAllSources,
    activeRankWebsites,
    pagedRankWebsites,
    activeRankArticles,
    pagedRankArticles,
    sourceTotalCount,
    uniqueSourceCount,
    brandedWebsiteCount,
    allCitationTotalCount,
    allCitationUniqueCount,
    allWebsiteCount,
    brandedCitationShare,
    platformWithSourcesCount,
    categoryStats,
    websiteShortList,
    activeSourceCategoryLabels,
    categorySummaryLabel,
    topCategory,
    officialRate,
    selectSourceCategory,
    selectWebsiteDomain,
    clearWebsiteDomain,
    sourceStructureRows,
    sourceTrendRows,
    analyticsPairMinHeight,
    hasStructurePanel,
    hasPageContent,
    insight,
    loadSummary,
    resetFilters,
    setRankTab,
    exportCsv,
    platformLabelMap,
    sourceCategoryLabels,
    sourceCategoryLabel,
    domainFromUrl,
  }
}
