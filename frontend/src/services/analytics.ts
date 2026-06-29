import { http } from './http'

export interface WordCloudItem {
  word: string
  count: number
}

export interface SentimentTrendPoint {
  date: string
  positive_rate: number
  negative_rate: number
  neutral_rate: number
  total: number
}

export interface CompetitorCompareItem {
  name: string
  mention_rate: number
  avg_rank: number | null
  positive_rate: number
  negative_rate: number
  source_count: number
  gap_summary: string | null
}

export async function getWordCloud(params?: { tenant_id?: number; platform?: string; days?: number }): Promise<WordCloudItem[]> {
  const response = await http.get('/v1/analytics/wordcloud', { params })
  return response.data.data
}

export async function getSentimentTrends(params?: { tenant_id?: number; platform?: string; days?: number }): Promise<SentimentTrendPoint[]> {
  const response = await http.get('/v1/analytics/sentiment-trends', { params })
  return response.data.data
}

export async function getCompetitorCompare(params?: { tenant_id?: number; platform?: string }): Promise<CompetitorCompareItem[]> {
  const response = await http.get('/v1/analytics/competitor-compare', { params })
  return response.data.data
}
