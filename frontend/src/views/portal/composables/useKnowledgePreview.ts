import { ref, watch, type ComputedRef } from 'vue'
import { withRetry } from '../../../composables/useRetry'
import { getKnowledgeFileContent, type KnowledgeFileRecord } from '../../../services/knowledge'

export function useKnowledgePreview(selectedFile: ComputedRef<KnowledgeFileRecord | null>) {
  const fullText = ref('')
  const fullTextLoading = ref(false)
  const fullTextError = ref('')

  async function loadFullText(fileId: number) {
    fullTextLoading.value = true
    fullTextError.value = ''
    try {
      const data = await withRetry(() => getKnowledgeFileContent(fileId))
      fullText.value = data.text || ''
    } catch (error: unknown) {
      fullTextError.value = error instanceof Error ? error.message : '预览加载失败'
      fullText.value = ''
    } finally {
      fullTextLoading.value = false
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
