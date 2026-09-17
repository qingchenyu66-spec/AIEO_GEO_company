<script setup lang="ts">
import { computed, onMounted, provide, ref, watch } from 'vue'
import { defineAsyncPage } from '../utils/reloadOnStaleChunk'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '../stores/auth'
import { useWorkspaceFullscreen } from '../composables/useWorkspaceFullscreen'
import type { MenuInfo } from '../services/auth'
import { getTenants, getPlatformLogoMeta, platformLogoUrl, tenantLogoUrl, type PlatformLogoMeta } from '../services/management'
import { applyDocumentFavicon, DEFAULT_FAVICON } from '../utils/platformFavicon'
import {
  getBrandAsset,
  type BrandAsset, type BrandCompetitor,
} from '../services/brand'
import { withRetry } from '../composables/useRetry'
import PortalLayout from './portal/PortalLayout.vue'
import { useMonitorAnalytics } from './portal/composables/useMonitorAnalytics'
import { usePlatformAdmin } from './portal/composables/usePlatformAdmin'
import { PortalAnalyticsKey, PlatformAdminKey, PortalNavigateKey, WorkspaceFullscreenKey, ApprovalPendingRefreshKey, PlatformBrandLogoTenantKey, PlatformTenantsRefreshKey, PlatformDefaultLogoRefreshKey, PreviewCustomerMenusKey, PreviewCustomerIncludesTodayKey } from './portal/injectionKeys'
import PlatformAdminDialogs from './portal/PlatformAdminDialogs.vue'
import { menuIcon } from './portal/menuIcons'
import {
  USER_CREATE_MENU,
  USER_CREATE_PLATFORM_MENU,
  USER_CREATE_CUSTOMER_MENU,
  USER_LIST_MENU,
  POSITION_MENU,
  CUSTOMER_PREVIEW_MENU,
  SETTINGS_MENU,
  SETTINGS_CHILD_MENUS,
  ENTERPRISE_CONFIG_MENU,
  ENTERPRISE_CHILD_MENUS,
  hiddenCustomerMenus,
  hiddenEnterpriseConfigPermissionMenus,
  hiddenEnterprisePermissionMenus,
  hiddenPlatformMenus,
  hiddenSettingsPermissionMenus,
  hiddenUserPermissionMenus,
  isEnterpriseConfigMenuCode,
  normalizeMenuCode,
} from './portal/constants'
import {
  buildCustomerPortalSidebarMenus,
  isCustomerPreviewActive,
  parsePreviewTenantId,
  parsePreviewTenantName,
  previewQueryFields,
} from './portal/customerPreview'
import { useCustomerPreviewMenus } from './portal/composables/useCustomerPreviewMenus'
import { platformLabelMap, monitorStatusLabelMap } from './portal/portalMaps'
import { usePortalMenu } from './portal/usePortalMenu'
import { useMenuFavorites } from './portal/composables/useMenuFavorites'
import { useApprovalPendingCount } from './portal/composables/useApprovalPendingCount'
import { resolveAccessibleTenantId, shouldPrefetchBrandForMenu } from './portal/tenantQueryScope'
import '../styles/menu-config.css'

const PositionPage = defineAsyncPage(() => import('./portal/PositionPage.vue'))
const PlatformDashboardPage = defineAsyncPage(() => import('./portal/PlatformDashboardPage.vue'))
const UserCreatePage = defineAsyncPage(() => import('./portal/UserCreatePage.vue'))
const UserListPage = defineAsyncPage(() => import('./portal/UserListPage.vue'))
const BrandAuditPage = defineAsyncPage(() => import('./portal/pages/BrandAuditPage.vue'))
const MonitorRealtimePage = defineAsyncPage(() => import('./portal/pages/MonitorRealtimePage.vue'))
const CompetitorAnalysisPage = defineAsyncPage(() => import('./portal/pages/CompetitorAnalysisPage.vue'))
const SourceAnalysisPage = defineAsyncPage(() => import('./portal/pages/SourceAnalysisPage.vue'))
const ReportCenterPage = defineAsyncPage(() => import('./portal/pages/ReportCenterPage.vue'))
const LeadDiagnosisPage = defineAsyncPage(() => import('./portal/pages/LeadDiagnosisPage.vue'))
const H5DiagnosisOrdersPage = defineAsyncPage(() => import('./portal/pages/H5DiagnosisOrdersPage.vue'))
const SnapshotBackfillOpsPage = defineAsyncPage(() => import('./portal/pages/SnapshotBackfillOpsPage.vue'))
const AlertThresholdsPage = defineAsyncPage(() => import('./portal/pages/AlertThresholdsPage.vue'))
const KnowledgeBasePage = defineAsyncPage(() => import('./portal/pages/KnowledgeBasePage.vue'))
const CustomerWorkspacePage = defineAsyncPage(() => import('./portal/pages/CustomerWorkspacePage.vue'))
const CustomerGoodsCardsPage = defineAsyncPage(() => import('./portal/pages/CustomerGoodsCardsPage.vue'))
const BrandAnalysisPage = defineAsyncPage(() => import('./portal/pages/BrandAnalysisPage.vue'))
const ApprovalCenterPage = defineAsyncPage(() => import('./portal/pages/ApprovalCenterPage.vue'))
const AnnouncementManagePage = defineAsyncPage(() => import('./portal/pages/AnnouncementManagePage.vue'))
const FunctionalFeaturePage = defineAsyncPage(() => import('./portal/pages/FunctionalFeaturePage.vue'))
const AnnouncementModal = defineAsyncPage(() => import('./portal/components/AnnouncementModal.vue'))
// 2026-09-08 - 算力运营 / 企业配置（credit）页挂载
const CreditOpsPage = defineAsyncPage(() => import('./portal/pages/CreditOpsPage.vue'))
const EnterpriseConfigPage = defineAsyncPage(() => import('./portal/pages/EnterpriseConfigPage.vue'))

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()
const isPlatform = computed(() => auth.session?.identity?.identity_type === 'PLATFORM')
const isPreviewActive = computed(() => isCustomerPreviewActive(route, isPlatform.value))
const previewTenantId = computed(() => parsePreviewTenantId(route))
const previewTenantName = computed(() => parsePreviewTenantName(route))
const {
  previewCustomerMenus,
  previewCustomerIncludesToday,
  previewMenusLoading,
  previewMenusError,
  reloadPreviewCustomerMenus,
} = useCustomerPreviewMenus(isPreviewActive, previewTenantId)
provide(PreviewCustomerMenusKey, previewCustomerMenus)
provide(PreviewCustomerIncludesTodayKey, previewCustomerIncludesToday)
const defaultMenuCode = normalizeMenuCode(auth.allowedMenus[0]?.menu_code || '')

/** 预览主区：菜单未就绪时不挂业务页，避免空权限连锁报错 */
const previewMenusReady = computed(() => (
  !isPreviewActive.value || previewCustomerMenus.value.length > 0
))
const previewMenusBlocked = computed(() => (
  isPreviewActive.value && !previewMenusReady.value
))

function userCreateRouteAllowed(menus: MenuInfo[]) {
  return menus.some(menu => (
    (menu.menu_code === USER_CREATE_PLATFORM_MENU || menu.menu_code === USER_CREATE_CUSTOMER_MENU)
    && menu.can_create
  ))
}

function auditRouteAllowed(menus: MenuInfo[]) {
  return menus.some(menu => (
    menu.menu_code.startsWith('platform.audit.')
    && (menu.can_export || menu.can_update || menu.can_create || menu.can_delete)
  ))
}

function sortSidebarMenus(list: MenuInfo[]) {
  return [...list].sort((a, b) => a.sort_order - b.sort_order || a.id - b.id)
}

function withSyntheticSidebarMenu(list: MenuInfo[], extra: MenuInfo) {
  if (list.some(menu => menu.menu_code === extra.menu_code)) return list
  return sortSidebarMenus([...list, extra])
}

function settingsRouteAllowed(menus: MenuInfo[]) {
  return menus.some(menu => (
    (menu.menu_code === SETTINGS_MENU || SETTINGS_CHILD_MENUS.includes(menu.menu_code as typeof SETTINGS_CHILD_MENUS[number]))
    && (menu.can_export || menu.can_update)
  ))
}

const allowedMenuCodes = computed(() => {
  if (isPreviewActive.value) {
    // 只认接口菜单；加载中为空，导航靠 isCustomerPreviewMenuCode 放行，禁止硬编码名兜底
    return previewCustomerMenus.value.map(item => item.menu_code)
  }
  const codes = auth.allowedMenus.map(item => item.menu_code)
  const extra: string[] = []
  if (userCreateRouteAllowed(auth.allowedMenus) && !codes.includes(USER_CREATE_MENU)) {
    extra.push(USER_CREATE_MENU)
  }
  if (auditRouteAllowed(auth.allowedMenus) && !codes.includes('platform.audit')) {
    extra.push('platform.audit')
  }
  if (settingsRouteAllowed(auth.allowedMenus) && !codes.includes(SETTINGS_MENU)) {
    extra.push(SETTINGS_MENU)
  }
  return extra.length ? [...codes, ...extra] : codes
})
const { activeMenuCode, navigateToMenu, isMenuBlocked } = usePortalMenu(
  router,
  route,
  defaultMenuCode,
  allowedMenuCodes,
  isPlatform,
)
provide(PortalNavigateKey, navigateToMenu)
const userMenuExpanded = ref(activeMenuCode.value.startsWith('platform.users') || activeMenuCode.value === POSITION_MENU)
const brandAuditRef = ref<{ resetDetailMode?: () => void } | null>(null)

const menus = computed(() => {
  // 预览侧栏只展示接口菜单；未返回前空着，绝不硬编码兜底名
  if (isPreviewActive.value) {
    return buildCustomerPortalSidebarMenus(previewCustomerMenus.value)
  }
  const filtered = auth.allowedMenus
    .filter(menu => menu.show_in_sidebar !== false)
    .filter(menu => ![USER_CREATE_MENU, USER_LIST_MENU, POSITION_MENU, 'customer.assets', ...hiddenCustomerMenus, ...hiddenPlatformMenus, ...hiddenEnterprisePermissionMenus, ...hiddenEnterpriseConfigPermissionMenus, ...hiddenUserPermissionMenus, ...hiddenSettingsPermissionMenus].includes(menu.menu_code))
  if (auditRouteAllowed(auth.allowedMenus) && !filtered.some(menu => menu.menu_code === 'platform.audit')) {
    const auditChild = auth.allowedMenus.find(menu => menu.menu_code.startsWith('platform.audit.'))
    if (auditChild) {
      return withSyntheticSidebarMenu(filtered, {
        ...auditChild,
        menu_code: 'platform.audit',
        menu_name: '企业管理',
        show_in_sidebar: true,
      })
    }
  }
  if (settingsRouteAllowed(auth.allowedMenus) && !filtered.some(menu => menu.menu_code === SETTINGS_MENU)) {
    const settingsChild = auth.allowedMenus.find(menu => SETTINGS_CHILD_MENUS.includes(menu.menu_code as typeof SETTINGS_CHILD_MENUS[number]))
    if (settingsChild) {
      return withSyntheticSidebarMenu(filtered, {
        ...settingsChild,
        menu_code: SETTINGS_MENU,
        menu_name: '系统配置',
        show_in_sidebar: true,
        sort_order: 90,
      })
    }
  }
  return filtered
})
const sessionUserId = computed(() => auth.session?.user?.id)
const sessionIdentityId = computed(() => auth.session?.identity?.id)
const menuFavoritesEnabled = computed(() => !isPreviewActive.value)
const {
  isMenuPinned,
  toggleMenuPin,
  displayMenus,
  pinnedMenuCount,
} = useMenuFavorites(sessionUserId, sessionIdentityId, menus, menuFavoritesEnabled)
const userManagementMenu = computed(() => displayMenus.value.find(item => item.menu_code === 'platform.users'))

const isRealtimeMonitorPage = computed(() => activeMenuCode.value === 'customer.realtime')
const isGoodsCardsPage = computed(() => activeMenuCode.value === 'customer.goods_cards')
const isCompetitorPage = computed(() => ['customer.competitor', 'platform.competitor'].includes(activeMenuCode.value))
const isSourcePage = computed(() => ['customer.sources', 'platform.sources'].includes(activeMenuCode.value))
const isReportCenterPage = computed(() => ['customer.reports', 'platform.reports'].includes(activeMenuCode.value))
const isLeadDiagnosisPage = computed(() => activeMenuCode.value === 'platform.lead_diagnosis')
const isH5DiagnosisOrdersPage = computed(() => activeMenuCode.value === 'platform.h5_diagnosis_orders')
const isSnapshotBackfillPage = computed(() => activeMenuCode.value === 'platform.snapshot_backfill')
const isAlertThresholdsPage = computed(() => activeMenuCode.value === 'platform.alerts')
const isKnowledgePage = computed(() => activeMenuCode.value === 'customer.knowledge')
const isBrandAssetPage = computed(() => activeMenuCode.value === 'platform.audit')
const isApprovalPage = computed(() => activeMenuCode.value === 'platform.approvals')
const isAnnouncementPage = computed(() => activeMenuCode.value === 'platform.announcements')
const isCustomerWorkspacePage = computed(() => activeMenuCode.value === 'customer.workspace')
const isBrandAnalysisPage = computed(() => activeMenuCode.value === 'customer.brand_analysis')
const isCreditOpsPage = computed(() => activeMenuCode.value === 'platform.credit_ops_board')
const isEnterpriseConfigPage = computed(() => isEnterpriseConfigMenuCode(activeMenuCode.value))
/** 侧栏高亮父级；子项仅作页内 Tab / deep-link */
const sidebarActiveMenuCode = computed(() => (
  (ENTERPRISE_CHILD_MENUS as readonly string[]).includes(activeMenuCode.value)
    ? ENTERPRISE_CONFIG_MENU
    : activeMenuCode.value
))
const isDashboardPage = computed(() => ['platform.dashboard', 'customer.workspace'].includes(activeMenuCode.value))

// 2026-09-08 - zero 仍解析，CreditOpsPage 映射到概览+仅零余额
function parseCreditOpsQueryTab(): 'overview' | 'recharge' | 'blocks' | 'zero' | 'pricing' | 'mode' | undefined {
  const raw = route.query.credit_tab
  const text = Array.isArray(raw) ? raw[0] : raw
  if (text === 'overview' || text === 'recharge' || text === 'blocks' || text === 'zero' || text === 'pricing' || text === 'mode') return text
  return undefined
}

function parseCreditOpsQueryTenantId(): number | undefined {
  const raw = route.query.tenant_id
  const text = Array.isArray(raw) ? raw[0] : raw
  const parsed = Number(text)
  return Number.isFinite(parsed) && parsed > 0 ? parsed : undefined
}

function parseCreditOpsQueryBlockTab(): 'tenant_credit' | 'platform_balance' | 'terms' | 'inactive' | 'daily_cap' | undefined {
  // 2026-09-09 - 旧 book_tab/block_tab 仍接受，CreditOps 一律进合并「提交拦截」
  const raw = route.query.block_tab
  const text = Array.isArray(raw) ? raw[0] : raw
  if (
    text === 'tenant_credit'
    || text === 'platform_balance'
    || text === 'terms'
    || text === 'inactive'
    || text === 'daily_cap'
  ) {
    return text
  }
  return undefined
}

const workspaceFullscreen = useWorkspaceFullscreen()
provide(WorkspaceFullscreenKey, workspaceFullscreen)

const portalFullscreen = computed(() => isCustomerWorkspacePage.value && workspaceFullscreen.isFullscreen.value)

watch(activeMenuCode, code => {
  if (code !== 'customer.workspace') {
    void workspaceFullscreen.exit()
  }
  if (code === 'platform.approvals') {
    void refreshPendingCount()
  }
})

const brandAsset = ref<BrandAsset | null>(null)
const brandCompetitors = ref<BrandCompetitor[]>([])

const platformAdmin = usePlatformAdmin({ auth, isPlatform, activeMenuCode, userMenuExpanded, navigateToMenu })
provide(PlatformAdminKey, platformAdmin)

const {
  tenants,
  isUserCreatePage,
  isUserListPage,
  isPositionManagementPage,
  creatableIdentityTypes,
  identityDisplayName,
  openMenuConfigDialog,
  errorMessage,
  notifyError,
} = platformAdmin

const hasUserCreateMenu = computed(() => creatableIdentityTypes.value.length > 0)
const hasUserListMenu = computed(() => auth.allowedMenus.some(item => item.menu_code === USER_LIST_MENU || item.menu_code === 'platform.users'))
const hasPositionMenu = computed(() => auth.allowedMenus.some(item => item.menu_code === POSITION_MENU))
const hasApprovalMenu = computed(() => auth.allowedMenus.some(item => item.menu_code === 'platform.approvals'))

const { pendingCount: pendingApprovalCount, refreshPendingCount } = useApprovalPendingCount(
  () => isPlatform.value && hasApprovalMenu.value,
)
provide(ApprovalPendingRefreshKey, refreshPendingCount)

const activeMenu = computed(() => {
  const userMenu = userManagementMenu.value
  if (isUserCreatePage.value && userMenu) return { ...userMenu, menu_code: USER_CREATE_MENU, menu_name: '用户新增' } as MenuInfo
  if (isUserListPage.value && userMenu) return { ...userMenu, menu_code: USER_LIST_MENU, menu_name: '用户列表' } as MenuInfo
  if (isPositionManagementPage.value) return { ...(userManagementMenu.value || displayMenus.value[0]), menu_code: POSITION_MENU, menu_name: '职位管理' } as MenuInfo
  return menus.value.find(item => item.menu_code === activeMenuCode.value) || menus.value[0]
})

const portalAnalytics = useMonitorAnalytics({
  activeMenuCode,
  isPlatform,
  isDashboardPage,
  brandAsset,
  brandCompetitors,
  tenants,
  notifyError,
  errorMessage,
})
provide(PortalAnalyticsKey, portalAnalytics)

const pageTitle = computed(() => {
  if (previewMenusBlocked.value) {
    return previewMenusError.value ? '预览菜单加载失败' : '正在加载客户菜单'
  }
  if (isEnterpriseConfigPage.value) return '企业配置'
  return activeMenu.value?.menu_name || (isPlatform.value ? '平台运营总览' : '客户运营工作台')
})
const pageSubtitle = computed(() => {
  if (isPreviewActive.value) {
    return `只读预览「${previewTenantName.value || '客户'}」门户，可切换左侧菜单核对客户可见数据`
  }
  if (isUserCreatePage.value) return '创建账号、分配身份、绑定所属企业，并配置可访问菜单'
  if (isUserListPage.value) return '按公司、姓名、身份和状态筛选账号，支持编辑、禁用、重置密码和恢复'
  if (isPositionManagementPage.value) return '维护运营、销售、交付等职位模板，新增人员时从职位库选择'
  if (isLeadDiagnosisPage.value) return '为潜在客户创建诊断：三时段自动抓取全平台数据，汇总后下载 HTML 发给客户'
  if (isH5DiagnosisOrdersPage.value) return 'H5 付费诊断订单：支付状态、金额与关联售前诊断'
  if (isSnapshotBackfillPage.value) return '粘贴 AI 分享链接，自动解析正文与信源并重算排名'
  if (isApprovalPage.value) {
    return '审核销售提交的用户、企业、报告与诊断操作；通过后才会真正生效'
  }
  // 2026-07-31 - 企业管理页副文案像运营总览 - 改为贴列表能力
  if (isBrandAssetPage.value) return '管理客户企业、服务状态与监测配置'
  if (isCreditOpsPage.value) return '算力企业余额、充扣、拦截与平台侧流水'
  if (isEnterpriseConfigPage.value) return '监测配置、成员权限、算力与操作记录'
  if (activeMenuCode.value === 'platform.logs') return '审计用户、企业、任务、权限和导出操作'
  if (activeMenuCode.value === 'platform.settings') return '基础参数、调度策略、菜单权限和安全配置'
  if (activeMenuCode.value === 'platform.models') return '展示系统支持的监测平台，以及今日各平台探测成功/失败条数。'
  if (activeMenuCode.value === 'customer.brand_analysis') {
    return '基于已购平台样本的文字诊断：提及率、短板、AI 描述与分端表现'
  }
  // 2026-07-30 - 顶栏副文案全局一句像没换页 - 仅 GEO/竞品/信源/报告/知识库按页区分
  const customerPageSubtitles: Record<string, string> = {
    'customer.realtime': '按平台与问题查看监测结果与推荐排名',
    'customer.goods_cards': '日常监测词的 AI 商品卡出卡与本品/竞品货架',
    'customer.competitor': '本品牌与竞品的提及率、首位提及与情绪对比',
    'customer.sources': '引用来源结构、官网占比与高频站点',
    'customer.reports': '预览与导出已发布的周期监测报告',
    'customer.knowledge': '归档品牌资料，供报告引用与团队共享',
  }
  if (customerPageSubtitles[activeMenuCode.value]) {
    return customerPageSubtitles[activeMenuCode.value]
  }
  return isPlatform.value ? '企业运营、任务消耗、平台运行与风险情况' : '品牌曝光、推荐排名、信源分析与监测趋势'
})

function exitCustomerPreview() {
  navigateToMenu('platform.audit')
}

function parseRouteTenantId(): number | null {
  const previewId = parsePreviewTenantId(route)
  if (previewId != null) return previewId
  const raw = route.query.tenant_id
  const text = Array.isArray(raw) ? raw[0] : raw
  const parsed = Number(text)
  return Number.isFinite(parsed) ? parsed : null
}

const platformBrandLogoTenantId = ref<number | null>(null)
provide(PlatformBrandLogoTenantKey, platformBrandLogoTenantId)

const effectiveTenantIdForLogo = computed(() => {
  if (isPreviewActive.value) return parsePreviewTenantId(route)
  if (!isPlatform.value) return auth.session?.identity?.tenant_id ?? null
  return parseRouteTenantId() ?? platformBrandLogoTenantId.value
})

async function ensureTenantsForLogo() {
  if (!isPlatform.value) return
  const tenantId = effectiveTenantIdForLogo.value
  if (!tenantId) return
  try {
    tenants.value = await withRetry(() => getTenants())
  } catch {
    /* 侧栏 Logo 失败时回退默认亦智图标 */
  }
}

provide(PlatformTenantsRefreshKey, ensureTenantsForLogo)

const platformLogoMeta = ref<PlatformLogoMeta>({ has_logo: false, logo_updated_at: null })

async function refreshPlatformDefaultLogo() {
  try {
    platformLogoMeta.value = await getPlatformLogoMeta()
  } catch {
    platformLogoMeta.value = { has_logo: false, logo_updated_at: null }
  }
}

provide(PlatformDefaultLogoRefreshKey, refreshPlatformDefaultLogo)

const brandLogoSrc = computed(() => {
  const tenantId = effectiveTenantIdForLogo.value
  if (tenantId) {
    if (!isPlatform.value) {
      if (auth.session?.identity?.tenant_has_logo) {
        return tenantLogoUrl(tenantId, auth.session.identity.tenant_logo_updated_at)
      }
    } else {
      const tenant = tenants.value.find(item => item.id === tenantId)
      if (tenant?.has_logo) return tenantLogoUrl(tenantId, tenant.logo_updated_at)
      // 2026-08-24 - 品牌审核编辑页无 query.tenant_id，刚上传后列表可能未刷新，仍尝试拉取
      if (platformBrandLogoTenantId.value === tenantId) {
        return tenantLogoUrl(tenantId, tenant?.logo_updated_at)
      }
    }
  }
  if (platformLogoMeta.value.has_logo) {
    return platformLogoUrl(platformLogoMeta.value.logo_updated_at)
  }
  return undefined
})

watch(
  brandLogoSrc,
  src => {
    applyDocumentFavicon(src || DEFAULT_FAVICON)
  },
  { immediate: true },
)

function shouldPrefetchBrandAsset() {
  // Brand audit / realtime load their own asset. Reports & admin pages must not hit /brand/asset.
  return shouldPrefetchBrandForMenu(activeMenuCode.value)
}

async function loadBrandAssetData() {
  if (!shouldPrefetchBrandAsset()) return
  try {
    let tenantId: number | null = null
    if (isPlatform.value) {
      if (!tenants.value.length) {
        tenants.value = await withRetry(() => getTenants())
      }
      // Never send a sticky URL tenant the account cannot access (sales ownership).
      tenantId = resolveAccessibleTenantId(
        parseRouteTenantId(),
        tenants.value.map(item => item.id),
      )
      if (!tenantId) {
        brandAsset.value = null
        brandCompetitors.value = []
        return
      }
    }
    const response = await withRetry(() => getBrandAsset(tenantId))
    brandAsset.value = response.asset
    brandCompetitors.value = response.competitors
  } catch (error: unknown) {
    notifyError(error, '品牌资产加载失败')
  }
}

function onBrandUpdated(asset: BrandAsset | null, competitors: BrandCompetitor[]) {
  brandAsset.value = asset
  brandCompetitors.value = competitors
}

async function switchIdentity(identityId: number) {
  if (identityId === auth.session?.identity.id) return
  try {
    await auth.switchIdentity(identityId)
    activeMenuCode.value = normalizeMenuCode(auth.allowedMenus[0]?.menu_code || '')
    userMenuExpanded.value = activeMenuCode.value.startsWith('platform.users') || activeMenuCode.value === POSITION_MENU
    ElMessage.success(`已切换至${identityDisplayName(auth.session?.identity)}`)
    await router.replace(auth.portalPath)
  } catch (error: unknown) {
    notifyError(error, '身份切换失败')
  }
}

function selectMenu(menu: MenuInfo) {
  navigateToMenu(menu.menu_code)
  userMenuExpanded.value = menu.menu_code === 'platform.users'
}

function toggleUserSubmenu() {
  userMenuExpanded.value = !userMenuExpanded.value
}

function ensureActiveMenuAllowed() {
  if (isPreviewActive.value) {
    const code = activeMenuCode.value
    if (code === CUSTOMER_PREVIEW_MENU) {
      navigateToMenu('customer.workspace', true, previewQueryFields(
        parsePreviewTenantId(route)!,
        parsePreviewTenantName(route),
      ))
      return
    }
    const codes = previewCustomerMenus.value.map(item => item.menu_code)
    // 菜单尚未拉回：先别改路由，避免空列表时乱跳
    if (!codes.length) return
    if (codes.includes(code)) return
    navigateToMenu('customer.workspace', true, previewQueryFields(
      parsePreviewTenantId(route)!,
      parsePreviewTenantName(route),
    ))
    return
  }
  const allowedCodes = allowedMenuCodes.value.map(code => normalizeMenuCode(code))
  if (isMenuBlocked(activeMenuCode.value) || !allowedCodes.includes(activeMenuCode.value)) {
    navigateToMenu(normalizeMenuCode(allowedMenuCodes.value[0] || auth.allowedMenus[0]?.menu_code || ''), true)
  }
  userMenuExpanded.value = activeMenuCode.value.startsWith('platform.users') || activeMenuCode.value === POSITION_MENU
}

async function refreshMenusFromServer() {
  try {
    await auth.refreshSession()
    ensureActiveMenuAllowed()
  } catch (error: unknown) {
    const status = (error as { response?: { status?: number } })?.response?.status
    // 2026-09-02 - /me 500 被当成会话失效 - 登录成功又踢回登录叠三条 toast；仅 401 才清会话
    if (status === 401) {
      ElMessage.warning('会话已失效，请重新登录')
      await auth.logout()
      await router.replace('/login')
      return
    }
  }
}

async function logout() {
  await auth.logout()
  await router.replace('/login')
}

watch(activeMenuCode, (newCode, oldCode) => {
  if (newCode === 'platform.diagnosis' && oldCode !== 'platform.diagnosis') {
    navigateToMenu('platform.competitor', true)
    ElMessage.info('品牌诊断已并入「品牌洞察」，已为您跳转')
    return
  }
  if (oldCode === 'platform.audit' && newCode !== 'platform.audit') {
    brandAuditRef.value?.resetDetailMode?.()
  }
  void loadBrandAssetData()
})
watch(() => route.query.tenant_id, () => {
  if (isPlatform.value) void loadBrandAssetData()
})
onMounted(refreshMenusFromServer)
onMounted(() => {
  void loadBrandAssetData()
  void ensureTenantsForLogo()
  // 2026-09-08 - 进门户就拉平台默认 Logo；此前只在系统配置保存后刷新，整页刷新侧栏会回退内置标
  void refreshPlatformDefaultLogo()
})
watch(previewCustomerMenus, () => {
  if (isPreviewActive.value) ensureActiveMenuAllowed()
})
watch(effectiveTenantIdForLogo, () => {
  void ensureTenantsForLogo()
})
</script>

<template>
  <PortalLayout
    :is-platform="isPlatform"
    :menus="displayMenus"
    :pinned-menu-count="pinnedMenuCount"
    :menu-favorites-enabled="menuFavoritesEnabled"
    :is-menu-pinned="isMenuPinned"
    :active-menu-code="sidebarActiveMenuCode"
    :user-menu-expanded="userMenuExpanded"
    :has-user-create-menu="hasUserCreateMenu"
    :has-user-list-menu="hasUserListMenu"
    :has-position-menu="hasPositionMenu"
    :page-title="pageTitle"
    :page-subtitle="pageSubtitle"
    :identity-display-name="identityDisplayName"
    :portal-identity-name="isPreviewActive ? (previewTenantName || '客户预览') : identityDisplayName(auth.session?.identity)"
    :portal-identity-subtitle="isPreviewActive ? '只读预览客户门户' : (auth.session?.identity?.tenant_name || 'GEO Monitor 平台')"
    :session-user-name="auth.session?.user.display_name || ''"
    :session-username="auth.session?.user.username || ''"
    :session-display-initial="auth.session?.user.display_name?.slice(0, 1) || ''"
    :identity-count="isPreviewActive ? 0 : (auth.session?.identities.length || 0)"
    :identities="isPreviewActive ? [] : (auth.session?.identities || [])"
    :current-identity-id="auth.session?.identity?.id"
    :immersive="isCustomerWorkspacePage"
    :fullscreen="portalFullscreen"
    :menu-icon="menuIcon"
    :pending-approval-count="pendingApprovalCount"
    :preview-mode="isPreviewActive"
    :brand-logo-src="brandLogoSrc"
    @toggle-user-submenu="toggleUserSubmenu"
    @toggle-menu-pin="toggleMenuPin"
    @select-menu="selectMenu"
    @set-menu-code="navigateToMenu"
    @switch-identity="switchIdentity"
    @logout="logout"
    @open-alerts="navigateToMenu('platform.alerts', true)"
    @exit-preview="exitCustomerPreview"
  >
    <div v-if="previewMenusBlocked" class="mini-empty preview-menus-gate">
      <p v-if="previewMenusLoading && !previewMenusError">正在加载客户菜单…</p>
      <template v-else>
        <p>{{ previewMenusError || '客户菜单暂不可用' }}</p>
        <div class="action-buttons" style="justify-content: center; margin-top: 12px">
          <button type="button" class="plain-btn" @click="exitCustomerPreview">返回企业管理</button>
          <button type="button" class="primary-btn" @click="reloadPreviewCustomerMenus">重试</button>
        </div>
      </template>
    </div>

    <template v-else>
    <PositionPage v-if="isPositionManagementPage" />

    <UserCreatePage v-else-if="isUserCreatePage" />

    <UserListPage v-else-if="isUserListPage" />

    <BrandAuditPage v-else-if="isBrandAssetPage" ref="brandAuditRef" @brand-updated="onBrandUpdated" />
    <MonitorRealtimePage v-else-if="isRealtimeMonitorPage" />
    <CustomerGoodsCardsPage v-else-if="isGoodsCardsPage" />
    <CompetitorAnalysisPage v-else-if="isCompetitorPage" />
    <SourceAnalysisPage v-else-if="isSourcePage" />
    <ReportCenterPage v-else-if="isReportCenterPage" :is-platform="isPlatform && !isPreviewActive" />
    <LeadDiagnosisPage v-else-if="isLeadDiagnosisPage" />
    <H5DiagnosisOrdersPage v-else-if="isH5DiagnosisOrdersPage" />
    <SnapshotBackfillOpsPage v-else-if="isSnapshotBackfillPage" />
    <AlertThresholdsPage v-else-if="isAlertThresholdsPage" />
    <KnowledgeBasePage v-else-if="isKnowledgePage" />
    <BrandAnalysisPage v-else-if="isBrandAnalysisPage" />
    <ApprovalCenterPage v-else-if="isApprovalPage" />
    <AnnouncementManagePage v-else-if="isAnnouncementPage" />
    <CreditOpsPage
      v-else-if="isCreditOpsPage"
      :initial-tab="parseCreditOpsQueryTab()"
      :initial-tenant-id="parseCreditOpsQueryTenantId()"
      :initial-block-tab="parseCreditOpsQueryBlockTab()"
    />
    <EnterpriseConfigPage
      v-else-if="isEnterpriseConfigPage"
      :preview-readonly="isPreviewActive"
      :initial-tab="activeMenuCode"
    />

    <template v-else>
      <template v-if="isDashboardPage">
        <CustomerWorkspacePage v-if="isCustomerWorkspacePage" />
        <PlatformDashboardPage
          v-else-if="isPlatform"
          :platform-label-map="platformLabelMap"
          :monitor-status-label-map="monitorStatusLabelMap"
          :navigate-to="navigateToMenu"
        />
        <CustomerWorkspacePage v-else />
      </template>
      <FunctionalFeaturePage v-else @open-menu-config="openMenuConfigDialog" />
    </template>
    </template>
  </PortalLayout>

  <AnnouncementModal />
  <PlatformAdminDialogs />
</template>
