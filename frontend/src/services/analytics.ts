import { http, type GeoHttpRequestConfig } from './http'

export interface WordCloudItem {
  word: string
  count: number
}

export interface CompetitorCompareRow {
  name: string
  is_brand?: boolean
  mention_count: number
  mention_rate: number
  first_mention_count?: number
  first_mention_rate?: number
  avg_rank: number | null
  rank_sample_count?: number
  sample_count?: number
  kpi_basis?: string
  positive_rate?: number
  negative_rate?: number
  sentiment_sample?: number
  source_count?: number
  gap_summary?: string | null
}

export interface MentionTrendSeries {
  name: string
  is_brand?: boolean
  values: number[]
}

export interface BrandInsightsTrends {
  labels: string[]
  series: MentionTrendSeries[]
}

export interface SentimentTrendSeries {
  labels: string[]
  positive: number[]
  neutral: number[]
  negative: number[]
}

export interface SentimentLeaderboardRow {
  name: string
  is_brand?: boolean
  positive_rate: number
  negative_rate: number
  sentiment_sample: number
}

export interface CompetitorPlatformCompareRow {
  platform: string
  sample_count: number
  rows: CompetitorCompareRow[]
  mention_trends?: BrandInsightsTrends
  sentiment_trends?: SentimentTrendSeries
  sentiment_rows?: SentimentLeaderboardRow[]
}

export interface CompetitorCompareSummary {
  brand_name: string | null
  competitor_count: number
  sample_total: number
  /** 本品牌日表完成样本（与工作台本期结论同源） */
  brand_sample_total?: number
  brand_mention_count?: number
  brand_kpi_basis?: string
  /** 平台 Tab 用：未按选中平台过滤的样本总数 */
  tab_sample_total?: number
  start_at?: string
  end_at?: string
  prompt_options?: string[]
  trend_day_keys?: string[]
  rows: CompetitorCompareRow[]
  platform_rows: CompetitorPlatformCompareRow[]
  /** 平台 Tab 用：各端样本数（不受当前平台筛选影响） */
  platform_tab_counts?: Array<{ platform: string; sample_count: number }>
  mention_trends?: BrandInsightsTrends
  sentiment_trends?: SentimentTrendSeries
  sentiment_rows?: SentimentLeaderboardRow[]
  sentiment_parse?: {
    parsed?: number
    pending_left?: number
    errors?: string[]
    source?: string
  }
}

/** @deprecated use CompetitorCompareRow */
export type CompetitorCompareItem = CompetitorCompareRow

/** @deprecated use CompetitorCompareSummary */
export type BrandInsightsSummary = CompetitorCompareSummary

export interface SentimentKeywordItem {
  text: string
  count: number
  subtask_id: string
  task_id: string
  subtask_ids?: string[]
}

export interface SentimentKeywordsSummary {
  positive: SentimentKeywordItem[]
  negative: SentimentKeywordItem[]
  positive_sample: number
  negative_sample: number
  source?: 'deepseek' | 'rule'
}

export interface SentimentWordCloudPlacement {
  text: string
  count: number
  subtask_id: string
  task_id: string
  x: number
  y: number
  w: number
  h: number
}

export interface SentimentWordCloudImageResult {
  image_base64: string
  width: number
  height: number
  placements: SentimentWordCloudPlacement[]
}

export async function generateSentimentWordCloudImage(payload: {
  items: SentimentKeywordItem[]
  polarity: 'positive' | 'negative'
}): Promise<SentimentWordCloudImageResult> {
  const response = await http.post('/v1/analytics/sentiment-wordcloud-image', {
    items: payload.items,
    polarity: payload.polarity,
    width: 1024,
    height: 1024,
    max_words: 72,
  }, {
    timeout: 60000,
  })
  return response.data.data
}

export async function getSentimentKeywords(params?: {
  tenant_id?: number
  platform?: string
  platforms?: string
  days?: number
  start_date?: string
  end_date?: string
  prompt?: string
  limit?: number
  llm?: boolean
}): Promise<SentimentKeywordsSummary> {
  const response = await http.get('/v1/analytics/sentiment-keywords', {
    params: { llm: true, ...params },
    timeout: 90000,
    silentError: true,
  } as GeoHttpRequestConfig)
  return response.data.data
}

export async function getWordCloud(params?: { tenant_id?: number; platform?: string; days?: number }): Promise<WordCloudItem[]> {
  const response = await http.get('/v1/analytics/wordcloud', { params })
  return response.data.data
}

export async function getCompetitorCompare(params?: {
  tenant_id?: number
  platform?: string
  platforms?: string
  days?: number
  start_date?: string
  end_date?: string
  prompt?: string
}): Promise<CompetitorCompareSummary> {
  const response = await http.get('/v1/analytics/competitor-compare', {
    params,
    timeout: 60000,
  })
  return response.data.data
}

/** @deprecated use getCompetitorCompare */
export const getBrandInsights = getCompetitorCompare

export type SourceStatRow = {
  title: string
  url: string
  site?: string | null
  count: number
  platforms?: string[]
  exposure_terms?: string[]
  questions?: string[]
  latest_time?: string | null
  has_exposure?: boolean
  category?: string | null
  category_label?: string | null
}

export type SourceCitationTrend = {
  start_at?: string | null
  end_at?: string | null
  points?: Array<{ label: string; value: number; day?: string }>
}

export type SourceAnalysisSummary = {
  tenant_id: number
  start_date?: string | null
  end_date?: string | null
  source_stats: SourceStatRow[]
  source_stats_all?: SourceStatRow[]
  source_citation_trend?: SourceCitationTrend
  source_citation_trend_by_platform?: Record<string, SourceCitationTrend>
  platform_stats?: Array<{
    platform: string
    total: number
    completed: number
    mention_rate: number
    avg_rank: number | null
  }>
}

export async function getSourceStats(params?: {
  tenant_id?: number
  start_date?: string
  end_date?: string
  platform?: string
}): Promise<SourceAnalysisSummary> {
  const response = await http.get('/v1/analytics/source-stats', {
    params,
    timeout: 60000,
  })
  return response.data.data
}
