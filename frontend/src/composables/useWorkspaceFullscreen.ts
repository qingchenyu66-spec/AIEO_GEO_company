import { onBeforeUnmount, onMounted, readonly, ref } from 'vue'

function getFullscreenElement(): Element | null {
  return document.fullscreenElement
    || (document as Document & { webkitFullscreenElement?: Element }).webkitFullscreenElement
    || null
}

async function requestAppFullscreen() {
  const root = document.documentElement
  if (root.requestFullscreen) {
    await root.requestFullscreen()
    return
  }
  const legacy = root as HTMLElement & { webkitRequestFullscreen?: () => Promise<void> }
  if (legacy.webkitRequestFullscreen) {
    await legacy.webkitRequestFullscreen()
  }
}

async function exitAppFullscreen() {
  if (document.exitFullscreen) {
    await document.exitFullscreen()
    return
  }
  const legacy = document as Document & { webkitExitFullscreen?: () => Promise<void> }
  if (legacy.webkitExitFullscreen) {
    await legacy.webkitExitFullscreen()
  }
}

export function useWorkspaceFullscreen() {
  const isFullscreen = ref(false)

  function syncFromBrowser() {
    isFullscreen.value = Boolean(getFullscreenElement())
  }

  async function enter() {
    isFullscreen.value = true
    try {
      if (!getFullscreenElement()) {
        await requestAppFullscreen()
      }
    } catch {
      // Layout-only fullscreen still works when the API is blocked.
    }
  }

  async function exit() {
    isFullscreen.value = false
    try {
      if (getFullscreenElement()) {
        await exitAppFullscreen()
      }
    } catch {
      // Ignore exit errors; local state already reset.
    }
  }

  async function toggle() {
    if (isFullscreen.value) {
      await exit()
      return
    }
    await enter()
  }

  function onFullscreenChange() {
    syncFromBrowser()
  }

  function onKeydown(event: KeyboardEvent) {
    if (event.key === 'F11') {
      event.preventDefault()
      void toggle()
    }
  }

  onMounted(() => {
    document.addEventListener('fullscreenchange', onFullscreenChange)
    document.addEventListener('webkitfullscreenchange', onFullscreenChange as EventListener)
    window.addEventListener('keydown', onKeydown)
    syncFromBrowser()
  })

  onBeforeUnmount(() => {
    document.removeEventListener('fullscreenchange', onFullscreenChange)
    document.removeEventListener('webkitfullscreenchange', onFullscreenChange as EventListener)
    window.removeEventListener('keydown', onKeydown)
    void exit()
  })

  return {
    isFullscreen: readonly(isFullscreen),
    enter,
    exit,
    toggle,
  }
}

export type WorkspaceFullscreenContext = ReturnType<typeof useWorkspaceFullscreen>
