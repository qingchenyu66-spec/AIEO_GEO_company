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

/** 写操作后调用；客户端 GET 缓存已移除，保留 API 供 mutation 钩子使用。 */
export function invalidateCache(_urlPattern?: string) {}
