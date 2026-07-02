<script setup lang="ts">
import { computed, ref } from 'vue'
import {
  AlertTriangle,
  BookOpen,
  BrainCircuit,
  CheckCircle2,
  FileText,
  Layers3,
  RefreshCw,
  Sparkles,
  Trash2,
  Upload,
} from '@lucide/vue'
import { useKnowledgeBase } from '../composables/useKnowledgeBase'
import { useKnowledgePreview } from '../composables/useKnowledgePreview'
import '../../../styles/knowledge-base.css'

const fileInputRef = ref<HTMLInputElement | null>(null)

const {
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
} = useKnowledgeBase()

const {
  previewMode,
  previewSections,
  fullText,
  fullTextLoading,
  fullTextError,
  loadFullText,
} = useKnowledgePreview(selectedFile)

const coverageScore = computed(() => {
  if (!files.value.length) return 0
  return Math.round((parsedCount.value / files.value.length) * 100)
})

function openUploadDialog() {
  if (!canUpload.value || uploading.value) return
  fileInputRef.value?.click()
}

function fileIconClass(ext: string) {
  const normalized = normalizeExt(ext)
  if (normalized === 'pdf') return 'is-pdf'
  if (normalized === 'doc') return 'is-doc'
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
        accept=".pdf,.doc,.docx,.md,.txt"
        :disabled="!canUpload || uploading"
        @change="handleFileInput"
      />
    </header>

    <article class="kb-hero">
      <div class="kb-hero-copy">
        <span class="kb-hero-eyebrow">{{ tenantName }}</span>
        <h2>{{ headline }}</h2>
        <p>沉淀产品手册、白皮书、FAQ 和品牌资料，上传后进入内容资产引擎，自动形成摘要、关键词与 GEO 引用要点，让资料变成可复用的交付素材。</p>
        <div class="kb-hero-signals">
          <span><BrainCircuit /> 内容资产引擎</span>
          <span><Layers3 /> GEO 引用要点</span>
          <span><CheckCircle2 /> 报告素材沉淀</span>
        </div>
      </div>
      <div class="kb-kpi-row">
        <div class="kb-kpi is-primary">
          <span>知识资产完成度</span>
          <b>{{ coverageScore }}%</b>
          <em>{{ parsedCount }} / {{ files.length || 0 }} 份已完成结构化</em>
        </div>
        <div class="kb-kpi-grid">
          <div class="kb-kpi">
            <span>资料总数</span>
            <b>{{ files.length }}</b>
            <em>PDF {{ pdfCount }} · Word {{ docCount }} · 文本 {{ textCount }}</em>
          </div>
          <div class="kb-kpi">
            <span>占用空间</span>
            <b>{{ formatFileSize(totalSize) }}</b>
            <em>单文件上限 30MB</em>
          </div>
          <div class="kb-kpi" :class="{ 'is-warn': failedCount > 0 }">
            <span>解析队列</span>
            <b>{{ parsingCount }}</b>
            <em>{{ failedCount > 0 ? `${failedCount} 份异常` : '上传后自动处理' }}</em>
          </div>
          <div class="kb-kpi">
            <span>内容要点</span>
            <b>{{ geoPointCount }}</b>
            <em>{{ extractedKeywordCount }} 个关键词已沉淀</em>
          </div>
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
          :class="{
            active: selectedId === file.id,
            'is-failed': file.parse_status === 'failed',
            'is-parsing': file.parse_status === 'parsing' || file.parse_status === 'none',
          }"
          @click="selectedId = file.id"
        >
          <span class="kb-file-icon" :class="fileIconClass(file.file_ext)">
            <FileText />
          </span>
          <span class="kb-rail-item-copy">
            <b>
              {{ file.original_name }}
              <AlertTriangle v-if="file.parse_status === 'failed'" class="kb-rail-alert-icon" />
            </b>
            <span>
              {{ extLabel(file.file_ext) }} · {{ formatFileSize(file.file_size) }}
              · <em class="kb-parse-badge" :class="parseStatusClass(file.parse_status)">{{ parseStatusLabel(file.parse_status) }}</em>
            </span>
            <i class="kb-rail-progress" aria-hidden="true">
              <small :style="{ width: `${parseProgress(file.parse_status)}%` }" />
            </i>
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
            <div v-if="canManage" class="kb-detail-actions">
              <button
                type="button"
                class="filter-reset-btn tiny-btn danger-btn"
                @click="removeSelectedFile"
              >
                <Trash2 />
                删除
              </button>
            </div>
          </header>

          <section class="kb-progress-panel" :class="parseStatusClass(selectedFile.parse_status)">
            <div class="kb-progress-icon">
              <Sparkles v-if="selectedFile.parse_status !== 'failed'" />
              <AlertTriangle v-else />
            </div>
            <div class="kb-progress-copy">
              <div class="kb-progress-title">
                <strong>{{ parseStatusLabel(selectedFile.parse_status) }}</strong>
                <span>{{ parseProgress(selectedFile.parse_status) }}%</span>
              </div>
              <div class="kb-progress-track" :class="{ 'is-indeterminate': parseProgress(selectedFile.parse_status) === null }" aria-hidden="true">
                <i :style="parseProgress(selectedFile.parse_status) != null ? { width: `${parseProgress(selectedFile.parse_status)}%` } : undefined" />
              </div>
              <p>{{ parseProgressText(selectedFile.parse_status) }}</p>
            </div>
          </section>

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
              <dt>解析时间</dt>
              <dd>{{ selectedFile.parsed_at ? formatDateTime(selectedFile.parsed_at) : '-' }}</dd>
            </div>
            <div>
              <dt>资产类型</dt>
              <dd>{{ selectedFile.parse_result?.topics?.[0] || '品牌资料' }}</dd>
            </div>
          </dl>

          <div v-if="selectedFile.parse_status === 'failed'" class="kb-parse-error">
            <AlertTriangle />
            <div>
              <strong>解析异常</strong>
              <p>{{ selectedFile.parse_error || '文件暂未完成文本提取，请检查文件格式或重新上传。' }}</p>
            </div>
          </div>

          <section v-else-if="selectedFile.parse_result || previewSections.length" class="kb-parse-panel">
            <div class="kb-preview-toolbar">
              <div class="kb-preview-tabs">
                <button type="button" :class="{ active: previewMode === 'structured' }" @click="previewMode = 'structured'">
                  结构化预览
                  <em>{{ previewSections.length }}</em>
                </button>
                <button type="button" :class="{ active: previewMode === 'fulltext' }" @click="previewMode = 'fulltext'">
                  全文阅读
                  <em v-if="fullText">{{ fullText.length }}</em>
                </button>
              </div>
              <button
                type="button"
                class="filter-reset-btn tiny-btn"
                :disabled="fullTextLoading"
                @click="selectedFile && loadFullText(selectedFile.id)"
              >
                <RefreshCw />
                刷新全文
              </button>
            </div>

            <div v-if="previewMode === 'structured'" class="kb-dynamic-preview">
              <article
                v-for="(section, index) in previewSections"
                :key="`${section.title}-${index}`"
                class="kb-preview-block"
                :class="{
                  'is-wide': section.type === 'text',
                  'is-cards': section.type === 'cards',
                }"
              >
                <header class="kb-preview-block-head">
                  <h4>{{ section.title }}</h4>
                </header>

                <p v-if="section.type === 'text'" class="kb-preview-text">{{ section.content }}</p>

                <ul v-else-if="section.type === 'list'" class="kb-preview-list">
                  <li v-for="(item, itemIndex) in section.items" :key="`${section.title}-${itemIndex}`">{{ item }}</li>
                </ul>

                <div v-else class="kb-preview-cards">
                  <article
                    v-for="(card, cardIndex) in section.cards"
                    :key="`${section.title}-card-${cardIndex}`"
                    class="kb-preview-card-item"
                  >
                    <strong v-if="card.title">{{ card.title }}</strong>
                    <p>{{ card.content }}</p>
                  </article>
                </div>
              </article>
              <div v-if="!previewSections.length" class="kb-preview-empty">暂无可展示的结构化内容，请切换到全文阅读查看原文件。</div>
            </div>

            <div v-else class="kb-fulltext-panel">
              <div v-if="fullTextLoading" class="kb-fulltext-state">全文加载中...</div>
              <div v-else-if="fullTextError" class="kb-fulltext-state is-error">
                {{ fullTextError }}
              </div>
              <pre v-else-if="fullText" class="kb-fulltext-body">{{ fullText }}</pre>
              <div v-else class="kb-fulltext-state">暂无全文内容。</div>
            </div>

            <p v-if="selectedFile.parse_result?.truncated" class="kb-parse-footnote">
              正文较长，结构化预览基于前 {{ selectedFile.parse_result?.extracted_chars }} 字生成；全文阅读展示完整提取结果。
            </p>
          </section>

          <div v-else class="kb-parse-loading">
            <Sparkles />
            <div>
              <strong>内容资产引擎正在处理资料</strong>
              <p>系统正在抽取摘要、关键词和可引用要点，完成后会自动刷新预览。</p>
            </div>
          </div>
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
              accept=".pdf,.doc,.docx,.md,.txt"
              :disabled="uploading"
              @change="handleFileInput"
            />
            <BookOpen />
            <h3>拖拽或点击上传品牌资料</h3>
            <p>支持 PDF、Word、Markdown、TXT，上传后自动解析，单个文件不超过 30MB</p>
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
