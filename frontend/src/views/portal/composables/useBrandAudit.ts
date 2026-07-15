import { computed, nextTick, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useAuthStore } from '../../../stores/auth'
import { withRetry } from '../../../composables/useRetry'
import { notifyOperationError } from '../../../utils/requestError'
import {
  createTenant, deleteTenant, getTenants, listTenantSalesOwners, restoreTenant, transferTenantOwner, updateTenant,
  type TenantInfo,
  type TenantSalesOwner,
} from '../../../services/management'
import {
  createCompetitor, deleteCompetitor, defaultKeywordGroupName, getBrandAsset, keywordGroupDisplayName, keywordGroupMonitorKeywords, saveBrandAsset, updateCompetitor,
  normalizePlatformSelections, platformSelectionCodes,
  type BrandAsset, type BrandCompetitor, type BrandKeywordGroup, type PlatformSelection,
} from '../../../services/brand'
import { getKnowledgeFiles, deleteKnowledgeFile, downloadKnowledgeFile, getKnowledgeFileContent, type KnowledgeFileRecord } from '../../../services/knowledge'
import { isDuplicateMergedApproval, isPendingApproval, pendingApprovalMessage } from '../../../services/approvals'
import { createReport, REPORT_TYPE_OPTIONS, type ReportType } from '../../../services/reports'
import { getPlatformsForBrandConfig } from '../../../services/platforms'
import { platformLabelMap, supportedPlatforms, formatPlatformLabels } from '../portalMaps'
import { regionOptions, selectableRegionOptions, regionLabels } from '../regionOptions'

export type EnterpriseTab = 'profile' | 'keywords' | 'schedule' | 'competitors' | 'files'

export const enterprisePermissionCodeMap = {
  list: 'platform.audit.list',
  profile: 'platform.audit.profile',
  keywords: 'platform.audit.keywords',
  schedule: 'platform.audit.schedule',
  competitors: 'platform.audit.competitors',
  files: 'platform.audit.files',
} as const

export type UseBrandAuditOptions = {
  onBrandUpdated?: (asset: BrandAsset | null, competitors: BrandCompetitor[]) => void
  navigateToReportCenter?: (reportId: number, tenantId: number) => void
}

function errorMessage(error: unknown) {
  const response = (error as { response?: { data?: { detail?: unknown } } })?.response
  const detail = response?.data?.detail
  if (Array.isArray(detail)) {
    const fieldMap: Record<string, string> = {
      username: '登录账号',
      password: '初始密码',
      display_name: '用户姓名',
      identities: '登录身份',
      role_code: '角色',
      identity_name: '身份名称',
      tenant_name: '企业名称',
      menu_ids: '菜单权限',
    }
    const translate = (msg: string) => {
      if (msg.includes('at least 3 characters')) return '至少填写 3 个字符'
      if (msg.includes('at least 2 characters')) return '至少填写 2 个字符'
      if (msg.includes('at least 6 characters')) return '至少填写 6 个字符'
      if (msg.includes('String should have at most')) return '内容过长'
      if (msg.includes('Field required')) return '不能为空'
      return msg
    }
    return detail.map((item: { loc?: unknown[]; msg?: string }) => {
      const field = String(item.loc?.slice(-1)[0] || '字段')
      return `${fieldMap[field] || field}：${translate(item.msg || '')}`
    }).join('；')
  }
  if (typeof detail === 'string') return detail
  return (error as Error)?.message || '操作失败，请稍后重试'
}

function notifyError(error: unknown, context: string) {
  notifyOperationError(error, context, errorMessage)
}

export function useBrandAudit(options: UseBrandAuditOptions = {}) {
  const auth = useAuthStore()
  const isPlatform = computed(() => auth.session?.identity?.identity_type === 'PLATFORM')

  function menuGrant(code: string) {
    return auth.allowedMenus.find(menu => menu.menu_code === code)
  }

  function canViewEnterpriseTab(tab: EnterpriseTab) {
    const grant = menuGrant(enterprisePermissionCodeMap[tab])
    return Boolean(grant && (grant.can_export || grant.can_update || grant.can_create || grant.can_delete))
  }

  function canEditEnterpriseTab(tab: EnterpriseTab) {
    const grant = menuGrant(enterprisePermissionCodeMap[tab])
    return Boolean(grant?.can_update)
  }

  const canCreateTenant = computed(() => Boolean(menuGrant(enterprisePermissionCodeMap.list)?.can_update))
  const canEditTenantList = computed(() => Boolean(menuGrant(enterprisePermissionCodeMap.list)?.can_update))

  const visibleEnterpriseTabs = computed(() => ([
    { code: 'profile', name: '企业资料' },
    { code: 'keywords', name: '监测词配置' },
    { code: 'schedule', name: '监控计划' },
    { code: 'competitors', name: '竞品监控' },
    { code: 'files', name: '上传文件' },
  ] as Array<{ code: EnterpriseTab; name: string }>).filter(tab => canViewEnterpriseTab(tab.code)))

  const tenants = ref<TenantInfo[]>([])
  const enterpriseDetailMode = ref(false)
  const enterpriseDetailTab = ref<EnterpriseTab>('profile')
  const enterpriseInfoDialog = ref(false)
  const enterpriseInfoLoading = ref(false)
  const enterpriseInfoTenant = ref<TenantInfo | null>(null)
  const enterpriseInfoAsset = ref<BrandAsset | null>(null)
  const enterpriseInfoCompetitors = ref<BrandCompetitor[]>([])
  const enterpriseFilters = reactive({
    keyword: '',
    expiry: 'active' as 'all' | 'active' | 'pending' | 'expired' | 'stopped',
    owner_user_id: 'all' as 'all' | 'none' | number,
  })
  const tenantDialog = ref(false)
  const tenantForm = reactive({ name: '', code: '', service_start_date: '', service_end_date: '' })
  const tenantTransferDialog = ref(false)
  const tenantTransferTarget = ref<TenantInfo | null>(null)
  const tenantTransferOwnerId = ref<number | null>(null)
  const tenantSalesOwners = ref<TenantSalesOwner[]>([])
  const loadingTenantSalesOwners = ref(false)
  const transferringTenantOwner = ref(false)
  const canTransferTenantOwner = computed(() => Boolean(menuGrant('platform.approvals')?.can_update))
  const canFilterBySales = computed(() => canTransferTenantOwner.value)
  const tenantSalesFilterOptions = computed(() => {
    const map = new Map<number, string>()
    for (const owner of tenantSalesOwners.value) {
      map.set(owner.id, owner.display_name)
    }
    for (const tenant of tenants.value) {
      if (tenant.owner_user_id && !map.has(tenant.owner_user_id)) {
        map.set(tenant.owner_user_id, tenantOwnerLabel(tenant))
      }
    }
    return Array.from(map.entries())
      .map(([id, name]) => ({ id, name }))
      .sort((a, b) => a.name.localeCompare(b.name, 'zh-CN'))
  })
  const knowledgeFiles = ref<KnowledgeFileRecord[]>([])
  const loadingKnowledgeFiles = ref(false)
  const knowledgePreviewVisible = ref(false)
  const knowledgePreviewFile = ref<KnowledgeFileRecord | null>(null)
  const knowledgePreviewText = ref('')
  const knowledgePreviewLoading = ref(false)
  const knowledgePreviewError = ref('')
  const canDeleteKnowledgeFiles = computed(() => isPlatform.value && canViewEnterpriseTab('files'))
  const brandAsset = ref<BrandAsset | null>(null)
  const brandCompetitors = ref<BrandCompetitor[]>([])
  const competitorRows = ref<Array<{
    id: number | null
    name: string
    short_name: string
    aliases_text: string
    website_url: string
    category: string
    saving?: boolean
  }>>([])
  const keywordGroupRows = ref<BrandKeywordGroup[]>([])
  const catalogPlatforms = ref<Awaited<ReturnType<typeof getPlatformsForBrandConfig>>['platforms']>([])
  const modeDialogVisible = ref(false)
  const modeDialogTarget = ref<{ groupIndex: number; code: string } | null>(null)
  const modeDialogForm = reactive({
    mode: 'standard' as PlatformSelection['mode'],
    screenshot: 1 as PlatformSelection['screenshot'],
  })
  const editingGroupIndex = ref<number | null>(null)
  const competitorNameInput = ref('')
  const loadingBrand = ref(false)
  const brandForm = reactive({
    tenant_id: null as number | null,
    company_full_name: '',
    tenant_code: '',
    tenant_status: true,
    tenant_stop_reason: null as TenantInfo['stop_reason'],
    service_start_date: '',
    service_end_date: '',
    brand_name: '',
    brand_short_name: '',
    monitor_keywords_text: '',
    aliases_text: '',
    region_codes: [] as string[],
    monitored_platforms: [] as string[],
    official_url: '',
    description: '',
    schedule_type: 'daily_times' as 'daily_times' | 'fixed_times' | 'weekly' | 'monthly',
    schedule_times: [] as string[],
    schedule_frequency: 3,
    schedule_weekdays: [] as number[],
    schedule_month_days_text: '',
  })

  const filteredTenants = computed(() => {
    const keyword = enterpriseFilters.keyword.trim().toLowerCase()
    return tenants.value.filter(tenant => {
      const keywordMatched = !keyword || `${tenant.name} ${tenant.code}`.toLowerCase().includes(keyword)
      const pending = isTenantPending(tenant) && tenant.stop_reason !== 'canceled'
      const expired = isTenantExpired(tenant)
      const stopped = !tenant.status && (tenant.stop_reason === 'manual' || tenant.stop_reason === 'canceled' || (!pending && !expired))
      const active = tenant.status && !pending && !expired
      const statusMatched = enterpriseFilters.expiry === 'all'
        || (enterpriseFilters.expiry === 'active' && active)
        || (enterpriseFilters.expiry === 'pending' && pending)
        || (enterpriseFilters.expiry === 'expired' && expired)
        || (enterpriseFilters.expiry === 'stopped' && stopped)
      const ownerFilter = enterpriseFilters.owner_user_id
      const ownerMatched = !canFilterBySales.value
        || ownerFilter === 'all'
        || (ownerFilter === 'none' && tenant.owner_user_id == null)
        || (typeof ownerFilter === 'number' && tenant.owner_user_id === ownerFilter)
      return keywordMatched && statusMatched && ownerMatched
    })
  })

  const enterpriseFormServiceState = computed(() => {
    if (!brandForm.tenant_status && brandForm.tenant_stop_reason === 'manual') return 'manual'
    if (!brandForm.tenant_status && brandForm.tenant_stop_reason === 'canceled') return 'canceled'
    return serviceStateFromPeriod(brandForm.service_start_date, brandForm.service_end_date)
  })
  const enterpriseFormServiceActive = computed(() => enterpriseFormServiceState.value === 'active')
  const enterpriseFormServiceLabel = computed(() => {
    if (enterpriseFormServiceState.value === 'manual') return '人工停服'
    if (enterpriseFormServiceState.value === 'canceled') return '已取消'
    if (enterpriseFormServiceState.value === 'pending') return '未开始'
    return enterpriseFormServiceState.value === 'active' ? '服务中' : '已停服'
  })

  function isTenantExpired(tenant: TenantInfo) {
    if (!tenant.service_end_date) return false
    const today = new Date()
    today.setHours(0, 0, 0, 0)
    const endDate = new Date(`${tenant.service_end_date} 23:59:59`)
    return endDate.getTime() < today.getTime()
  }

  function isTenantPending(tenant: TenantInfo) {
    if (!tenant.service_start_date) return false
    const today = new Date()
    today.setHours(0, 0, 0, 0)
    const startDate = new Date(`${tenant.service_start_date} 00:00:00`)
    return startDate.getTime() > today.getTime()
  }

  function tenantServiceLabel(tenant: TenantInfo) {
    if (!tenant.status && tenant.stop_reason === 'manual') return '人工停服'
    if (!tenant.status && tenant.stop_reason === 'canceled') return '已取消'
    if (isTenantPending(tenant)) return '未开始'
    if (isTenantExpired(tenant)) return '已到期'
    if (!tenant.status) return '已停服'
    return '服务中'
  }

  function canStopTenantService(tenant: TenantInfo) {
    if (!menuGrant(enterprisePermissionCodeMap.list)?.can_delete) return false
    if (isTenantExpired(tenant)) return false
    if (isTenantPending(tenant) && tenant.stop_reason !== 'canceled') return true
    return tenant.status
  }

  function canRestoreTenantService(tenant: TenantInfo) {
    if (!menuGrant(enterprisePermissionCodeMap.list)?.can_update) return false
    return !tenant.status && ['manual', 'canceled'].includes(tenant.stop_reason || '') && !isTenantExpired(tenant)
  }

  function stopTenantActionLabel(tenant: TenantInfo) {
    return isTenantPending(tenant) ? '取消服务' : '停止服务'
  }

  function tenantServicePeriod(tenant: TenantInfo) {
    const start = tenant.service_start_date || '未设置'
    const end = tenant.service_end_date || '长期'
    return `${start} 至 ${end}`
  }

  function tenantOwnerLabel(tenant: TenantInfo) {
    return tenant.owner_display_name || tenant.owner_username || '未指定'
  }

  function serviceStateFromPeriod(serviceStartDate: string, serviceEndDate: string) {
    const today = new Date()
    today.setHours(0, 0, 0, 0)
    if (serviceStartDate) {
      const startDate = new Date(`${serviceStartDate} 00:00:00`)
      if (startDate.getTime() > today.getTime()) return 'pending'
    }
    if (serviceEndDate) {
      const endDate = new Date(`${serviceEndDate} 23:59:59`)
      if (endDate.getTime() < today.getTime()) return 'stopped'
    }
    return 'active'
  }

  function makeKeywordGroup(monitorKeyword = '', exposureTerms: string[] = []): BrandKeywordGroup {
    const keywords = monitorKeyword.trim() ? [monitorKeyword.trim()] : []
    const index = keywordGroupRows.value.length
    const inheritedPlatforms = normalizePlatformSelections(
      keywordGroupRows.value.find(item => (item.platforms || []).length)?.platforms
      || (brandForm.monitored_platforms.length ? [...brandForm.monitored_platforms] : []),
    )
    return {
      id: null,
      name: defaultKeywordGroupName(index),
      monitor_keyword: keywords[0] || '',
      monitor_keywords: keywords,
      exposure_terms: exposureTerms.length ? exposureTerms : keywords,
      platforms: inheritedPlatforms,
      sort_order: index,
      status: true,
    }
  }

  function normalizeKeywordGroups(asset: BrandAsset | null, tenantName = '') {
    const groups = asset?.keyword_groups?.length ? asset.keyword_groups : []
    if (groups.length) {
      keywordGroupRows.value = groups.map((group, index) => {
        const monitorKeywords = keywordGroupMonitorKeywords(group)
        return {
          id: group.id || null,
          tenant_id: group.tenant_id,
          name: (group.name || '').trim() || defaultKeywordGroupName(index),
          monitor_keyword: monitorKeywords[0] || '',
          monitor_keywords: [...monitorKeywords],
          exposure_terms: [...(group.exposure_terms || [])],
          platforms: normalizePlatformSelections(
            group.platforms?.length ? group.platforms : (asset?.monitored_platforms || []),
          ),
          sort_order: group.sort_order ?? index,
          status: group.status,
        }
      })
      return
    }
    const aliases = asset?.aliases?.length ? asset.aliases : []
    const keywords = [...new Set([asset?.company_full_name || tenantName, ...(asset?.monitor_keywords || []), ...(asset?.product_keywords || [])].filter(Boolean))]
    keywordGroupRows.value = keywords.map((keyword, index) => ({
      id: null,
      name: defaultKeywordGroupName(index),
      monitor_keyword: keyword,
      monitor_keywords: [keyword],
      exposure_terms: index === 0 && aliases.length ? aliases : [keyword],
      platforms: normalizePlatformSelections(asset?.monitored_platforms || []),
      sort_order: index,
      status: true,
    }))
  }

  async function startEditGroupName(index: number) {
    if (!canEditEnterpriseTab('keywords')) return
    editingGroupIndex.value = index
    await nextTick()
    const input = document.getElementById(`keyword-group-name-${index}`) as HTMLInputElement | null
    input?.focus()
    input?.select()
  }

  function finishEditGroupName(group: BrandKeywordGroup, index: number, value: string) {
    group.name = value.trim() || defaultKeywordGroupName(index)
    editingGroupIndex.value = null
  }

  function cancelEditGroupName() {
    editingGroupIndex.value = null
  }

  function addKeywordGroup() {
    keywordGroupRows.value.push(makeKeywordGroup())
  }

  function removeKeywordGroup(index: number) {
    keywordGroupRows.value.splice(index, 1)
    keywordGroupRows.value.forEach((item, itemIndex) => { item.sort_order = itemIndex })
  }

  function addExposureTerm(group: BrandKeywordGroup, term: string) {
    const text = term.trim()
    if (!text) return
    if (!group.exposure_terms.some(item => item.toLowerCase() === text.toLowerCase())) {
      group.exposure_terms.push(text)
    }
  }

  function addExposureTermsFromText(group: BrandKeywordGroup, text: string) {
    splitKeywordInput(text).forEach(term => addExposureTerm(group, term))
  }

  function commitExposureTermInput(group: BrandKeywordGroup, event: Event) {
    const input = event.target as HTMLInputElement
    addExposureTermsFromText(group, input.value)
    input.value = ''
  }

  function handleExposureTermPaste(group: BrandKeywordGroup, event: ClipboardEvent) {
    const text = event.clipboardData?.getData('text') || ''
    const terms = splitKeywordInput(text)
    if (terms.length <= 1) return
    event.preventDefault()
    addExposureTermsFromText(group, text)
    const input = event.target as HTMLInputElement
    input.value = ''
  }

  function removeExposureTerm(group: BrandKeywordGroup, index: number) {
    group.exposure_terms.splice(index, 1)
  }

  function syncGroupPrimaryKeyword(group: BrandKeywordGroup) {
    const keywords = (group.monitor_keywords || []).map(item => item.trim()).filter(Boolean)
    group.monitor_keywords = keywords
    group.monitor_keyword = keywords[0] || ''
  }

  function splitKeywordInput(text: string) {
    return text.split(/[\n\r、,，;；\t]+/).map(item => item.trim()).filter(Boolean)
  }

  function addMonitorKeyword(group: BrandKeywordGroup, term: string) {
    const text = term.trim()
    if (!text) return
    if (!group.monitor_keywords) group.monitor_keywords = []
    if (!group.monitor_keywords.some(item => item.toLowerCase() === text.toLowerCase())) {
      group.monitor_keywords.push(text)
    }
    syncGroupPrimaryKeyword(group)
  }

  function addMonitorKeywordsFromText(group: BrandKeywordGroup, text: string) {
    splitKeywordInput(text).forEach(term => addMonitorKeyword(group, term))
  }

  function commitMonitorKeywordInput(group: BrandKeywordGroup, event: Event) {
    const input = event.target as HTMLInputElement
    addMonitorKeywordsFromText(group, input.value)
    input.value = ''
  }

  function handleMonitorKeywordPaste(group: BrandKeywordGroup, event: ClipboardEvent) {
    const text = event.clipboardData?.getData('text') || ''
    const terms = splitKeywordInput(text)
    if (terms.length <= 1) return
    event.preventDefault()
    addMonitorKeywordsFromText(group, text)
    const input = event.target as HTMLInputElement
    input.value = ''
  }

  function removeMonitorKeyword(group: BrandKeywordGroup, index: number) {
    if (!group.monitor_keywords) return
    group.monitor_keywords.splice(index, 1)
    syncGroupPrimaryKeyword(group)
  }

  function normalizeTimeValue(value: string) {
    return value && /^\d{2}:\d{2}$/.test(value) ? value : '09:30'
  }

  function addScheduleTime() {
    brandForm.schedule_times.push('09:30')
  }

  function removeScheduleTime(index: number) {
    if (brandForm.schedule_times.length <= 1) {
      ElMessage.warning('至少保留一个执行时间')
      return
    }
    brandForm.schedule_times.splice(index, 1)
  }

  function scheduleTimeList() {
    return [...new Set(brandForm.schedule_times.map(normalizeTimeValue).filter(Boolean))].sort()
  }

  function fillBrandForm(asset: BrandAsset | null, tenantId: number | null = null) {
    const tenant = tenants.value.find(item => item.id === tenantId)
    brandForm.tenant_id = tenantId
    brandForm.company_full_name = asset?.company_full_name || tenant?.name || ''
    brandForm.tenant_code = tenant?.code || ''
    brandForm.tenant_status = tenant?.status ?? true
    brandForm.tenant_stop_reason = tenant?.stop_reason || null
    brandForm.service_start_date = tenant?.service_start_date || ''
    brandForm.service_end_date = tenant?.service_end_date || ''
    brandForm.brand_name = asset?.brand_name || asset?.company_full_name || tenant?.name || ''
    brandForm.brand_short_name = asset?.brand_short_name || ''
    brandForm.monitor_keywords_text = [...new Set([...(asset?.monitor_keywords || []), ...(asset?.product_keywords || [])])].join('\n')
    brandForm.aliases_text = (asset?.aliases || []).join('\n')
    brandForm.region_codes = [...(asset?.region_codes || [])]
    normalizeKeywordGroups(asset, tenant?.name || '')
    brandForm.monitored_platforms = asset ? [...(asset.monitored_platforms || [])] : []
    brandForm.official_url = asset?.official_url || ''
    brandForm.description = asset?.description || ''
    brandForm.schedule_type = 'daily_times'
    brandForm.schedule_times = asset?.schedule_times?.length ? [...asset.schedule_times] : ['09:30', '14:30', '20:30']
    brandForm.schedule_frequency = asset?.schedule_frequency || brandForm.schedule_times.length || 3
    brandForm.schedule_weekdays = []
    brandForm.schedule_month_days_text = ''
  }

  function fillCompetitorRows(rows: BrandCompetitor[]) {
    competitorRows.value = rows.map(item => ({
      id: item.id,
      name: item.name,
      short_name: item.short_name || '',
      aliases_text: (item.aliases || []).join('、'),
      website_url: item.website_url || '',
      category: item.category || '直接竞品',
    }))
  }

  function notifyBrandUpdated() {
    options.onBrandUpdated?.(brandAsset.value, brandCompetitors.value)
  }

  async function loadBrandAssetData() {
    loadingBrand.value = true
    try {
      if (isPlatform.value && !brandForm.tenant_id) {
        const firstTenant = tenants.value[0]
        if (firstTenant) {
          brandForm.tenant_id = firstTenant.id
          brandForm.company_full_name = firstTenant.name
        } else {
          brandAsset.value = null
          brandCompetitors.value = []
          fillBrandForm(null, null)
          notifyBrandUpdated()
          return
        }
      }
      const response = await withRetry(() => getBrandAsset(isPlatform.value ? brandForm.tenant_id : null))
      brandAsset.value = response.asset
      brandCompetitors.value = response.competitors
      fillBrandForm(response.asset, response.tenant_id)
      if (!response.asset && isPlatform.value) {
        brandForm.company_full_name = tenants.value.find(item => item.id === response.tenant_id)?.name || ''
      }
      fillCompetitorRows(response.competitors)
      notifyBrandUpdated()
    } catch (error: unknown) {
      notifyError(error, '品牌资产加载失败')
    } finally {
      loadingBrand.value = false
    }
  }

  async function loadEnterpriseList() {
    if (!isPlatform.value) return
    loadingBrand.value = true
    try {
      tenants.value = await withRetry(() => getTenants())
      if (canFilterBySales.value && !tenantSalesOwners.value.length) {
        try {
          tenantSalesOwners.value = await listTenantSalesOwners()
        } catch {
          // 销售筛选项加载失败不阻断企业列表
        }
      }
    } catch (error: unknown) {
      notifyError(error, '企业列表加载失败')
    } finally {
      loadingBrand.value = false
    }
  }

  async function loadKnowledgeFiles() {
    if (!enterpriseDetailMode.value || !brandForm.tenant_id) return
    loadingKnowledgeFiles.value = true
    try {
      knowledgeFiles.value = await withRetry(() => getKnowledgeFiles(brandForm.tenant_id))
    } catch (error: unknown) {
      notifyError(error, '知识库文件加载失败')
    } finally {
      loadingKnowledgeFiles.value = false
    }
  }

  async function previewKnowledgeFile(file: KnowledgeFileRecord) {
    knowledgePreviewFile.value = file
    knowledgePreviewVisible.value = true
    knowledgePreviewLoading.value = true
    knowledgePreviewError.value = ''
    knowledgePreviewText.value = ''
    try {
      const data = await withRetry(() => getKnowledgeFileContent(file.id))
      knowledgePreviewText.value = data.text || ''
    } catch (error: unknown) {
      knowledgePreviewError.value = errorMessage(error)
    } finally {
      knowledgePreviewLoading.value = false
    }
  }

  function closeKnowledgePreview() {
    knowledgePreviewVisible.value = false
    knowledgePreviewFile.value = null
    knowledgePreviewText.value = ''
    knowledgePreviewError.value = ''
  }

  async function downloadKnowledgeFileItem(file: KnowledgeFileRecord) {
    try {
      const filename = await downloadKnowledgeFile(file.id, file.original_name)
      ElMessage.success(`已开始下载：${filename}`)
    } catch (error: unknown) {
      notifyError(error, '文件下载失败')
    }
  }

  async function removeKnowledgeFile(file: KnowledgeFileRecord) {
    if (!canDeleteKnowledgeFiles.value) return
    try {
      await ElMessageBox.confirm(`确定删除「${file.original_name}」？删除后不可恢复。`, '删除客户上传文件', {
        type: 'warning',
        confirmButtonText: '删除',
        cancelButtonText: '取消',
      })
    } catch {
      return
    }
    loadingKnowledgeFiles.value = true
    try {
      await deleteKnowledgeFile(file.id)
      if (knowledgePreviewFile.value?.id === file.id) closeKnowledgePreview()
      await loadKnowledgeFiles()
      ElMessage.success('文件已删除')
    } catch (error: unknown) {
      notifyError(error, '文件删除失败')
    } finally {
      loadingKnowledgeFiles.value = false
    }
  }

  async function openEnterpriseDetail(tenant: TenantInfo) {
    const firstVisibleTab = visibleEnterpriseTabs.value[0]?.code
    if (!firstVisibleTab) {
      ElMessage.warning('当前职位只有企业列表权限，没有企业详情配置权限')
      return
    }
    enterpriseDetailMode.value = true
    enterpriseDetailTab.value = firstVisibleTab
    brandForm.tenant_id = tenant.id
    brandForm.company_full_name = tenant.name
    await loadBrandAssetData()
    await loadKnowledgeFiles()
  }

  async function openEnterpriseInfo(tenant: TenantInfo) {
    enterpriseInfoDialog.value = true
    enterpriseInfoLoading.value = true
    enterpriseInfoTenant.value = tenant
    enterpriseInfoAsset.value = null
    enterpriseInfoCompetitors.value = []
    try {
      const response = await withRetry(() => getBrandAsset(tenant.id))
      enterpriseInfoAsset.value = response.asset
      enterpriseInfoCompetitors.value = response.competitors
    } catch (error: unknown) {
      notifyError(error, '企业详情加载失败')
    } finally {
      enterpriseInfoLoading.value = false
    }
  }

  function backToEnterpriseList() {
    enterpriseDetailMode.value = false
    brandAsset.value = null
    brandCompetitors.value = []
    competitorRows.value = []
    knowledgeFiles.value = []
    fillBrandForm(null, null)
  }

  async function submitBrandAsset(successText = '品牌资产已保存') {
    if (!brandForm.company_full_name.trim()) {
      ElMessage.warning('请先填写企业全称')
      return
    }
    const keywordGroups = keywordGroupRows.value
      .map((group, index) => {
        const monitorKeywords = (group.monitor_keywords || []).map(item => item.trim()).filter(Boolean)
        const platforms = normalizePlatformSelections(group.platforms)
        return {
          id: group.id || null,
          name: (group.name || '').trim() || defaultKeywordGroupName(index),
          monitor_keyword: monitorKeywords[0] || '',
          monitor_keywords: monitorKeywords,
          exposure_terms: group.exposure_terms.map(item => item.trim()).filter(Boolean),
          platforms,
          sort_order: index,
          status: group.status,
        }
      })
      .filter(group => group.monitor_keywords.length)
    if (!keywordGroups.length) {
      ElMessage.warning('请至少配置一个监测词组')
      return
    }
    const missingPlatforms = keywordGroups.find(group => group.status && !group.platforms.length)
    if (missingPlatforms) {
      ElMessage.warning('每个启用的监测词组至少选择一个监测平台')
      return
    }
    loadingBrand.value = true
    try {
      if (brandForm.tenant_id) {
        const tenant = await updateTenant(brandForm.tenant_id, {
          name: brandForm.company_full_name.trim(),
          code: null,
          service_start_date: brandForm.service_start_date || null,
          service_end_date: brandForm.service_end_date || null,
          status: enterpriseFormServiceActive.value,
        })
        const tenantIndex = tenants.value.findIndex(item => item.id === tenant.id)
        if (tenantIndex >= 0) tenants.value.splice(tenantIndex, 1, tenant)
      }
      const saved = await saveBrandAsset({
        tenant_id: brandForm.tenant_id,
        company_full_name: brandForm.company_full_name.trim(),
        brand_name: brandForm.company_full_name.trim(),
        brand_short_name: null,
        monitor_keywords: keywordGroups.flatMap(group => group.monitor_keywords),
        aliases: [...new Set(keywordGroups.flatMap(group => group.exposure_terms))],
        product_keywords: [],
        monitored_platforms: [...new Set(keywordGroups.flatMap(group => platformSelectionCodes(group.platforms)))],
        keyword_groups: keywordGroups,
        region_codes: [...brandForm.region_codes],
        official_url: brandForm.official_url.trim() || null,
        description: brandForm.description.trim() || null,
        schedule_type: 'daily_times',
        schedule_times: scheduleTimeList(),
        schedule_frequency: Math.max(1, scheduleTimeList().length || brandForm.schedule_frequency),
        schedule_weekdays: [],
        schedule_month_days: [],
      })
      if (isPendingApproval(saved)) {
        const msg = pendingApprovalMessage(saved, '已提交审批，等待运营或管理员审核')
        if (isDuplicateMergedApproval(saved)) ElMessage.warning(msg)
        else ElMessage.info(msg)
        return
      }
      await loadBrandAssetData()
      ElMessage.success(successText)
    } catch (error: unknown) {
      notifyError(error, '品牌资产保存失败')
    } finally {
      loadingBrand.value = false
    }
  }

  async function submitTenant() {
    if (!tenantForm.name.trim()) {
      ElMessage.warning('请填写企业名称')
      return
    }
    loadingBrand.value = true
    try {
      const tenant = await createTenant({
        name: tenantForm.name.trim(),
        code: null,
        service_start_date: tenantForm.service_start_date || null,
        service_end_date: tenantForm.service_end_date || null,
      })
      tenantForm.name = ''
      tenantForm.service_start_date = ''
      tenantForm.service_end_date = ''
      tenantDialog.value = false
      await loadEnterpriseList()
      await openEnterpriseDetail(tenant)
      ElMessage.success('企业已新增，请继续维护监控配置')
    } catch (error: unknown) {
      notifyError(error, '企业新增失败')
    } finally {
      loadingBrand.value = false
    }
  }

  async function removeTenant(tenant: TenantInfo) {
    const actionLabel = stopTenantActionLabel(tenant)
    try {
      await ElMessageBox.confirm(`确认${actionLabel}「${tenant.name}」吗？操作后客户账号将停用，定时监测不再提交，历史数据仍保留。`, actionLabel, { type: 'warning' })
    } catch {
      return
    }
    loadingBrand.value = true
    try {
      await deleteTenant(tenant.id)
      await loadEnterpriseList()
      ElMessage.success(`企业已${actionLabel}`)
    } catch (error: unknown) {
      notifyError(error, `${actionLabel}失败`)
    } finally {
      loadingBrand.value = false
    }
  }

  async function restoreTenantService(tenant: TenantInfo) {
    try {
      await ElMessageBox.confirm(`确认恢复「${tenant.name}」的服务吗？恢复后客户账号将重新启用；如果服务开始日期还没到，企业仍会保持未开始状态。`, '恢复服务', { type: 'warning' })
    } catch {
      return
    }
    loadingBrand.value = true
    try {
      await restoreTenant(tenant.id)
      await loadEnterpriseList()
      ElMessage.success('企业服务已恢复')
    } catch (error: unknown) {
      notifyError(error, '恢复服务失败')
    } finally {
      loadingBrand.value = false
    }
  }

  async function openTenantTransferDialog(tenant: TenantInfo) {
    tenantTransferTarget.value = tenant
    tenantTransferOwnerId.value = tenant.owner_user_id
    tenantTransferDialog.value = true
    if (tenantSalesOwners.value.length) return
    loadingTenantSalesOwners.value = true
    try {
      tenantSalesOwners.value = await listTenantSalesOwners()
    } catch (error: unknown) {
      notifyError(error, '销售列表加载失败')
    } finally {
      loadingTenantSalesOwners.value = false
    }
  }

  async function submitTenantTransfer() {
    if (!tenantTransferTarget.value) return
    if (!tenantTransferOwnerId.value) {
      ElMessage.warning('请选择归属销售')
      return
    }
    if (tenantTransferTarget.value.owner_user_id === tenantTransferOwnerId.value) {
      ElMessage.info('归属销售未变更')
      tenantTransferDialog.value = false
      return
    }
    const targetName = tenantTransferTarget.value.name
    const ownerName = tenantSalesOwners.value.find(item => item.id === tenantTransferOwnerId.value)?.display_name || '所选销售'
    try {
      await ElMessageBox.confirm(`确认将「${targetName}」的归属销售转移给「${ownerName}」吗？转移后原销售将无法再访问该企业。`, '转移归属销售', { type: 'warning' })
    } catch {
      return
    }
    transferringTenantOwner.value = true
    try {
      const updated = await transferTenantOwner(tenantTransferTarget.value.id, tenantTransferOwnerId.value)
      const index = tenants.value.findIndex(item => item.id === updated.id)
      if (index >= 0) tenants.value.splice(index, 1, updated)
      if (enterpriseInfoTenant.value?.id === updated.id) enterpriseInfoTenant.value = updated
      tenantTransferDialog.value = false
      ElMessage.success('企业归属销售已更新')
    } catch (error: unknown) {
      notifyError(error, '转移归属销售失败')
    } finally {
      transferringTenantOwner.value = false
    }
  }

  function addCompetitorRow() {
    const name = competitorNameInput.value.trim()
    competitorRows.value.push({
      id: null,
      name,
      short_name: '',
      aliases_text: '',
      website_url: '',
      category: '直接竞品',
    })
    competitorNameInput.value = ''
  }

  async function addCompetitorTag() {
    const name = competitorNameInput.value.trim()
    if (!name) {
      ElMessage.warning('请填写竞品名称')
      return
    }
    const row = {
      id: null,
      name,
      short_name: '',
      aliases_text: '',
      website_url: '',
      category: '直接竞品',
      saving: false,
    }
    competitorRows.value.push(row)
    competitorNameInput.value = ''
    await saveCompetitorRow(row)
  }

  async function saveCompetitorRow(row: typeof competitorRows.value[number]) {
    if (!row.name.trim()) {
      ElMessage.warning('请填写竞品名称')
      return
    }
    row.saving = true
    try {
      const payload = {
        tenant_id: brandForm.tenant_id,
        name: row.name.trim(),
        short_name: null,
        aliases: [],
        website_url: null,
        category: row.category.trim() || '直接竞品',
      }
      if (row.id) {
        await updateCompetitor(row.id, payload)
      } else {
        await createCompetitor(payload)
      }
      await loadBrandAssetData()
      ElMessage.success('竞品已保存')
    } catch (error: unknown) {
      notifyError(error, '竞品保存失败')
    } finally {
      row.saving = false
    }
  }

  async function removeCompetitorRow(row: typeof competitorRows.value[number], index: number) {
    if (!row.id) {
      competitorRows.value.splice(index, 1)
      if (!competitorRows.value.length) addCompetitorRow()
      return
    }
    try {
      await ElMessageBox.confirm('确认移除这个竞品吗？后续提交检测任务将不再带上它。', '移除竞品', { type: 'warning' })
    } catch {
      return
    }
    loadingBrand.value = true
    try {
      await deleteCompetitor(row.id, brandForm.tenant_id)
      await loadBrandAssetData()
      ElMessage.success('竞品已移除')
    } catch (error: unknown) {
      notifyError(error, '竞品移除失败')
    } finally {
      loadingBrand.value = false
    }
  }

  function formatFileSize(size: number) {
    if (size >= 1024 * 1024) return `${(size / 1024 / 1024).toFixed(1)}MB`
    if (size >= 1024) return `${(size / 1024).toFixed(1)}KB`
    return `${size}B`
  }

  function demoAction(action: string) {
    ElMessage.success(`${action}：演示动作已触发，正式项目可在这里接入导出、上传或详情接口`)
  }

  function resetDetailMode() {
    enterpriseDetailMode.value = false
  }

  const reportDialog = ref(false)
  const reportDialogTenant = ref<TenantInfo | null>(null)
  const reportGenerating = ref(false)
  const reportType = ref<ReportType>('diagnosis')
  const reportTitle = ref('')

  function openReportDialog(tenant: TenantInfo) {
    reportDialogTenant.value = tenant
    reportType.value = 'diagnosis'
    reportTitle.value = ''
    reportDialog.value = true
  }

  const canGenerateEnterpriseReport = computed(() => Boolean(menuGrant('platform.reports')?.can_create))

  async function submitEnterpriseReport() {
    if (!canGenerateEnterpriseReport.value) {
      ElMessage.warning('当前账号无权生成报告')
      return
    }
    if (!reportDialogTenant.value) return
    reportGenerating.value = true
    try {
      const created = await withRetry(() => createReport({
        tenant_id: reportDialogTenant.value!.id,
        report_type: reportType.value,
        report_title: reportTitle.value.trim() || undefined,
      }))
      ElMessage.success('企业内部诊断已生成，可在报告中心预览与导出（不同步至客户端）')
      reportDialog.value = false
      options.navigateToReportCenter?.(created.id, created.tenant_id)
    } catch (error: unknown) {
      notifyError(error, '报告生成失败')
    } finally {
      reportGenerating.value = false
    }
  }

  async function loadCatalogPlatforms() {
    try {
      const data = await getPlatformsForBrandConfig()
      catalogPlatforms.value = data.platforms || []
    } catch {
      catalogPlatforms.value = supportedPlatforms.map(item => ({
        code: item.code,
        name: item.name,
        channel: 'web',
        catalog_listed: true,
        service_available: true,
        selectable: true,
        labels: [],
        modes: ['standard', 'search', 'reasoning', 'reasoning_search'],
        default_mode: 'standard',
        default_screenshot: 1,
      }))
    }
  }

  function groupHasPlatform(group: BrandKeywordGroup, code: string) {
    return platformSelectionCodes(group.platforms).includes(code)
  }

  function onPlatformCheckClick(groupIndex: number, code: string) {
    const group = keywordGroupRows.value[groupIndex]
    if (!group) return
    if (!canEditEnterpriseTab('keywords')) return
    const meta = catalogPlatforms.value.find(item => item.code === code)
    if (groupHasPlatform(group, code)) {
      const next = normalizePlatformSelections(group.platforms).filter(item => item.code !== code)
      keywordGroupRows.value[groupIndex] = { ...group, platforms: next }
      return
    }
    if (meta && !meta.selectable) {
      ElMessage.warning(meta.labels.includes('已下架') ? '该平台已下架，不可勾选' : '该平台暂无服务，不可勾选')
      return
    }
    // 先弹窗；确认后再写入 platforms（不要让原生 checkbox 自行切换状态）
    modeDialogTarget.value = { groupIndex, code }
    modeDialogForm.mode = (meta?.default_mode as PlatformSelection['mode']) || 'standard'
    modeDialogForm.screenshot = 1
    modeDialogVisible.value = true
  }

  function confirmModeDialog() {
    const target = modeDialogTarget.value
    if (!target) {
      modeDialogVisible.value = false
      return
    }
    const group = keywordGroupRows.value[target.groupIndex]
    if (!group) {
      modeDialogVisible.value = false
      modeDialogTarget.value = null
      return
    }
    const next = normalizePlatformSelections(group.platforms).filter(item => item.code !== target.code)
    next.push({
      code: target.code,
      mode: modeDialogForm.mode,
      screenshot: 1,
    })
    keywordGroupRows.value[target.groupIndex] = { ...group, platforms: next }
    modeDialogVisible.value = false
    modeDialogTarget.value = null
  }

  function cancelModeDialog() {
    modeDialogVisible.value = false
    modeDialogTarget.value = null
  }

  return {
    platformLabelMap,
    supportedPlatforms,
    catalogPlatforms,
    formatPlatformLabels,
    loadCatalogPlatforms,
    groupHasPlatform,
    onPlatformCheckClick,
    modeDialogVisible,
    modeDialogForm,
    confirmModeDialog,
    cancelModeDialog,
    regionOptions,
    selectableRegionOptions,
    regionLabels,
    tenants,
    enterpriseDetailMode,
    enterpriseDetailTab,
    enterpriseInfoDialog,
    enterpriseInfoLoading,
    enterpriseInfoTenant,
    enterpriseInfoAsset,
    enterpriseInfoCompetitors,
    enterpriseFilters,
    tenantDialog,
    tenantForm,
    tenantTransferDialog,
    tenantTransferTarget,
    tenantTransferOwnerId,
    tenantSalesOwners,
    loadingTenantSalesOwners,
    transferringTenantOwner,
    canTransferTenantOwner,
    canFilterBySales,
    tenantSalesFilterOptions,
    knowledgeFiles,
    loadingKnowledgeFiles,
    knowledgePreviewVisible,
    knowledgePreviewFile,
    knowledgePreviewText,
    knowledgePreviewLoading,
    knowledgePreviewError,
    canDeleteKnowledgeFiles,
    previewKnowledgeFile,
    closeKnowledgePreview,
    downloadKnowledgeFileItem,
    removeKnowledgeFile,
    brandAsset,
    brandCompetitors,
    competitorRows,
    keywordGroupRows,
    competitorNameInput,
    loadingBrand,
    brandForm,
    filteredTenants,
    enterpriseFormServiceActive,
    enterpriseFormServiceLabel,
    visibleEnterpriseTabs,
    canViewEnterpriseTab,
    canEditEnterpriseTab,
    canCreateTenant,
    canEditTenantList,
    isTenantExpired,
    isTenantPending,
    tenantServiceLabel,
    canStopTenantService,
    canRestoreTenantService,
    stopTenantActionLabel,
    tenantServicePeriod,
    tenantOwnerLabel,
    editingGroupIndex,
    keywordGroupDisplayName,
    startEditGroupName,
    finishEditGroupName,
    cancelEditGroupName,
    addKeywordGroup,
    removeKeywordGroup,
    addExposureTerm,
    removeExposureTerm,
    addMonitorKeyword,
    addMonitorKeywordsFromText,
    commitMonitorKeywordInput,
    handleMonitorKeywordPaste,
    removeMonitorKeyword,
    commitExposureTermInput,
    handleExposureTermPaste,
    addScheduleTime,
    removeScheduleTime,
    loadBrandAssetData,
    loadEnterpriseList,
    loadKnowledgeFiles,
    openEnterpriseDetail,
    openEnterpriseInfo,
    backToEnterpriseList,
    submitBrandAsset,
    submitTenant,
    removeTenant,
    restoreTenantService,
    openTenantTransferDialog,
    submitTenantTransfer,
    addCompetitorTag,
    removeCompetitorRow,
    formatFileSize,
    demoAction,
    resetDetailMode,
    reportDialog,
    reportDialogTenant,
    reportGenerating,
    reportType,
    reportTitle,
    reportTypeOptions: REPORT_TYPE_OPTIONS,
    canGenerateEnterpriseReport,
    openReportDialog,
    submitEnterpriseReport,
  }
}
