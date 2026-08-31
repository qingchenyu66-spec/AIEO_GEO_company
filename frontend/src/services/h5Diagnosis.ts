import axios from 'axios'
import { extractErrorDetail } from '../utils/requestError'

const http = axios.create({
  baseURL: '/api',
  timeout: 60000,
  withCredentials: true,
})

// 2026-08-31 - H5 400 只显示英文 axios 文案 - 拦截器转成后端 detail 中文
http.interceptors.response.use(
  response => response,
  error => Promise.reject(new Error(extractErrorDetail(error) || '请求失败，请稍后重试')),
)

export interface H5DiagnosisConfig {
  enabled: boolean
  price_fen: number
  price_yuan: number
  schedule_days: number
  schedule_slots_per_day: number
  schedule_total: number
  platforms: string[]
  max_prompts: number
  min_prompts: number
  oauth_required: boolean
  dev_mode: boolean
}

export interface H5DiagnosisSession {
  ready: boolean
  openid_masked: string
  dev_mode: boolean
}

export interface H5PayParams {
  appId: string
  timeStamp: string
  nonceStr: string
  package: string
  signType: string
  paySign: string
  devAutoPaid?: boolean
}

export interface H5OrderCreateResult {
  out_trade_no: string
  amount_fen: number
  pay_channel?: string
  pay_trade_type?: 'jsapi' | 'native' | string
  code_url?: string | null
  pay_params: H5PayParams | null
  dev_auto_paid?: boolean
}

export interface H5OrderStatus {
  out_trade_no: string
  status: string
  brand_name: string
  amount_fen: number
  lead_diagnosis_id: number | null
  paid_at: string | null
  contact_phone_masked: string
}

function unwrap<T>(resp: { data: { code?: number; data?: T; message?: string } }): T {
  const body = resp.data
  if (body.code !== 0) {
    throw new Error(body.message || '请求失败')
  }
  return body.data as T
}

export async function fetchH5DiagnosisConfig(): Promise<H5DiagnosisConfig> {
  const resp = await http.get('/v1/h5/diagnosis/config')
  return unwrap(resp)
}

export async function fetchH5DiagnosisSession(): Promise<H5DiagnosisSession> {
  const resp = await http.get('/v1/h5/diagnosis/session')
  return unwrap(resp)
}

export function startH5OAuth(target: 'apply' | 'landing' = 'apply') {
  window.location.href = `/api/v1/h5/diagnosis/oauth/start?target=${encodeURIComponent(target)}`
}

export async function createH5DiagnosisOrder(payload: {
  contact_phone: string
  brand_name: string
  prompts: string[]
  brand_aliases?: string
  industry?: string
  product_focus?: string
  website_url?: string
  competitors?: string
  pay_trade_type?: 'jsapi' | 'native'
  pay_channel?: 'wechat' | string
}): Promise<H5OrderCreateResult> {
  const resp = await http.post('/v1/h5/diagnosis/orders', payload)
  return unwrap(resp)
}

export async function fetchH5OrderStatus(outTradeNo: string): Promise<H5OrderStatus> {
  const resp = await http.get(`/v1/h5/diagnosis/orders/${encodeURIComponent(outTradeNo)}`)
  return unwrap(resp)
}

export async function markH5OrderDevPaid(outTradeNo: string): Promise<H5OrderStatus> {
  const resp = await http.post(`/v1/h5/diagnosis/orders/${encodeURIComponent(outTradeNo)}/dev-paid`)
  return unwrap(resp)
}

declare global {
  interface Window {
    WeixinJSBridge?: {
      invoke: (
        method: string,
        params: Record<string, string>,
        callback: (res: { err_msg?: string }) => void,
      ) => void
    }
  }
}

export function invokeWechatPay(params: H5PayParams): Promise<void> {
  return new Promise((resolve, reject) => {
    const pay = () => {
      window.WeixinJSBridge!.invoke(
        'getBrandWCPayRequest',
        {
          appId: params.appId,
          timeStamp: params.timeStamp,
          nonceStr: params.nonceStr,
          package: params.package,
          signType: params.signType,
          paySign: params.paySign,
        },
        (res) => {
          const msg = String(res?.err_msg || '')
          if (msg.includes(':ok')) resolve()
          else reject(new Error(msg || '支付未完成'))
        },
      )
    }
    if (typeof window.WeixinJSBridge === 'undefined') {
      document.addEventListener('WeixinJSBridgeReady', pay, { once: true })
    } else {
      pay()
    }
  })
}
