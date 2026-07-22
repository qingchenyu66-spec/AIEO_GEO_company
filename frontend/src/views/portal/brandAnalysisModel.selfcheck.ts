/**
 * Run: npx --yes tsx src/views/portal/brandAnalysisModel.selfcheck.ts
 */
import {
  MIN_RISK_SAMPLES,
  WEAK_MENTION_RATE,
  buildBrandConclusions,
  buildBrandRisks,
  buildBrandSuggestions,
} from './brandAnalysisModel'

function assert(cond: unknown, msg: string): asserts cond {
  if (!cond) throw new Error(msg)
}

const formatRank = (n: number | null) => (n == null ? '—' : String(n))
const platformLabel = (code: string) => code

const risks = buildBrandRisks({
  alerts: [{ level: 'warn', message: '任务延迟' }],
  platforms: [
    { platform: 'a', mention_rate: 10, avg_rank: 5, sample_count: 2 },
    { platform: 'b', mention_rate: 8, avg_rank: 4, sample_count: MIN_RISK_SAMPLES },
    { platform: 'c', mention_rate: WEAK_MENTION_RATE + 5, avg_rank: 2, sample_count: 20 },
  ],
  platformLabel,
  formatRank,
  negativeCount: 1,
  negativeRate: 12,
})

assert(risks.some(r => r.kind === 'thin' && r.key === 'thin-a'), 'low-sample must be thin, not platform shortfall')
assert(risks.some(r => r.kind === 'platform' && r.key === 'plat-b'), 'enough samples + weak rate => platform risk')
assert(!risks.some(r => r.key === 'plat-c'), 'healthy platform must not be risk')
assert(risks.some(r => r.kind === 'negative'), 'negative samples become risk')

const conclusions = buildBrandConclusions({
  platformCount: 2,
  platformLabels: 'A、B',
  healthScore: 80,
  healthLabel: '良好',
  riskActionCount: 1,
})
assert(conclusions.length === 3, 'exactly 3 conclusion bullets')
assert(!conclusions.some(line => /提及率|均位|Top3/.test(line)), 'conclusions must not restate KPI tiles')

const suggestions = buildBrandSuggestions({
  weakPlatforms: ['豆包'],
  negativeCount: 0,
  competitorCount: 2,
})
assert(suggestions.length === 2, 'exactly 2 suggestions when enough signals')
assert(suggestions[0].includes('豆包'), 'weak platforms lead suggestions')

console.log('brandAnalysisModel.selfcheck ok')
