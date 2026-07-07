/** Market-usage ranking for AI platforms (display order only). */

const PLATFORM_MARKET_RANK: Record<string, number> = {
  doubao: 10,
  doubao_mobile: 11,
  baiduai: 20,
  deepseek: 30,
  deepseek_mobile: 31,
  weibo_zhisou: 40,
  yuanbao: 50,
  qianwen: 60,
  quark: 70,
  kimi: 80,
  wenxinyiyan: 90,
}

export function platformMarketRank(code: string): number {
  const text = String(code || '').trim()
  if (!text) return 999
  if (PLATFORM_MARKET_RANK[text] !== undefined) return PLATFORM_MARKET_RANK[text]
  const base = text.replace(/_mobile$/, '')
  return PLATFORM_MARKET_RANK[base] ?? 999
}

export function comparePlatformCodes(left: string, right: string): number {
  const rankDiff = platformMarketRank(left) - platformMarketRank(right)
  if (rankDiff !== 0) return rankDiff
  return left.localeCompare(right, 'zh-CN')
}

export function sortPlatformCodes(codes: string[]): string[] {
  return [...codes].filter(Boolean).sort(comparePlatformCodes)
}

export function sortPlatformRows<T extends { platform?: string; code?: string }>(rows: T[]): T[] {
  return [...rows].sort((left, right) => comparePlatformCodes(left.platform || left.code || '', right.platform || right.code || ''))
}

export function sortPlatformTabs<T extends { code: string }>(rows: T[]): T[] {
  const all = rows.find(row => row.code === 'all')
  const rest = rows.filter(row => row.code !== 'all').sort((left, right) => comparePlatformCodes(left.code, right.code))
  return all ? [all, ...rest] : rest
}

export function formatPlatformLabels(codes: string[], labelMap: Record<string, string>): string {
  return sortPlatformCodes(codes).map(code => labelMap[code] || code).join('、')
}

/** 客户已购平台优先；无配置时回退到监测数据里出现的平台 */
export function resolvePurchasedPlatformCodes(
  monitoredPlatforms: string[] | null | undefined,
  fallbackCodes: string[] = [],
): string[] {
  const purchased = (monitoredPlatforms || []).filter(Boolean)
  if (purchased.length) return sortPlatformCodes(purchased)
  return sortPlatformCodes(fallbackCodes.filter(Boolean))
}
