import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export const useLoadingStore = defineStore('loading', () => {
  const requestCount = ref(0)
  const loadingKeys = ref(new Set<string>())

  const isLoading = computed(() => requestCount.value > 0)

  function start(key?: string) {
    requestCount.value++
    if (key) {
      loadingKeys.value.add(key)
    }
  }

  function end(key?: string) {
    requestCount.value = Math.max(0, requestCount.value - 1)
    if (key) {
      loadingKeys.value.delete(key)
    }
  }

  function isKeyLoading(key: string) {
    return loadingKeys.value.has(key)
  }

  return {
    isLoading,
    isKeyLoading,
    start,
    end,
  }
})
