<script setup lang="ts">
import { ref } from 'vue'
import {
  AlertTriangle,
  BookOpen,
  FileText,
  RefreshCw,
  Upload,
} from '@lucide/vue'
import { useKnowledgeBase } from '../composables/useKnowledgeBase'
import { useKnowledgePreview } from '../composables/useKnowledgePreview'
import '../../../styles/knowledge-base.css'

const fileInputRef = ref<HTMLInputElement | null>(null)

const {
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
  pptCount,
  imageCount,
  htmlCount,
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
} = useKnowledgeBase()

const {
  previewUrl,
  previewLoading,
  previewError,
  loadPreview,
} = useKnowledgePreview(selectedFile)

function openUploadDialog() {
  if (!canUpload.value || uploading.value) return
  fileInputRef.value?.click()
}

function fileIconClass(ext: string) {
  const normalized = normalizeExt(ext)
  if (normalized === 'pdf') return 'is-pdf'
  if (normalized === 'doc') return 'is-doc'
  if (normalized === 'ppt') return 'is-ppt'
  if (normalized === 'image') return 'is-image'
  if (normalized === 'html') return 'is-html'
  if (normalized === 'md') return 'is-md'
  return 'is-txt'
}
</script>

<template>
  <section class="kb-page">
    <header class="kb-sticky-bar">
      <div class="kb-sticky-inner">
        <div class="kb-type-tabs">
          <button
            v-for="tab in typeTabs"
            :key="tab.value"
            type="button"
            :class="{ active: typeFilter === tab.value }"
            @click="typeFilter = tab.value"
          >
            {{ tab.label }}
            <em>{{ tab.count }}</em>
          </button>
        </div>
        <input
          v-model="keywordFilter"
          class="kb-search-input"
          placeholder="搜索文件名称"
          type="search"
        />
        <div class="kb-sticky-actions">
          <span v-if="loading" class="kb-loading-dot">加载中...</span>
          <button type="button" class="filter-reset-btn tiny-btn" @click="resetFilters">重置</button>
          <button type="button" class="filter-reset-btn tiny-btn" :disabled="loading" @click="loadFiles()">
            <RefreshCw />
            刷新
          </button>
          <button
            v-if="canUpload"
            type="button"
            class="primary-btn small-btn"
            :disabled="uploading"
            @click="openUploadDialog"
          >
            <Upload />
            {{ uploading ? '上传中...' : '上传资料' }}
          </button>
        </div>
      </div>
      <input
        ref="fileInputRef"
        type="file"
        class="kb-hidden-input"
        accept=".pdf,.doc,.docx,.ppt,.pptx,.png,.jpg,.jpeg,.webp,.html,.htm,.md,.txt"
        :disabled="!canUpload || uploading"
        @change="handleFileInput"
      />
    </header>

    <article class="kb-hero">
      <div class="kb-hero-copy">
        <span class="kb-hero-eyebrow">{{ tenantName }}</span>
        <h2>{{ headline }}</h2>
        <p>集中管理产品手册、白皮书、FAQ 与品牌资料，上传后可在线预览原版排版，便于团队查阅与复用。</p>
        <div class="kb-hero-signals">
          <span><BookOpen /> 资料归档</span>
          <span><FileText /> 在线预览</span>
        </div>
      </div>
      <div class="kb-stats-panel">
        <div class="kb-stat">
          <span>资料总数</span>
          <b>{{ files.length }}</b>
          <em>PDF {{ pdfCount }} · Word {{ docCount }} · PPT {{ pptCount }} · 图 {{ imageCount }} · HTML {{ htmlCount }} · 文本 {{ textCount }}</em>
        </div>
        <div class="kb-stat">
          <span>占用空间</span>
          <b>{{ formatFileSize(totalSize) }}</b>
          <em>单文件上限 30MB</em>
        </div>
        <div class="kb-stat">
          <span>最近上传</span>
          <b>{{ lastUploadLabel === '-' ? '—' : lastUploadLabel }}</b>
          <em>{{ lastUploadLabel === '-' ? '暂无上传记录' : '最近一次归档时间' }}</em>
        </div>
        <div class="kb-stat">
          <span>支持格式</span>
          <b>4 类</b>
          <em>PDF · Word · Markdown · TXT</em>
        </div>
      </div>
    </article>

    <div v-if="loadError" class="kb-error-banner">
      <AlertTriangle />
      <span>{{ loadError }}</span>
      <button type="button" class="ghost-link-btn" @click="loadFiles()">重试</button>
    </div>

    <div class="kb-main">
      <aside class="kb-rail">
        <div class="kb-rail-head">
          <strong>资料列表</strong>
          <span>{{ filteredFiles.length }} 项</span>
        </div>

        <div v-if="loading && !filteredFiles.length" class="kb-rail-empty">加载中...</div>
        <div v-else-if="!filteredFiles.length" class="kb-rail-empty">
          {{ keywordFilter || typeFilter !== 'all' ? '没有符合筛选条件的资料' : '暂无资料，请上传品牌相关文档。' }}
        </div>

        <button
          v-for="file in filteredFiles"
          :key="file.id"
          type="button"
          class="kb-rail-item"
          :class="{ active: selectedId === file.id }"
          @click="selectedId = file.id"
        >
          <span class="kb-file-icon" :class="fileIconClass(file.file_ext)">
            <FileText />
          </span>
          <span class="kb-rail-item-copy">
            <b>{{ file.original_name }}</b>
            <span>
              {{ extLabel(file.file_ext) }} · {{ formatFileSize(file.file_size) }}
              · {{ formatDateTime(file.created_at) }}
            </span>
          </span>
        </button>
      </aside>

      <main class="kb-detail">
        <template v-if="selectedFile">
          <header class="kb-detail-head">
            <div>
              <span class="kb-detail-type" :class="fileIconClass(selectedFile.file_ext)">{{ extLabel(selectedFile.file_ext) }}</span>
              <h3>{{ selectedFile.original_name }}</h3>
            </div>
          </header>

          <dl class="kb-meta-grid">
            <div>
              <dt>文件大小</dt>
              <dd>{{ formatFileSize(selectedFile.file_size) }}</dd>
            </div>
            <div>
              <dt>上传时间</dt>
              <dd>{{ formatDateTime(selectedFile.created_at) }}</dd>
            </div>
            <div>
              <dt>文件格式</dt>
              <dd>{{ extLabel(selectedFile.file_ext) }}</dd>
            </div>
          </dl>

          <section class="kb-preview-panel">
            <div class="kb-preview-toolbar">
              <strong>原版预览</strong>
              <button
                type="button"
                class="filter-reset-btn tiny-btn"
                :disabled="previewLoading"
                @click="loadPreview(selectedFile.id)"
              >
                <RefreshCw />
                刷新预览
              </button>
            </div>

            <div class="kb-fulltext-panel kb-pdf-preview-panel">
              <div v-if="previewLoading" class="kb-fulltext-state">正在生成原版预览...</div>
              <div v-else-if="previewError" class="kb-fulltext-state is-error">
                {{ previewError }}
              </div>
              <iframe
                v-else-if="previewUrl"
                class="kb-pdf-frame"
                :src="previewUrl"
                title="知识库文件原版预览"
              />
              <div v-else class="kb-fulltext-state">暂无可预览内容，请确认文件格式是否支持。</div>
            </div>
          </section>
        </template>

        <template v-else-if="canUpload">
          <label
            class="kb-upload-panel"
            :class="{ disabled: uploading }"
            @dragover="handleDragOver"
            @drop="handleDrop"
          >
            <input
              type="file"
              accept=".pdf,.doc,.docx,.ppt,.pptx,.png,.jpg,.jpeg,.webp,.html,.htm,.md,.txt"
              :disabled="uploading"
              @change="handleFileInput"
            />
            <BookOpen />
            <h3>拖拽或点击上传品牌资料</h3>
            <p>支持 PDF、Word、PPT、图片、HTML、Markdown、TXT，上传后可原版预览，单个文件不超过 30MB</p>
            <span class="kb-upload-hint">建议上传：产品说明书、品牌白皮书、FAQ、核心卖点文案</span>
          </label>
        </template>

        <div v-else class="kb-detail-empty">
          <BookOpen />
          <h3>暂无资料</h3>
          <p>当前账号仅有查看权限，请联系管理员上传资料。</p>
        </div>
      </main>
    </div>
  </section>
</template>
