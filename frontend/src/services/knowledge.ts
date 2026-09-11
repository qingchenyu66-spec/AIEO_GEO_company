import { http, type GeoHttpRequestConfig } from './http'

export type KnowledgeParseStatus = 'none' | 'parsing' | 'parsed' | 'failed'

export interface KnowledgeParseSection {
  title: string
  type: 'text' | 'list' | 'cards'
  content?: string
  items?: string[]
}

export interface KnowledgeParseResult {
  source?: string
  model?: string
  summary?: string
  keywords?: string[]
  topics?: string[]
  geo_points?: string[]
  sections?: KnowledgeParseSection[]
  extracted_chars?: number
  truncated?: boolean
}

export interface KnowledgeFileContent {
  file_id: number
  original_name: string
  char_count: number
  text: string
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

export async function getKnowledgeFileContent(fileId: number): Promise<KnowledgeFileContent> {
  const response = await http.get(`/v1/knowledge/files/${fileId}/content`)
  return response.data.data
}

export async function getKnowledgeFilePreviewObjectUrl(fileId: number): Promise<string> {
  const response = await http.get(`/v1/knowledge/files/${fileId}/preview`, {
    responseType: 'blob',
    timeout: 120_000,
  } as GeoHttpRequestConfig)
  const contentType = String(response.headers['content-type'] || 'application/pdf')
  if (contentType.includes('application/json')) {
    const text = await (response.data as Blob).text()
    let detail = '预览生成失败'
    try {
      const parsed = JSON.parse(text) as { detail?: string; message?: string }
      detail = String(parsed.detail || parsed.message || detail)
    } catch {
      detail = text.slice(0, 200) || detail
    }
    throw new Error(detail)
  }
  const blob = response.data instanceof Blob
    ? response.data
    : new Blob([response.data], { type: contentType.includes('pdf') ? contentType : 'application/pdf' })
  return URL.createObjectURL(blob)
}

function parseDownloadFilename(contentDisposition: string | undefined, fallback: string) {
  if (!contentDisposition) return fallback
  const utfMatch = contentDisposition.match(/filename\*=UTF-8''([^;]+)/i)
  if (utfMatch?.[1]) {
    try {
      return decodeURIComponent(utfMatch[1])
    } catch {
      return utfMatch[1]
    }
  }
  const plainMatch = contentDisposition.match(/filename="?([^";]+)"?/i)
  return plainMatch?.[1] || fallback
}

export async function downloadKnowledgeFile(fileId: number, fallbackName: string): Promise<string> {
  const response = await http.get(`/v1/knowledge/files/${fileId}/download`, {
    responseType: 'blob',
  })
  const contentType = String(response.headers['content-type'] || 'application/octet-stream')
  const filename = parseDownloadFilename(response.headers['content-disposition'], fallbackName)
  const blob = response.data instanceof Blob ? response.data : new Blob([response.data], { type: contentType })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  URL.revokeObjectURL(url)
  return filename
}

export async function deleteKnowledgeFile(fileId: number): Promise<void> {
  await http.delete(`/v1/knowledge/files/${fileId}`)
}
