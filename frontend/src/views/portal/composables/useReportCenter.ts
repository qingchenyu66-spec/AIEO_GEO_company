import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useAuthStore } from '../../../stores/auth'
import { withRetry } from '../../../composables/useRetry'
import {
  downloadReportExport,
  fetchReportPreviewHtml,
  getReportDetail,
  getReportList,
  isHtmlTemplateReportType,
  startReportRefreshJob,
  waitReportRefreshJob,
  type ReportDetail,
  type ReportListItem,
  type ReportType,
  type ReportExportFormat,
} from '../../../services/reports'
import { getTenants, isTenantInService, type TenantInfo } from '../../../services/management'
import { formatReportDisplayTitle } from '../portalUtils'
import { prepareReportPreviewHtml, prefetchReportPreviewAssets } from '../../../utils/reportPreviewHtml'
import { isCustomerPreviewActive, parsePreviewTenantId } from '../customerPreview'

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
  { value: 'completion', label: '项目结项报告' },
]

const CUSTOMER_PORTAL_REPORT_TYPES = new Set(['weekly', 'monthly', 'quarterly', 'annual', 'completion'])

type UseReportCenterOptions = {
  isPlatform: () => boolean
}

export function useReportCenter(options: UseReportCenterOptions) {
  const route = useRoute()
  const auth = useAuthStore()
  const isPreviewMode = computed(() => (
    isCustomerPreviewActive(route, auth.session?.identity?.identity_type === 'PLATFORM')
  ))
  const previewTenantId = computed(() => parsePreviewTenantId(route))
  const loading = ref(false)
  const refreshing = ref(false)
  const exporting = ref(false)
  const exportingFormat = ref<ReportExportFormat | null>(null)
  const exportProgress = ref('')
  const detailLoading = ref(false)
  const previewHtmlLoading = ref(false)
  const reports = ref<ReportListItem[]>([])
  const selectedReportId = ref<number | null>(null)
  const reportDetail = ref<ReportDetail | null>(null)
  const previewHtmlBlobUrl = ref<string | null>(null)
  /** 会话内按报告 id 复用 blob，避免反复下 30MB+ HTML */
  const previewHtmlBlobById = new Map<number, string>()
  const typeFilter = ref<ReportTypeFilter>('all')
  const keywordFilter = ref('')
  const tenantFilter = ref<number | ''>('')
  // 2026-07-29 - 报告中心企业筛选项为空：不依赖 platformAdmin.tenants（仅用户管理页加载），本页自拉服务中企业
  const filterTenants = ref<TenantInfo[]>([])

  async function loadFilterTenants() {
    if (!options.isPlatform() || isPreviewMode.value) {
      filterTenants.value = []
      return
    }
    try {
      const rows = await withRetry(() => getTenants())
      filterTenants.value = rows.filter(isTenantInService)
    } catch {
      filterTenants.value = []
    }
    if (
      tenantFilter.value !== ''
      && !filterTenants.value.some(tenant => tenant.id === tenantFilter.value)
    ) {
      tenantFilter.value = ''
    }
  }

  function revokePreviewHtmlBlob() {
    previewHtmlBlobUrl.value = null
  }

  function revokeAllPreviewHtmlBlobs() {
    for (const url of previewHtmlBlobById.values()) {
      URL.revokeObjectURL(url)
    }
    previewHtmlBlobById.clear()
    previewHtmlBlobUrl.value = null
  }

  const filteredReports = computed(() => {
    let rows = reports.value
    if (isPreviewMode.value && previewTenantId.value != null) {
      rows = rows.filter(item => (
        item.tenant_id === previewTenantId.value
        && item.status === 'published'
        && CUSTOMER_PORTAL_REPORT_TYPES.has(item.report_type)
      ))
    }
    if (typeFilter.value !== 'all') {
      rows = rows.filter(item => item.report_type === typeFilter.value)
    }
    if (options.isPlatform() && !isPreviewMode.value && tenantFilter.value !== '') {
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
    auth.allowedMenus.find(menu => menu.menu_code === (options.isPlatform() || isPreviewMode.value ? 'platform.reports' : 'customer.reports')) || null
  ))

  const canGenerateReport = computed(() => !isPreviewMode.value && Boolean(reportMenuGrant.value?.can_create))
  const canExportReport = computed(() => Boolean(reportMenuGrant.value?.can_export))
  // 运营端报告中心可见即可重算；客户/预览不露
  const canRefreshReport = computed(() => (
    options.isPlatform()
    && !isPreviewMode.value
    && Boolean(selectedReportId.value)
  ))

  function invalidatePreviewCache(reportId: number) {
    const cached = previewHtmlBlobById.get(reportId)
    if (cached) {
      URL.revokeObjectURL(cached)
      previewHtmlBlobById.delete(reportId)
    }
    if (previewHtmlBlobUrl.value && selectedReportId.value === reportId) {
      previewHtmlBlobUrl.value = null
    }
  }

  const visibleReportTypeOptions = computed(() => {
    if (options.isPlatform() && !isPreviewMode.value) return reportTypeOptions
    return reportTypeOptions.filter(item => item.value === 'all' || CUSTOMER_PORTAL_REPORT_TYPES.has(item.value))
  })

  const selectedReport = computed(() => (
    reports.value.find(item => item.id === selectedReportId.value) || null
  ))

  const heroMetrics = computed(() => {
    const rows = filteredReports.value
    const latest = rows[0]
    const publishedCount = rows.filter(item => item.status === 'published').length
    const latestTitle = latest ? formatReportDisplayTitle(latest) : null
    const latestTypeLabel = latest?.report_type_label || latest?.report_type || null
    // 2026-07-30 - hero 去健康分 - 第三卡优先提及率，缺省再均位
    let latestMetricLabel = '最新提及率'
    let latestMetricValue: string | number = '—'
    let latestMetricHint = latestTitle || '暂无报告'
    if (latest?.mention_rate != null) {
      latestMetricLabel = '最新提及率'
      latestMetricValue = `${latest.mention_rate}%`
    } else if (latest?.avg_rank != null) {
      latestMetricLabel = '最新均位'
      latestMetricValue = latest.avg_rank
    } else if (!latest) {
      latestMetricHint = '暂无报告'
    } else {
      latestMetricHint = '暂无监测指标'
    }
    return {
      total: rows.length,
      publishedCount,
      latestTitle,
      latestTypeLabel,
      latestMetricLabel,
      latestMetricValue,
      latestMetricHint,
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
    const cachedUrl = previewHtmlBlobById.get(reportId)
    if (cachedUrl) {
      previewHtmlBlobUrl.value = cachedUrl
      previewHtmlLoading.value = false
      return
    }
    previewHtmlLoading.value = true
    try {
      const html = await prepareReportPreviewHtml(await withRetry(() => fetchReportPreviewHtml(reportId)))
      const url = URL.createObjectURL(new Blob([html], { type: 'text/html;charset=utf-8' }))
      previewHtmlBlobById.set(reportId, url)
      previewHtmlBlobUrl.value = url
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
    if (options.isPlatform() && !isPreviewMode.value) {
      return previewContent.value?.brand_name || selectedReport.value?.tenant_name || 'GEO 监测报告'
    }
    return selectedReport.value?.report_type_label
      || reportDetail.value?.report_type_label
      || 'GEO 监测报告'
  })

  function applyInitialRouteQuery() {
    const tenantId = route.query.tenantId
    if (options.isPlatform() && !isPreviewMode.value && typeof tenantId === 'string' && tenantId) {
      tenantFilter.value = Number(tenantId)
    }
    if (isPreviewMode.value && previewTenantId.value != null) {
      tenantFilter.value = previewTenantId.value
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
    exportingFormat.value = format
    exportProgress.value = '内容写入中…'
    try {
      await downloadReportExport(selectedReportId.value!, format, (label) => {
        exportProgress.value = label
      })
      const label = format === 'pdf' ? 'PDF' : format === 'html' ? 'HTML' : 'Word'
      ElMessage.success(`${label} 已下载`)
    } catch (error: unknown) {
      ElMessage.error(`报告导出失败：${errorMessage(error)}`)
    } finally {
      exporting.value = false
      exportingFormat.value = null
      exportProgress.value = ''
    }
  }

  async function refreshCurrentReport() {
    if (!canRefreshReport.value || !selectedReportId.value) {
      ElMessage.warning('请先选择一份报告')
      return
    }
    const reportId = selectedReportId.value
    const title = selectedReport.value ? displayReportTitle(selectedReport.value) : `报告 #${reportId}`
    try {
      await ElMessageBox.confirm(
        `将按最新监测数据重新计算「${title}」，并覆盖当前预览与导出内容。任务在后台执行，可离开本页。是否继续？`,
        '重新计算报告',
        { type: 'warning', confirmButtonText: '开始重算', cancelButtonText: '取消' },
      )
    } catch {
      return
    }
    refreshing.value = true
    try {
      const job = await startReportRefreshJob(reportId)
      ElMessage.info('开始后台重算')
      const finished = await waitReportRefreshJob(job.job_id, (label) => {
        if (label) exportProgress.value = label
      })
      const updated = finished.result
      if (updated) {
        const idx = reports.value.findIndex(item => item.id === reportId)
        if (idx >= 0) {
          reports.value[idx] = { ...reports.value[idx], ...updated }
        }
      } else {
        await loadReports()
      }
      invalidatePreviewCache(reportId)
      if (selectedReportId.value === reportId) {
        const reportType = updated?.report_type
          || reports.value.find(item => item.id === reportId)?.report_type
        if (isHtmlTemplateReportType(reportType)) {
          reportDetail.value = null
          await loadPreviewHtml(reportId)
        } else {
          await loadReportDetail(reportId)
        }
      }
      ElMessage.success('报告已重新计算')
    } catch (error: unknown) {
      ElMessage.error(`报告重算失败：${errorMessage(error)}`)
    } finally {
      refreshing.value = false
      exportProgress.value = ''
    }
  }

  watch(selectedReportId, reportId => {
    if (reportId) {
      const reportType = reports.value.find(item => item.id === reportId)?.report_type
      if (isHtmlTemplateReportType(reportType)) {
        // HTML 模板预览不依赖 detail JSON，免并行拖慢首屏
        reportDetail.value = null
        void loadPreviewHtml(reportId)
      } else {
        revokePreviewHtmlBlob()
        void loadReportDetail(reportId)
      }
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
    // 2026-07-28 - 客户门户首点周报慢：进页先预取母版图/echarts（平台端常已有缓存）
    prefetchReportPreviewAssets()
    applyInitialRouteQuery()
    await loadFilterTenants()
    applyInitialRouteQuery()
    // 2026-07-29 - 深链 tenantId 可能指向非服务中企业；筛选项只含服务中，需再次钳制
    if (
      tenantFilter.value !== ''
      && !filterTenants.value.some(tenant => tenant.id === tenantFilter.value)
    ) {
      tenantFilter.value = ''
    }
    await loadReports()
    if (selectedReportId.value) {
      await Promise.all([
        loadReportDetail(selectedReportId.value),
        loadPreviewHtml(selectedReportId.value),
      ])
    }
  })

  onUnmounted(() => {
    revokeAllPreviewHtmlBlobs()
  })

  return {
    loading,
    refreshing,
    exporting,
    exportingFormat,
    exportProgress,
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
    filterTenants,
    reportTypeOptions: visibleReportTypeOptions,
    heroMetrics,
    canGenerateReport,
    canExportReport,
    canRefreshReport,
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
    refreshCurrentReport,
  }
}
