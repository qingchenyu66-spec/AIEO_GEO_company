import axios from 'axios'

export const http = axios.create({
  baseURL: '/api',
  timeout: 10000,
  headers: {
    'Content-Type': 'application/json;charset=utf-8',
  },
})

http.interceptors.request.use((config) => {
  const raw = localStorage.getItem('geo-auth-session')
  if (raw) {
    const session = JSON.parse(raw)
    if (session.access_token) config.headers.Authorization = `Bearer ${session.access_token}`
  }
  return config
})
