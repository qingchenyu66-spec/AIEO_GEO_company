import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { withRetry } from '../../../composables/useRetry'
import {
  getKnowledgeFiles,
  uploadKnowledgeFile,
  type KnowledgeFileRecord,
} from '../../../services/knowledge'
import { useAuthStore } from '../../../stores/auth'
import { formatDateTime, formatFileSize } from '../portalUtils'

export type KnowledgeTypeFilter = 'all' | 'pdf' | 'doc' | 'md' | 'txt'

const MAX_FILE_SIZE = 30 * 1024 * 1024

function normalizeExt(ext: string) {
  const value = ext.toLowerCase().replace(/^\./, '')
  if (value === 'doc' || value === 'docx') return 'doc'
  return value
}

function matchesTypeFilter(file: KnowledgeFileRecord, filter: KnowledgeTypeFilter) {
  if (filter === 'all') return true
  return normalizeExt(file.file_ext) === filter
}

export function useKnowledgeBase() {
  const auth = useAuthStore()
  const files = ref<KnowledgeFileRecord[]>([])
  const loading = ref(false)
  const uploading = ref(false)
  const loadError = ref('')
  const keywordFilter = ref('')
  const typeFilter = ref<KnowledgeTypeFilter>('all')
  const selectedId = ref<number | null>(null)

  const pageMenuName = computed(() => (
    auth.allowedMenus.find(menu => menu.menu_code === 'customer.knowledge')?.menu_name || '企业知识库'
  ))

  const menuGrant = computed(() => auth.allowedMenus.find(menu => menu.menu_code === 'customer.knowledge'))
  const canUpload = computed(() => Boolean(menuGrant.value?.can_create))
  const tenantName = computed(() => auth.session?.identity?.tenant_name || '当前企业')

  const filteredFiles = computed(() => {
    const keyword = keywordFilter.value.trim().toLowerCase()
    return files.value.filter(file => {
      if (!matchesTypeFilter(file, typeFilter.value)) return false
      if (!keyword) return true
      return file.original_name.toLowerCase().includes(keyword)
    })
  })

  const selectedFile = computed(() => (
    filteredFiles.value.find(file => file.id === selectedId.value)
      || files.value.find(file => file.id === selectedId.value)
      || null
  ))

  const totalSize = computed(() => files.value.reduce((sum, file) => sum + file.file_size, 0))
  const pdfCount = computed(() => files.value.filter(file => normalizeExt(file.file_ext) === 'pdf').length)
  const docCount = computed(() => files.value.filter(file => normalizeExt(file.file_ext) === 'doc').length)
  const textCount = computed(() => files.value.filter(file => ['md', 'txt'].includes(normalizeExt(file.file_ext))).length)

  const lastUploadLabel = computed(() => {
    if (!files.value.length) return '-'
    return formatDateTime(files.value[0]?.created_at)
  })

  const headline = computed(() => {
    if (loadError.value) return '资料加载失败，请刷新后重试'
    if (!files.value.length) return '尚未归档品牌资料，建议先上传产品说明与核心卖点文档'
    const latest = files.value[0]
    return `已归档 ${files.value.length} 份资料，最近上传「${latest.original_name}」`
  })

  const typeTabs = computed<Array<{ value: KnowledgeTypeFilter; label: string; count: number }>>(() => [
    { value: 'all', label: '全部', count: files.value.length },
    { value: 'pdf', label: 'PDF', count: pdfCount.value },
    { value: 'doc', label: 'Word', count: docCount.value },
    { value: 'md', label: 'Markdown', count: files.value.filter(file => normalizeExt(file.file_ext) === 'md').length },
    { value: 'txt', label: 'TXT', count: files.value.filter(file => normalizeExt(file.file_ext) === 'txt').length },
  ])

  watch(filteredFiles, items => {
    if (!items.length) {
      selectedId.value = null
      return
    }
    if (!items.some(item => item.id === selectedId.value)) {
      selectedId.value = items[0].id
    }
  })

  async function loadFiles() {
    loading.value = true
    loadError.value = ''
    try {
      files.value = await withRetry(() => getKnowledgeFiles(null))
      if (files.value.length && selectedId.value === null) {
        selectedId.value = files.value[0].id
      }
    } catch (error: unknown) {
      loadError.value = error instanceof Error ? error.message : '知识库文件加载失败'
      files.value = []
    } finally {
      loading.value = false
    }
  }

  function validateFile(file: File) {
    const ext = file.name.includes('.') ? file.name.slice(file.name.lastIndexOf('.')).toLowerCase() : ''
    const bare = ext.replace(/^\./, '')
    const allowed = new Set(['pdf', 'doc', 'docx', 'md', 'txt'])
    if (!allowed.has(bare)) {
      throw new Error('仅支持 PDF、Word、Markdown 和 TXT 文件')
    }
    if (file.size === 0) throw new Error('不能上传空文件')
    if (file.size > MAX_FILE_SIZE) throw new Error('单个文件不能超过 30MB')
  }

  async function uploadFile(file: File) {
    validateFile(file)
    uploading.value = true
    try {
      const record = await uploadKnowledgeFile(file, null)
      ElMessage.success('资料已上传')
      files.value = [record, ...files.value.filter(item => item.id !== record.id)]
      selectedId.value = record.id
    } catch (error: unknown) {
      ElMessage.error(error instanceof Error ? error.message : '文件上传失败')
    } finally {
      uploading.value = false
    }
  }

  async function handleFileInput(event: Event) {
    const input = event.target as HTMLInputElement
    const file = input.files?.[0]
    input.value = ''
    if (!file) return
    await uploadFile(file)
  }

  async function handleDrop(event: DragEvent) {
    event.preventDefault()
    if (!canUpload.value || uploading.value) return
    const file = event.dataTransfer?.files?.[0]
    if (!file) return
    await uploadFile(file)
  }

  function handleDragOver(event: DragEvent) {
    event.preventDefault()
  }

  function resetFilters() {
    keywordFilter.value = ''
    typeFilter.value = 'all'
  }

  function extLabel(ext: string) {
    const normalized = normalizeExt(ext)
    if (normalized === 'pdf') return 'PDF'
    if (normalized === 'doc') return 'Word'
    if (normalized === 'md') return 'Markdown'
    if (normalized === 'txt') return 'TXT'
    return ext.toUpperCase()
  }

  onMounted(loadFiles)

  return {
    pageMenuName,
    tenantName,
    canUpload,
    files,
    filteredFiles,
    loading,
    uploading,
    loadError,
    keywordFilter,
    typeFilter,
    typeTabs,
    selectedId,
    selectedFile,
    totalSize,
    pdfCount,
    docCount,
    textCount,
    lastUploadLabel,
    headline,
    loadFiles,
    handleFileInput,
    handleDrop,
    handleDragOver,
    resetFilters,
    formatFileSize,
    formatDateTime,
    extLabel,
    normalizeExt,
  }
}
