import { onMounted, onUnmounted, ref } from 'vue'
import { getPendingApprovalCount } from '../../../services/approvals'

export function useApprovalPendingCount(enabled: () => boolean) {
  const pendingCount = ref(0)
  let timer: number | undefined

  async function refreshPendingCount() {
    if (!enabled()) {
      pendingCount.value = 0
      return
    }
    try {
      pendingCount.value = await getPendingApprovalCount()
    } catch {
      /* ignore polling errors */
    }
  }

  function onWindowFocus() {
    void refreshPendingCount()
  }

  onMounted(() => {
    void refreshPendingCount()
    timer = window.setInterval(() => void refreshPendingCount(), 60000)
    window.addEventListener('focus', onWindowFocus)
  })

  onUnmounted(() => {
    if (timer) window.clearInterval(timer)
    window.removeEventListener('focus', onWindowFocus)
  })

  return { pendingCount, refreshPendingCount }
}
