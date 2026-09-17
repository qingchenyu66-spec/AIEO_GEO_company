/** After deploy, hashed chunks may be gone; open tabs still reference old URLs. */

import { defineAsyncComponent, type AsyncComponentLoader, type Component } from 'vue'

const RELOAD_KEY = 'geo:stale-chunk-reload'
const RELOAD_TTL_MS = 15_000

export function isChunkLoadError(error: unknown): boolean {
  const message = String((error as { message?: string })?.message ?? error ?? '')
  return (
    /Failed to fetch dynamically imported module/i.test(message) ||
    /Importing a module script failed/i.test(message) ||
    /error loading dynamically imported module/i.test(message) ||
    /Loading chunk [\w-]+ failed/i.test(message) ||
    /Unable to preload CSS/i.test(message)
  )
}

function reloadOnce(): void {
  try {
    const raw = sessionStorage.getItem(RELOAD_KEY)
    const last = raw ? Number(raw) : 0
    if (Number.isFinite(last) && Date.now() - last < RELOAD_TTL_MS) {
      return
    }
    sessionStorage.setItem(RELOAD_KEY, String(Date.now()))
  } catch {
    // sessionStorage may be blocked; still attempt one reload
  }
  window.location.reload()
}

/** True if this error triggered a reload. */
export function reloadOnceOnChunkError(error: unknown): boolean {
  if (!isChunkLoadError(error)) return false
  reloadOnce()
  return true
}

/** Portal menu pages: catch lazy-import 404 that router.onError never sees. */
export function defineAsyncPage(loader: AsyncComponentLoader): Component {
  return defineAsyncComponent({
    loader,
    onError(error, _retry, fail) {
      if (reloadOnceOnChunkError(error)) return
      fail()
    },
  })
}

/** Listen for Vite preload / router / unhandled dynamic-import failures. */
export function installStaleChunkReload(options?: {
  onRouterError?: (handler: (error: unknown) => void) => void
}): void {
  window.addEventListener('vite:preloadError', (event) => {
    event.preventDefault()
    reloadOnce()
  })

  window.addEventListener('unhandledrejection', (event) => {
    if (reloadOnceOnChunkError(event.reason)) {
      event.preventDefault()
    }
  })

  options?.onRouterError?.((error) => {
    reloadOnceOnChunkError(error)
  })
}
