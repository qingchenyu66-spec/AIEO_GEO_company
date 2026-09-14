import type { MenuInfo } from '../../../services/auth'
import { computed, inject, nextTick, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useAuthStore } from '../../../stores/auth'
import { withRetry } from '../../../composables/useRetry'
import { notifyOperationError } from '../../../utils/requestError'
import {
  deleteTenant, getTenants, listTenantSalesOwners, purgeTenant, restoreTenant, transferTenantOwner, updateTenant, checkTenantNameAvailable, tenantLogoUrl, uploadTenantLogo,
  type TenantInfo,
  type TenantSalesOwner,
} from '../../../services/management'
import {
  createCompetitor, deleteCompetitor, defaultBrandWordGroupName, defaultKeywordGroupName, getBrandAsset, keywordGroupDisplayName, keywordGroupMonitorKeywords, saveBrandAsset, saveBrandWordGroups, updateCompetitor, uploadLogoStaging,
  normalizePlatformSelection, normalizePlatformSelections, platformSelectionCodes,
  type BrandAsset, type BrandCompetitor, type BrandKeywordGroup, type BrandWordGroup, type PlatformSelection,
} from '../../../services/brand'
import { getKnowledgeFiles, deleteKnowledgeFile, downloadKnowledgeFile, getKnowledgeFilePreviewObjectUrl, uploadKnowledgeFile, type KnowledgeFileRecord } from '../../../services/knowledge'
import { getApproval, isDuplicateMergedApproval, isPendingApproval, isResubmittedApproval, pendingApprovalMessage, resubmitApproval } from '../../../services/approvals'
import { createReport, REPORT_TYPE_OPTIONS, type ReportType } from '../../../services/reports'
import { getPlatformsForBrandConfig } from '../../../services/platforms'
import { getTenantCredit } from '../../../services/credit'
import { platformLabelMap, supportedPlatforms, formatPlatformLabels } from '../portalMaps'
import { regionOptions, selectableRegionOptions, regionLabels } from '../regionOptions'
import {
  readEnterprisePin,
  sortTenantsWithPin,
  writeEnterprisePin,
} from './useEnterprisePin'
import { PlatformBrandLogoTenantKey, PlatformTenantsRefreshKey, PreviewCustomerMenusKey } from '../injectionKeys'
import { TENANT_LOGO_ACCEPT, TENANT_LOGO_MAX_BYTES } from '../../../constants/tenantLogo'
import {
  deleteEnterpriseCompetitor,
  getEnterpriseMonitor,
  estimateEnterpriseBrandWords,
  saveEnterpriseBrandWords,
  saveEnterpriseCompetitor,
  saveEnterpriseMonitor,
} from '../../../services/credit'
import { resolveEnterprisePreviewTenantId } from '../customerPreview'

const KNOWLEDGE_UPLOAD_MAX_BYTES = 30 * 1024 * 1024
const KNOWLEDGE_UPLOAD_EXTENSIONS = new Set([
  'pdf', 'doc', 'docx', 'md', 'txt',
  'png', 'jpg', 'jpeg', 'webp',
  'html', 'htm',
  'ppt', 'pptx',
])

function validateKnowledgeUploadFile(file: File) {
  const ext = file.name.includes('.') ? file.name.slice(file.name.lastIndexOf('.') + 1).toLowerCase() : ''
  if (!KNOWLEDGE_UPLOAD_EXTENSIONS.has(ext)) {
    throw new Error('仅支持 PDF、Word、PPT、图片、HTML、Markdown 和 TXT 文件')
  }
  if (file.size === 0) throw new Error('不能上传空文件')
  if (file.size > KNOWLEDGE_UPLOAD_MAX_BYTES) throw new Error('单个文件不能超过 30MB')
}

export type EnterpriseTab = 'profile' | 'keywords' | 'brand_words' | 'schedule' | 'competitors' | 'files' | 'credit'

export const enterprisePermissionCodeMap = {
  list: 'platform.audit.list',
  profile: 'platform.audit.profile',
  regions: 'platform.audit.regions',
  keywords: 'platform.audit.keywords',
  brand_words: 'platform.audit.keywords',
  models: 'platform.audit.models',
  purge: 'platform.audit.purge',
  schedule: 'platform.audit.schedule',
  competitors: 'platform.audit.competitors',
  files: 'platform.audit.files',
  // 主码算力运营；页内仍兼容旧 tenant_credit（见 creditMenuGrant）
  credit: 'platform.credit_ops_board',
} as const

function creditMenuGrantFrom(menus: { menu_code: string; can_export?: boolean; can_update?: boolean; can_create?: boolean; can_delete?: boolean }[]) {
  const board = menus.find(menu => menu.menu_code === 'platform.credit_ops_board')
  const legacy = menus.find(menu => menu.menu_code === 'platform.tenant_credit')
  if (!board && !legacy) return undefined
  return {
    menu_code: 'platform.credit_ops_board',
    can_export: Boolean(board?.can_export || legacy?.can_export),
    can_update: Boolean(board?.can_update || legacy?.can_update),
    can_create: Boolean(board?.can_create || legacy?.can_create),
    can_delete: Boolean(board?.can_delete || legacy?.can_delete),
  }
}

export type UseBrandAuditOptions = {
  onBrandUpdated?: (asset: BrandAsset | null, competitors: BrandCompetitor[]) => void
  navigateToReportCenter?: (reportId: number, tenantId: number) => void
  /** 客户门户企业配置：复用同一套监测 UI，走 enterprise API */
  customerEnterpriseMode?: boolean
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
  const route = useRoute()
  const isPlatform = computed(() => auth.session?.identity?.identity_type === 'PLATFORM')
  const customerEnterpriseMode = Boolean(options.customerEnterpriseMode)
  const previewTenantId = computed(() => (isPlatform.value ? resolveEnterprisePreviewTenantId(route) : null))
  const previewReadonly = computed(() => customerEnterpriseMode && previewTenantId.value != null)
  const customerPlatformWhitelist = ref<string[]>([])
  // 2026-09-07 - 算力自助地区/平台不设配额；policy 仅作展示预留
  const customerCreditPolicy = ref<Record<string, unknown>>({})
  const customerDailyEstimate = ref<Record<string, unknown>>({})

  const previewCustomerMenus = inject(PreviewCustomerMenusKey, ref<MenuInfo[]>([]))

  function menuGrant(code: string) {
    if (previewReadonly.value) {
      return previewCustomerMenus.value.find(menu => menu.menu_code === code)
    }
    if (code === 'platform.credit_ops_board' || code === 'platform.tenant_credit') {
      return creditMenuGrantFrom(auth.allowedMenus)
    }
    return auth.allowedMenus.find(menu => menu.menu_code === code)
  }

  function customerMonitorGrant() {
    return menuGrant('customer.enterprise_monitor')
  }

  function canViewEnterpriseTab(tab: EnterpriseTab) {
    if (customerEnterpriseMode) {
      if (tab === 'files' || tab === 'credit') return false
      if (previewReadonly.value) return true
      const grant = customerMonitorGrant()
      return Boolean(grant && (grant.can_export || grant.can_update))
    }
    // 2026-09-07 - 托管企业不显示「算力与账单」，避免和自助计费口径打架
    if (tab === 'credit' && brandForm.billing_mode !== 'credit') {
      return false
    }
    const grant = menuGrant(enterprisePermissionCodeMap[tab])
    return Boolean(grant && (grant.can_export || grant.can_update || grant.can_create || grant.can_delete))
  }

  function canEditEnterpriseTab(tab: EnterpriseTab) {
    if (previewReadonly.value) return false
    if (customerEnterpriseMode) {
      return Boolean(customerMonitorGrant()?.can_update)
    }
    const grant = menuGrant(enterprisePermissionCodeMap[tab])
    return Boolean(grant?.can_update)
  }

  function canCreateEnterpriseTab(tab: EnterpriseTab) {
    if (previewReadonly.value) return false
    const grant = menuGrant(enterprisePermissionCodeMap[tab])
    return Boolean(grant?.can_create)
  }

  // 2026-07-30 - 地区仍看菜单编辑权；平台以职位白名单为准（非空即可勾对应端）
  const canEditRegions = computed(() => {
    if (previewReadonly.value) return false
    if (customerEnterpriseMode) {
      // 2026-09-07 - 算力自助地区完全由客户支配
      return Boolean(customerMonitorGrant()?.can_update)
    }
    return Boolean(menuGrant(enterprisePermissionCodeMap.regions)?.can_update)
  })
  const allowedMonitorPlatforms = computed(() => {
    const raw = auth.session?.allowed_monitor_platforms
    return Array.isArray(raw) ? raw.map(code => String(code || '').trim()).filter(Boolean) : []
  })
  // 2026-09-07 - 算力自助不设平台白名单：空数组=不限制（与 isMonitorPlatformAllowed 一致）
  const effectiveMonitorPlatforms = computed(() => (
    customerEnterpriseMode ? customerPlatformWhitelist.value : allowedMonitorPlatforms.value
  ))
  const canEditModels = computed(() => {
    if (previewReadonly.value) return false
    if (customerEnterpriseMode) {
      return Boolean(customerMonitorGrant()?.can_update)
    }
    return allowedMonitorPlatforms.value.length > 0
  })
  const editableCatalogPlatforms = computed(() => {
    const source = catalogPlatforms.value.length
      ? catalogPlatforms.value
      : supportedPlatforms.map(item => ({
          code: item.code,
          name: item.name,
          selectable: true,
          labels: [] as string[],
          default_mode: 'standard' as const,
        }))
    if (customerEnterpriseMode) {
      // 2026-09-07 - 客户侧展示目录全部，不再按租户白名单裁切
      return source
    }
    if (!allowedMonitorPlatforms.value.length) return []
    const allow = new Set(allowedMonitorPlatforms.value)
    return source.filter(item => allow.has(item.code))
  })

  const canCreateTenant = computed(() => Boolean(menuGrant(enterprisePermissionCodeMap.list)?.can_update))
  const canEditTenantList = computed(() => !customerEnterpriseMode && Boolean(menuGrant(enterprisePermissionCodeMap.list)?.can_update))

  const visibleEnterpriseTabs = computed(() => ([
    { code: 'profile', name: '企业资料' },
    { code: 'keywords', name: '监测词配置' },
    { code: 'brand_words', name: '品牌词配置' },
    { code: 'schedule', name: '监控计划' },
    { code: 'competitors', name: '竞品监控' },
    { code: 'files', name: '企业知识库' },
    { code: 'credit', name: '算力与账单' },
  ] as Array<{ code: EnterpriseTab; name: string }>).filter(tab => {
    if (creatingDraftTenant.value && tab.code === 'files') {
      return false
    }
    return canViewEnterpriseTab(tab.code)
  }))

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
    billing_mode: 'all' as 'all' | 'hosted' | 'credit',
    owner_user_id: 'all' as 'all' | 'none' | number,
  })
  const tenantDialog = ref(false)
  const creatingDraftTenant = ref(false)
  const resubmitApprovalId = ref<number | null>(null)
  const resubmitOperationKey = ref<string | null>(null)
  const tenantForm = reactive({
    name: '',
    code: '',
    service_start_date: '',
    service_end_date: '',
    billing_mode: 'hosted' as 'hosted' | 'credit',
    opening_credit_amount: '',
  })
  const pendingTenantLogoFile = ref<File | null>(null)
  const pendingTenantLogoPreview = ref<string | null>(null)
  const pendingTenantLogoFileName = computed(() => pendingTenantLogoFile.value?.name || '')

  const platformBrandLogoTenantId = inject(PlatformBrandLogoTenantKey, null)
  const refreshPlatformTenants = inject(PlatformTenantsRefreshKey, null)

  const tenantTransferDialog = ref(false)
  const tenantTransferTarget = ref<TenantInfo | null>(null)
  const tenantTransferOwnerId = ref<number | null>(null)
  const tenantSalesOwners = ref<TenantSalesOwner[]>([])
  const loadingTenantSalesOwners = ref(false)
  const transferringTenantOwner = ref(false)
  const canTransferTenantOwner = computed(() => Boolean(menuGrant('platform.approvals')?.can_update))
  const canFilterBySales = computed(() => canTransferTenantOwner.value)
  /** 销售只看名下企业，列表无需再标归属销售 */
  const showOwnerOnEnterpriseList = computed(() => {
    const identity = auth.session?.identity
    if (!identity || identity.identity_type !== 'PLATFORM') return false
    if (identity.position_code === 'PLATFORM_SALES') return false
    if (!identity.position_code && identity.position_name === '销售') return false
    return true
  })
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
  const knowledgePreviewUrl = ref('')
  const knowledgePreviewLoading = ref(false)
  const knowledgePreviewError = ref('')
  let knowledgePreviewObjectUrl = ''

  function revokeKnowledgePreviewUrl() {
    if (knowledgePreviewObjectUrl) {
      URL.revokeObjectURL(knowledgePreviewObjectUrl)
      knowledgePreviewObjectUrl = ''
    }
    knowledgePreviewUrl.value = ''
  }
  const canUploadKnowledgeFiles = computed(() => (
    isPlatform.value
    && Boolean(menuGrant(enterprisePermissionCodeMap.files)?.can_create)
  ))
  const canDeleteKnowledgeFiles = computed(() => (
    isPlatform.value
    && Boolean(menuGrant(enterprisePermissionCodeMap.files)?.can_update)
  ))
  const uploadingKnowledgeFile = ref(false)
  const knowledgeUploadDialogVisible = ref(false)
  const knowledgeUploadTenant = ref<TenantInfo | null>(null)
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
  const brandWordGroupRows = ref<BrandWordGroup[]>([])
  const catalogPlatforms = ref<Awaited<ReturnType<typeof getPlatformsForBrandConfig>>['platforms']>([])
  const modeDialogVisible = ref(false)
  const modeDialogTarget = ref<{ source: 'keywords' | 'brand_words'; groupIndex: number; code: string } | null>(null)
  const modeDialogForm = reactive({
    mode: 'standard' as PlatformSelection['mode'],
    screenshot: 1 as PlatformSelection['screenshot'],
  })
  const editingGroupIndex = ref<number | null>(null)
  const editingBrandWordGroupIndex = ref<number | null>(null)
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
    billing_mode: 'hosted' as 'hosted' | 'credit',
    opening_credit_amount: '',
    goods_card_enabled: false,
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
    schedule_frequency: 1,
    schedule_weekdays: [] as number[],
    schedule_month_days_text: '',
  })

  watch(
    () => (enterpriseDetailMode.value && brandForm.tenant_id ? brandForm.tenant_id : null),
    (tenantId) => {
      if (platformBrandLogoTenantId) platformBrandLogoTenantId.value = tenantId
    },
    { immediate: true },
  )
  onBeforeUnmount(() => {
    if (platformBrandLogoTenantId) platformBrandLogoTenantId.value = null
  })

  const editingTenant = computed(() => tenants.value.find(item => item.id === brandForm.tenant_id) || null)
  const editingTenantLogoSrc = computed(() => {
    if (pendingTenantLogoPreview.value) return pendingTenantLogoPreview.value
    const tenant = editingTenant.value
    if (tenant?.has_logo) return tenantLogoUrl(tenant.id, tenant.logo_updated_at)
    if (brandForm.tenant_id) return tenantLogoUrl(brandForm.tenant_id)
    return ''
  })

  // 2026-08-05 - 企业列表置顶仅本人可见 - localStorage 单 id，新置顶覆盖旧的
  const pinnedTenantId = ref<number | null>(null)
  const ENTERPRISE_PAGE_SIZE = 10
  const enterprisePage = ref(1)

  function loadEnterprisePin() {
    const userId = auth.session?.user?.id
    const identityId = auth.session?.identity?.id
    if (!userId || !identityId) {
      pinnedTenantId.value = null
      return
    }
    pinnedTenantId.value = readEnterprisePin(userId, identityId)
  }

  function persistEnterprisePin(tenantId: number | null) {
    pinnedTenantId.value = tenantId
    const userId = auth.session?.user?.id
    const identityId = auth.session?.identity?.id
    if (userId && identityId) writeEnterprisePin(userId, identityId, tenantId)
  }

  function isEnterprisePinned(tenant: TenantInfo) {
    return pinnedTenantId.value === tenant.id
  }

  function pinEnterprise(tenant: TenantInfo) {
    persistEnterprisePin(tenant.id)
    enterprisePage.value = 1
    ElMessage.success('已置顶')
  }

  function unpinEnterprise(tenant: TenantInfo) {
    if (pinnedTenantId.value !== tenant.id) return
    persistEnterprisePin(null)
    ElMessage.success('已取消置顶')
  }

  watch(
    () => [auth.session?.user?.id, auth.session?.identity?.id] as const,
    () => loadEnterprisePin(),
    { immediate: true },
  )

  const filteredTenants = computed(() => {
    const keyword = enterpriseFilters.keyword.trim().toLowerCase()
    const matched = tenants.value.filter(tenant => {
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
      const billingFilter = enterpriseFilters.billing_mode
      const billingMatched = billingFilter === 'all'
        || (billingFilter === 'credit' && tenant.billing_mode === 'credit')
        || (billingFilter === 'hosted' && tenant.billing_mode !== 'credit')
      return keywordMatched && statusMatched && ownerMatched && billingMatched
    })
    // 2026-08-05 - 企业列表个人单条置顶 - 仅当前结果集内提前，不破坏筛选口径
    return sortTenantsWithPin(matched, pinnedTenantId.value)
  })

  const enterpriseTotalPages = computed(() =>
    Math.max(1, Math.ceil(filteredTenants.value.length / ENTERPRISE_PAGE_SIZE)),
  )
  const pagedTenants = computed(() => {
    const page = Math.min(Math.max(1, enterprisePage.value), enterpriseTotalPages.value)
    const start = (page - 1) * ENTERPRISE_PAGE_SIZE
    return filteredTenants.value.slice(start, start + ENTERPRISE_PAGE_SIZE)
  })

  watch(
    () => [enterpriseFilters.keyword, enterpriseFilters.expiry, enterpriseFilters.billing_mode, enterpriseFilters.owner_user_id] as const,
    () => {
      enterprisePage.value = 1
    },
  )
  watch(filteredTenants, () => {
    if (enterprisePage.value > enterpriseTotalPages.value) {
      enterprisePage.value = enterpriseTotalPages.value
    }
  })
  watch(
    () => brandForm.billing_mode,
    () => {
      // 切成托管或打开托管企业时，若还停在算力 Tab 则跳回可见第一项
      if (enterpriseDetailTab.value !== 'credit') return
      if (canViewEnterpriseTab('credit')) return
      const first = visibleEnterpriseTabs.value[0]?.code
      if (first) enterpriseDetailTab.value = first
    },
  )
  watch(enterpriseDetailTab, (tab) => {
    if (tab === 'credit' && brandForm.tenant_id) {
      void refreshEditingTenantBilling(brandForm.tenant_id)
    }
  })

  function changeEnterprisePage(page: number) {
    enterprisePage.value = Math.min(Math.max(1, page), enterpriseTotalPages.value)
  }

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
  // 2026-08-10 - 企业资料仅企业全称必填；监测词/平台/计划等均可后补
  const brandAssetProfileMissing = computed(() => {
    const missing: string[] = []
    if (brandForm.company_full_name.trim().length < 2) missing.push('企业全称（至少2个字）')
    return missing
  })
  const canSubmitBrandAssetProfile = computed(() => brandAssetProfileMissing.value.length === 0)

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

  function canPurgeTenant() {
    return Boolean(menuGrant(enterprisePermissionCodeMap.purge)?.can_delete)
  }

  function isPlatformAdminIdentity() {
    const identity = auth.session?.identity
    if (!identity) return false
    return identity.position_code === 'PLATFORM_ADMIN' || identity.role_code === 'PLATFORM_ADMIN'
  }

  async function ensurePurgeMenuInSession() {
    // 职位勾了彻底删除但本地会话菜单仍是旧的：进企业列表时补一次 /me
    if (customerEnterpriseMode || previewReadonly.value) return
    if (!isPlatformAdminIdentity() || canPurgeTenant()) return
    try {
      await auth.refreshSession()
    } catch {
      // 刷新失败不挡列表；按钮仍按当前会话权限隐藏
    }
  }

  function stopTenantActionLabel(tenant: TenantInfo) {
    return isTenantPending(tenant) ? '取消服务' : '停止服务'
  }

  function tenantServicePeriod(tenant: TenantInfo) {
    const start = tenant.service_start_date || '未设置'
    const end = tenant.service_end_date || '长期'
    return `${start} 至 ${end}`
  }

  function tenantBillingLabel(tenant: TenantInfo) {
    if (tenant.billing_mode !== 'credit') return '平台托管'
    const balance = Number(tenant.credit_balance)
    if (Number.isFinite(balance) && balance <= 0) return '算力自助·零余额'
    return '算力自助'
  }

  async function refreshEditingTenantBilling(tenantId?: number | null) {
    const id = tenantId ?? brandForm.tenant_id
    if (!id || customerEnterpriseMode) return
    try {
      const detail = await getTenantCredit(id)
      const mode = detail.billing_mode === 'credit' ? 'credit' : 'hosted'
      const balance = Number(detail.credit_balance)
      brandForm.billing_mode = mode
      const idx = tenants.value.findIndex(item => item.id === id)
      if (idx >= 0) {
        tenants.value.splice(idx, 1, {
          ...tenants.value[idx],
          billing_mode: mode,
          credit_balance: Number.isFinite(balance) ? balance : tenants.value[idx].credit_balance,
        })
      }
    } catch {
      /* 详情刷新失败不阻断编辑页 */
    }
  }

  function tenantMonitorLabel(tenant: TenantInfo) {
    const n = Number(tenant.schedule_frequency)
    if (!Number.isFinite(n) || n <= 0) return '未配置'
    return `每日 ${n} 次`
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

  function normalizeKeywordGroups(asset: BrandAsset | null, _tenantName = '') {
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
    // 2026-07-30 - 监测词不预填企业名；无词组时给一个空词组卡片
    keywordGroupRows.value = []
    keywordGroupRows.value = [makeKeywordGroup()]
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

  function makeBrandWordGroup(monitorKeyword = ''): BrandWordGroup {
    const keywords = monitorKeyword.trim() ? [monitorKeyword.trim()] : []
    const index = brandWordGroupRows.value.length
    const inheritedPlatforms = normalizePlatformSelections(
      brandWordGroupRows.value.find(item => (item.platforms || []).length)?.platforms
      || keywordGroupRows.value.find(item => (item.platforms || []).length)?.platforms
      || (brandForm.monitored_platforms.length ? [...brandForm.monitored_platforms] : []),
    )
    return {
      id: null,
      name: defaultBrandWordGroupName(index),
      monitor_keyword: keywords[0] || '',
      monitor_keywords: keywords,
      platforms: inheritedPlatforms,
      run_mode: 'once',
      run_immediately: false,
      sort_order: index,
      status: true,
    }
  }

  function normalizeBrandWordGroups(asset: BrandAsset | null) {
    const groups = asset?.brand_word_groups?.length ? asset.brand_word_groups : []
    brandWordGroupRows.value = groups.map((group, index) => {
      const monitorKeywords = keywordGroupMonitorKeywords(group)
      const runMode = group.run_mode === 'weekly' ? 'weekly' : 'once'
      return {
        id: group.id || null,
        tenant_id: group.tenant_id,
        name: (group.name || '').trim() || defaultBrandWordGroupName(index),
        monitor_keyword: monitorKeywords[0] || '',
        monitor_keywords: [...monitorKeywords],
        platforms: normalizePlatformSelections(
          group.platforms?.length ? group.platforms : (asset?.monitored_platforms || []),
        ),
        run_mode: runMode,
        run_immediately: Boolean(group.run_immediately),
        sort_order: group.sort_order ?? index,
        status: group.status,
      }
    })
  }

  async function startEditBrandWordGroupName(index: number) {
    if (!canEditEnterpriseTab('brand_words')) return
    editingBrandWordGroupIndex.value = index
    await nextTick()
    const input = document.getElementById(`brand-word-group-name-${index}`) as HTMLInputElement | null
    input?.focus()
    input?.select()
  }

  function finishEditBrandWordGroupName(group: BrandWordGroup, index: number, value: string) {
    group.name = value.trim() || defaultBrandWordGroupName(index)
    editingBrandWordGroupIndex.value = null
  }

  function cancelEditBrandWordGroupName() {
    editingBrandWordGroupIndex.value = null
  }

  function addBrandWordGroup() {
    brandWordGroupRows.value.push(makeBrandWordGroup())
  }

  function removeBrandWordGroup(index: number) {
    brandWordGroupRows.value.splice(index, 1)
    brandWordGroupRows.value.forEach((item, itemIndex) => { item.sort_order = itemIndex })
  }

  function brandWordGroupDisplayName(group: BrandWordGroup, index = group.sort_order ?? 0) {
    return (group.name || '').trim() || defaultBrandWordGroupName(index)
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

  function syncGroupPrimaryKeyword(group: BrandKeywordGroup | BrandWordGroup) {
    const keywords = (group.monitor_keywords || []).map(item => item.trim()).filter(Boolean)
    group.monitor_keywords = keywords
    group.monitor_keyword = keywords[0] || ''
  }

  function splitKeywordInput(text: string) {
    return text.split(/[\n\r、,，;；\t]+/).map(item => item.trim()).filter(Boolean)
  }

  function addMonitorKeyword(group: BrandKeywordGroup | BrandWordGroup, term: string) {
    const text = term.trim()
    if (!text) return
    if (!group.monitor_keywords) group.monitor_keywords = []
    if (!group.monitor_keywords.some(item => item.toLowerCase() === text.toLowerCase())) {
      group.monitor_keywords.push(text)
    }
    syncGroupPrimaryKeyword(group)
  }

  function addMonitorKeywordsFromText(group: BrandKeywordGroup | BrandWordGroup, text: string) {
    splitKeywordInput(text).forEach(term => addMonitorKeyword(group, term))
  }

  function commitMonitorKeywordInput(group: BrandKeywordGroup | BrandWordGroup, event: Event) {
    const input = event.target as HTMLInputElement
    addMonitorKeywordsFromText(group, input.value)
    input.value = ''
  }

  function handleMonitorKeywordPaste(group: BrandKeywordGroup | BrandWordGroup, event: ClipboardEvent) {
    const text = event.clipboardData?.getData('text') || ''
    const terms = splitKeywordInput(text)
    if (terms.length <= 1) return
    event.preventDefault()
    addMonitorKeywordsFromText(group, text)
    const input = event.target as HTMLInputElement
    input.value = ''
  }

  function removeMonitorKeyword(group: BrandKeywordGroup | BrandWordGroup, index: number) {
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
    // 2026-09-09 - 新建企业允许监测计划为空，不强制留默认场次
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
    brandForm.billing_mode = (tenant?.billing_mode === 'credit' ? 'credit' : 'hosted')
    brandForm.opening_credit_amount = ''
    // 2026-09-01 - 商品卡默认关；仅显式 true 才算开通
    brandForm.goods_card_enabled = tenant?.goods_card_enabled === true
    brandForm.brand_name = asset?.brand_name || asset?.company_full_name || tenant?.name || ''
    brandForm.brand_short_name = asset?.brand_short_name || ''
    brandForm.monitor_keywords_text = [...new Set([...(asset?.monitor_keywords || []), ...(asset?.product_keywords || [])])].join('\n')
    brandForm.aliases_text = (asset?.aliases || []).join('\n')
    brandForm.region_codes = [...(asset?.region_codes || [])]
    normalizeKeywordGroups(asset, tenant?.name || '')
    normalizeBrandWordGroups(asset)
    brandForm.monitored_platforms = asset ? [...(asset.monitored_platforms || [])] : []
    brandForm.official_url = asset?.official_url || ''
    brandForm.description = asset?.description || ''
    brandForm.schedule_type = 'daily_times'
    brandForm.schedule_times = asset?.schedule_times?.length ? [...asset.schedule_times] : []
    brandForm.schedule_frequency = asset?.schedule_frequency || brandForm.schedule_times.length || 1
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

  function applyResubmitBrandBody(body: Record<string, unknown>) {
    const tidRaw = body.tenant_id
    const tid = tidRaw != null && Number.isFinite(Number(tidRaw)) ? Number(tidRaw) : null
    enterpriseDetailMode.value = true
    if (!tid) {
      creatingDraftTenant.value = true
      const firstVisibleTab = visibleEnterpriseTabs.value[0]?.code
      if (firstVisibleTab) enterpriseDetailTab.value = firstVisibleTab
    } else {
      creatingDraftTenant.value = false
    }
    const pseudoAsset = body as unknown as BrandAsset
    fillBrandForm(pseudoAsset, tid)
    if (Array.isArray(body.competitors)) {
      fillCompetitorRows(body.competitors as BrandCompetitor[])
    }
    normalizeBrandWordGroups(pseudoAsset)
    if (body.logo_staging_key) {
      ElMessage.warning('上次驳回已清理 Logo 暂存，如有需要请重新上传')
    }
  }

  async function loadResubmitDraftFromRoute() {
    const raw = route.query.resubmit_approval_id
    const id = Number(Array.isArray(raw) ? raw[0] : raw)
    if (!Number.isFinite(id) || id <= 0) return
    try {
      const row = await getApproval(id)
      if (row.status !== 'rejected') {
        ElMessage.warning('该审批单不是已驳回状态')
        return
      }
      if (!['brand.asset.upsert', 'management.tenant.create'].includes(row.operation_key)) {
        ElMessage.warning('请从对应业务页修改此审批单')
        return
      }
      resubmitApprovalId.value = id
      resubmitOperationKey.value = row.operation_key
      const body = ((row.payload?.body || row.payload || {}) as Record<string, unknown>)
      if (row.review_comment) {
        ElMessage.warning(`上次驳回：${row.review_comment}`)
      }
      if (row.operation_key === 'management.tenant.create') {
        tenantForm.name = String(body.name || '')
        tenantForm.service_start_date = String(body.service_start_date || '')
        tenantForm.service_end_date = String(body.service_end_date || '')
        tenantForm.billing_mode = body.billing_mode === 'credit' ? 'credit' : 'hosted'
        tenantForm.opening_credit_amount = body.opening_credit_amount != null ? String(body.opening_credit_amount) : ''
        tenantDialog.value = true
        return
      }
      applyResubmitBrandBody(body)
    } catch (error: unknown) {
      notifyError(error, '加载驳回单失败')
    }
  }

  function notifyBrandUpdated() {
    options.onBrandUpdated?.(brandAsset.value, brandCompetitors.value)
  }

  async function loadCustomerEnterpriseMonitor() {
    loadingBrand.value = true
    try {
      const data = await getEnterpriseMonitor(previewTenantId.value ?? undefined)
      brandForm.tenant_id = Number(data.tenant_id) || null
      brandAsset.value = (data.asset as BrandAsset | null) || null
      brandCompetitors.value = (data.competitors as BrandCompetitor[]) || []
      // 2026-09-07 - 忽略接口里的历史白名单，客户侧始终按「不限制」处理
      customerPlatformWhitelist.value = []
      customerCreditPolicy.value = (data.policy as Record<string, unknown>) || {}
      customerDailyEstimate.value = (data.daily_estimate as Record<string, unknown>) || {}
      fillBrandForm(brandAsset.value, brandForm.tenant_id)
      fillCompetitorRows(brandCompetitors.value)
      notifyBrandUpdated()
    } catch (error: unknown) {
      notifyError(error, '监测配置加载失败')
    } finally {
      loadingBrand.value = false
    }
  }

  async function initCustomerEnterpriseConfig() {
    enterpriseDetailMode.value = true
    enterpriseDetailTab.value = 'keywords'
    await loadCatalogPlatforms()
    await loadCustomerEnterpriseMonitor()
  }

  async function loadBrandAssetData() {
    if (creatingDraftTenant.value) return
    if (customerEnterpriseMode) {
      await loadCustomerEnterpriseMonitor()
      return
    }
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
      // 2026-09-04 - 接口缺字段时勿默认关：回落到企业列表里的开通状态
      if (typeof response.goods_card_enabled === 'boolean') {
        brandForm.goods_card_enabled = response.goods_card_enabled === true
      } else {
        const fromTenant = tenants.value.find(item => item.id === response.tenant_id)
        brandForm.goods_card_enabled = fromTenant?.goods_card_enabled === true
      }
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
      await ensurePurgeMenuInSession()
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

  async function uploadKnowledgeFileToTenant(tenantId: number, file: File) {
    validateKnowledgeUploadFile(file)
    uploadingKnowledgeFile.value = true
    try {
      const record = await uploadKnowledgeFile(file, tenantId)
      if (enterpriseDetailMode.value && brandForm.tenant_id === tenantId) {
        knowledgeFiles.value = [record, ...knowledgeFiles.value.filter(item => item.id !== record.id)]
      }
      ElMessage.success(`已上传：${record.original_name}`)
      return record
    } catch (error: unknown) {
      notifyError(error, '资料上传失败')
      throw error
    } finally {
      uploadingKnowledgeFile.value = false
    }
  }

  function openKnowledgeUploadDialog(tenant: TenantInfo) {
    if (!canUploadKnowledgeFiles.value) {
      ElMessage.warning('当前账号无权上传资料')
      return
    }
    knowledgeUploadTenant.value = tenant
    knowledgeUploadDialogVisible.value = true
  }

  async function openEnterpriseDetailFiles(tenant: TenantInfo) {
    if (!canViewEnterpriseTab('files')) {
      ElMessage.warning('当前账号无权查看企业知识库')
      return
    }
    knowledgeUploadDialogVisible.value = false
    clearPendingTenantLogo()
    enterpriseDetailMode.value = true
    enterpriseDetailTab.value = 'files'
    brandForm.tenant_id = tenant.id
    brandForm.company_full_name = tenant.name
    await loadBrandAssetData()
    await loadKnowledgeFiles()
  }

  async function handleKnowledgeUploadInput(event: Event, tenantId: number) {
    const input = event.target as HTMLInputElement
    const file = input.files?.[0]
    input.value = ''
    if (!file) return
    await uploadKnowledgeFileToTenant(tenantId, file)
    if (knowledgeUploadDialogVisible.value && knowledgeUploadTenant.value?.id === tenantId) {
      knowledgeUploadDialogVisible.value = false
      knowledgeUploadTenant.value = null
    }
  }

  async function previewKnowledgeFile(file: KnowledgeFileRecord) {
    knowledgePreviewFile.value = file
    knowledgePreviewVisible.value = true
    knowledgePreviewLoading.value = true
    knowledgePreviewError.value = ''
    revokeKnowledgePreviewUrl()
    try {
      const url = await withRetry(() => getKnowledgeFilePreviewObjectUrl(file.id))
      knowledgePreviewObjectUrl = url
      knowledgePreviewUrl.value = url
    } catch (error: unknown) {
      knowledgePreviewError.value = errorMessage(error)
      revokeKnowledgePreviewUrl()
    } finally {
      knowledgePreviewLoading.value = false
    }
  }

  function closeKnowledgePreview() {
    knowledgePreviewVisible.value = false
    knowledgePreviewFile.value = null
    knowledgePreviewError.value = ''
    revokeKnowledgePreviewUrl()
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
      await ElMessageBox.confirm(`确定删除「${file.original_name}」？删除后不可恢复。`, '删除知识库文件', {
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
    clearPendingTenantLogo()
    const firstVisibleTab = visibleEnterpriseTabs.value[0]?.code
    if (!firstVisibleTab) {
      ElMessage.warning('当前职位只有企业列表权限，没有企业详情配置权限')
      return
    }
    enterpriseDetailMode.value = true
    enterpriseDetailTab.value = firstVisibleTab
    brandForm.tenant_id = tenant.id
    brandForm.company_full_name = tenant.name
    await refreshEditingTenantBilling(tenant.id)
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
      await refreshEditingTenantBilling(tenant.id)
      const latest = tenants.value.find(item => item.id === tenant.id) || tenant
      enterpriseInfoTenant.value = latest
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
    clearPendingTenantLogo()
    creatingDraftTenant.value = false
    enterpriseDetailMode.value = false
    brandAsset.value = null
    brandCompetitors.value = []
    competitorRows.value = []
    knowledgeFiles.value = []
    fillBrandForm(null, null)
  }

  async function applyPendingTenantLogoDirect(): Promise<boolean> {
    if (!pendingTenantLogoFile.value || !brandForm.tenant_id) return false
    if (creatingDraftTenant.value || customerEnterpriseMode || previewReadonly.value) return false
    const file = pendingTenantLogoFile.value
    loadingBrand.value = true
    try {
      // 2026-08-27 - 已有企业改 Logo 走直传接口，勿只写暂存（审批回滚会库盘不一致）
      await uploadTenantLogo(brandForm.tenant_id, file)
      clearPendingTenantLogo()
      await loadEnterpriseList()
      await refreshPlatformTenants?.()
      ElMessage.success('企业 Logo 已更新')
      return true
    } catch (error: unknown) {
      notifyError(error, 'Logo 上传失败')
      return false
    } finally {
      loadingBrand.value = false
    }
  }

  async function submitBrandAsset(successText = '品牌资产已保存') {
    if (previewReadonly.value) {
      ElMessage.info('预览模式为只读，不可保存')
      return
    }
    // 2026-08-10 - 监测词组非必填；企业资料只需全称即可落资产，勿再卡「至少一个词组」
    const missing = brandAssetProfileMissing.value
    if (missing.length) {
      ElMessage.warning(`请先完善：${missing.join('、')}`)
      return
    }
    const isDraftCreateEarly = creatingDraftTenant.value || !brandForm.tenant_id
    if (!isDraftCreateEarly && pendingTenantLogoFile.value) {
      const logoOk = await applyPendingTenantLogoDirect()
      if (!logoOk) return
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
    const missingPlatforms = keywordGroups.find(group => group.status && !group.platforms.length)
    if (missingPlatforms && canEditModels.value) {
      ElMessage.warning('每个启用的监测词组至少选择一个监测平台')
      return
    }
    const scheduleFrequency = Math.max(1, scheduleTimeList().length || brandForm.schedule_frequency)
    if (customerEnterpriseMode) {
      loadingBrand.value = true
      try {
        await saveEnterpriseMonitor({
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
          schedule_frequency: scheduleFrequency,
          schedule_weekdays: [],
          schedule_month_days: [],
        })
        await loadCustomerEnterpriseMonitor()
        ElMessage.success(successText)
      } catch (error: unknown) {
        notifyError(error, '监测配置保存失败')
      } finally {
        loadingBrand.value = false
      }
      return
    }
    loadingBrand.value = true
    try {
      const isDraftCreate = creatingDraftTenant.value || !brandForm.tenant_id
      if (brandForm.tenant_id) {
        const tenant = await updateTenant(brandForm.tenant_id, {
          name: brandForm.company_full_name.trim(),
          code: null,
          service_start_date: brandForm.service_start_date || null,
          service_end_date: brandForm.service_end_date || null,
        goods_card_enabled: brandForm.goods_card_enabled === true,
          status: enterpriseFormServiceActive.value,
        })
        const tenantIndex = tenants.value.findIndex(item => item.id === tenant.id)
        if (tenantIndex >= 0) tenants.value.splice(tenantIndex, 1, tenant)
      }
      const scheduleFrequency = Math.max(1, scheduleTimeList().length || brandForm.schedule_frequency)
      const brandWordGroups = isDraftCreate
        ? brandWordGroupRows.value
          .map((group, index) => {
            const monitorKeywords = (group.monitor_keywords || []).map(item => item.trim()).filter(Boolean)
            return {
              id: null,
              name: (group.name || '').trim() || defaultBrandWordGroupName(index),
              monitor_keyword: monitorKeywords[0] || '',
              monitor_keywords: monitorKeywords,
              platforms: normalizePlatformSelections(group.platforms),
              run_mode: group.run_mode === 'weekly' ? 'weekly' as const : 'once' as const,
              sort_order: index,
              status: group.status,
            }
          })
          .filter(group => group.monitor_keywords.length)
        : undefined
      const competitors = isDraftCreate
        ? competitorRows.value
          .map(row => ({
            name: (row.name || '').trim(),
            short_name: null,
            aliases: [],
            website_url: null,
            category: (row.category || '').trim() || '直接竞品',
          }))
          .filter(item => item.name)
        : undefined
      let logoStagingKey: string | null = null
      if (pendingTenantLogoFile.value && isDraftCreate) {
        const staged = await uploadLogoStaging(pendingTenantLogoFile.value)
        logoStagingKey = staged.staging_key
      }
      const assetPayload = {
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
        schedule_type: 'daily_times' as const,
        schedule_times: scheduleTimeList(),
        schedule_frequency: scheduleFrequency,
        schedule_weekdays: [] as number[],
        schedule_month_days: [] as number[],
        service_start_date: brandForm.service_start_date || null,
        service_end_date: brandForm.service_end_date || null,
        billing_mode: brandForm.billing_mode,
        // 2026-09-04 - 与 updateTenant 双写，平台保存品牌资产时也带上开关
        goods_card_enabled: brandForm.goods_card_enabled === true,
        brand_word_groups: brandWordGroups,
        competitors,
        logo_staging_key: logoStagingKey,
      }
      if (resubmitApprovalId.value) {
        const saved = await resubmitApproval(resubmitApprovalId.value, { body: assetPayload as Record<string, unknown> })
        resubmitApprovalId.value = null
        resubmitOperationKey.value = null
        const msg = pendingApprovalMessage(saved, isDraftCreate ? '已重新提交，通过后企业才会创建' : '已重新提交，等待运营或管理员审核')
        ElMessage.success(msg)
        if (logoStagingKey) clearPendingTenantLogo()
        if (isDraftCreate) backToEnterpriseList()
        return
      }
      const saved = await saveBrandAsset(assetPayload)
      if (isPendingApproval(saved)) {
        const msg = pendingApprovalMessage(saved, isDraftCreate ? '已提交审批，通过后企业才会创建' : '已提交审批，等待运营或管理员审核')
        if (isDuplicateMergedApproval(saved)) ElMessage.warning(msg)
        else if (isResubmittedApproval(saved)) ElMessage.success(msg)
        else ElMessage.info(msg)
        if (logoStagingKey) clearPendingTenantLogo()
        if (isDraftCreate) backToEnterpriseList()
        return
      }
      if (isDraftCreate && saved.tenant_id) {
        creatingDraftTenant.value = false
        brandForm.tenant_id = saved.tenant_id
        await loadEnterpriseList()
      }
      const logoTenantId = brandForm.tenant_id || saved.tenant_id
      // 2026-08-25 - Logo 随企业资料进审批 - 直执成功时后端已从暂存落库
      if (logoStagingKey) {
        clearPendingTenantLogo()
        if (logoTenantId) {
          await loadEnterpriseList()
          await refreshPlatformTenants?.()
        }
      }
      const listIndex = tenants.value.findIndex(item => item.id === brandForm.tenant_id)
      if (listIndex >= 0) {
        tenants.value.splice(listIndex, 1, {
          ...tenants.value[listIndex],
          schedule_frequency: scheduleFrequency,
        })
      }
      await loadBrandAssetData()
      ElMessage.success(successText)
    } catch (error: unknown) {
      notifyError(error, '品牌资产保存失败')
    } finally {
      loadingBrand.value = false
    }
  }

  async function submitBrandWordGroups(successText = '品牌词配置已保存') {
    if (previewReadonly.value) {
      ElMessage.info('预览模式为只读，不可保存')
      return
    }
    if (creatingDraftTenant.value || !brandForm.tenant_id) {
      if (creatingDraftTenant.value) {
        // 2026-08-18 - 草稿点品牌词保存会整单进审批 - 仅右上角保存当前配置才提交
        return
      }
      ElMessage.warning('请先选择企业')
      return
    }
    // 2026-08-10 - 无企业资产时禁止提交/入队，避免审批通过再报「请先保存企业资料」
    if (!brandAsset.value) {
      ElMessage.warning('请先保存企业资料，再配置品牌词')
      return
    }
    const groups = brandWordGroupRows.value
      .map((group, index) => {
        const monitorKeywords = (group.monitor_keywords || []).map(item => item.trim()).filter(Boolean)
        const platforms = normalizePlatformSelections(group.platforms)
        return {
          id: group.id || null,
          name: (group.name || '').trim() || defaultBrandWordGroupName(index),
          monitor_keyword: monitorKeywords[0] || '',
          monitor_keywords: monitorKeywords,
          platforms,
          run_mode: group.run_mode === 'weekly' ? 'weekly' as const : 'once' as const,
          sort_order: index,
          status: group.status,
        }
      })
      .filter(group => group.monitor_keywords.length)
    const missingPlatforms = groups.find(group => group.status && !group.platforms.length)
    if (missingPlatforms && canEditModels.value) {
      ElMessage.warning('每个启用的品牌词组至少选择一个监测平台')
      return
    }
    if (customerEnterpriseMode) {
      loadingBrand.value = true
      try {
        const payloadGroups = brandWordGroupRows.value
          .map((group, index) => {
            const monitorKeywords = (group.monitor_keywords || []).map(item => item.trim()).filter(Boolean)
            return {
              id: group.id || null,
              name: (group.name || '').trim() || defaultBrandWordGroupName(index),
              monitor_keyword: monitorKeywords[0] || '',
              monitor_keywords: monitorKeywords,
              platforms: normalizePlatformSelections(group.platforms),
              run_mode: group.run_mode === 'weekly' ? 'weekly' as const : 'once' as const,
              run_immediately: Boolean(group.run_immediately),
              sort_order: index,
              status: group.status,
            }
          })
          .filter(group => group.monitor_keywords.length)
        const needImmediate = payloadGroups.some(group => group.run_immediately)
        if (needImmediate) {
          try {
            const estimate = await estimateEnterpriseBrandWords({
              tenant_id: brandForm.tenant_id,
              groups: payloadGroups,
            })
            const credits = Number(estimate?.credits || 0)
            await ElMessageBox.confirm(
              `勾选立即跑一轮将额外消耗约 ${credits} 算力（${estimate?.group_count || 0} 组），确认保存并提交？`,
              '算力确认',
              { type: 'warning' },
            )
          } catch {
            loadingBrand.value = false
            return
          }
        }
        const saved = await saveEnterpriseBrandWords({
          tenant_id: brandForm.tenant_id,
          groups: payloadGroups,
          confirm_immediate: needImmediate,
        })
        await loadCustomerEnterpriseMonitor()
        const onceRows = (saved.once_submitted as Array<{ status?: string }>) || []
        const onceCount = onceRows.filter(item => item.status === 'submitted').length
        ElMessage.success(onceCount ? `${successText}，已提交 ${onceCount} 组` : successText)
      } catch (error: unknown) {
        notifyError(error, '品牌词保存失败')
      } finally {
        loadingBrand.value = false
      }
      return
    }
    loadingBrand.value = true
    try {
      const saved = await saveBrandWordGroups({
        tenant_id: brandForm.tenant_id,
        groups,
      })
      if (isPendingApproval(saved)) {
        const msg = pendingApprovalMessage(saved, '已提交审批，等待运营或管理员审核')
        if (isDuplicateMergedApproval(saved)) ElMessage.warning(msg)
        else ElMessage.info(msg)
        return
      }
      await loadBrandAssetData()
      const onceRows = saved.once_submitted || []
      const onceCount = onceRows.filter(item => item.status === 'submitted').length
      const onceFailed = onceRows.filter(item => item.status === 'failed')
      const onceServiceSkipped = onceRows.filter(item => {
        if (item.status !== 'skipped') return false
        const msg = String(item.message || '')
        return /尚未开始|已到期|未开通|已停服|暂不提交/.test(msg)
      })
      if (onceServiceSkipped.length) {
        // 2026-08-03 - 服务未开通：配置已存、监测未跑，用 info 而非「调度失败」恐吓
        const reason = onceServiceSkipped.map(item => String(item.message || '').trim()).filter(Boolean)[0]
        ElMessage.info(reason ? `${successText}；${reason}` : `${successText}；服务未开通，监测暂未提交`)
      } else if (onceFailed.length) {
        const reason = onceFailed
          .map(item => String(item.message || '').trim())
          .filter(Boolean)
          .join('；')
        ElMessage.warning(reason
          ? `${successText}；立即提交失败 ${onceFailed.length} 组：${reason}`
          : `${successText}；立即提交失败 ${onceFailed.length} 组`)
      } else if (onceCount) {
        ElMessage.success(`${successText}；已立即提交 ${onceCount} 组检测任务`)
      } else {
        ElMessage.success(successText)
      }
    } catch (error: unknown) {
      notifyError(error, '品牌词配置保存失败')
    } finally {
      loadingBrand.value = false
    }
  }

  function clearPendingTenantLogo() {
    if (pendingTenantLogoPreview.value?.startsWith('blob:')) {
      URL.revokeObjectURL(pendingTenantLogoPreview.value)
    }
    pendingTenantLogoFile.value = null
    pendingTenantLogoPreview.value = null
  }

  function onTenantLogoPick(event: Event) {
    const input = event.target as HTMLInputElement
    const file = input.files?.[0]
    input.value = ''
    if (!file) return
    const allowed = TENANT_LOGO_ACCEPT.split(',').map(item => item.trim().toLowerCase())
    const ext = file.name.includes('.') ? `.${file.name.split('.').pop()?.toLowerCase() || ''}` : ''
    const mimeOk = file.type && allowed.includes(file.type.toLowerCase())
    const extOk = ext && allowed.includes(ext)
    if (!mimeOk && !extOk) {
      ElMessage.warning('Logo 仅支持 PNG / JPG / WebP')
      return
    }
    if (file.size > TENANT_LOGO_MAX_BYTES) {
      ElMessage.warning('Logo 不能超过 2MB')
      return
    }
    clearPendingTenantLogo()
    pendingTenantLogoFile.value = file
    pendingTenantLogoPreview.value = URL.createObjectURL(file)
  }

  async function goNextFromTenantDialog() {
    const name = tenantForm.name.trim()
    if (name.length < 2) {
      ElMessage.warning('请填写企业名称（至少2个字）')
      return
    }
    if (tenantForm.service_start_date && tenantForm.service_end_date && tenantForm.service_end_date < tenantForm.service_start_date) {
      ElMessage.warning('服务结束日期不能早于服务开始日期')
      return
    }
    if (resubmitApprovalId.value && resubmitOperationKey.value === 'management.tenant.create') {
      loadingBrand.value = true
      try {
        const saved = await resubmitApproval(resubmitApprovalId.value, {
          body: {
            name,
            code: null,
            service_start_date: tenantForm.service_start_date || null,
            service_end_date: tenantForm.service_end_date || null,
            billing_mode: tenantForm.billing_mode,
          },
        })
        resubmitApprovalId.value = null
        resubmitOperationKey.value = null
        tenantDialog.value = false
        tenantForm.name = ''
        tenantForm.service_start_date = ''
        tenantForm.service_end_date = ''
        tenantForm.billing_mode = 'hosted'
        tenantForm.opening_credit_amount = ''
        ElMessage.success(pendingApprovalMessage(saved, '已重新提交，等待审核'))
      } catch (error: unknown) {
        notifyError(error, '重新提交失败')
      } finally {
        loadingBrand.value = false
      }
      return
    }
    loadingBrand.value = true
    try {
      // 2026-08-18 - 同名仍能进草稿 - 下一步先打全库重名/待审校验
      await checkTenantNameAvailable(name)
    } catch (error: unknown) {
      notifyOperationError(error, '该企业名称不可用')
      return
    } finally {
      loadingBrand.value = false
    }
    creatingDraftTenant.value = true
    enterpriseDetailMode.value = true
    const firstVisibleTab = visibleEnterpriseTabs.value[0]?.code
    if (firstVisibleTab) enterpriseDetailTab.value = firstVisibleTab
    brandAsset.value = null
    brandCompetitors.value = []
    competitorRows.value = []
    knowledgeFiles.value = []
    fillBrandForm(null, null)
    brandForm.company_full_name = name
    brandForm.brand_name = name
    brandForm.service_start_date = tenantForm.service_start_date || ''
    brandForm.service_end_date = tenantForm.service_end_date || ''
    brandForm.billing_mode = tenantForm.billing_mode
    brandForm.opening_credit_amount = ''
    brandForm.goods_card_enabled = false
    tenantForm.name = ''
    tenantForm.service_start_date = ''
    tenantForm.service_end_date = ''
    tenantForm.billing_mode = 'hosted'
    tenantForm.opening_credit_amount = ''
    tenantDialog.value = false
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

  async function purgeTenantThoroughly(tenant: TenantInfo) {
    if (!canPurgeTenant()) return
    try {
      const { value } = await ElMessageBox.prompt(
        `将备份后清除「${tenant.name}」的监测历史、品牌配置，并删除该企业下客户账号。此操作不可在界面恢复。请输入企业全称确认：`,
        '彻底删除企业',
        {
          type: 'warning',
          confirmButtonText: '确认彻底删除',
          cancelButtonText: '取消',
          inputPlaceholder: tenant.name,
          inputValidator: (val) => {
            if (!val || val.trim() !== tenant.name.trim()) return '请输入与企业名称完全一致的文字'
            return true
          },
        },
      )
      loadingBrand.value = true
      await purgeTenant(tenant.id, String(value || '').trim())
      if (brandForm.tenant_id === tenant.id) {
        brandForm.tenant_id = null
      }
      await loadEnterpriseList()
      ElMessage.success('企业已彻底删除（已保留备份）')
    } catch (error: unknown) {
      if (error === 'cancel' || error === 'close') return
      notifyError(error, '彻底删除失败')
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
      const restored = await restoreTenant(tenant.id)
      if (isPendingApproval(restored)) {
        const msg = pendingApprovalMessage(restored, '已提交审批，通过后才会恢复服务')
        if (isDuplicateMergedApproval(restored)) ElMessage.warning(msg)
        else ElMessage.info(msg)
        return
      }
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
    if (creatingDraftTenant.value || !brandForm.tenant_id) return
    await saveCompetitorRow(row)
  }

  async function saveCompetitorRow(row: typeof competitorRows.value[number]) {
    if (previewReadonly.value) {
      ElMessage.info('预览模式为只读，不可保存')
      return
    }
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
        if (customerEnterpriseMode) {
          await saveEnterpriseCompetitor(payload)
        } else {
          await updateCompetitor(row.id, payload)
        }
      } else if (customerEnterpriseMode) {
        await saveEnterpriseCompetitor(payload)
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
    if (previewReadonly.value) {
      ElMessage.info('预览模式为只读，不可保存')
      return
    }
    if (!row.id) {
      competitorRows.value.splice(index, 1)
      return
    }
    try {
      await ElMessageBox.confirm('确认移除这个竞品吗？后续提交检测任务将不再带上它。', '移除竞品', { type: 'warning' })
    } catch {
      return
    }
    loadingBrand.value = true
    try {
      if (customerEnterpriseMode) {
        await deleteEnterpriseCompetitor(row.id)
      } else {
        await deleteCompetitor(row.id, brandForm.tenant_id)
      }
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
      const data = await getPlatformsForBrandConfig({ silentError: customerEnterpriseMode })
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
        modes: ['standard', 'reasoning'],
        default_mode: 'standard',
        default_screenshot: 1,
      }))
    }
  }

  function coerceSelectableMode(mode: PlatformSelection['mode'] | string | undefined): PlatformSelection['mode'] {
    if (mode === 'reasoning' || mode === 'reasoning_search') return 'reasoning'
    return 'standard'
  }

  function groupHasPlatform(group: BrandKeywordGroup | BrandWordGroup, code: string) {
    return platformSelectionCodes(group.platforms).includes(code)
  }

  function platformRows(source: 'keywords' | 'brand_words') {
    return source === 'brand_words' ? brandWordGroupRows : keywordGroupRows
  }

  function isMonitorPlatformAllowed(code: string) {
    // 2026-09-04 - 空白名单=不限制；此前 includes 空数组导致点击全灭
    const allow = effectiveMonitorPlatforms.value
    if (!allow.length) return true
    return allow.includes(code)
  }

  function onPlatformCheckClick(groupIndex: number, code: string, source: 'keywords' | 'brand_words' = 'keywords') {
    const rows = platformRows(source)
    const group = rows.value[groupIndex]
    if (!group) return
    // 2026-07-30 - 无平台权限整块隐藏且不可选；仅职位多选内的端可点
    if (!canEditModels.value) return
    if (!isMonitorPlatformAllowed(code)) return
    if (!canEditEnterpriseTab(source === 'brand_words' ? 'brand_words' : 'keywords')) return
    const meta = catalogPlatforms.value.find(item => item.code === code)
    if (groupHasPlatform(group, code)) {
      const current = normalizePlatformSelections(group.platforms).find(item => item.code === code)
      modeDialogTarget.value = { source, groupIndex, code }
      modeDialogForm.mode = coerceSelectableMode(current?.mode || meta?.default_mode)
      modeDialogForm.screenshot = 1
      modeDialogVisible.value = true
      return
    }
    if (meta && !meta.selectable) {
      ElMessage.warning(meta.labels.includes('已下架') ? '该平台已下架，不可勾选' : '该平台暂无服务，不可勾选')
      return
    }
    modeDialogTarget.value = { source, groupIndex, code }
    modeDialogForm.mode = coerceSelectableMode(meta?.default_mode)
    modeDialogForm.screenshot = 1
    modeDialogVisible.value = true
  }

  function removeGroupPlatform(groupIndex: number, code: string, source: 'keywords' | 'brand_words' = 'keywords') {
    const rows = platformRows(source)
    const group = rows.value[groupIndex]
    if (!group || !canEditModels.value) return
    if (!isMonitorPlatformAllowed(code)) return
    if (!canEditEnterpriseTab(source === 'brand_words' ? 'brand_words' : 'keywords')) return
    const next = normalizePlatformSelections(group.platforms).filter(item => item.code !== code)
    rows.value[groupIndex] = { ...group, platforms: next }
  }

  function confirmModeDialog() {
    const target = modeDialogTarget.value
    if (!target || !canEditModels.value) {
      modeDialogVisible.value = false
      modeDialogTarget.value = null
      return
    }
    const rows = platformRows(target.source)
    const group = rows.value[target.groupIndex]
    if (!group) {
      modeDialogVisible.value = false
      modeDialogTarget.value = null
      return
    }
    const next = normalizePlatformSelections(group.platforms).filter(item => item.code !== target.code)
    // 2026-08-11 - 弹窗选「快速」落库为 search；选深度思考落库 reasoning_search
    const saved = normalizePlatformSelection({
      code: target.code,
      mode: modeDialogForm.mode,
      screenshot: 1,
    })
    if (saved) next.push(saved)
    rows.value[target.groupIndex] = { ...group, platforms: next }
    // 2026-09-04 - 确认后偶发弹窗不关 - 先清 target 再关，并 destroy-on-close
    modeDialogTarget.value = null
    modeDialogVisible.value = false
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
    removeGroupPlatform,
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
    creatingDraftTenant,
    tenantForm,
    pendingTenantLogoPreview,
    pendingTenantLogoFileName,
    editingTenantLogoSrc,
    onTenantLogoPick,
    clearPendingTenantLogo,
    tenantTransferDialog,
    tenantTransferTarget,
    tenantTransferOwnerId,
    tenantSalesOwners,
    loadingTenantSalesOwners,
    transferringTenantOwner,
    canTransferTenantOwner,
    canFilterBySales,
    showOwnerOnEnterpriseList,
    tenantSalesFilterOptions,
    knowledgeFiles,
    loadingKnowledgeFiles,
    knowledgePreviewVisible,
    knowledgePreviewFile,
    knowledgePreviewUrl,
    knowledgePreviewLoading,
    knowledgePreviewError,
    canDeleteKnowledgeFiles,
    canUploadKnowledgeFiles,
    uploadingKnowledgeFile,
    knowledgeUploadDialogVisible,
    knowledgeUploadTenant,
    uploadKnowledgeFileToTenant,
    openKnowledgeUploadDialog,
    openEnterpriseDetailFiles,
    handleKnowledgeUploadInput,
    previewKnowledgeFile,
    closeKnowledgePreview,
    downloadKnowledgeFileItem,
    removeKnowledgeFile,
    brandAsset,
    customerEnterpriseMode,
    customerDailyEstimate,
    initCustomerEnterpriseConfig,
    brandCompetitors,
    competitorRows,
    keywordGroupRows,
    brandWordGroupRows,
    competitorNameInput,
    loadingBrand,
    brandForm,
    filteredTenants,
    pagedTenants,
    enterprisePage,
    enterpriseTotalPages,
    changeEnterprisePage,
    isEnterprisePinned,
    pinEnterprise,
    unpinEnterprise,
    enterpriseFormServiceActive,
    brandAssetProfileMissing,
    canSubmitBrandAssetProfile,
    enterpriseFormServiceLabel,
    visibleEnterpriseTabs,
    canViewEnterpriseTab,
    canEditEnterpriseTab,
    canCreateEnterpriseTab,
    canEditRegions,
    canEditModels,
    editableCatalogPlatforms,
    canCreateTenant,
    canEditTenantList,
    isTenantExpired,
    isTenantPending,
    tenantServiceLabel,
    canStopTenantService,
    canRestoreTenantService,
    canPurgeTenant,
    stopTenantActionLabel,
    tenantServicePeriod,
    tenantMonitorLabel,
    tenantBillingLabel,
    tenantOwnerLabel,
    editingGroupIndex,
    editingBrandWordGroupIndex,
    keywordGroupDisplayName,
    brandWordGroupDisplayName,
    startEditGroupName,
    finishEditGroupName,
    cancelEditGroupName,
    startEditBrandWordGroupName,
    finishEditBrandWordGroupName,
    cancelEditBrandWordGroupName,
    addKeywordGroup,
    removeKeywordGroup,
    addBrandWordGroup,
    removeBrandWordGroup,
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
    loadResubmitDraftFromRoute,
    openEnterpriseDetail,
    openEnterpriseInfo,
    backToEnterpriseList,
    submitBrandAsset,
    submitBrandWordGroups,
    goNextFromTenantDialog,
    removeTenant,
    purgeTenantThoroughly,
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
