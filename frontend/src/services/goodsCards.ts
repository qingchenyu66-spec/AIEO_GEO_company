import { http } from './http'

export interface GoodsCardKpi {
  out_rate: number | null
  out_note: string
  brand_rate: number | null
  brand_note: string
  gap_vs_top_comp: number | null
  gap_note: string
  unknown_rate: number | null
  unknown_note: string
}

export interface GoodsCardDiagnosis {
  headline: string
  opportunity: string
  risk_title: string
  risk_text: string
  priority_text: string
  actions: string[]
}

export interface GoodsCardHit {
  subtask_id: string
  platform: string
  platform_cn: string
  prompt: string
  title: string
  thumbnail: string | null
  price: string | null
  mall: string | null
  url: string | null
  link_kind: 'http' | 'app' | 'none'
  brand_hit: boolean
  brand_term: string | null
  comp_hits: string[]
  page_screenshot: string | null
  updated_at: string | null
}

export interface GoodsCardSummary {
  tenant_id: number
  brand_label: string
  start_date: string
  end_date: string
  has_mobile_platform: boolean
  empty_reason: 'no_mobile_platform' | 'no_completed_samples' | 'no_goods' | null
  denominator_platforms: string[]
  denominator_platform_labels: string[]
  sample_total: number
  goods_task_total: number
  kpi: GoodsCardKpi
  diagnosis: GoodsCardDiagnosis | null
  brand_competitor_rows: Array<{
    name: string
    is_brand: boolean
    hit: number
    rate: number | null
  }>
  prompt_rows: Array<{
    prompt: string
    total: number
    goods: number
    out_rate: number | null
    brand: number
    brand_rate: number | null
    is_brand_prompt: boolean
  }>
  platform_rows: Array<{
    platform: string
    platform_cn: string
    total: number
    goods: number
    out_rate: number | null
    brand: number
    brand_rate: number | null
  }>
  hits: GoodsCardHit[]
  stats_note: string
}

export async function fetchGoodsCardSummary(params: {
  tenant_id?: number | null
  days?: number
  start_date?: string | null
  end_date?: string | null
}) {
  const res = await http.get('/v1/analytics/goods-cards/summary', {
    params: {
      tenant_id: params.tenant_id || undefined,
      days: params.days ?? 7,
      start_date: params.start_date || undefined,
      end_date: params.end_date || undefined,
    },
  })
  return res.data.data as GoodsCardSummary
}
