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
  brand_word_groups?: BrandWordGroup[]
  region_codes: string[]
  official_url: string | null
  description: string | null
  schedule_type: 'daily_times' | 'fixed_times' | 'weekly' | 'monthly'
  schedule_times: string[]
  schedule_frequency: number
  schedule_weekdays: number[]
  schedule_month_days: number[]
}

export interface PlatformSelection {
  code: string
  mode: 'standard' | 'reasoning' | 'search' | 'reasoning_search'
  screenshot: 0 | 1 | 2
}

export interface BrandKeywordGroup {
  id: number | null
  tenant_id?: number
  name?: string
  display_name?: string
  monitor_keyword: string
  monitor_keywords?: string[]
  exposure_terms: string[]
  platforms?: Array<string | PlatformSelection>
  sort_order: number
  status: boolean
}

/** 品牌词组：无露出词；匹配靠品牌词本身 + 企业资产别名。 */
export interface BrandWordGroup {
  id: number | null
  tenant_id?: number
  name?: string
  display_name?: string
  monitor_keyword: string
  monitor_keywords?: string[]
  platforms?: Array<string | PlatformSelection>
  run_mode: 'once' | 'weekly'
  sort_order: number
  status: boolean
}

export function defaultBrandWordGroupName(index: number) {
  return `品牌词组 ${index + 1}`
}

function coercePlatformMode(mode: unknown): PlatformSelection['mode'] {
  const value = String(mode || '').trim()
  // 2026-08-18 - 快速=search；深度=reasoning_search（深度+联网）
  if (value === 'reasoning' || value === 'reasoning_search') {
    return 'reasoning_search'
  }
  if (value === 'search') return 'search'
  // standard / 非法 / 空 → search
  return 'search'
}

export function normalizePlatformSelection(raw: string | PlatformSelection | null | undefined): PlatformSelection | null {
  if (!raw) return null
  if (typeof raw === 'string') {
    const code = raw.trim()
    if (!code) return null
    return { code, mode: 'search', screenshot: 1 }
  }
  const code = String(raw.code || '').trim()
  if (!code) return null
  return { code, mode: coercePlatformMode(raw.mode), screenshot: 1 }
}

export function normalizePlatformSelections(raw: Array<string | PlatformSelection> | null | undefined): PlatformSelection[] {
  const seen = new Set<string>()
  const rows: PlatformSelection[] = []
  for (const item of raw || []) {
    const entry = normalizePlatformSelection(item)
    if (!entry || seen.has(entry.code)) continue
    seen.add(entry.code)
    rows.push(entry)
  }
  return rows
}

export function platformSelectionCodes(raw: Array<string | PlatformSelection> | null | undefined): string[] {
  return normalizePlatformSelections(raw).map(item => item.code)
}

export function defaultKeywordGroupName(index: number) {
  return `词组 ${index + 1}`
}

export function keywordGroupDisplayName(group: BrandKeywordGroup, index = group.sort_order ?? 0) {
  return (group.name || '').trim() || defaultKeywordGroupName(index)
}

export function keywordGroupSelectValue(group: BrandKeywordGroup, index = group.sort_order ?? 0): string {
  if (group.id != null) return `id:${group.id}`
  return `idx:${index}`
}

export function findKeywordGroupBySelectValue(value: string, groups: BrandKeywordGroup[]): BrandKeywordGroup | null {
  const text = value.trim()
  if (!text) return null
  if (text.startsWith('id:')) {
    const id = text.slice(3)
    return groups.find(group => group.id != null && String(group.id) === id) || null
  }
  if (text.startsWith('idx:')) {
    const idx = Number(text.slice(4))
    if (!Number.isFinite(idx)) return null
    const sorted = [...groups].sort((left, right) => (left.sort_order ?? 0) - (right.sort_order ?? 0))
    return sorted[idx] || null
  }
  return findKeywordGroupByFilter(text, groups)
}

export function keywordGroupFilterValue(group: BrandKeywordGroup, index = group.sort_order ?? 0) {
  return formatKeywordGroupLabel(group, index)
}

export function keywordGroupMonitorKeywords(group: {
  monitor_keyword?: string | null
  monitor_keywords?: string[] | null
}): string[] {
  const fromList = [...new Set((group.monitor_keywords || []).map(item => item.trim()).filter(Boolean))]
  if (fromList.length) return fromList
  const primary = (group.monitor_keyword || '').trim()
  return primary ? [primary] : []
}

function truncateKeywordText(text: string, max = 24): string {
  const cleaned = text.trim()
  if (cleaned.length <= max) return cleaned
  return `${cleaned.slice(0, max - 1)}…`
}

function isGenericKeywordGroupName(name: string | null | undefined): boolean {
  const text = (name || '').trim()
  return !text || /^词组(\s*\d+)?$/.test(text)
}

export function formatKeywordGroupLabel(group: BrandKeywordGroup, index = group.sort_order ?? 0): string {
  const displayName = (group.display_name || '').trim()
  if (displayName && !isGenericKeywordGroupName(displayName)) return displayName

  const title = keywordGroupDisplayName(group, index)
  const keywords = keywordGroupMonitorKeywords(group)
  if (!keywords.length) {
    const primary = (group.monitor_keyword || '').trim()
    if (primary) return truncateKeywordText(primary, 36)
    return displayName || title
  }

  const genericTitle = isGenericKeywordGroupName(group.name)
  if (keywords.length === 1) {
    if (genericTitle) return truncateKeywordText(keywords[0], 36)
    return `${title} · ${truncateKeywordText(keywords[0], 24)}`
  }
  if (genericTitle) {
    return `${truncateKeywordText(keywords[0], 18)} 等 ${keywords.length} 个监测词`
  }
  return `${title} · ${truncateKeywordText(keywords[0], 16)} 等 ${keywords.length} 词`
}

/** Full hint for select tooltip: monitor + exposure terms. */
export function formatKeywordGroupDetailHint(group: BrandKeywordGroup): string {
  const keywords = keywordGroupMonitorKeywords(group)
  const exposure = (group.exposure_terms || []).map(term => term.trim()).filter(Boolean)
  const platforms = platformSelectionCodes(group.platforms || [])
  const parts: string[] = []
  if (keywords.length) parts.push(`监测词：${keywords.join('、')}`)
  if (exposure.length) parts.push(`露出词：${exposure.join('、')}`)
  if (platforms.length) parts.push(`平台：${platforms.join('、')}`)
  return parts.join(' · ')
}

export function findKeywordGroupByFilter(filterValue: string, groups: BrandKeywordGroup[]): BrandKeywordGroup | null {
  const text = filterValue.trim()
  if (!text) return null
  return groups.find((group, index) => (
    keywordGroupFilterValue(group, index) === text
    || keywordGroupDisplayName(group, index) === text
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
  region_codes?: string[]
  official_url?: string | null
  description?: string | null
  schedule_type: 'daily_times' | 'fixed_times' | 'weekly' | 'monthly'
  schedule_times: string[]
  schedule_frequency: number
  schedule_weekdays: number[]
  schedule_month_days: number[]
  service_start_date?: string | null
  service_end_date?: string | null
  brand_word_groups?: BrandWordGroup[]
  competitors?: Array<{
    name: string
    short_name?: string | null
    aliases?: string[]
    website_url?: string | null
    category?: string | null
  }>
  logo_staging_key?: string | null
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

export async function uploadLogoStaging(file: File): Promise<{ staging_key: string; filename: string }> {
  const form = new FormData()
  form.append('file', file)
  const response = await http.post('/v1/brand/logo-staging', form)
  return response.data.data
}

export function logoStagingUrl(stagingKey: string): string {
  return `/api/v1/brand/logo-staging/${encodeURIComponent(stagingKey)}`
}

export interface BrandWordGroupsPayload {
  tenant_id?: number | null
  groups: BrandWordGroup[]
}

export interface BrandWordGroupsResponse extends BrandAssetResponse {
  once_submitted?: Array<{ status?: string; message?: string; keyword?: string | null }>
}

export async function saveBrandWordGroups(payload: BrandWordGroupsPayload): Promise<BrandWordGroupsResponse> {
  const response = await http.put('/v1/brand/brand-word-groups', payload)
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
