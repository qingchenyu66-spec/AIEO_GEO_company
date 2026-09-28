import { http } from './http'

export type KeywordMinerExample = {
  id: number
  kind: string
  industry: string
  product_tags: string[]
  stage: string
  word: string
  answer: string
  intent: string
  heat: number | null
  note: string
  edit_reason: string
  status: string
  source_job_id: string | null
  source_company: string
  source_product: string
  use_count: number
  created_at: number | null
  updated_at: number | null
}

export async function listKeywordMinerExamples(params: {
  kind?: string
  industry?: string
  status?: string
  q?: string
  limit?: number
} = {}) {
  const response = await http.get('/v1/keyword-miner/examples', { params })
  return response.data.data as { items: KeywordMinerExample[] }
}

export async function updateKeywordMinerExample(
  id: number,
  body: Partial<{
    industry: string
    stage: string
    word: string
    answer: string
    intent: string
    heat: number | null
    note: string
    edit_reason: string
    status: string
    product_tags: string[]
  }>,
) {
  const response = await http.patch(`/v1/keyword-miner/examples/${id}`, body)
  return response.data.data as KeywordMinerExample
}
