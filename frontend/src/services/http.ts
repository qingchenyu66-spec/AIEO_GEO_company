import axios, { type AxiosRequestConfig } from 'axios'
import { ElMessage } from 'element-plus'
import { useLoadingStore } from '../stores/loading'
import { readCsrfToken } from '../utils/csrf'

export const http = axios.create({
  baseURL: '/api',
  timeout: 30000,
  withCredentials: true,
  headers: {
    'Content-Type': 'application/json;charset=utf-8',
  },
})

export type GeoHttpRequestConfig = AxiosRequestConfig & {
  silentError?: boolean
  noCache?: boolean
}

interface CacheItem {
  data: unknown
  timestamp: number
  url: string
}

const cache = new Map<string, CacheItem>()
const CACHE_TTL = 5 * 60 * 1000

function getCacheKey(config: { method?: string; url?: string; params?: unknown }): string {
  const params = JSON.stringify(config.params || {})
  return `${config.method}:${config.url}:${params}`
}

function isCacheable(config: { method?: string; url?: string; params?: unknown; noCache?: boolean }): boolean {
  if (config.method !== 'get') return false
  if (config.noCache) return false
  if (config.url?.includes('/health')) return false
  return true
}

function clearRelatedCache(urlPattern: string) {
  for (const [key, item] of cache.entries()) {
    if (item.url.includes(urlPattern)) {
      cache.delete(key)
    }
  }
}

http.interceptors.request.use(
  (config) => {
    useLoadingStore().start()

    const method = (config.method || 'get').toLowerCase()
    if (!['get', 'head', 'options'].includes(method)) {
      const csrf = readCsrfToken()
      if (csrf) config.headers['X-CSRF-Token'] = csrf
    }

    return config
  },
  (error) => {
    useLoadingStore().end()
    return Promise.reject(error)
  },
)

http.interceptors.response.use(
  (response) => {
    useLoadingStore().end()
    return response
  },
  (error) => {
    useLoadingStore().end()

    const status = error.response?.status
    const url = error.config?.url || ''
    const hasResponse = Boolean(error.response)

    if (status === 401) {
      if (url.includes('/auth/login')) {
        const message = error.response?.data?.detail || error.message || '账号或密码错误'
        ElMessage.error(message)
      } else {
        ElMessage.warning('登录已过期，请重新登录')
        localStorage.removeItem('geo-auth-session')
        window.location.href = '/login'
      }
      return Promise.reject(error)
    }

    if (!hasResponse) {
      if (!(error.config as { silentError?: boolean } | undefined)?.silentError) {
        ElMessage.error(error.message || '网络异常，请检查连接后重试')
      }
      return Promise.reject(error)
    }

    return Promise.reject(error)
  },
)

export function invalidateCache(urlPattern?: string) {
  if (urlPattern) {
    clearRelatedCache(urlPattern)
  } else {
    cache.clear()
  }
}

export function getCacheStats() {
  return {
    size: cache.size,
    items: Array.from(cache.values()).map(item => ({
      url: item.url,
      age: `${Math.round((Date.now() - item.timestamp) / 1000)}s`,
    })),
  }
}

export function getWithCache<T>(url: string, params?: unknown): Promise<T> {
  if (!isCacheable({ method: 'get', url, params })) {
    return http.get(url, { params }).then(response => response.data as T)
  }

  const cacheKey = getCacheKey({ method: 'get', url, params })
  const cached = cache.get(cacheKey)

  if (cached && Date.now() - cached.timestamp < CACHE_TTL) {
    return Promise.resolve(cached.data as T)
  }

  if (cached) {
    cache.delete(cacheKey)
  }

  return http.get(url, { params }).then(response => {
    cache.set(cacheKey, {
      data: response.data,
      timestamp: Date.now(),
      url,
    })
    return response.data as T
  })
}
