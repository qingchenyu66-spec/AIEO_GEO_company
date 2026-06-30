import { onUnmounted, watch, type ComputedRef, type Ref } from 'vue'

const INNER_SCROLL_SELECTOR = '.workspace-platform-matrix-scroll, .workspace-source-list, .workspace-snapshot-list, .workspace-unpurchased-grid'
const WHEEL_LOCK_MS = 650

export function useWorkspaceDeckWheel(
  deckRef: Ref<HTMLElement | null>,
  pageIds: ComputedRef<string[]>,
) {
  let wheelLocked = false
  let lockTimer: ReturnType<typeof setTimeout> | null = null
  let detachWheel: (() => void) | null = null

  function currentPageIndex(container: HTMLElement) {
    const pageHeight = container.clientHeight
    if (!pageHeight) return 0
    return Math.max(0, Math.min(
      pageIds.value.length - 1,
      Math.round(container.scrollTop / pageHeight),
    ))
  }

  function goToDeckPage(index: number) {
    const container = deckRef.value
    if (!container || !pageIds.value.length) return
    const targetIndex = Math.max(0, Math.min(pageIds.value.length - 1, index))
    const pageId = pageIds.value[targetIndex]
    const target = container.querySelector(`#${CSS.escape(pageId)}`)
    target?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  function scrollToDeckPage(id: string) {
    deckRef.value?.querySelector(`#${CSS.escape(id)}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  function onWheel(event: WheelEvent) {
    const container = deckRef.value
    if (!container || pageIds.value.length <= 1) return

    const inner = (event.target as HTMLElement | null)?.closest(INNER_SCROLL_SELECTOR) as HTMLElement | null
    if (inner && inner.scrollHeight > inner.clientHeight + 2) {
      const goingDown = event.deltaY > 0
      const goingUp = event.deltaY < 0
      const atTop = inner.scrollTop <= 1
      const atBottom = inner.scrollTop + inner.clientHeight >= inner.scrollHeight - 1
      if ((goingDown && !atBottom) || (goingUp && !atTop)) return
    }

    if (Math.abs(event.deltaY) < 4) return

    const index = currentPageIndex(container)
    const nextIndex = event.deltaY > 0 ? index + 1 : index - 1
    if (nextIndex < 0 || nextIndex >= pageIds.value.length) {
      event.preventDefault()
      return
    }
    if (nextIndex === index) return

    event.preventDefault()
    if (wheelLocked) return

    wheelLocked = true
    goToDeckPage(nextIndex)
    if (lockTimer) clearTimeout(lockTimer)
    lockTimer = setTimeout(() => { wheelLocked = false }, WHEEL_LOCK_MS)
  }

  watch(deckRef, (element, _, onCleanup) => {
    detachWheel?.()
    detachWheel = null
    if (!element) return
    element.addEventListener('wheel', onWheel, { passive: false })
    detachWheel = () => element.removeEventListener('wheel', onWheel)
    onCleanup(() => detachWheel?.())
  }, { immediate: true })

  onUnmounted(() => {
    detachWheel?.()
    if (lockTimer) clearTimeout(lockTimer)
  })

  return { goToDeckPage, scrollToDeckPage }
}
