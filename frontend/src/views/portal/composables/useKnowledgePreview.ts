import { ref, watch, type ComputedRef } from 'vue'
import { withRetry } from '../../../composables/useRetry'
import { getKnowledgeFilePreviewObjectUrl, type KnowledgeFileRecord } from '../../../services/knowledge'

export function useKnowledgePreview(selectedFile: ComputedRef<KnowledgeFileRecord | null>) {
  const previewUrl = ref('')
  const previewLoading = ref(false)
  const previewError = ref('')
  let loadSeq = 0
  let activeObjectUrl = ''

  function revokePreviewUrl() {
    if (activeObjectUrl) {
      URL.revokeObjectURL(activeObjectUrl)
      activeObjectUrl = ''
    }
    previewUrl.value = ''
  }

  async function loadPreview(fileId: number) {
    const seq = ++loadSeq
    previewLoading.value = true
    previewError.value = ''
    revokePreviewUrl()
    try {
      const url = await withRetry(() => getKnowledgeFilePreviewObjectUrl(fileId))
      if (seq !== loadSeq) {
        URL.revokeObjectURL(url)
        return
      }
      activeObjectUrl = url
      previewUrl.value = url
    } catch (error: unknown) {
      if (seq !== loadSeq) return
      previewError.value = error instanceof Error ? error.message : '预览加载失败'
      revokePreviewUrl()
    } finally {
      if (seq === loadSeq) previewLoading.value = false
    }
  }

  watch(selectedFile, file => {
    previewError.value = ''
    if (file?.id) void loadPreview(file.id)
    else revokePreviewUrl()
  }, { immediate: true })

  return {
    previewUrl,
    previewLoading,
    previewError,
    loadPreview,
  }
}
