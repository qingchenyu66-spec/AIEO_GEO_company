import { http } from './http'

export type KnowledgeParseStatus = 'none' | 'parsing' | 'parsed' | 'failed'

export interface KnowledgeParseResult {
  source?: string
  model?: string
  summary?: string
  keywords?: string[]
  topics?: string[]
  geo_points?: string[]
  extracted_chars?: number
  truncated?: boolean
}

export interface KnowledgeFileRecord {
  id: number
  tenant_id: number
  original_name: string
  file_ext: string
  file_size: number
  status: string
  parse_status: KnowledgeParseStatus
  parse_error?: string | null
  parsed_at?: string | null
  parse_result?: KnowledgeParseResult | null
  created_at: string
}

export async function getKnowledgeFiles(tenantId?: number | null): Promise<KnowledgeFileRecord[]> {
  const response = await http.get('/v1/knowledge/files', { params: tenantId ? { tenant_id: tenantId } : {} })
  return response.data.data
}

export async function uploadKnowledgeFile(file: File, tenantId?: number | null): Promise<KnowledgeFileRecord> {
  const form = new FormData()
  form.append('file', file)
  if (tenantId) form.append('tenant_id', String(tenantId))
  const response = await http.post('/v1/knowledge/files', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 30000,
  })
  return response.data.data
}

export async function parseKnowledgeFile(fileId: number): Promise<KnowledgeFileRecord> {
  const response = await http.post(`/v1/knowledge/files/${fileId}/parse`)
  return response.data.data
}

export async function deleteKnowledgeFile(fileId: number): Promise<void> {
  await http.delete(`/v1/knowledge/files/${fileId}`)
}
