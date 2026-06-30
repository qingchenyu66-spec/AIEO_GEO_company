import { http, invalidateCache } from './http'


export interface BrandAsset {
  id: number
  tenant_id: number
  company_full_name: string
  brand_name: string
  brand_short_name: string | null
  monitor_keywords: string[]
  aliases: string[]
  product_keywords: string[]
  monitored_platforms: string[]
  keyword_groups: BrandKeywordGroup[]
  region_code: string | null
  official_url: string | null
  description: string | null
  schedule_type: 'daily_times' | 'fixed_times' | 'weekly' | 'monthly'
  schedule_times: string[]
  schedule_frequency: number
  schedule_weekdays: number[]
  schedule_month_days: number[]
}

export interface BrandKeywordGroup {
  id: number | null
  tenant_id?: number
  name?: string
  monitor_keyword: string
  monitor_keywords?: string[]
  exposure_terms: string[]
  sort_order: number
  status: boolean
}

export function defaultKeywordGroupName(index: number) {
  return `词组 ${index + 1}`
}

export function keywordGroupDisplayName(group: BrandKeywordGroup, index = group.sort_order ?? 0) {
  return (group.name || '').trim() || defaultKeywordGroupName(index)
}

export function keywordGroupFilterValue(group: BrandKeywordGroup, index = group.sort_order ?? 0) {
  return keywordGroupDisplayName(group, index)
}

export function keywordGroupMonitorKeywords(group: BrandKeywordGroup): string[] {
  const fromList = [...new Set((group.monitor_keywords || []).map(item => item.trim()).filter(Boolean))]
  if (fromList.length) return fromList
  const primary = (group.monitor_keyword || '').trim()
  return primary ? [primary] : []
}

export function formatKeywordGroupLabel(group: BrandKeywordGroup, index = group.sort_order ?? 0): string {
  const title = keywordGroupDisplayName(group, index)
  const exposure = (group.exposure_terms || []).map(term => term.trim()).filter(Boolean)
  if (!exposure.length) return title
  return `${title}（露出：${exposure.join('、')}）`
}

export function findKeywordGroupByFilter(filterValue: string, groups: BrandKeywordGroup[]): BrandKeywordGroup | null {
  const text = filterValue.trim()
  if (!text) return null
  return groups.find((group, index) => (
    keywordGroupDisplayName(group, index) === text
    || keywordGroupMonitorKeywords(group).includes(text)
  )) || null
}

export interface BrandCompetitor {
  id: number
  tenant_id: number
  name: string
  short_name: string | null
  aliases: string[]
  website_url: string | null
  category: string | null
}

export interface BrandAssetPayload {
  tenant_id?: number | null
  company_full_name: string
  brand_name: string
  brand_short_name?: string | null
  monitor_keywords: string[]
  aliases: string[]
  product_keywords: string[]
  monitored_platforms: string[]
  keyword_groups: BrandKeywordGroup[]
  region_code?: string | null
  official_url?: string | null
  description?: string | null
  schedule_type: 'daily_times' | 'fixed_times' | 'weekly' | 'monthly'
  schedule_times: string[]
  schedule_frequency: number
  schedule_weekdays: number[]
  schedule_month_days: number[]
}

export interface CompetitorPayload {
  tenant_id?: number | null
  name: string
  short_name?: string | null
  aliases: string[]
  website_url?: string | null
  category?: string | null
}

export interface BrandAssetResponse {
  tenant_id: number
  asset: BrandAsset | null
  competitors: BrandCompetitor[]
}

export async function getBrandAsset(tenantId?: number | null): Promise<BrandAssetResponse> {
  const response = await http.get('/v1/brand/asset', { params: tenantId ? { tenant_id: tenantId } : {} })
  return response.data.data
}

export async function saveBrandAsset(payload: BrandAssetPayload): Promise<BrandAssetResponse> {
  const response = await http.put('/v1/brand/asset', payload)
  invalidateCache('/v1/brand/asset')
  return response.data.data
}

export async function createCompetitor(payload: CompetitorPayload): Promise<BrandCompetitor> {
  const response = await http.post('/v1/brand/competitors', payload)
  invalidateCache('/v1/brand/asset')
  return response.data.data
}

export async function updateCompetitor(id: number, payload: CompetitorPayload): Promise<BrandCompetitor> {
  const response = await http.put(`/v1/brand/competitors/${id}`, payload)
  invalidateCache('/v1/brand/asset')
  return response.data.data
}

export async function deleteCompetitor(id: number, tenantId?: number | null): Promise<void> {
  await http.delete(`/v1/brand/competitors/${id}`, { params: tenantId ? { tenant_id: tenantId } : {} })
  invalidateCache('/v1/brand/asset')
}
