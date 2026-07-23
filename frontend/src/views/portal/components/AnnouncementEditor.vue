<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
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
  const range = ensureSelectionInEditor()
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
  /* blob URLs 随页面生命周期即可；不做全局 revoke，避免编辑中图挂掉 */
})
</script>

<template>
  <div class="announcement-editor" :class="{ 'is-dragging': dragging, 'is-uploading': uploading }">
    <div class="announcement-editor-toolbar">
      <div class="toolbar-group">
        <select v-model="fontFamily" class="toolbar-select" title="字体" @change="onFontFamilyChange">
          <option v-for="item in FONT_FAMILIES" :key="item.label" :value="item.value">{{ item.label }}</option>
        </select>
        <select v-model="fontSize" class="toolbar-select toolbar-select-size" title="字号" @change="onFontSizeChange">
          <option v-for="item in FONT_SIZES" :key="item.label" :value="item.value">{{ item.label }}</option>
        </select>
        <button type="button" title="加粗" @click="run('bold')"><b>B</b></button>
        <button type="button" @click="run('insertUnorderedList')">• 列表</button>
        <button type="button" @click="run('insertOrderedList')">1. 编号</button>
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
    <div
      ref="editorRef"
      class="announcement-editor-body"
      contenteditable="true"
      data-placeholder="在此编辑公告正文，可直接拖拽图片或文件到此处…"
      @input="emitHtml"
      @dragover="onDragOver"
      @dragleave="onDragLeave"
      @drop="onDrop"
    />
    <div v-if="dragging" class="drop-hint">松开以上传图片 / 附件</div>
    <div v-else-if="uploading" class="drop-hint is-upload">上传中…</div>
  </div>
</template>

<style scoped>
.announcement-editor {
  position: relative;
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
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  justify-content: space-between;
  padding: 8px 10px;
  border-bottom: 1px solid #eef2f7;
  background: linear-gradient(180deg, #f8fafc, #f1f5f9);
}
.toolbar-group {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.announcement-editor-toolbar button,
.toolbar-file,
.toolbar-select {
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
.announcement-editor-toolbar button:hover,
.toolbar-file:hover {
  border-color: #93c5fd;
  color: #1d4ed8;
}
.toolbar-file {
  display: inline-flex;
  align-items: center;
}
.announcement-editor-body {
  min-height: 240px;
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
