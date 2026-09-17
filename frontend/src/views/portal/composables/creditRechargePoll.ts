/** 算力在线充值：支付结果轮询（可单测）。 */

export type CreditRechargePollStatus = {
  status: string
  credits_amount?: number
}

export type CreditRechargePollOptions = {
  outTradeNo: string
  intervalMs?: number
  /** 含首次：attempt 从 0 起，达到 maxAttempts 仍未 paid 则超时 */
  maxAttempts?: number
  isActive: () => boolean
  fetchStatus: (outTradeNo: string) => Promise<CreditRechargePollStatus>
  onStatus?: (status: CreditRechargePollStatus) => void
  onPaid: (status: CreditRechargePollStatus) => void | Promise<void>
  onTimeout: () => void
  onError?: (message: string) => void
  isCanceledError?: (error: unknown) => boolean
  extractError?: (error: unknown, fallback: string) => string
  schedule?: (fn: () => void, ms: number) => ReturnType<typeof setTimeout>
  clearSchedule?: (id: ReturnType<typeof setTimeout>) => void
}

export type CreditRechargePollController = {
  start: () => void
  stop: () => void
  isPolling: () => boolean
}

export function createCreditRechargePoll(opts: CreditRechargePollOptions): CreditRechargePollController {
  const intervalMs = opts.intervalMs ?? 2000
  const maxAttempts = opts.maxAttempts ?? 60
  const schedule = opts.schedule ?? setTimeout
  const clearSchedule = opts.clearSchedule ?? clearTimeout

  let timer: ReturnType<typeof setTimeout> | null = null
  let polling = false
  let stopped = false

  function stop() {
    stopped = true
    polling = false
    if (timer != null) {
      clearSchedule(timer)
      timer = null
    }
  }

  function isPolling() {
    return polling
  }

  async function tick(attempt: number) {
    if (stopped || !opts.isActive()) {
      stop()
      return
    }
    polling = true
    try {
      const status = await opts.fetchStatus(opts.outTradeNo)
      if (stopped || !opts.isActive()) {
        stop()
        return
      }
      opts.onStatus?.(status)
      if (status.status === 'paid') {
        stop()
        await opts.onPaid(status)
        return
      }
    } catch (error) {
      if (!opts.isCanceledError?.(error) && attempt >= 2) {
        opts.onError?.(
          opts.extractError?.(error, '查询支付结果失败') || '查询支付结果失败',
        )
      }
    }
    if (stopped || !opts.isActive()) {
      stop()
      return
    }
    if (attempt >= maxAttempts) {
      stop()
      opts.onTimeout()
      return
    }
    timer = schedule(() => {
      void tick(attempt + 1)
    }, intervalMs)
  }

  function start() {
    stopped = false
    void tick(0)
  }

  return { start, stop, isPolling }
}
