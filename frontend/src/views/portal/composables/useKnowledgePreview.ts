import { ref, watch, type ComputedRef } from 'vue'
import { withRetry } from '../../../composables/useRetry'
import { getKnowledgeFileContent, type KnowledgeFileRecord } from '../../../services/knowledge'

export function useKnowledgePreview(selectedFile: ComputedRef<KnowledgeFileRecord | null>) {
  const fullText = ref('')
  const fullTextLoading = ref(false)
  const fullTextError = ref('')
  let loadSeq = 0

  async function loadFullText(fileId: number) {
    const seq = ++loadSeq
    fullTextLoading.value = true
    fullTextError.value = ''
    try {
      const data = await withRetry(() => getKnowledgeFileContent(fileId))
      if (seq !== loadSeq) return
      fullText.value = data.text || ''
    } catch (error: unknown) {
      if (seq !== loadSeq) return
      fullTextError.value = error instanceof Error ? error.message : '预览加载失败'
      fullText.value = ''
    } finally {
      if (seq === loadSeq) fullTextLoading.value = false
    }
  }

  watch(selectedFile, file => {
    fullText.value = ''
    fullTextError.value = ''
    if (file?.id) void loadFullText(file.id)
  }, { immediate: true })

  return {
    fullText,
    fullTextLoading,
    fullTextError,
    loadFullText,
  }
}
