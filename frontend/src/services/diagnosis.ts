import { http } from './http'

export interface DiagnosisRecord {
  id: number
  tenant_id: number
  diagnosis_title: string
  health_score: number
  sentiment_summary: string | null
  strength_points: string | null
  weakness_points: string | null
  recommendation: string | null
  diagnosis_platforms: string[]
  reference_count: number
  status: string
  created_at: string
}

export async function getDiagnosisRecords(tenantId?: number | null): Promise<DiagnosisRecord[]> {
  const response = await http.get('/v1/diagnosis/records', { params: tenantId ? { tenant_id: tenantId } : {} })
  return response.data.data
}

export async function getDiagnosisDetail(recordId: number): Promise<DiagnosisRecord> {
  const response = await http.get(`/v1/diagnosis/records/${recordId}`)
  return response.data.data
}

export async function createDiagnosis(payload: { tenant_id: number; diagnosis_title: string; health_score: number; strength_points?: string; weakness_points?: string; recommendation?: string; diagnosis_platforms?: string[] }): Promise<{ id: number }> {
  const response = await http.post('/v1/diagnosis/records', payload)
  return response.data.data
}
