import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useAuthStore } from '../../../stores/auth'
import { withRetry } from '../../../composables/useRetry'
import {
  downloadReportExport,
  getReportDetail,
  getReportList,
  publishReport,
  updateReport,
  type ReportDetail,
  type ReportListItem,
  type ReportType,
  type ReportExportFormat,
} from '../../../services/reports'
import type { TenantInfo } from '../../../services/management'
import { stripReportCompanyPrefix } from '../portalUtils'

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : String(error)
}

export type ReportTypeFilter = 'all' | ReportType

const reportTypeOptions: Array<{ value: ReportTypeFilter; label: string }> = [
  { value: 'all', label: '全部' },
  { value: 'diagnosis', label: '企业诊断' },
  { value: 'weekly', label: '监测周报' },
  { value: 'monthly', label: '监测月报' },
  { value: 'annual', label: '监测年报' },
  { value: 'comparison', label: '对比报告' },
]

type UseReportCenterOptions = {
  isPlatform: () => boolean
  tenants: () => TenantInfo[]
}

export function useReportCenter(options: UseReportCenterOptions) {
  const route = useRoute()
  const auth = useAuthStore()
  const loading = ref(false)
  const saving = ref(false)
  const publishing = ref(false)
  const exporting = ref(false)
  const detailLoading = ref(false)
  const editMode = ref(false)
  const reports = ref<ReportListItem[]>([])
  const selectedReportId = ref<number | null>(null)
  const reportDetail = ref<ReportDetail | null>(null)
  const typeFilter = ref<ReportTypeFilter>('all')
  const keywordFilter = ref('')
  const tenantFilter = ref<number | ''>('')

  const editForm = reactive({
    report_title: '',
    data_summary: '',
    executive_summary: '',
    highlightsText: '',
    sentiment_summary: '',
    strength_points: '',
    weakness_points: '',
    recommendation: '',
    diagnosis_title: '',
  })

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
  const canEditReport = computed(() => Boolean(reportMenuGrant.value?.can_update))
  const canExportReport = computed(() => Boolean(reportMenuGrant.value?.can_export))

  const selectedReport = computed(() => (
    reports.value.find(item => item.id === selectedReportId.value) || null
  ))

  const canEditSelected = computed(() => (
    canEditReport.value
    && (selectedReport.value?.status === 'draft' || reportDetail.value?.status === 'draft')
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
        ? (options.isPlatform() ? latest.report_title : displayReportTitle(latest))
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

  function reportCompanyNames(item?: { tenant_name?: string | null } | null) {
    return [
      previewContent.value?.brand_name,
      item?.tenant_name,
      selectedReport.value?.tenant_name,
    ]
  }

  function displayReportTitle(item: Pick<ReportListItem, 'report_title' | 'tenant_name'>) {
    if (options.isPlatform()) return item.report_title
    return stripReportCompanyPrefix(item.report_title, reportCompanyNames(item))
  }

  const heroTitle = computed(() => {
    if (options.isPlatform()) {
      return previewContent.value?.brand_name || selectedReport.value?.tenant_name || 'GEO 监测报告'
    }
    return selectedReport.value?.report_type_label
      || reportDetail.value?.report_type_label
      || 'GEO 监测报告'
  })

  function syncEditFormFromDetail(detail: ReportDetail | null) {
    const content = detail?.report_content
    editForm.report_title = detail?.report_title || ''
    editForm.data_summary = detail?.data_summary || ''
    editForm.executive_summary = content?.ai_insights?.executive_summary || ''
    editForm.highlightsText = (content?.monitor_snapshot?.highlights || []).join('\n')
    editForm.sentiment_summary = content?.diagnosis?.sentiment_summary || ''
    editForm.strength_points = content?.diagnosis?.strength_points || ''
    editForm.weakness_points = content?.diagnosis?.weakness_points || ''
    editForm.recommendation = content?.diagnosis?.recommendation || ''
    editForm.diagnosis_title = content?.diagnosis?.diagnosis_title || ''
  }

  function applyInitialRouteQuery() {
    const tenantId = route.query.tenantId
    if (options.isPlatform() && typeof tenantId === 'string' && tenantId) {
      tenantFilter.value = Number(tenantId)
    }
    const reportId = route.query.reportId
    if (typeof reportId === 'string' && reportId) {
      selectedReportId.value = Number(reportId)
      if (canEditSelected.value || options.isPlatform()) {
        editMode.value = true
      }
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
        editMode.value = false
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
      syncEditFormFromDetail(reportDetail.value)
      if (canEditSelected.value) {
        editMode.value = true
      }
    } catch (error: unknown) {
      reportDetail.value = null
      ElMessage.error(`报告详情加载失败：${errorMessage(error)}`)
    } finally {
      detailLoading.value = false
    }
  }

  function selectReport(reportId: number) {
    selectedReportId.value = reportId
    editMode.value = false
  }

  async function handleSaveDraft() {
    if (!selectedReportId.value || !canEditSelected.value) return
    saving.value = true
    try {
      const updated = await withRetry(() => updateReport(selectedReportId.value!, {
        report_title: editForm.report_title.trim(),
        data_summary: editForm.data_summary.trim(),
        executive_summary: editForm.executive_summary.trim(),
        highlights: editForm.highlightsText,
        diagnosis: {
          sentiment_summary: editForm.sentiment_summary.trim(),
          strength_points: editForm.strength_points.trim(),
          weakness_points: editForm.weakness_points.trim(),
          recommendation: editForm.recommendation.trim(),
          diagnosis_title: editForm.diagnosis_title.trim(),
        },
      }))
      reportDetail.value = updated
      syncEditFormFromDetail(updated)
      ElMessage.success('草稿已保存')
      await loadReports()
    } catch (error: unknown) {
      ElMessage.error(`保存失败：${errorMessage(error)}`)
    } finally {
      saving.value = false
    }
  }

  async function handlePublish() {
    if (!selectedReportId.value || !canEditReport.value) return
    try {
      await ElMessageBox.confirm('发布后客户可在报告中心查看，确认发布？', '发布报告', {
        confirmButtonText: '发布',
        cancelButtonText: '取消',
        type: 'warning',
      })
    } catch {
      return
    }
    publishing.value = true
    try {
      if (canEditSelected.value) {
        await withRetry(() => updateReport(selectedReportId.value!, {
          report_title: editForm.report_title.trim(),
          data_summary: editForm.data_summary.trim(),
          executive_summary: editForm.executive_summary.trim(),
          highlights: editForm.highlightsText,
          diagnosis: {
            sentiment_summary: editForm.sentiment_summary.trim(),
            strength_points: editForm.strength_points.trim(),
            weakness_points: editForm.weakness_points.trim(),
            recommendation: editForm.recommendation.trim(),
            diagnosis_title: editForm.diagnosis_title.trim(),
          },
        }))
      }
      await withRetry(() => publishReport(selectedReportId.value!))
      ElMessage.success('报告已发布')
      editMode.value = false
      await loadReports()
      await loadReportDetail(selectedReportId.value!)
    } catch (error: unknown) {
      ElMessage.error(`发布失败：${errorMessage(error)}`)
    } finally {
      publishing.value = false
    }
  }

  function printReport() {
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
      ElMessage.success(format === 'pdf' ? 'PDF 已下载' : 'Word 已下载')
    } catch (error: unknown) {
      ElMessage.error(`报告导出失败：${errorMessage(error)}`)
    } finally {
      exporting.value = false
    }
  }

  watch(selectedReportId, reportId => {
    if (reportId) void loadReportDetail(reportId)
    else reportDetail.value = null
  })

  watch([typeFilter, tenantFilter], () => {
    if (!filteredReports.value.length) {
      selectedReportId.value = null
      reportDetail.value = null
      editMode.value = false
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
      await loadReportDetail(selectedReportId.value)
    }
  })

  return {
    loading,
    saving,
    publishing,
    exporting,
    detailLoading,
    editMode,
    editForm,
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
    canEditSelected,
    canGenerateReport,
    canEditReport,
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
    heroTitle,
    displayReportTitle,
    loadReports,
    selectReport,
    handleSaveDraft,
    handlePublish,
    printReport,
    exportReport,
  }
}
