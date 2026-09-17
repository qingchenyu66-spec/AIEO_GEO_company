import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { installStaleChunkReload, isChunkLoadError, reloadOnceOnChunkError } from './reloadOnStaleChunk'

function mockSessionStorage() {
  const store = new Map<string, string>()
  return {
    getItem: (key: string) => store.get(key) ?? null,
    setItem: (key: string, value: string) => {
      store.set(key, value)
    },
    clear: () => {
      store.clear()
    },
    removeItem: (key: string) => {
      store.delete(key)
    },
  }
}

describe('reloadOnStaleChunk', () => {
  const listeners = new Map<string, Set<EventListener>>()

  beforeEach(() => {
    listeners.clear()
    vi.stubGlobal('sessionStorage', mockSessionStorage())
    vi.stubGlobal('location', { reload: vi.fn() })
    vi.stubGlobal('window', {
      addEventListener: (type: string, listener: EventListener) => {
        if (!listeners.has(type)) listeners.set(type, new Set())
        listeners.get(type)!.add(listener)
      },
      location: { reload: vi.fn() },
      dispatchEvent: (event: Event) => {
        const set = listeners.get(event.type)
        if (!set) return true
        for (const listener of set) listener(event)
        return true
      },
    })
    ;(globalThis as unknown as { window: { location: { reload: ReturnType<typeof vi.fn> } } }).window.location =
      globalThis.location as { reload: ReturnType<typeof vi.fn> }
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('detects common chunk load error messages', () => {
    expect(isChunkLoadError(new TypeError('Failed to fetch dynamically imported module: http://x/a.js'))).toBe(true)
    expect(isChunkLoadError(new Error('navigation cancelled'))).toBe(false)
  })

  it('vite:preloadError triggers one reload', () => {
    installStaleChunkReload()
    const event = new Event('vite:preloadError')
    const preventDefault = vi.spyOn(event, 'preventDefault')
    window.dispatchEvent(event)
    expect(preventDefault).toHaveBeenCalled()
    expect(window.location.reload).toHaveBeenCalledTimes(1)
  })

  it('unhandledrejection chunk error triggers reload', () => {
    installStaleChunkReload()
    const event = new Event('unhandledrejection') as Event & {
      reason: Error
      preventDefault: () => void
    }
    event.reason = new TypeError('Failed to fetch dynamically imported module: http://x/a.js')
    event.preventDefault = vi.fn()
    const set = listeners.get('unhandledrejection')
    expect(set).toBeTruthy()
    for (const listener of set!) listener(event)
    expect(event.preventDefault).toHaveBeenCalled()
    expect(window.location.reload).toHaveBeenCalledTimes(1)
  })

  it('router chunk load error triggers reload', () => {
    let routerHandler: ((error: unknown) => void) | undefined
    installStaleChunkReload({
      onRouterError: (handler) => {
        routerHandler = handler
      },
    })
    routerHandler?.(new TypeError('Failed to fetch dynamically imported module: http://x/a.js'))
    expect(window.location.reload).toHaveBeenCalledTimes(1)
  })

  it('reloadOnceOnChunkError ignores non-chunk errors', () => {
    expect(reloadOnceOnChunkError(new Error('navigation cancelled'))).toBe(false)
    expect(window.location.reload).not.toHaveBeenCalled()
  })
})
