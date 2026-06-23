import { http } from './http'

export interface HealthData {
  service: string
  environment: string
  api: string
  database: string
  timestamp: string
}

export async function getHealth(): Promise<HealthData> {
  const response = await http.get('/v1/health')
  return response.data.data
}

