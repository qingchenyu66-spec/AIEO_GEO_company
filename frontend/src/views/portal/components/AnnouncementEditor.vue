<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { uploadAnnouncementMedia } from '../../../services/announcements'
import { hydrateAnnouncementHtml, persistAnnouncementHtml } from '../../../services/announcementHtml'
import { http, type GeoHttpRequestConfig } from '../../../services/http'

const props = defineProps<{ modelValue: string }>()
const emit = defineEmits<{ 'update:modelValue': [value: string] }>()

const editorRef = ref<HTMLElement | null>(null)
const syncing = ref(false)
const dragging = ref(false)
const uploading = ref(false)
const fontFamily = ref('')
const fontSize = ref('')
const textColor = ref('#0f172a')
const bgColor = ref('#fff2cc')
const paintPanel = ref<'color' | 'background-color' | null>(null)
const moreColorInput = ref<HTMLInputElement | null>(null)
const paintPanelStyle = ref<Record<string, string>>({ top: '0px', left: '0px' })
// 2026-09-08 - 长文撑屏 + 底部改色要滚回顶栏 - 正文限高；选区旁迷你条
const bubbleVisible = ref(false)
const bubbleStyle = ref<Record<string, string>>({ top: '0px', left: '0px' })
let bubbleTimer: number | null = null

/** Office 风格主题色 + 标准色（点一下即上色，免系统取色器） */
const THEME_COLORS = [
  '#ffffff',
  '#000000',
  '#e7e6e6',
  '#44546a',
  '#4472c4',
  '#ed7d31',
  '#a5a5a5',
  '#ffc000',
  '#5b9bd5',
  '#70ad47',
] as const
const THEME_SHADES = [
  ['#f2f2f2', '#7f7f7f', '#d0cece', '#d6dce4', '#d6dce5', '#fce4d6', '#ededed', '#fff2cc', '#ddebf7', '#e2efda'],
  ['#d8d8d8', '#595959', '#aeaaaa', '#adb9ca', '#b4c6e7', '#f8cbad', '#dbdbdb', '#ffe699', '#bdd7ee', '#c6e0b4'],
  ['#bfbfbf', '#3f3f3f', '#757070', '#8496b0', '#8ea9db', '#f4b183', '#c9c9c9', '#ffd966', '#9bc2e6', '#a9d08e'],
  ['#a5a5a5', '#262626', '#3a3838', '#323f4f', '#2f5496', '#c55a11', '#7b7b7b', '#bf8f00', '#2e75b6', '#548235'],
  ['#7f7f7f', '#0c0c0c', '#171616', '#222a35', '#1f3864', '#833c0c', '#3f3f3f', '#806000', '#1e4e79', '#375623'],
] as const
const STANDARD_COLORS = [
  '#c00000',
  '#ff0000',
  '#ffc000',
  '#ffff00',
  '#92d050',
  '#00b050',
  '#00b0f0',
  '#0070c0',
  '#002060',
  '#7030a0',
] as const

const FONT_FAMILIES = [
  { label: '默认字体', value: '' },
  { label: '微软雅黑', value: '"Microsoft YaHei", sans-serif' },
  { label: '宋体', value: 'SimSun, serif' },
  { label: '黑体', value: 'SimHei, sans-serif' },
  { label: '楷体', value: 'KaiTi, serif' },
  { label: 'Arial', value: 'Arial, sans-serif' },
  { label: 'Georgia', value: 'Georgia, serif' },
] as const

const FONT_SIZES = [
  { label: '字号', value: '' },
  { label: '12', value: '12px' },
  { label: '14', value: '14px' },
  { label: '16', value: '16px' },
  { label: '18', value: '18px' },
  { label: '20', value: '20px' },
  { label: '24', value: '24px' },
  { label: '28', value: '28px' },
  { label: '32', value: '32px' },
] as const

watch(
  () => props.modelValue,
  async (html) => {
    await nextTick()
    if (!editorRef.value || syncing.value) return
    const hydrated = await hydrateAnnouncementHtml(html || '')
    if (editorRef.value.innerHTML !== hydrated) {
      editorRef.value.innerHTML = hydrated
    }
  },
  { immediate: true },
)

function emitHtml() {
  if (!editorRef.value) return
  syncing.value = true
  emit('update:modelValue', persistAnnouncementHtml(editorRef.value.innerHTML))
  queueMicrotask(() => {
    syncing.value = false
  })
}

function run(cmd: string, value?: string) {
  document.execCommand(cmd, false, value)
  editorRef.value?.focus()
  emitHtml()
}

// 2026-09-08 - 点工具栏取色/下拉会失焦清选区，颜色看似「没反应」- mousedown 先记下再恢复
let savedRange: Range | null = null

function captureSelection() {
  const el = editorRef.value
  const sel = window.getSelection()
  if (!el || !sel?.rangeCount) return
  const range = sel.getRangeAt(0)
  if (!el.contains(range.commonAncestorContainer)) return
  try {
    savedRange = range.cloneRange()
  } catch {
    savedRange = null
  }
}

function restoreSavedSelection(): Range | null {
  const el = editorRef.value
  const sel = window.getSelection()
  if (!el || !sel) return null
  el.focus()
  if (savedRange) {
    try {
      sel.removeAllRanges()
      sel.addRange(savedRange)
      return savedRange.cloneRange()
    } catch {
      /* fall through */
    }
  }
  return ensureSelectionInEditor()
}

function ensureSelectionInEditor(): Range | null {
  const el = editorRef.value
  if (!el) return null
  el.focus()
  const sel = window.getSelection()
  if (!sel) return null
  if (!sel.rangeCount || !el.contains(sel.anchorNode)) {
    const range = document.createRange()
    range.selectNodeContents(el)
    range.collapse(false)
    sel.removeAllRanges()
    sel.addRange(range)
  }
  return sel.getRangeAt(0)
}

/** 用 span + 白名单 style 包选区；比 execCommand fontSize(1-7) 可控 */
function applyInlineStyle(cssText: string) {
  const el = editorRef.value
  const range = restoreSavedSelection()
  const sel = window.getSelection()
  if (!el || !range || !sel) return

  const span = document.createElement('span')
  span.setAttribute('style', cssText)

  if (range.collapsed) {
    span.appendChild(document.createTextNode('\u200b'))
    range.insertNode(span)
    const caret = document.createRange()
    caret.setStart(span.firstChild as Text, 1)
    caret.collapse(true)
    sel.removeAllRanges()
    sel.addRange(caret)
  } else {
    try {
      range.surroundContents(span)
    } catch {
      const contents = range.extractContents()
      span.appendChild(contents)
      range.insertNode(span)
    }
    const wrapped = document.createRange()
    wrapped.selectNodeContents(span)
    sel.removeAllRanges()
    sel.addRange(wrapped)
  }
  savedRange = null
  emitHtml()
}

const PAINT_TAGS = new Set(['P', 'DIV', 'SPAN', 'TD', 'TH', 'LI', 'OL', 'UL', 'H1', 'H2', 'H3', 'H4'])
const BLOCK_PAINT_TAGS = new Set(['P', 'DIV', 'LI', 'OL', 'UL', 'H1', 'H2', 'H3', 'H4'])

function collectPaintHits(range: Range, el: HTMLElement): HTMLElement[] {
  const hit: HTMLElement[] = []
  el.querySelectorAll('p,div,span,td,th,li,ol,ul,h1,h2,h3,h4').forEach((node) => {
    const he = node as HTMLElement
    if (!PAINT_TAGS.has(he.tagName)) return
    try {
      if (range.intersectsNode(he)) hit.push(he)
    } catch {
      /* ignore */
    }
  })
  return hit
}

/** 选中列表任一段时，整份 ol/ul 的 li 一起改，避免只清中间、上下黑条还在 */
function expandPaintHits(hits: HTMLElement[]): HTMLElement[] {
  const out = new Set<HTMLElement>(hits)
  for (const he of hits) {
    const list = he.closest('ol, ul') as HTMLElement | null
    if (!list) continue
    out.add(list)
    list.querySelectorAll('li').forEach((li) => out.add(li as HTMLElement))
  }
  return [...out]
}

/** 清粘贴深色条：background 简写、底色、描边/阴影都要去掉，单清 background-color 不够 */
function stripBlockChrome(he: HTMLElement) {
  const props = [
    'background',
    'background-color',
    'background-image',
    'border',
    'border-color',
    'border-top',
    'border-right',
    'border-bottom',
    'border-left',
    'border-width',
    'border-style',
    'outline',
    'box-shadow',
  ]
  for (const prop of props) {
    he.style.removeProperty(prop)
  }
}

/** 字色改选区节点；底色按荧光笔；列表黑条与选区一起清/设 */
function applyPaintStyle(kind: 'color' | 'background-color', value: string, opts?: { clear?: boolean }) {
  const el = editorRef.value
  const range = restoreSavedSelection()
  if (!el || !range) return

  const hits = range.collapsed ? [] : expandPaintHits(collectPaintHits(range, el))

  if (kind === 'background-color') {
    for (const he of hits) {
      if (BLOCK_PAINT_TAGS.has(he.tagName) || opts?.clear) {
        stripBlockChrome(he)
      }
    }
    if (opts?.clear) {
      savedRange = null
      emitHtml()
      return
    }
    if (!value) return
    bgColor.value = value
    // 块级底（含列表黑条）已清；再给选中文字上荧光笔
    applyInlineStyle(`background-color: ${value}`)
    return
  }

  if (!value) return
  textColor.value = value
  // 改字色时一并拆掉选区里的深色底/黑边，否则浅字深底仍看不见
  for (const he of hits) {
    if (BLOCK_PAINT_TAGS.has(he.tagName)) {
      stripBlockChrome(he)
    }
  }
  if (range.collapsed || !hits.length) {
    applyInlineStyle(`color: ${value}`)
    return
  }
  for (const he of hits) {
    he.style.setProperty('color', value)
  }
  savedRange = null
  emitHtml()
}

function onFontFamilyChange() {
  const value = fontFamily.value
  if (!value) return
  applyInlineStyle(`font-family: ${value}`)
}

function onFontSizeChange() {
  const value = fontSize.value
  if (!value) return
  applyInlineStyle(`font-size: ${value}`)
}

function openPaintPanel(kind: 'color' | 'background-color', event?: MouseEvent) {
  captureSelection()
  const next = paintPanel.value === kind ? null : kind
  paintPanel.value = next
  if (!next) return
  const anchor = (event?.currentTarget as HTMLElement | undefined)?.getBoundingClientRect()
  const panelW = 232
  const panelH = 300
  let top = (anchor?.bottom ?? 80) + 4
  let left = anchor?.left ?? 80
  if (top + panelH > window.innerHeight - 8) {
    top = Math.max(8, (anchor?.top ?? panelH) - panelH - 4)
  }
  left = Math.max(8, Math.min(left, window.innerWidth - panelW - 8))
  paintPanelStyle.value = { top: `${top}px`, left: `${left}px` }
}

function pickPaintColor(color: string) {
  const kind = paintPanel.value
  if (!kind) return
  applyPaintStyle(kind, color)
  paintPanel.value = null
  scheduleBubble()
}

function clearBackgroundPaint() {
  captureSelection()
  paintPanel.value = 'background-color'
  applyPaintStyle('background-color', '', { clear: true })
  paintPanel.value = null
  scheduleBubble()
}

function openMoreColor() {
  captureSelection()
  moreColorInput.value?.click()
}

function onMoreColorInput(event: Event) {
  const input = event.target as HTMLInputElement
  const value = input.value
  if (!value || !paintPanel.value) return
  pickPaintColor(value)
}

function updateBubble() {
  const el = editorRef.value
  const sel = window.getSelection()
  if (!el || !sel || !sel.rangeCount || sel.isCollapsed) {
    bubbleVisible.value = false
    return
  }
  const range = sel.getRangeAt(0)
  if (!el.contains(range.commonAncestorContainer)) {
    bubbleVisible.value = false
    return
  }
  const rect = range.getBoundingClientRect()
  if (rect.width < 1 && rect.height < 1) {
    bubbleVisible.value = false
    return
  }
  try {
    savedRange = range.cloneRange()
  } catch {
    /* keep previous */
  }
  const bubbleW = 168
  let left = rect.left + rect.width / 2 - bubbleW / 2
  let top = rect.top - 46
  left = Math.max(8, Math.min(left, window.innerWidth - bubbleW - 8))
  if (top < 8) top = rect.bottom + 8
  bubbleStyle.value = { top: `${top}px`, left: `${left}px`, width: `${bubbleW}px` }
  bubbleVisible.value = true
}

function scheduleBubble() {
  if (bubbleTimer != null) window.clearTimeout(bubbleTimer)
  bubbleTimer = window.setTimeout(() => {
    updateBubble()
  }, 40)
}

function runBubbleBold() {
  captureSelection()
  run('bold')
  scheduleBubble()
}

function onDocPointerDown(event: PointerEvent) {
  const target = event.target as Node | null
  if (!target) return
  const panel = document.querySelector('.paint-panel-float')
  const bubble = document.querySelector('.ann-sel-bubble')
  if (panel?.contains(target) || bubble?.contains(target)) return
  const root = editorRef.value?.closest('.announcement-editor')
  if (root) {
    for (const t of root.querySelectorAll('.paint-trigger')) {
      if (t.contains(target)) return
    }
  }
  if (paintPanel.value) paintPanel.value = null
}

function onSelectionChange() {
  scheduleBubble()
}

watch(paintPanel, (open) => {
  if (open) {
    document.addEventListener('pointerdown', onDocPointerDown, true)
  } else {
    document.removeEventListener('pointerdown', onDocPointerDown, true)
  }
})

onMounted(() => {
  document.addEventListener('selectionchange', onSelectionChange)
})

function insertTable() {
  const colsRaw = window.prompt('表格列数（1～8）', '2')
  if (colsRaw == null) return
  const rowsRaw = window.prompt('数据行数（不含表头，1～20）', '3')
  if (rowsRaw == null) return
  const cols = Math.min(8, Math.max(1, Number.parseInt(colsRaw, 10) || 2))
  const rows = Math.min(20, Math.max(1, Number.parseInt(rowsRaw, 10) || 3))
  const ths = Array.from({ length: cols }, (_, i) => `<th>列${i + 1}</th>`).join('')
  const emptyRow = `<tr>${Array.from({ length: cols }, () => '<td><br></td>').join('')}</tr>`
  const body = Array.from({ length: rows }, () => emptyRow).join('')
  insertHtml(
    `<table style="width: 100%; border-collapse: collapse"><thead><tr>${ths}</tr></thead><tbody>${body}</tbody></table><p><br></p>`,
  )
}

function insertHtml(snippet: string) {
  const el = editorRef.value
  if (!el) return
  el.focus()
  const sel = window.getSelection()
  if (!sel || !sel.rangeCount || !el.contains(sel.anchorNode)) {
    const range = document.createRange()
    range.selectNodeContents(el)
    range.collapse(false)
    sel?.removeAllRanges()
    sel?.addRange(range)
  }
  const ok = document.execCommand('insertHTML', false, snippet)
  if (!ok) el.insertAdjacentHTML('beforeend', snippet)
  emitHtml()
}

function insertLink() {
  const url = window.prompt('输入链接 URL（https:// 或站内路径）')
  if (!url?.trim()) return
  const href = url.trim()
  const selected = window.getSelection()?.toString().trim()
  const label = (selected || href).replace(/[<>]/g, '')
  insertHtml(`<a href="${href}" target="_blank" rel="noopener noreferrer">${label}</a>`)
}

async function uploadAndInsert(file: File) {
  const isImage = file.type.startsWith('image/') || /\.(png|jpe?g|gif|webp)$/i.test(file.name)
  uploading.value = true
  try {
    const uploaded = await uploadAnnouncementMedia(file, isImage ? 'image' : 'file')
    if (isImage || uploaded.kind === 'image') {
      const response = await http.get(`/v1/announcements/media/${uploaded.id}`, {
        responseType: 'blob',
        silentError: true,
      } as GeoHttpRequestConfig)
      const blobUrl = URL.createObjectURL(response.data as Blob)
      const alt = uploaded.original_name.replace(/[<>"]/g, '')
      insertHtml(
        `<img src="${blobUrl}" data-media-src="${uploaded.url}" alt="${alt}" style="max-width:100%;border-radius:8px;">`,
      )
      ElMessage.success('图片已插入')
    } else {
      const safeName = uploaded.original_name.replace(/[<>]/g, '')
      insertHtml(
        `<p class="announcement-file"><a href="${uploaded.url}" download target="_blank" rel="noopener noreferrer">📎 ${safeName}</a></p>`,
      )
      ElMessage.success('附件已插入')
    }
  } catch (error: unknown) {
    const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    ElMessage.error(typeof detail === 'string' && detail ? detail : isImage ? '图片上传失败' : '附件上传失败')
  } finally {
    uploading.value = false
  }
}

function dataUrlToFile(dataUrl: string, fallbackName = 'paste.png'): File | null {
  const match = /^data:(image\/[a-z0-9+.-]+);base64,(.+)$/i.exec(dataUrl)
  if (!match) return null
  const mime = match[1].toLowerCase()
  const ext = mime.split('/')[1]?.replace('jpeg', 'jpg') || 'png'
  try {
    const binary = atob(match[2])
    const bytes = new Uint8Array(binary.length)
    for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i)
    return new File([bytes], fallbackName.replace(/\.\w+$/, `.${ext}`), { type: mime })
  } catch {
    return null
  }
}

/** 2026-07-28 - 粘贴截图变 data:base64 撑爆 20 万字限制 - 改走媒体上传 */
async function onPaste(event: ClipboardEvent) {
  const clipboard = event.clipboardData
  if (!clipboard) return

  const imageFiles = Array.from(clipboard.items || [])
    .filter((item) => item.type.startsWith('image/'))
    .map((item) => item.getAsFile())
    .filter((file): file is File => !!file)
  if (imageFiles.length) {
    event.preventDefault()
    for (const file of imageFiles) {
      await uploadAndInsert(file)
    }
    return
  }

  const html = clipboard.getData('text/html') || ''
  if (!/data:image\//i.test(html)) return

  event.preventDefault()
  uploading.value = true
  try {
    const doc = new DOMParser().parseFromString(`<div id="root">${html}</div>`, 'text/html')
    const root = doc.getElementById('root')
    if (!root) return
    const imgs = Array.from(root.querySelectorAll('img'))
    let index = 0
    for (const img of imgs) {
      const src = img.getAttribute('src') || ''
      if (!src.startsWith('data:image/')) continue
      index += 1
      const file = dataUrlToFile(src, `paste-${index}.png`)
      if (!file) {
        img.remove()
        continue
      }
      try {
        const uploaded = await uploadAnnouncementMedia(file, 'image')
        const response = await http.get(`/v1/announcements/media/${uploaded.id}`, {
          responseType: 'blob',
          silentError: true,
        } as GeoHttpRequestConfig)
        const blobUrl = URL.createObjectURL(response.data as Blob)
        img.setAttribute('src', blobUrl)
        img.setAttribute('data-media-src', uploaded.url)
        img.setAttribute('alt', uploaded.original_name.replace(/[<>"]/g, ''))
        img.setAttribute('style', 'max-width:100%;border-radius:8px;')
      } catch {
        img.remove()
      }
    }
    insertHtml(root.innerHTML)
    if (index > 0) ElMessage.success('粘贴图片已上传')
  } finally {
    uploading.value = false
  }
}

async function onPickImage(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (file) await uploadAndInsert(file)
}

async function onPickFile(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (file) await uploadAndInsert(file)
}

function insertImageUrl() {
  const url = window.prompt('输入图片 URL')
  if (!url?.trim()) return
  const href = url.trim().replace(/"/g, '')
  insertHtml(`<img src="${href}" alt="" style="max-width:100%;border-radius:8px;">`)
}

function insertFileUrl() {
  const url = window.prompt('输入附件下载 URL')
  if (!url?.trim()) return
  const name = (window.prompt('显示文件名', '附件下载') || '附件下载').replace(/[<>]/g, '')
  insertHtml(`<p class="announcement-file"><a href="${url.trim()}" download target="_blank" rel="noopener noreferrer">📎 ${name}</a></p>`)
}

function onDragOver(event: DragEvent) {
  event.preventDefault()
  dragging.value = true
}

function onDragLeave() {
  dragging.value = false
}

async function onDrop(event: DragEvent) {
  event.preventDefault()
  dragging.value = false
  const files = Array.from(event.dataTransfer?.files || [])
  if (!files.length) return
  for (const file of files) {
    await uploadAndInsert(file)
  }
}

onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', onDocPointerDown, true)
  document.removeEventListener('selectionchange', onSelectionChange)
  if (bubbleTimer != null) window.clearTimeout(bubbleTimer)
  /* blob URLs 随页面生命周期即可；不做全局 revoke，避免编辑中图挂掉 */
})
</script>

<template>
  <div class="announcement-editor" :class="{ 'is-dragging': dragging, 'is-uploading': uploading }">
    <div class="announcement-editor-toolbar">
      <div class="toolbar-group">
        <select
          v-model="fontFamily"
          class="toolbar-select"
          title="字体"
          @mousedown="captureSelection"
          @change="onFontFamilyChange"
        >
          <option v-for="item in FONT_FAMILIES" :key="item.label" :value="item.value">{{ item.label }}</option>
        </select>
        <select
          v-model="fontSize"
          class="toolbar-select toolbar-select-size"
          title="字号"
          @mousedown="captureSelection"
          @change="onFontSizeChange"
        >
          <option v-for="item in FONT_SIZES" :key="item.label" :value="item.value">{{ item.label }}</option>
        </select>

        <button
          type="button"
          class="paint-trigger"
          title="字体颜色"
          @mousedown="captureSelection"
          @click="openPaintPanel('color', $event)"
        >
          <span class="paint-letter">A</span>
          <span class="paint-bar" :style="{ background: textColor }" />
          字色
        </button>

        <button
          type="button"
          class="paint-trigger"
          title="底纹 / 高亮"
          @mousedown="captureSelection"
          @click="openPaintPanel('background-color', $event)"
        >
          <span class="paint-letter paint-letter-bg">ab</span>
          <span class="paint-bar" :style="{ background: bgColor }" />
          底色
        </button>

        <button type="button" title="加粗" @click="run('bold')"><b>B</b></button>
        <button type="button" @click="run('insertUnorderedList')">• 列表</button>
        <button type="button" @click="run('insertOrderedList')">1. 编号</button>
        <button type="button" @click="insertTable">表格</button>
        <button type="button" @click="insertLink">链接</button>
      </div>
      <div class="toolbar-group">
        <label class="toolbar-file">
          图片
          <input type="file" accept="image/png,image/jpeg,image/gif,image/webp" hidden @change="onPickImage">
        </label>
        <button type="button" @click="insertImageUrl">图片链接</button>
        <label class="toolbar-file">
          附件
          <input
            type="file"
            accept=".pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.zip,.txt,.md,application/pdf"
            hidden
            @change="onPickFile"
          >
        </label>
        <button type="button" @click="insertFileUrl">附件链接</button>
      </div>
    </div>

    <div class="announcement-editor-scroll">
      <div
        ref="editorRef"
        class="announcement-editor-body"
        contenteditable="true"
        data-placeholder="在此编辑公告正文，可直接拖拽图片或文件到此处…"
        @input="emitHtml"
        @paste="onPaste"
        @mouseup="scheduleBubble"
        @keyup="scheduleBubble"
        @dragover="onDragOver"
        @dragleave="onDragLeave"
        @drop="onDrop"
      />
    </div>

    <input
      ref="moreColorInput"
      type="color"
      class="paint-more-native"
      @change="onMoreColorInput"
    >
    <div v-if="dragging" class="drop-hint">松开以上传图片 / 附件</div>
    <div v-else-if="uploading" class="drop-hint is-upload">上传中…</div>

    <Teleport to="body">
      <div
        v-if="bubbleVisible"
        class="ann-sel-bubble"
        :style="bubbleStyle"
        @mousedown.prevent="captureSelection"
      >
        <button type="button" title="加粗" @click="runBubbleBold"><b>B</b></button>
        <button type="button" class="paint-trigger" title="字色" @click="openPaintPanel('color', $event)">
          <span class="paint-letter">A</span>
          <span class="paint-bar" :style="{ background: textColor }" />
        </button>
        <button
          type="button"
          class="paint-trigger"
          title="底色"
          @click="openPaintPanel('background-color', $event)"
        >
          <span class="paint-letter paint-letter-bg">ab</span>
          <span class="paint-bar" :style="{ background: bgColor }" />
        </button>
      </div>

      <div
        v-if="paintPanel"
        class="paint-panel paint-panel-float"
        :style="paintPanelStyle"
        @mousedown.prevent
      >
        <button
          v-if="paintPanel === 'background-color'"
          type="button"
          class="paint-clear"
          @click="clearBackgroundPaint"
        >
          无填充
        </button>
        <div class="paint-caption">主题颜色</div>
        <div class="paint-row">
          <button
            v-for="c in THEME_COLORS"
            :key="`t-${c}`"
            type="button"
            class="paint-swatch"
            :style="{ background: c }"
            :title="c"
            @click="pickPaintColor(c)"
          />
        </div>
        <div v-for="(row, ri) in THEME_SHADES" :key="`shade-${ri}`" class="paint-row">
          <button
            v-for="c in row"
            :key="`s-${ri}-${c}`"
            type="button"
            class="paint-swatch"
            :style="{ background: c }"
            :title="c"
            @click="pickPaintColor(c)"
          />
        </div>
        <div class="paint-caption">标准色</div>
        <div class="paint-row">
          <button
            v-for="c in STANDARD_COLORS"
            :key="`std-${c}`"
            type="button"
            class="paint-swatch"
            :style="{ background: c }"
            :title="c"
            @click="pickPaintColor(c)"
          />
        </div>
        <button type="button" class="paint-more" @click="openMoreColor">更多颜色…</button>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.announcement-editor {
  position: relative;
  display: flex;
  flex-direction: column;
  border: 1px solid #d7e0ec;
  border-radius: 12px;
  overflow: hidden;
  background: #fff;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.announcement-editor.is-dragging {
  border-color: #3b82f6;
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.15);
}
.announcement-editor-toolbar {
  flex-shrink: 0;
  z-index: 2;
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  justify-content: space-between;
  padding: 8px 10px;
  border-bottom: 1px solid #eef2f7;
  background: linear-gradient(180deg, #f8fafc, #f1f5f9);
}
.announcement-editor-scroll {
  flex: 1 1 auto;
  min-height: 200px;
  max-height: min(52vh, 520px);
  overflow: auto;
  overscroll-behavior: contain;
}
.toolbar-group {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.announcement-editor-toolbar button,
.toolbar-file,
.toolbar-select,
.ann-sel-bubble button {
  border: 1px solid #d0d7e2;
  background: #fff;
  border-radius: 8px;
  padding: 5px 10px;
  font-size: 12px;
  cursor: pointer;
  color: #334155;
}
.toolbar-select {
  max-width: 120px;
  height: 30px;
}
.toolbar-select-size {
  max-width: 72px;
}
.paint-trigger {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  min-height: 30px;
}
.paint-letter {
  font-weight: 700;
  font-size: 13px;
  line-height: 1;
  color: #0f172a;
}
.paint-letter-bg {
  font-size: 11px;
  font-weight: 700;
  padding: 1px 2px;
  border-radius: 2px;
  background: #fff2cc;
}
.paint-bar {
  width: 16px;
  height: 4px;
  border-radius: 1px;
  border: 1px solid #cbd5e1;
}
.paint-panel {
  width: 232px;
  padding: 10px;
  border: 1px solid #d0d7e2;
  border-radius: 10px;
  background: #fff;
  box-shadow: 0 12px 28px rgba(15, 23, 42, 0.16);
}
.paint-panel-float {
  position: fixed;
  z-index: 4100;
}
.paint-caption {
  margin: 6px 0 4px;
  font-size: 11px;
  color: #64748b;
}
.paint-caption:first-child {
  margin-top: 0;
}
.paint-row {
  display: grid;
  grid-template-columns: repeat(10, 1fr);
  gap: 2px;
  margin-bottom: 2px;
}
.paint-swatch {
  width: 18px;
  height: 18px;
  padding: 0;
  border: 1px solid rgba(15, 23, 42, 0.18);
  border-radius: 2px;
  cursor: pointer;
}
.paint-swatch:hover {
  outline: 2px solid #2563eb;
  outline-offset: 1px;
  border-color: #2563eb;
}
.paint-clear,
.paint-more {
  width: 100%;
  margin-top: 6px;
  border: 1px solid #d0d7e2;
  background: #f8fafc;
  border-radius: 6px;
  padding: 6px 8px;
  font-size: 12px;
  color: #334155;
  cursor: pointer;
  text-align: left;
}
.paint-clear:hover,
.paint-more:hover {
  border-color: #93c5fd;
  color: #1d4ed8;
}
.paint-more-native {
  position: absolute;
  width: 0;
  height: 0;
  opacity: 0;
  pointer-events: none;
}
.ann-sel-bubble {
  position: fixed;
  z-index: 4090;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px;
  border: 1px solid #d0d7e2;
  border-radius: 10px;
  background: #fff;
  box-shadow: 0 10px 24px rgba(15, 23, 42, 0.18);
}
.announcement-editor-toolbar button:hover,
.toolbar-file:hover,
.paint-trigger:hover,
.ann-sel-bubble button:hover {
  border-color: #93c5fd;
  color: #1d4ed8;
}
.toolbar-file {
  display: inline-flex;
  align-items: center;
}
.announcement-editor-body {
  min-height: 200px;
  padding: 14px 16px 28px;
  outline: none;
  line-height: 1.7;
  font-size: 14px;
  color: #0f172a;
}
.announcement-editor-body:empty:before {
  content: attr(data-placeholder);
  color: #94a3b8;
}
.announcement-editor-body :deep(img) {
  max-width: 100%;
  border-radius: 8px;
  margin: 8px 0;
  display: block;
}
.announcement-editor-body :deep(a) {
  color: #2563eb;
}
.announcement-editor-body :deep(table) {
  width: 100%;
  border-collapse: collapse;
  margin: 10px 0;
  font-size: 13px;
}
.announcement-editor-body :deep(th),
.announcement-editor-body :deep(td) {
  border: 1px solid #cbd5e1;
  padding: 8px 10px;
  vertical-align: top;
  text-align: left;
}
.announcement-editor-body :deep(th) {
  background: #f1f5f9;
  font-weight: 600;
}
.drop-hint {
  position: absolute;
  inset: 48px 0 0;
  display: grid;
  place-items: center;
  background: rgba(239, 246, 255, 0.92);
  color: #1d4ed8;
  font-size: 14px;
  font-weight: 600;
  pointer-events: none;
}
.drop-hint.is-upload {
  background: rgba(248, 250, 252, 0.88);
  color: #475569;
}
</style>
