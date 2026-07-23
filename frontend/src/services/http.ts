import axios, { type AxiosRequestConfig } from 'axios'
import { ElMessage } from 'element-plus'
import { useLoadingStore } from '../stores/loading'
import { readCsrfToken } from '../utils/csrf'
import { isRequestCanceled } from '../utils/requestError'

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

    // FormData 必须由浏览器自带 multipart boundary；默认 json Content-Type 会导致上传无响应
    if (typeof FormData !== 'undefined' && config.data instanceof FormData) {
      if (config.headers && typeof (config.headers as { delete?: (k: string) => void }).delete === 'function') {
        ;(config.headers as { delete: (k: string) => void }).delete('Content-Type')
      } else if (config.headers) {
        delete (config.headers as Record<string, unknown>)['Content-Type']
      }
    }

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
      // 页面切换/列表重拉会 abort 旧请求；axios message 常为 "canceled"，不能当网络错误弹红条
      if (isRequestCanceled(error)) return Promise.reject(error)
      if (!(error.config as { silentError?: boolean } | undefined)?.silentError) {
        ElMessage.error(error.message || '网络异常，请检查连接后重试')
      }
      return Promise.reject(error)
    }

    if (status === 403) {
      if (!(error.config as { silentError?: boolean } | undefined)?.silentError) {
        const message = error.response?.data?.detail || '当前账号无权执行此操作'
        ElMessage.warning(typeof message === 'string' ? message : '当前账号无权执行此操作')
      }
      return Promise.reject(error)
    }

    if (status && status >= 500) {
      if (!(error.config as { silentError?: boolean } | undefined)?.silentError) {
        const message = error.response?.data?.detail || '服务暂时不可用，请稍后重试'
        ElMessage.error(typeof message === 'string' ? message : '服务暂时不可用，请稍后重试')
      }
      return Promise.reject(error)
    }

    return Promise.reject(error)
  },
)

/** 写操作后调用；客户端 GET 缓存已移除，保留 API 供 mutation 钩子使用。 */
export function invalidateCache(_urlPattern?: string) {}
