<script setup lang="ts">
import { computed, inject } from 'vue'
import {
  ArrowRight,
  Download,
  FileBarChart,
  FileText,
  FileType,
  Printer,
  RefreshCw,
} from '@lucide/vue'
import PlatformBadge from '../../../components/PlatformBadge.vue'
import { useAuthStore } from '../../../stores/auth'
import { PlatformAdminKey } from '../injectionKeys'
import { useReportCenter } from '../composables/useReportCenter'
import { platformLabelMap } from '../portalMaps'
import { formatDateTime, externalLink } from '../portalUtils'
import '../../../styles/report-center.css'

const props = defineProps<{ isPlatform: boolean }>()

const platformAdmin = inject(PlatformAdminKey, null)
const auth = useAuthStore()

const pageMenuName = computed(() => (
  auth.allowedMenus.find(menu => ['customer.reports', 'platform.reports'].includes(menu.menu_code))?.menu_name || '报告中心'
))

const {
  loading,
  exporting,
  detailLoading,
  previewHtmlLoading,
  filteredReports,
  selectedReportId,
  selectedReport,
  reportDetail,
  typeFilter,
  keywordFilter,
  tenantFilter,
  reportTypeOptions,
  heroMetrics,
  heroTitle,
  displayReportTitle,
  canExportReport,
  previewContent,
  previewKpis,
  previewDiagnosis,
  previewHighlights,
  previewPlatforms,
  previewSources,
  previewAiInsights,
  usesHtmlTemplatePreview,
  previewHtmlUrl,
  loadReports,
  selectReport,
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
  <section class="report-page" :class="{ 'is-customer-reports': !isPlatform }">
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
            placeholder="搜索报告标题或摘要"
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
        <h2>{{ heroTitle }}</h2>
        <p>
          汇总 AI 平台监测结果、品牌诊断与信源引用，形成可交付的结构化报告。
          {{ isPlatform ? '周期报告自动发布至客户端；企业诊断仅供运营内部预览导出。' : '此处展示已发布的周期监测报告，支持在线预览、导出 PDF/HTML/Word 与打印。' }}
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
          <p v-if="isPlatform">请前往「企业管理」生成企业内部诊断；周期报告由系统自动生成。</p>
          <p v-else>暂无已发布的周期监测报告，请联系运营。</p>
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
              <b>{{ displayReportTitle(item) }}</b>
              <span v-if="item.health_score != null" class="report-score-chip">{{ item.health_score }} 分</span>
            </div>
            <div class="report-card-meta">
              <span class="report-badge type">{{ item.report_type_label || item.report_type }}</span>
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
            <h3>报告预览</h3>
            <p>{{ selectedReport ? '在线阅读 · 支持导出与打印' : '从左侧选择一份报告' }}</p>
          </div>
          <div v-if="selectedReport" class="report-preview-actions">
            <button v-if="canExportReport" type="button" class="filter-reset-btn tiny-btn" :disabled="exporting" @click="exportReport('pdf')">
              <Download />
              PDF
            </button>
            <button v-if="canExportReport && usesHtmlTemplatePreview" type="button" class="filter-reset-btn tiny-btn" :disabled="exporting" @click="exportReport('html')">
              <FileText />
              HTML
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

        <div
          v-if="usesHtmlTemplatePreview && (previewHtmlLoading || previewHtmlUrl)"
          class="report-preview-body report-html-preview"
        >
          <div v-if="previewHtmlLoading && !previewHtmlUrl" class="report-empty-panel">
            <p>报告预览加载中…</p>
          </div>
          <iframe
            v-else-if="previewHtmlUrl"
            :key="previewHtmlUrl"
            class="report-html-frame"
            :src="previewHtmlUrl"
            title="报告 HTML 预览"
          />
          <div class="report-preview-actions">
            <button v-if="canExportReport" type="button" class="primary-btn small-btn" :disabled="exporting" @click="exportReport('pdf')">
              <Download />
              导出 PDF
            </button>
            <button v-if="canExportReport" type="button" class="filter-reset-btn tiny-btn" :disabled="exporting" @click="exportReport('html')">
              <FileText />
              导出 HTML
            </button>
            <button v-if="canExportReport" type="button" class="filter-reset-btn tiny-btn" :disabled="exporting" @click="exportReport('docx')">
              <FileType />
              导出 Word
            </button>
            <button type="button" class="filter-reset-btn tiny-btn" @click="printReport">
              <Printer />
              打印报告
            </button>
          </div>
        </div>
        <div v-else-if="detailLoading && !reportDetail" class="report-empty-panel">
          <p>报告内容加载中…</p>
        </div>
        <div v-else-if="!selectedReport" class="report-empty-panel">
          <FileBarChart />
          <h3>选择报告开始预览</h3>
          <p>报告包含 KPI 摘要、诊断结论、各平台表现与高频引用信源，便于对外交付与复盘。</p>
        </div>
        <div v-else-if="!reportDetail" class="report-empty-panel">
          <FileBarChart />
          <h3>报告详情加载失败</h3>
          <p>请点击刷新重试；HTML 模板类报告应走上方预览通道。</p>
        </div>
        <div v-else class="report-preview-body">
          <div class="report-preview-title">
            <div class="report-card-meta">
              <span class="report-badge type">{{ reportDetail.report_type_label || reportDetail.report_type }}</span>
              <span class="report-badge status">{{ reportDetail.status_label || reportDetail.status }}</span>
              <span
                v-if="previewContent?.period_label && reportDetail.report_type !== 'diagnosis'"
                class="report-badge type"
              >{{ previewContent.period_label }}</span>
            </div>
            <h2>{{ displayReportTitle(reportDetail) }}</h2>
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
              <template v-for="(source, index) in previewSources" :key="source.url">
                <a
                  v-if="externalLink(source.url)"
                  class="report-source-item"
                  :href="externalLink(source.url)!"
                  target="_blank"
                  rel="noopener noreferrer"
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
              </template>
            </div>
          </section>

          <div class="report-preview-actions">
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
              v-if="externalLink(reportDetail.report_url)"
              class="ghost-link-btn"
              :href="externalLink(reportDetail.report_url)!"
              target="_blank"
              rel="noopener noreferrer"
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
