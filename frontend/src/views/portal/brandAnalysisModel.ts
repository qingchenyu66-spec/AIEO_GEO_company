/**
 * Pure helpers for Brand Analysis (方案 A 诊断看板).
 * Run: npx --yes tsx src/views/portal/brandAnalysisModel.selfcheck.ts
 */

export const WEAK_MENTION_RATE = 20
/** 样本过少时不标为「短板风险」，改为「样本不足」提示。 */
export const MIN_RISK_SAMPLES = 5

export type PlatformHighlightLike = {
  platform: string
  mention_rate: number
  avg_rank: number | null
  sample_count: number
}

export type BrandRiskItem = {
  key: string
  title: string
  kind: 'alert' | 'platform' | 'negative' | 'thin'
  badge: string
  desc: string
  tip: string
}

export function buildBrandRisks(input: {
  alerts: Array<{ level: string; message: string }>
  platforms: PlatformHighlightLike[]
  platformLabel: (code: string) => string
  formatRank: (n: number | null) => string
  negativeCount: number
  negativeRate: number
}): BrandRiskItem[] {
  const items: BrandRiskItem[] = []

  input.alerts
    .filter(alert => alert.level === 'warn')
    .forEach((alert, index) => {
      const msg = alert.message.trim()
      items.push({
        key: `alert-${index}`,
        title: msg.length > 32 ? `${msg.slice(0, 32)}…` : msg,
        kind: 'alert',
        badge: '系统提醒',
        desc: msg,
        tip: '建议在「GEO 监测」核对具体问法与回答。',
      })
    })

  const ranked = [...input.platforms]
    .filter(row => row.sample_count > 0)
    .sort((a, b) => a.mention_rate - b.mention_rate)

  ranked.forEach(row => {
    const name = input.platformLabel(row.platform)
    if (row.sample_count < MIN_RISK_SAMPLES) {
      items.push({
        key: `thin-${row.platform}`,
        title: `${name} 样本不足`,
        kind: 'thin',
        badge: '样本不足',
        desc: `本轮仅 ${row.sample_count} 条样本，暂不宜下结论。`,
        tip: '待样本累积后再判断是否为真实短板。',
      })
      return
    }
    if (row.mention_rate >= WEAK_MENTION_RATE) return
    items.push({
      key: `plat-${row.platform}`,
      title: `${name} 提及率偏低`,
      kind: 'platform',
      badge: '平台短板',
      desc: `本轮样本 ${row.sample_count} 条，提及率约 ${row.mention_rate.toFixed(1)}%`
        + `${row.avg_rank != null ? `，均位 ${input.formatRank(row.avg_rank)}` : ''}。`,
      tip: '可针对该平台补可核验语料或调整监测词覆盖。',
    })
  })

  if (input.negativeCount > 0) {
    items.push({
      key: 'negative',
      title: '口碑负面样本',
      kind: 'negative',
      badge: `${input.negativeCount} 条`,
      desc: `曝光类监测中负面占比 ${input.negativeRate}%。`,
      tip: '建议在「GEO 监测」查看具体问法与回答摘录。',
    })
  }

  // 短板优先，样本不足靠后；最多 6 条
  const priority = { platform: 0, negative: 1, alert: 2, thin: 3 } as const
  return items
    .sort((a, b) => priority[a.kind] - priority[b.kind])
    .slice(0, 6)
}

export function buildBrandConclusions(input: {
  platformCount: number
  platformLabels: string
  healthScore: number | null | undefined
  healthLabel: string
  riskActionCount: number
}): string[] {
  const bullets: string[] = []
  bullets.push(
    `已购 ${input.platformCount} 个平台（${input.platformLabels || '—'}）本轮有可读样本。`,
  )
  if (input.riskActionCount > 0) {
    bullets.push(`需优先跟进 ${input.riskActionCount} 项短板/风险（见上方问题区）。`)
  } else {
    bullets.push('本轮未发现达到样本门槛的平台短板，整体露出相对稳定。')
  }
  const health = input.healthScore != null ? `${input.healthScore}（${input.healthLabel}）` : '—'
  bullets.push(`健康分 ${health}；持续分端跟踪，勿合并桌面/移动统计。`)
  return bullets.slice(0, 3)
}

export function buildBrandSuggestions(input: {
  weakPlatforms: string[]
  negativeCount: number
  competitorCount: number
}): string[] {
  const items: string[] = []
  if (input.weakPlatforms.length) {
    items.push(`补强 ${input.weakPlatforms.join('、')} 的可核验案例与场景证据。`)
  }
  if (input.negativeCount > 0) {
    items.push('针对负面口碑样本补正事实与引用来源。')
  }
  if (input.competitorCount > 0) {
    items.push('结合竞品对比，突出差异化证据而非泛化套话。')
  }
  if (!items.length) {
    items.push('保持分端复盘节奏，关注提及率与均位的周环比变化。')
  }
  return items.slice(0, 2)
}
