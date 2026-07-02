import { computed, ref, watch, type ComputedRef } from 'vue'
import { withRetry } from '../../../composables/useRetry'
import { getKnowledgeFileContent, type KnowledgeFileRecord, type KnowledgeParseResult } from '../../../services/knowledge'

export type KnowledgePreviewSection = {
  title: string
  type: 'text' | 'list' | 'cards'
  content?: string
  items?: string[]
  cards?: Array<{ title: string; content: string }>
}

const META_KEYS = new Set(['source', 'model', 'extracted_chars', 'truncated', 'sections'])

function asString(value: unknown) {
  return typeof value === 'string' ? value.trim() : ''
}

function asStringList(value: unknown) {
  if (!Array.isArray(value)) return []
  return value.map(item => String(item).trim()).filter(Boolean)
}

function legacySectionTitle(key: string) {
  return key
}

function buildLegacySections(result: KnowledgeParseResult): KnowledgePreviewSection[] {
  const sections: KnowledgePreviewSection[] = []
  for (const [key, value] of Object.entries(result)) {
    if (META_KEYS.has(key) || value == null) continue
    const title = legacySectionTitle(key)
    if (typeof value === 'string' && value.trim()) {
      sections.push({ title, type: 'text', content: value.trim() })
      continue
    }
    if (Array.isArray(value)) {
      if (value.every(item => typeof item === 'string')) {
        const items = asStringList(value)
        if (items.length) sections.push({ title, type: 'list', items })
        continue
      }
      const cards = value
        .filter(item => item && typeof item === 'object')
        .map(item => {
          const row = item as Record<string, unknown>
          return {
            title: asString(row.title),
            content: asString(row.content),
          }
        })
        .filter(card => card.title || card.content)
      if (cards.length) sections.push({ title, type: 'cards', cards })
    }
  }
  return sections
}

function normalizeSections(raw: unknown): KnowledgePreviewSection[] {
  if (!Array.isArray(raw)) return []
  const sections: KnowledgePreviewSection[] = []
  for (const item of raw) {
    if (!item || typeof item !== 'object') continue
    const row = item as Record<string, unknown>
    const title = asString(row.title)
    const type = asString(row.type).toLowerCase()
    if (!title) continue
    if (type === 'list') {
      const items = asStringList(row.items)
      if (items.length) sections.push({ title, type: 'list', items })
      continue
    }
    if (type === 'cards') {
      const cards = (Array.isArray(row.items) ? row.items : [])
        .filter(entry => entry && typeof entry === 'object')
        .map(entry => {
          const card = entry as Record<string, unknown>
          return { title: asString(card.title), content: asString(card.content) }
        })
        .filter(card => card.title || card.content)
      if (cards.length) sections.push({ title, type: 'cards', cards })
      continue
    }
    const content = asString(row.content)
    if (content) sections.push({ title, type: 'text', content })
  }
  return sections
}

export function buildKnowledgePreviewSections(result: KnowledgeParseResult | null | undefined): KnowledgePreviewSection[] {
  if (!result) return []
  const structured = normalizeSections(result.sections)
  if (structured.length) return structured
  return buildLegacySections(result)
}

export function useKnowledgePreview(selectedFile: ComputedRef<KnowledgeFileRecord | null>) {
  const previewMode = ref<'structured' | 'fulltext'>('structured')
  const fullText = ref('')
  const fullTextLoading = ref(false)
  const fullTextError = ref('')

  const previewSections = computed(() => buildKnowledgePreviewSections(selectedFile.value?.parse_result))

  async function loadFullText(fileId: number) {
    fullTextLoading.value = true
    fullTextError.value = ''
    try {
      const data = await withRetry(() => getKnowledgeFileContent(fileId))
      fullText.value = data.text || ''
    } catch (error: unknown) {
      fullTextError.value = error instanceof Error ? error.message : '全文加载失败'
      fullText.value = ''
    } finally {
      fullTextLoading.value = false
    }
  }

  watch(selectedFile, file => {
    previewMode.value = 'structured'
    fullText.value = ''
    fullTextError.value = ''
    if (file?.id) void loadFullText(file.id)
  }, { immediate: true })

  return {
    previewMode,
    previewSections,
    fullText,
    fullTextLoading,
    fullTextError,
    loadFullText,
  }
}
