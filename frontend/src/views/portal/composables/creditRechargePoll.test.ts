import { describe, expect, it, vi } from 'vitest'

import { createCreditRechargePoll } from './creditRechargePoll'

function createFakeScheduler() {
  const timers = new Map<number, { fn: () => void; ms: number }>()
  let nextId = 1
  let now = 0

  return {
    schedule(fn: () => void, ms: number) {
      const id = nextId++
      timers.set(id, { fn, ms: now + ms })
      return id as unknown as ReturnType<typeof setTimeout>
    },
    clearSchedule(id: ReturnType<typeof setTimeout>) {
      timers.delete(id as unknown as number)
    },
    async flush(ms: number) {
      now += ms
      const due = [...timers.entries()]
        .filter(([, t]) => t.ms <= now)
        .sort((a, b) => a[1].ms - b[1].ms)
      for (const [id, t] of due) {
        timers.delete(id)
        t.fn()
        await Promise.resolve()
      }
    },
    pendingCount() {
      return timers.size
    },
  }
}

describe('createCreditRechargePoll', () => {
  it('paid 后触发 onPaid 并停止后续调度', async () => {
    const scheduler = createFakeScheduler()
    const fetchStatus = vi
      .fn()
      .mockResolvedValueOnce({ status: 'pending' })
      .mockResolvedValueOnce({ status: 'paid', credits_amount: 42 })
    const onPaid = vi.fn()
    const onTimeout = vi.fn()
    let active = true

    const poll = createCreditRechargePoll({
      outTradeNo: 'CR1',
      intervalMs: 1000,
      maxAttempts: 60,
      isActive: () => active,
      fetchStatus,
      onPaid,
      onTimeout,
      schedule: scheduler.schedule,
      clearSchedule: scheduler.clearSchedule,
    })
    poll.start()
    await Promise.resolve()
    expect(fetchStatus).toHaveBeenCalledTimes(1)
    expect(onPaid).not.toHaveBeenCalled()

    await scheduler.flush(1000)
    expect(fetchStatus).toHaveBeenCalledTimes(2)
    expect(onPaid).toHaveBeenCalledWith({ status: 'paid', credits_amount: 42 })
    expect(poll.isPolling()).toBe(false)
    expect(scheduler.pendingCount()).toBe(0)

    await scheduler.flush(1000)
    expect(fetchStatus).toHaveBeenCalledTimes(2)
    expect(onTimeout).not.toHaveBeenCalled()
  })

  it('stop / 失活后不再继续轮询', async () => {
    const scheduler = createFakeScheduler()
    const fetchStatus = vi.fn().mockResolvedValue({ status: 'pending' })
    let active = true

    const poll = createCreditRechargePoll({
      outTradeNo: 'CR2',
      intervalMs: 1000,
      isActive: () => active,
      fetchStatus,
      onPaid: vi.fn(),
      onTimeout: vi.fn(),
      schedule: scheduler.schedule,
      clearSchedule: scheduler.clearSchedule,
    })
    poll.start()
    await Promise.resolve()
    expect(fetchStatus).toHaveBeenCalledTimes(1)
    expect(scheduler.pendingCount()).toBe(1)

    poll.stop()
    expect(scheduler.pendingCount()).toBe(0)
    await scheduler.flush(1000)
    expect(fetchStatus).toHaveBeenCalledTimes(1)

    active = true
    poll.start()
    await Promise.resolve()
    expect(fetchStatus).toHaveBeenCalledTimes(2)
    active = false
    await scheduler.flush(1000)
    expect(fetchStatus).toHaveBeenCalledTimes(2)
    expect(scheduler.pendingCount()).toBe(0)
  })

  it('达到 maxAttempts 触发 onTimeout', async () => {
    const scheduler = createFakeScheduler()
    const fetchStatus = vi.fn().mockResolvedValue({ status: 'pending' })
    const onTimeout = vi.fn()

    const poll = createCreditRechargePoll({
      outTradeNo: 'CR3',
      intervalMs: 10,
      maxAttempts: 2,
      isActive: () => true,
      fetchStatus,
      onPaid: vi.fn(),
      onTimeout,
      schedule: scheduler.schedule,
      clearSchedule: scheduler.clearSchedule,
    })
    poll.start()
    await Promise.resolve()
    // attempt 0
    await scheduler.flush(10)
    // attempt 1
    await scheduler.flush(10)
    // attempt 2 -> timeout
    expect(fetchStatus).toHaveBeenCalledTimes(3)
    expect(onTimeout).toHaveBeenCalledTimes(1)
    expect(poll.isPolling()).toBe(false)
    expect(scheduler.pendingCount()).toBe(0)
  })

  it('连续失败从第 3 次起回调 onError，但仍继续轮询直至超时', async () => {
    const scheduler = createFakeScheduler()
    const fetchStatus = vi.fn().mockRejectedValue(new Error('network'))
    const onError = vi.fn()
    const onTimeout = vi.fn()

    const poll = createCreditRechargePoll({
      outTradeNo: 'CR4',
      intervalMs: 10,
      maxAttempts: 2,
      isActive: () => true,
      fetchStatus,
      onPaid: vi.fn(),
      onTimeout,
      onError,
      extractError: (err, fallback) => (err instanceof Error ? err.message : fallback),
      schedule: scheduler.schedule,
      clearSchedule: scheduler.clearSchedule,
    })
    poll.start()
    await Promise.resolve()
    expect(onError).not.toHaveBeenCalled()
    await scheduler.flush(10)
    expect(onError).not.toHaveBeenCalled()
    await scheduler.flush(10)
    expect(onError).toHaveBeenCalledWith('network')
    expect(onTimeout).toHaveBeenCalledTimes(1)
  })

  it('onStatus 透传每次查询结果', async () => {
    const scheduler = createFakeScheduler()
    const onStatus = vi.fn()
    const fetchStatus = vi
      .fn()
      .mockResolvedValueOnce({ status: 'pending', yuan_amount: 1 })
      .mockResolvedValueOnce({ status: 'paid', credits_amount: 5 })

    createCreditRechargePoll({
      outTradeNo: 'CR5',
      intervalMs: 5,
      isActive: () => true,
      fetchStatus,
      onStatus,
      onPaid: vi.fn(),
      onTimeout: vi.fn(),
      schedule: scheduler.schedule,
      clearSchedule: scheduler.clearSchedule,
    }).start()

    await Promise.resolve()
    expect(onStatus).toHaveBeenCalledWith({ status: 'pending', yuan_amount: 1 })
    await scheduler.flush(5)
    expect(onStatus).toHaveBeenCalledWith({ status: 'paid', credits_amount: 5 })
  })
})
