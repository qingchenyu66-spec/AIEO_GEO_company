/** After deploy, hashed chunks are deleted; open tabs still reference old URLs. */

const RELOAD_KEY = 'geo:stale-chunk-reload'
const RELOAD_TTL_MS = 15_000

function isChunkLoadError(error: unknown): boolean {
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

/** Listen for Vite preload failures and router dynamic-import failures. */
export function installStaleChunkReload(options?: {
  onRouterError?: (handler: (error: unknown) => void) => void
}): void {
  window.addEventListener('vite:preloadError', (event) => {
    event.preventDefault()
    reloadOnce()
  })

  options?.onRouterError?.((error) => {
    if (isChunkLoadError(error)) {
      reloadOnce()
    }
  })
}
