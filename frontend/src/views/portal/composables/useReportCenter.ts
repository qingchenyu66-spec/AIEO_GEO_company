import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '../../../stores/auth'
import { withRetry } from '../../../composables/useRetry'
import {
  downloadReportExport,
  fetchReportPreviewHtml,
  getReportDetail,
  getReportList,
  isHtmlTemplateReportType,
  type ReportDetail,
  type ReportListItem,
  type ReportType,
  type ReportExportFormat,
} from '../../../services/reports'
import type { TenantInfo } from '../../../services/management'
import { formatReportDisplayTitle } from '../portalUtils'
import { prepareReportPreviewHtml } from '../../../utils/reportPreviewHtml'

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : String(error)
}

export type ReportTypeFilter = 'all' | ReportType

const reportTypeOptions: Array<{ value: ReportTypeFilter; label: string }> = [
  { value: 'all', label: '全部' },
  { value: 'diagnosis', label: '品牌诊断' },
  { value: 'weekly', label: '监测周报' },
  { value: 'monthly', label: '监测月报' },
  { value: 'quarterly', label: '监测季报' },
  { value: 'annual', label: '监测年报' },
]

type UseReportCenterOptions = {
  isPlatform: () => boolean
  tenants: () => TenantInfo[]
}

export function useReportCenter(options: UseReportCenterOptions) {
  const route = useRoute()
  const auth = useAuthStore()
  const loading = ref(false)
  const exporting = ref(false)
  const detailLoading = ref(false)
  const previewHtmlLoading = ref(false)
  const reports = ref<ReportListItem[]>([])
  const selectedReportId = ref<number | null>(null)
  const reportDetail = ref<ReportDetail | null>(null)
  const previewHtmlBlobUrl = ref<string | null>(null)
  const typeFilter = ref<ReportTypeFilter>('all')
  const keywordFilter = ref('')
  const tenantFilter = ref<number | ''>('')

  function revokePreviewHtmlBlob() {
    if (previewHtmlBlobUrl.value) {
      URL.revokeObjectURL(previewHtmlBlobUrl.value)
      previewHtmlBlobUrl.value = null
    }
  }

  const filteredReports = computed(() => {
    let rows = reports.value
    if (typeFilter.value !== 'all') {
      rows = rows.filter(item => item.report_type === typeFilter.value)
    }
    if (options.isPlatform() && tenantFilter.value !== '') {
      rows = rows.filter(item => item.tenant_id === tenantFilter.value)
    }
    const keyword = keywordFilter.value.trim().toLowerCase()
    if (keyword) {
      rows = rows.filter(item => (
        item.report_title.toLowerCase().includes(keyword)
        || (item.tenant_name || '').toLowerCase().includes(keyword)
        || (item.data_summary || '').toLowerCase().includes(keyword)
      ))
    }
    return rows
  })

  const reportMenuGrant = computed(() => (
    auth.allowedMenus.find(menu => menu.menu_code === (options.isPlatform() ? 'platform.reports' : 'customer.reports')) || null
  ))

  const canGenerateReport = computed(() => Boolean(reportMenuGrant.value?.can_create))
  const canExportReport = computed(() => Boolean(reportMenuGrant.value?.can_export))

  const selectedReport = computed(() => (
    reports.value.find(item => item.id === selectedReportId.value) || null
  ))

  const heroMetrics = computed(() => {
    const rows = filteredReports.value
    const latest = rows[0]
    const publishedCount = rows.filter(item => item.status === 'published').length
    const avgHealth = rows.filter(item => item.health_score != null)
    const healthAvg = avgHealth.length
      ? Math.round(avgHealth.reduce((sum, item) => sum + (item.health_score || 0), 0) / avgHealth.length)
      : null
    return {
      total: rows.length,
      publishedCount,
      latestTitle: latest
        ? formatReportDisplayTitle(latest)
        : null,
      latestHealth: latest?.health_score ?? null,
      avgHealth: healthAvg,
    }
  })

  const previewContent = computed(() => reportDetail.value?.report_content || null)
  const previewKpis = computed(() => previewContent.value?.kpis || {})
  const previewDiagnosis = computed(() => previewContent.value?.diagnosis || {})
  const previewSnapshot = computed(() => previewContent.value?.monitor_snapshot || {})
  const previewHighlights = computed(() => previewSnapshot.value.highlights || [])
  const previewPlatforms = computed(() => previewSnapshot.value.platform_stats || [])
  const previewSources = computed(() => previewSnapshot.value.top_sources || [])
  const previewAiInsights = computed(() => previewContent.value?.ai_insights || null)
  const isDeepseekReport = computed(() => previewAiInsights.value?.source === 'deepseek')

  const usesHtmlTemplatePreview = computed(() => isHtmlTemplateReportType(selectedReport.value?.report_type))

  const previewHtmlUrl = computed(() => (
    usesHtmlTemplatePreview.value ? previewHtmlBlobUrl.value : null
  ))

  async function loadPreviewHtml(reportId: number) {
    if (!isHtmlTemplateReportType(reports.value.find(item => item.id === reportId)?.report_type)) {
      revokePreviewHtmlBlob()
      return
    }
    previewHtmlLoading.value = true
    try {
      const html = await prepareReportPreviewHtml(await withRetry(() => fetchReportPreviewHtml(reportId)))
      revokePreviewHtmlBlob()
      previewHtmlBlobUrl.value = URL.createObjectURL(new Blob([html], { type: 'text/html;charset=utf-8' }))
    } catch (error: unknown) {
      revokePreviewHtmlBlob()
      ElMessage.error(`报告预览加载失败：${errorMessage(error)}`)
    } finally {
      previewHtmlLoading.value = false
    }
  }

  function displayReportTitle(item: Pick<ReportListItem, 'report_title' | 'report_type' | 'tenant_name'>) {
    return formatReportDisplayTitle(item)
  }

  const heroTitle = computed(() => {
    if (options.isPlatform()) {
      return previewContent.value?.brand_name || selectedReport.value?.tenant_name || 'GEO 监测报告'
    }
    return selectedReport.value?.report_type_label
      || reportDetail.value?.report_type_label
      || 'GEO 监测报告'
  })

  function applyInitialRouteQuery() {
    const tenantId = route.query.tenantId
    if (options.isPlatform() && typeof tenantId === 'string' && tenantId) {
      tenantFilter.value = Number(tenantId)
    }
    const reportId = route.query.reportId
    if (typeof reportId === 'string' && reportId) {
      selectedReportId.value = Number(reportId)
    }
  }

  async function loadReports() {
    loading.value = true
    try {
      reports.value = await withRetry(() => getReportList())
      const visibleRows = filteredReports.value
      if (!visibleRows.length) {
        selectedReportId.value = null
        reportDetail.value = null
      } else if (!selectedReportId.value || !visibleRows.some(item => item.id === selectedReportId.value)) {
        selectedReportId.value = visibleRows[0].id
      }
    } catch (error: unknown) {
      ElMessage.error(`报告列表加载失败：${errorMessage(error)}`)
    } finally {
      loading.value = false
    }
  }

  async function loadReportDetail(reportId: number) {
    detailLoading.value = true
    try {
      reportDetail.value = await withRetry(() => getReportDetail(reportId))
    } catch (error: unknown) {
      reportDetail.value = null
      ElMessage.error(`报告详情加载失败：${errorMessage(error)}`)
    } finally {
      detailLoading.value = false
    }
  }

  function selectReport(reportId: number) {
    selectedReportId.value = reportId
  }

  function printReport() {
    const frame = document.querySelector('.report-html-frame') as HTMLIFrameElement | null
    if (frame?.contentWindow) {
      frame.contentWindow.focus()
      frame.contentWindow.print()
      return
    }
    window.print()
  }

  async function exportReport(format: ReportExportFormat) {
    if (!selectedReportId.value) {
      ElMessage.warning('请先选择一份报告')
      return
    }
    if (!canExportReport.value) {
      ElMessage.warning('当前账号无权导出报告')
      return
    }
    exporting.value = true
    try {
      await withRetry(() => downloadReportExport(selectedReportId.value!, format))
      const label = format === 'pdf' ? 'PDF' : format === 'html' ? 'HTML' : 'Word'
      ElMessage.success(`${label} 已下载`)
    } catch (error: unknown) {
      ElMessage.error(`报告导出失败：${errorMessage(error)}`)
    } finally {
      exporting.value = false
    }
  }

  watch(selectedReportId, reportId => {
    if (reportId) {
      void loadReportDetail(reportId)
      void loadPreviewHtml(reportId)
    } else {
      reportDetail.value = null
      revokePreviewHtmlBlob()
    }
  })

  watch([typeFilter, tenantFilter], () => {
    if (!filteredReports.value.length) {
      selectedReportId.value = null
      reportDetail.value = null
      revokePreviewHtmlBlob()
    } else if (!filteredReports.value.some(item => item.id === selectedReportId.value)) {
      selectedReportId.value = filteredReports.value[0]?.id ?? null
    }
  })

  onMounted(async () => {
    applyInitialRouteQuery()
    if (options.isPlatform() && options.tenants().length && tenantFilter.value === '') {
      tenantFilter.value = options.tenants()[0].id
    }
    await loadReports()
    applyInitialRouteQuery()
    if (selectedReportId.value) {
      await Promise.all([
        loadReportDetail(selectedReportId.value),
        loadPreviewHtml(selectedReportId.value),
      ])
    }
  })

  onUnmounted(() => {
    revokePreviewHtmlBlob()
  })

  return {
    loading,
    exporting,
    detailLoading,
    previewHtmlLoading,
    reports,
    filteredReports,
    selectedReportId,
    selectedReport,
    reportDetail,
    typeFilter,
    keywordFilter,
    tenantFilter,
    reportTypeOptions,
    heroMetrics,
    canGenerateReport,
    canExportReport,
    previewContent,
    previewKpis,
    previewDiagnosis,
    previewSnapshot,
    previewHighlights,
    previewPlatforms,
    previewSources,
    previewAiInsights,
    isDeepseekReport,
    usesHtmlTemplatePreview,
    previewHtmlUrl,
    heroTitle,
    displayReportTitle,
    loadReports,
    selectReport,
    printReport,
    exportReport,
  }
}
