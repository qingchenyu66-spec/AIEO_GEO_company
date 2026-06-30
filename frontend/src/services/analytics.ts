import { http } from './http'

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
  positive_rate?: number
  negative_rate?: number
  sentiment_sample?: number
  source_count?: number
  gap_summary?: string | null
}

export interface CompetitorPlatformCompareRow {
  platform: string
  sample_count: number
  rows: CompetitorCompareRow[]
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

export interface CompetitorCompareSummary {
  brand_name: string | null
  competitor_count: number
  sample_total: number
  start_at?: string
  end_at?: string
  prompt_options?: string[]
  trend_day_keys?: string[]
  rows: CompetitorCompareRow[]
  platform_rows: CompetitorPlatformCompareRow[]
  mention_trends?: BrandInsightsTrends
  sentiment_trends?: SentimentTrendSeries
  sentiment_rows?: SentimentLeaderboardRow[]
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

export async function getSentimentKeywords(params?: {
  tenant_id?: number
  platform?: string
  platforms?: string
  days?: number
  prompt?: string
  limit?: number
}): Promise<SentimentKeywordsSummary> {
  const response = await http.get('/v1/analytics/sentiment-keywords', { params })
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
  prompt?: string
}): Promise<CompetitorCompareSummary> {
  const response = await http.get('/v1/analytics/competitor-compare', { params })
  return response.data.data
}

/** @deprecated use getCompetitorCompare */
export const getBrandInsights = getCompetitorCompare
