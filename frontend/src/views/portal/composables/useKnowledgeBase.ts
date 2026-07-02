import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { withRetry } from '../../../composables/useRetry'
import {
  deleteKnowledgeFile,
  getKnowledgeFiles,
  parseKnowledgeFile,
  uploadKnowledgeFile,
  type KnowledgeFileRecord,
  type KnowledgeParseStatus,
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

const parseStatusLabels: Record<KnowledgeParseStatus, string> = {
  none: '待解析',
  parsing: '解析中',
  parsed: '已完成',
  failed: '解析异常',
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
  const canManage = computed(() => Boolean(menuGrant.value?.can_update))
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
  const parsedCount = computed(() => files.value.filter(file => file.parse_status === 'parsed').length)
  const failedCount = computed(() => files.value.filter(file => file.parse_status === 'failed').length)
  const parsingCount = computed(() => files.value.filter(file => file.parse_status === 'parsing' || file.parse_status === 'none').length)

  const extractedKeywordCount = computed(() => {
    const keywords = new Set<string>()
    files.value.forEach(file => {
      file.parse_result?.keywords?.forEach(keyword => keywords.add(keyword))
    })
    return keywords.size
  })

  const geoPointCount = computed(() => (
    files.value.reduce((sum, file) => sum + (file.parse_result?.geo_points?.length || 0), 0)
  ))

  const lastUploadLabel = computed(() => {
    if (!files.value.length) return '-'
    return formatDateTime(files.value[0]?.created_at)
  })

  const headline = computed(() => {
    if (loadError.value) return '资料加载失败，请刷新后重试'
    if (!files.value.length) return '尚未归档品牌资料，建议先上传产品说明与核心卖点文档'
    if (parsingCount.value > 0) return `已归档 ${files.value.length} 份资料，${parsingCount.value} 份正在智能解析`
    if (failedCount.value > 0) return `已归档 ${files.value.length} 份资料，${failedCount.value} 份解析异常需查看`
    if (parsedCount.value > 0) return `已归档 ${files.value.length} 份资料，${parsedCount.value} 份已完成知识提炼`
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

  let parsePollTimer: number | null = null

  function stopParsePolling() {
    if (parsePollTimer !== null) {
      window.clearInterval(parsePollTimer)
      parsePollTimer = null
    }
  }

  function syncParsePolling() {
    const shouldPoll = files.value.some(file => file.parse_status === 'parsing' || file.parse_status === 'none')
    if (!shouldPoll) {
      stopParsePolling()
      return
    }
    if (parsePollTimer !== null) return
    parsePollTimer = window.setInterval(() => {
      if (document.visibilityState === 'visible') {
        void loadFiles({ silent: true })
      }
    }, 3000)
  }

  watch(files, syncParsePolling, { deep: true })

  let pendingParseQueued = false

  async function schedulePendingParses(items: KnowledgeFileRecord[]) {
    const pending = items.filter(file => file.parse_status === 'none')
    if (!pending.length || pendingParseQueued) return
    pendingParseQueued = true
    try {
      await Promise.allSettled(pending.map(file => parseKnowledgeFile(file.id)))
      await loadFiles({ silent: true })
    } finally {
      pendingParseQueued = false
    }
  }

  async function loadFiles(options?: { silent?: boolean }) {
    if (!options?.silent) {
      loading.value = true
      loadError.value = ''
    }
    try {
      files.value = await withRetry(() => getKnowledgeFiles(null))
      if (files.value.length && selectedId.value === null) {
        selectedId.value = files.value[0].id
      }
      if (!options?.silent) {
        void schedulePendingParses(files.value)
      }
      syncParsePolling()
    } catch (error: unknown) {
      if (!options?.silent) {
        loadError.value = error instanceof Error ? error.message : '知识库文件加载失败'
        files.value = []
      }
    } finally {
      if (!options?.silent) loading.value = false
    }
  }

  function validateFile(file: File) {
    const ext = file.name.includes('.') ? file.name.slice(file.name.lastIndexOf('.')).toLowerCase() : ''
    const bare = ext.replace(/^\./, '')
    const normalized = normalizeExt(bare)
    if (!['pdf', 'doc', 'md', 'txt'].includes(normalized)) {
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
      ElMessage.success('资料已上传，正在进行智能解析')
      files.value = [record, ...files.value.filter(item => item.id !== record.id)]
      selectedId.value = record.id
      syncParsePolling()
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

  async function removeSelectedFile() {
    if (!selectedFile.value || !canManage.value) return
    try {
      await ElMessageBox.confirm(
        `确定删除「${selectedFile.value.original_name}」？删除后不可恢复。`,
        '删除资料',
        { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' },
      )
    } catch {
      return
    }
    try {
      await deleteKnowledgeFile(selectedFile.value.id)
      ElMessage.success('资料已删除')
      selectedId.value = null
      await loadFiles()
    } catch (error: unknown) {
      ElMessage.error(error instanceof Error ? error.message : '删除失败')
    }
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

  function parseStatusLabel(status?: KnowledgeParseStatus) {
    if (!status) return parseStatusLabels.none
    return parseStatusLabels[status] || status
  }

  function parseStatusClass(status?: KnowledgeParseStatus) {
    if (status === 'parsed') return 'is-success'
    if (status === 'parsing') return 'is-pending'
    if (status === 'failed') return 'is-failed'
    return 'is-idle'
  }

  function parseProgress(status?: KnowledgeParseStatus) {
    if (status === 'parsed') return 100
    if (status === 'failed') return 100
    if (status === 'parsing') return 68
    return 18
  }

  function parseProgressText(status?: KnowledgeParseStatus) {
    if (status === 'parsed') return '知识结构化完成，可用于引用分析与报告素材'
    if (status === 'failed') return '解析未完成，请检查文件内容或重新上传'
    if (status === 'parsing') return '正在提取摘要、关键词和可引用要点'
    return '已入库，等待智能解析引擎处理'
  }

  onMounted(loadFiles)
  onUnmounted(stopParsePolling)

  return {
    pageMenuName,
    tenantName,
    canUpload,
    canManage,
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
    parsedCount,
    failedCount,
    parsingCount,
    extractedKeywordCount,
    geoPointCount,
    lastUploadLabel,
    headline,
    loadFiles,
    handleFileInput,
    handleDrop,
    handleDragOver,
    removeSelectedFile,
    parseStatusLabel,
    parseStatusClass,
    parseProgress,
    parseProgressText,
    resetFilters,
    formatFileSize,
    formatDateTime,
    extLabel,
    normalizeExt,
  }
}
