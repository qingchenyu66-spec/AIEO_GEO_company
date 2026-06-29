import { computed, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useAuthStore } from '../../../stores/auth'
import { withRetry } from '../../../composables/useRetry'
import { notifyOperationError } from '../../../utils/requestError'
import {
  createTenant, deleteTenant, getTenants, restoreTenant, updateTenant,
  type TenantInfo,
} from '../../../services/management'
import {
  createCompetitor, deleteCompetitor, getBrandAsset, saveBrandAsset, updateCompetitor,
  type BrandAsset, type BrandCompetitor, type BrandKeywordGroup,
} from '../../../services/brand'
import { getKnowledgeFiles, type KnowledgeFileRecord } from '../../../services/knowledge'
import { platformLabelMap, supportedPlatforms } from '../portalMaps'
import { regionOptions } from '../regionOptions'

export type EnterpriseTab = 'profile' | 'keywords' | 'platforms' | 'schedule' | 'competitors' | 'files'

export const enterprisePermissionCodeMap = {
  list: 'platform.audit.list',
  profile: 'platform.audit.profile',
  keywords: 'platform.audit.keywords',
  platforms: 'platform.audit.models',
  schedule: 'platform.audit.schedule',
  competitors: 'platform.audit.competitors',
  files: 'platform.audit.files',
} as const

export type UseBrandAuditOptions = {
  onBrandUpdated?: (asset: BrandAsset | null, competitors: BrandCompetitor[]) => void
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

function textToList(value: string) {
  return value.split(/[\n,，;；]/).map(item => item.trim()).filter(Boolean)
}

export function useBrandAudit(options: UseBrandAuditOptions = {}) {
  const auth = useAuthStore()
  const isPlatform = computed(() => auth.session?.identity?.identity_type === 'PLATFORM')

  function menuGrant(code: string) {
    return auth.allowedMenus.find(menu => menu.menu_code === code)
  }

  function canViewEnterpriseTab(tab: EnterpriseTab) {
    const grant = menuGrant(enterprisePermissionCodeMap[tab])
    return Boolean(grant)
  }

  function canEditEnterpriseTab(tab: EnterpriseTab) {
    const grant = menuGrant(enterprisePermissionCodeMap[tab])
    return Boolean(grant?.can_update)
  }

  const visibleEnterpriseTabs = computed(() => ([
    { code: 'profile', name: '企业资料' },
    { code: 'keywords', name: '监测词配置' },
    { code: 'platforms', name: '平台范围' },
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
  })
  const tenantDialog = ref(false)
  const tenantForm = reactive({ name: '', code: '', service_start_date: '', service_end_date: '' })
  const knowledgeFiles = ref<KnowledgeFileRecord[]>([])
  const loadingKnowledgeFiles = ref(false)
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
    region_code: '',
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
      return keywordMatched && statusMatched
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
    if (isTenantExpired(tenant)) return false
    if (isTenantPending(tenant) && tenant.stop_reason !== 'canceled') return true
    return tenant.status
  }

  function canRestoreTenantService(tenant: TenantInfo) {
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

  function numberList(value: string, min: number, max: number) {
    return textToList(value)
      .map(item => Number(item))
      .filter(item => Number.isInteger(item) && item >= min && item <= max)
  }

  function makeKeywordGroup(monitorKeyword = '', exposureTerms: string[] = []): BrandKeywordGroup {
    return {
      id: null,
      monitor_keyword: monitorKeyword,
      exposure_terms: exposureTerms.length ? exposureTerms : (monitorKeyword ? [monitorKeyword] : []),
      sort_order: keywordGroupRows.value.length,
      status: true,
    }
  }

  function normalizeKeywordGroups(asset: BrandAsset | null, tenantName = '') {
    const groups = asset?.keyword_groups?.length ? asset.keyword_groups : []
    if (groups.length) {
      keywordGroupRows.value = groups.map((group, index) => ({
        id: group.id || null,
        tenant_id: group.tenant_id,
        monitor_keyword: group.monitor_keyword,
        exposure_terms: [...(group.exposure_terms || [])],
        sort_order: group.sort_order ?? index,
        status: group.status,
      }))
      return
    }
    const aliases = asset?.aliases?.length ? asset.aliases : []
    const keywords = [...new Set([asset?.company_full_name || tenantName, ...(asset?.monitor_keywords || []), ...(asset?.product_keywords || [])].filter(Boolean))]
    keywordGroupRows.value = keywords.map((keyword, index) => ({
      id: null,
      monitor_keyword: keyword,
      exposure_terms: index === 0 && aliases.length ? aliases : [keyword],
      sort_order: index,
      status: true,
    }))
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

  function removeExposureTerm(group: BrandKeywordGroup, index: number) {
    group.exposure_terms.splice(index, 1)
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
    brandForm.region_code = asset?.region_code || ''
    normalizeKeywordGroups(asset, tenant?.name || '')
    brandForm.monitored_platforms = asset ? [...(asset.monitored_platforms || [])] : []
    brandForm.official_url = asset?.official_url || ''
    brandForm.description = asset?.description || ''
    brandForm.schedule_type = asset?.schedule_type === 'fixed_times' ? 'daily_times' : (asset?.schedule_type || 'daily_times')
    brandForm.schedule_times = asset ? [...(asset.schedule_times || [])] : []
    brandForm.schedule_frequency = asset?.schedule_frequency || 3
    brandForm.schedule_weekdays = asset?.schedule_weekdays || []
    brandForm.schedule_month_days_text = (asset?.schedule_month_days || []).join('\n')
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
      .map((group, index) => ({
        id: group.id || null,
        monitor_keyword: group.monitor_keyword.trim(),
        exposure_terms: group.exposure_terms.map(item => item.trim()).filter(Boolean),
        sort_order: index,
        status: group.status,
      }))
      .filter(group => group.monitor_keyword)
    if (!keywordGroups.length) {
      ElMessage.warning('请至少配置一个监测词组')
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
      const response = await saveBrandAsset({
        tenant_id: brandForm.tenant_id,
        company_full_name: brandForm.company_full_name.trim(),
        brand_name: brandForm.company_full_name.trim(),
        brand_short_name: null,
        monitor_keywords: keywordGroups.map(group => group.monitor_keyword),
        aliases: [...new Set(keywordGroups.flatMap(group => group.exposure_terms))],
        product_keywords: [],
        monitored_platforms: brandForm.monitored_platforms,
        keyword_groups: keywordGroups,
        region_code: brandForm.region_code || null,
        official_url: brandForm.official_url.trim() || null,
        description: brandForm.description.trim() || null,
        schedule_type: brandForm.schedule_type,
        schedule_times: scheduleTimeList(),
        schedule_frequency: Math.max(1, scheduleTimeList().length || brandForm.schedule_frequency),
        schedule_weekdays: brandForm.schedule_weekdays,
        schedule_month_days: numberList(brandForm.schedule_month_days_text, 1, 31),
      })
      brandAsset.value = response.asset
      brandCompetitors.value = response.competitors
      fillBrandForm(response.asset, response.tenant_id)
      fillCompetitorRows(response.competitors)
      ElMessage.success(successText)
      notifyBrandUpdated()
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

  return {
    platformLabelMap,
    supportedPlatforms,
    regionOptions,
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
    knowledgeFiles,
    loadingKnowledgeFiles,
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
    isTenantExpired,
    isTenantPending,
    tenantServiceLabel,
    canStopTenantService,
    canRestoreTenantService,
    stopTenantActionLabel,
    tenantServicePeriod,
    addKeywordGroup,
    removeKeywordGroup,
    addExposureTerm,
    removeExposureTerm,
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
    addCompetitorTag,
    removeCompetitorRow,
    formatFileSize,
    demoAction,
    resetDetailMode,
  }
}
