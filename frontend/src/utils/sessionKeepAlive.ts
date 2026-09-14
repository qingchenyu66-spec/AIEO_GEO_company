import { refreshSessionApi } from '../services/auth'
import { useAuthStore } from '../stores/auth'

/** Min gap between sliding renewals while user keeps interacting. */
const RENEW_MIN_INTERVAL_MS = 5 * 60 * 1000

let started = false
let lastRenewAt = 0
let renewInFlight: Promise<void> | null = null

function isLoggedIn(): boolean {
  return Boolean(useAuthStore().session?.identity)
}

async function renewIfDue(): Promise<void> {
  if (!isLoggedIn()) return
  const now = Date.now()
  if (now - lastRenewAt < RENEW_MIN_INTERVAL_MS) return
  if (renewInFlight) return
  lastRenewAt = now
  renewInFlight = (async () => {
    try {
      await refreshSessionApi()
    } catch {
      // 401 handled by http interceptor; other errors ignore (next activity retries)
    } finally {
      renewInFlight = null
    }
  })()
  await renewInFlight
}

function onUserActivity(): void {
  void renewIfDue()
}

/** Start sliding session keep-alive. Polling APIs do not call this. */
export function startSessionKeepAlive(): void {
  if (started || typeof window === 'undefined') return
  started = true
  lastRenewAt = Date.now()
  window.addEventListener('pointerdown', onUserActivity, { passive: true })
  window.addEventListener('keydown', onUserActivity, { passive: true })
  window.addEventListener('touchstart', onUserActivity, { passive: true })
}

export function stopSessionKeepAlive(): void {
  if (!started || typeof window === 'undefined') return
  started = false
  window.removeEventListener('pointerdown', onUserActivity)
  window.removeEventListener('keydown', onUserActivity)
  window.removeEventListener('touchstart', onUserActivity)
}

/** Call after successful login / identity select so the idle clock starts now. */
export function markSessionRenewed(): void {
  lastRenewAt = Date.now()
}
