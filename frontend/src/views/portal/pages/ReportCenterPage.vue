<script setup lang="ts">
import { computed, inject } from 'vue'
import {
  ArrowRight,
  Download,
  FileBarChart,
  FileText,
  FileType,
  Pencil,
  Printer,
  RefreshCw,
  Send,
} from '@lucide/vue'
import PlatformBadge from '../../../components/PlatformBadge.vue'
import { useAuthStore } from '../../../stores/auth'
import { PlatformAdminKey } from '../injectionKeys'
import { useReportCenter } from '../composables/useReportCenter'
import { platformLabelMap } from '../portalMaps'
import { formatDateTime } from '../portalUtils'
import '../../../styles/report-center.css'

const props = defineProps<{ isPlatform: boolean }>()

const platformAdmin = inject(PlatformAdminKey, null)
const auth = useAuthStore()

const pageMenuName = computed(() => (
  auth.allowedMenus.find(menu => ['customer.reports', 'platform.reports'].includes(menu.menu_code))?.menu_name || '报告中心'
))

const {
  loading,
  saving,
  publishing,
  exporting,
  detailLoading,
  editMode,
  editForm,
  filteredReports,
  selectedReportId,
  selectedReport,
  reportDetail,
  typeFilter,
  keywordFilter,
  tenantFilter,
  reportTypeOptions,
  heroMetrics,
  canEditSelected,
  canExportReport,
  previewContent,
  previewKpis,
  previewDiagnosis,
  previewHighlights,
  previewPlatforms,
  previewSources,
  previewAiInsights,
  isDeepseekReport,
  loadReports,
  selectReport,
  handleSaveDraft,
  handlePublish,
  printReport,
  exportReport,
} = useReportCenter({
  isPlatform: () => props.isPlatform,
  tenants: () => platformAdmin?.tenants.value || [],
})

function formatRank(value: number | null | undefined) {
  if (value === null || value === undefined) return '—'
  return Number.isInteger(value) ? `#${value}` : `#${value.toFixed(1)}`
}

function healthTone(score: number | null | undefined) {
  if (score == null) return ''
  if (score >= 80) return 'is-good'
  if (score >= 60) return 'is-mid'
  return 'is-warn'
}

function diagnosisTitleText(title: string | null | undefined) {
  const text = (title || '').trim()
  if (!text) return '结合监测数据的诊断建议'
  const marks = (text.match(/[?？]/g) || []).length
  if (marks >= Math.max(3, text.length / 2)) return '结合监测数据的诊断建议'
  return text
}
</script>

<template>
  <section class="report-page">
    <header class="report-sticky-bar">
      <div class="report-sticky-inner">
        <div class="report-sticky-row">
          <div class="report-type-presets">
            <button
              v-for="option in reportTypeOptions"
              :key="option.value"
              type="button"
              :class="{ active: typeFilter === option.value }"
              @click="typeFilter = option.value"
            >
              {{ option.label }}
            </button>
          </div>

          <input
            v-model="keywordFilter"
            class="report-search-input"
            placeholder="搜索报告标题、企业或摘要"
          />

          <div v-if="isPlatform" class="report-sticky-filters">
            <select v-model="tenantFilter">
              <option value="">全部企业</option>
              <option v-for="tenant in platformAdmin?.tenants.value || []" :key="tenant.id" :value="tenant.id">
                {{ tenant.name }}
              </option>
            </select>
          </div>

          <div class="report-sticky-actions">
            <span v-if="loading || detailLoading" class="competitor-loading-dot">更新中…</span>
            <button type="button" class="filter-reset-btn tiny-btn" :disabled="loading" @click="loadReports()">
              <RefreshCw />
              刷新
            </button>
          </div>
        </div>
      </div>
    </header>

    <article class="report-hero panel">
      <div class="report-hero-copy">
        <span class="report-hero-eyebrow">
          <FileBarChart />
          {{ pageMenuName }} · 监测交付
        </span>
        <h2>{{ previewContent?.brand_name || selectedReport?.tenant_name || 'GEO 监测报告' }}</h2>
        <p>
          汇总 AI 平台监测结果、品牌诊断与信源引用，形成可交付的结构化报告。
          {{ isPlatform ? '请在「企业管理」为企业生成报告，编辑确认后发布；客户仅可查看已发布报告。' : '此处展示运营已发布的报告，支持在线预览、导出 PDF/Word 与打印。' }}
        </p>
      </div>
      <article class="report-hero-metric">
        <span>报告总数</span>
        <b>{{ heroMetrics.total }}</b>
        <em>{{ heroMetrics.publishedCount }} 份已发布</em>
      </article>
      <article class="report-hero-metric">
        <span>最新健康分</span>
        <b>{{ heroMetrics.latestHealth ?? '—' }}</b>
        <em>{{ heroMetrics.latestTitle || '暂无报告' }}</em>
      </article>
      <article class="report-hero-metric">
        <span>平均健康分</span>
        <b>{{ heroMetrics.avgHealth ?? '—' }}</b>
        <em>基于当前筛选范围</em>
      </article>
    </article>

    <div class="report-layout">
      <aside class="report-list-panel">
        <div class="report-list-head">
          <div>
            <h3>报告列表</h3>
            <p>{{ filteredReports.length }} 份报告</p>
          </div>
        </div>
        <div v-if="loading && !filteredReports.length" class="report-empty-panel">
          <p>报告加载中…</p>
        </div>
        <div v-else-if="!filteredReports.length" class="report-empty-panel">
          <FileText />
          <h3>暂无报告</h3>
          <p v-if="isPlatform">请前往「企业管理」，在企业行点击「报告」选择类型并生成；生成后可在此编辑并发布。</p>
          <p v-else>暂无已发布报告，请联系运营为您生成并发布。</p>
        </div>
        <div v-else class="report-list-body">
          <button
            v-for="item in filteredReports"
            :key="item.id"
            type="button"
            class="report-card"
            :class="{ 'is-active': selectedReportId === item.id }"
            @click="selectReport(item.id)"
          >
            <div class="report-card-top">
              <b>{{ item.report_title }}</b>
              <span v-if="item.health_score != null" class="report-score-chip">{{ item.health_score }} 分</span>
            </div>
            <div class="report-card-meta">
              <span class="report-badge type">{{ item.report_type_label || item.report_type }}</span>
              <span v-if="item.ai_source === 'deepseek'" class="report-badge status">智能生成</span>
              <span class="report-badge status" :class="{ 'is-draft': item.status === 'draft' }">{{ item.status_label || item.status }}</span>
              <span v-if="isPlatform && item.tenant_name" class="report-badge type">{{ item.tenant_name }}</span>
            </div>
            <p class="report-card-summary">{{ item.data_summary || '暂无摘要' }}</p>
            <div class="report-card-foot">
              <span>{{ formatDateTime(item.created_at) }}</span>
              <span v-if="item.mention_rate != null">提及率 {{ item.mention_rate }}%</span>
            </div>
          </button>
        </div>
      </aside>

      <article class="report-preview-panel">
        <div class="report-preview-head">
          <div>
            <h3>{{ canEditSelected && editMode ? '编辑报告' : '报告预览' }}</h3>
            <p>{{ selectedReport ? (canEditSelected ? '修改后可保存草稿或直接发布' : '在线阅读 · 支持打印') : '从左侧选择一份报告' }}</p>
          </div>
          <div v-if="selectedReport" class="report-preview-actions">
            <button
              v-if="canEditSelected"
              type="button"
              class="filter-reset-btn tiny-btn"
              @click="editMode = !editMode"
            >
              <Pencil />
              {{ editMode ? '预览' : '编辑' }}
            </button>
            <button v-if="canExportReport" type="button" class="filter-reset-btn tiny-btn" :disabled="exporting" @click="exportReport('pdf')">
              <Download />
              PDF
            </button>
            <button v-if="canExportReport" type="button" class="filter-reset-btn tiny-btn" :disabled="exporting" @click="exportReport('docx')">
              <FileType />
              Word
            </button>
            <button type="button" class="filter-reset-btn tiny-btn" @click="printReport">
              <Printer />
              打印
            </button>
          </div>
        </div>

        <div v-if="detailLoading && !reportDetail" class="report-empty-panel">
          <p>报告内容加载中…</p>
        </div>
        <div v-else-if="!reportDetail" class="report-empty-panel">
          <FileBarChart />
          <h3>选择报告开始预览</h3>
          <p>报告包含 KPI 摘要、诊断结论、各平台表现与高频引用信源，便于对外交付与复盘。</p>
        </div>
        <div v-else-if="canEditSelected && editMode" class="report-preview-body report-edit-body">
          <div class="report-edit-form">
            <label><span>报告标题</span><input v-model="editForm.report_title" /></label>
            <label><span>数据摘要</span><input v-model="editForm.data_summary" /></label>
            <label><span>执行摘要</span><textarea v-model="editForm.executive_summary" rows="4" /></label>
            <label><span>核心结论（每行一条）</span><textarea v-model="editForm.highlightsText" rows="5" /></label>
            <label><span>诊断标题</span><input v-model="editForm.diagnosis_title" /></label>
            <label><span>情绪与口碑概述</span><textarea v-model="editForm.sentiment_summary" rows="3" /></label>
            <label><span>优势亮点</span><textarea v-model="editForm.strength_points" rows="3" /></label>
            <label><span>待改善项</span><textarea v-model="editForm.weakness_points" rows="3" /></label>
            <label><span>优化建议</span><textarea v-model="editForm.recommendation" rows="4" /></label>
          </div>
          <div class="report-preview-actions">
            <button type="button" class="filter-reset-btn tiny-btn" :disabled="saving" @click="handleSaveDraft">
              {{ saving ? '保存中…' : '保存草稿' }}
            </button>
            <button type="button" class="primary-btn small-btn" :disabled="publishing" @click="handlePublish">
              <Send />
              {{ publishing ? '发布中…' : '保存并发布' }}
            </button>
          </div>
        </div>
        <div v-else class="report-preview-body">
          <div class="report-preview-title">
            <div class="report-card-meta">
              <span class="report-badge type">{{ reportDetail.report_type_label || reportDetail.report_type }}</span>
              <span v-if="isDeepseekReport" class="report-badge status">智能撰写</span>
              <span class="report-badge status">{{ reportDetail.status_label || reportDetail.status }}</span>
              <span v-if="previewContent?.period_label" class="report-badge type">{{ previewContent.period_label }}</span>
            </div>
            <h2>{{ reportDetail.report_title }}</h2>
            <p v-if="previewAiInsights?.executive_summary" class="report-executive-summary">{{ previewAiInsights.executive_summary }}</p>
            <p>{{ reportDetail.data_summary }}</p>
          </div>

          <div class="report-kpi-row">
            <article class="report-kpi">
              <span>健康分</span>
              <b :class="healthTone(previewDiagnosis.health_score ?? previewKpis.health_score)">
                {{ previewDiagnosis.health_score ?? previewKpis.health_score ?? '—' }}
              </b>
              <em>综合诊断</em>
            </article>
            <article class="report-kpi">
              <span>品牌提及率</span>
              <b>{{ previewKpis.mention_rate ?? '—' }}<template v-if="previewKpis.mention_rate != null">%</template></b>
              <em>{{ previewKpis.completed_count ?? 0 }} 条样本</em>
            </article>
            <article class="report-kpi">
              <span>平均排名</span>
              <b>{{ formatRank(previewKpis.avg_rank) }}</b>
              <em>越小越靠前</em>
            </article>
            <article class="report-kpi">
              <span>引用信源</span>
              <b>{{ previewKpis.source_count ?? 0 }}</b>
              <em>含露出词引用</em>
            </article>
          </div>

          <section v-if="previewHighlights.length" class="report-section">
            <div class="report-section-head">
              <h4>核心结论</h4>
              <p>基于最新监测样本自动提炼</p>
            </div>
            <ul class="report-highlight-list">
              <li v-for="(line, index) in previewHighlights" :key="index">{{ line }}</li>
            </ul>
          </section>

          <section
            v-if="previewDiagnosis.strength_points || previewDiagnosis.weakness_points || previewDiagnosis.recommendation || previewDiagnosis.sentiment_summary"
            class="report-section"
          >
            <div class="report-section-head">
              <h4>品牌诊断</h4>
              <p>{{ diagnosisTitleText(previewDiagnosis.diagnosis_title) }}</p>
            </div>
            <p v-if="previewDiagnosis.sentiment_summary" class="report-card-summary">{{ previewDiagnosis.sentiment_summary }}</p>
            <div class="report-diagnosis-grid">
              <article v-if="previewDiagnosis.strength_points" class="report-diagnosis-block">
                <strong>优势亮点</strong>
                <p>{{ previewDiagnosis.strength_points }}</p>
              </article>
              <article v-if="previewDiagnosis.weakness_points" class="report-diagnosis-block">
                <strong>待改善项</strong>
                <p>{{ previewDiagnosis.weakness_points }}</p>
              </article>
              <article v-if="previewDiagnosis.recommendation" class="report-diagnosis-block" style="grid-column: 1 / -1">
                <strong>优化建议</strong>
                <p>{{ previewDiagnosis.recommendation }}</p>
              </article>
            </div>
          </section>

          <section v-if="previewPlatforms.length" class="report-section">
            <div class="report-section-head">
              <h4>各平台表现</h4>
              <p>已购平台 · 提及率与平均排名</p>
            </div>
            <div class="report-platform-table">
              <div class="report-platform-table-head">
                <span>平台</span><span>完成数</span><span>提及率</span><span>平均排名</span>
              </div>
              <div v-for="row in previewPlatforms" :key="row.platform" class="report-platform-table-row">
                <span>{{ platformLabelMap[row.platform] || row.platform }}</span>
                <span>{{ row.completed }}/{{ row.total }}</span>
                <span>{{ row.mention_rate }}%</span>
                <span>{{ formatRank(row.avg_rank) }}</span>
              </div>
            </div>
          </section>

          <section v-if="previewSources.length" class="report-section">
            <div class="report-section-head">
              <h4>高频引用信源</h4>
              <p>AI 回答中引用品牌露出词较多的来源</p>
            </div>
            <div class="report-source-list">
              <a
                v-for="(source, index) in previewSources"
                :key="source.url"
                class="report-source-item"
                :href="source.url"
                target="_blank"
                rel="noopener"
              >
                <span class="report-source-rank">{{ index + 1 }}</span>
                <div class="report-source-copy">
                  <b>{{ source.title }}</b>
                  <span>
                    <PlatformBadge
                      v-for="code in source.platforms.slice(0, 3)"
                      :key="code"
                      :code="code"
                      size="xs"
                      icon-only
                    />
                    {{ source.platforms.length > 3 ? `+${source.platforms.length - 3}` : '' }}
                  </span>
                </div>
                <span class="report-source-count">{{ source.count }} 次</span>
              </a>
            </div>
          </section>

          <div class="report-preview-actions">
            <button v-if="canEditSelected" type="button" class="filter-reset-btn tiny-btn" @click="editMode = true">
              <Pencil />
              编辑草稿
            </button>
            <button v-if="canExportReport" type="button" class="primary-btn small-btn" :disabled="exporting" @click="exportReport('pdf')">
              <Download />
              导出 PDF
            </button>
            <button v-if="canExportReport" type="button" class="filter-reset-btn tiny-btn" :disabled="exporting" @click="exportReport('docx')">
              <FileType />
              导出 Word
            </button>
            <button type="button" class="filter-reset-btn tiny-btn" @click="printReport">
              <Printer />
              打印报告
            </button>
            <a
              v-if="reportDetail.report_url"
              class="ghost-link-btn"
              :href="reportDetail.report_url"
              target="_blank"
              rel="noopener"
            >
              下载附件
              <ArrowRight />
            </a>
          </div>
        </div>
      </article>
    </div>
  </section>
</template>
