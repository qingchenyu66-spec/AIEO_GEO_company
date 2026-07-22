import { ref, watch, onBeforeUnmount } from 'vue'

function easeOutCubic(progress: number) {
  return 1 - (1 - progress) ** 3
}

export function useCountUp(
  getTarget: () => number | null | undefined,
  options: {
    duration?: number
    decimals?: number
    enabled?: () => boolean
  } = {},
) {
  const duration = options.duration ?? 1200
  const decimals = options.decimals ?? 0
  const display = ref(0)
  let frameId = 0

  function format(value: number) {
    if (decimals > 0) return value.toFixed(decimals)
    return String(Math.round(value))
  }

  function animateTo(target: number) {
    cancelAnimationFrame(frameId)
    const startValue = display.value
    const startedAt = performance.now()

    const tick = (now: number) => {
      const progress = Math.min((now - startedAt) / duration, 1)
      display.value = startValue + (target - startValue) * easeOutCubic(progress)
      if (progress < 1) {
        frameId = requestAnimationFrame(tick)
        return
      }
      display.value = target
    }

    frameId = requestAnimationFrame(tick)
  }

  function restart(fromZero = false) {
    const enabled = options.enabled?.() ?? true
    const target = getTarget()
    if (!enabled || target === null || target === undefined || Number.isNaN(Number(target))) {
      cancelAnimationFrame(frameId)
      display.value = 0
      return
    }
    if (fromZero) display.value = 0
    animateTo(Number(target))
  }

  watch(
    () => [getTarget(), options.enabled?.() ?? true] as const,
    () => restart(false),
    { immediate: true },
  )

  onBeforeUnmount(() => {
    cancelAnimationFrame(frameId)
  })

  return {
    display,
    formatted: () => format(display.value),
    restart: () => restart(true),
  }
}

export function useWorkspaceEnter(source: () => unknown) {
  const enterActive = ref(false)
  const enterGeneration = ref(0)

  watch(source, value => {
    if (!value) {
      enterActive.value = false
      return
    }
    enterActive.value = false
    enterGeneration.value += 1
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        enterActive.value = true
      })
    })
  }, { immediate: true })

  return { enterActive, enterGeneration }
}
