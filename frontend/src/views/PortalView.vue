<script setup lang="ts">
import { computed, defineAsyncComponent, onMounted, provide, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '../stores/auth'
import { useWorkspaceFullscreen } from '../composables/useWorkspaceFullscreen'
import type { MenuInfo } from '../services/auth'
import { getTenants } from '../services/management'
import {
  getBrandAsset,
  type BrandAsset, type BrandCompetitor,
} from '../services/brand'
import { withRetry } from '../composables/useRetry'
import PortalLayout from './portal/PortalLayout.vue'
import { useMonitorAnalytics } from './portal/composables/useMonitorAnalytics'
import { usePlatformAdmin } from './portal/composables/usePlatformAdmin'
import { PortalAnalyticsKey, PlatformAdminKey, PortalNavigateKey, WorkspaceFullscreenKey, ApprovalPendingRefreshKey } from './portal/injectionKeys'
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
  hiddenCustomerMenus,
  hiddenEnterprisePermissionMenus,
  hiddenPlatformMenus,
  hiddenSettingsPermissionMenus,
  hiddenUserPermissionMenus,
  normalizeMenuCode,
} from './portal/constants'
import {
  CUSTOMER_PREVIEW_MENUS,
  CUSTOMER_PREVIEW_MENU_CODES,
  isCustomerPreviewActive,
  parsePreviewTenantId,
  parsePreviewTenantName,
  previewQueryFields,
} from './portal/customerPreview'
import { platformLabelMap, monitorStatusLabelMap } from './portal/portalMaps'
import { usePortalMenu } from './portal/usePortalMenu'
import { useApprovalPendingCount } from './portal/composables/useApprovalPendingCount'
import { resolveAccessibleTenantId, shouldPrefetchBrandForMenu } from './portal/tenantQueryScope'
import '../styles/menu-config.css'

const PositionPage = defineAsyncComponent(() => import('./portal/PositionPage.vue'))
const PlatformDashboardPage = defineAsyncComponent(() => import('./portal/PlatformDashboardPage.vue'))
const UserCreatePage = defineAsyncComponent(() => import('./portal/UserCreatePage.vue'))
const UserListPage = defineAsyncComponent(() => import('./portal/UserListPage.vue'))
const BrandAuditPage = defineAsyncComponent(() => import('./portal/pages/BrandAuditPage.vue'))
const MonitorRealtimePage = defineAsyncComponent(() => import('./portal/pages/MonitorRealtimePage.vue'))
const CompetitorAnalysisPage = defineAsyncComponent(() => import('./portal/pages/CompetitorAnalysisPage.vue'))
const SourceAnalysisPage = defineAsyncComponent(() => import('./portal/pages/SourceAnalysisPage.vue'))
const ReportCenterPage = defineAsyncComponent(() => import('./portal/pages/ReportCenterPage.vue'))
const LeadDiagnosisPage = defineAsyncComponent(() => import('./portal/pages/LeadDiagnosisPage.vue'))
const SnapshotBackfillOpsPage = defineAsyncComponent(() => import('./portal/pages/SnapshotBackfillOpsPage.vue'))
const AlertThresholdsPage = defineAsyncComponent(() => import('./portal/pages/AlertThresholdsPage.vue'))
const KnowledgeBasePage = defineAsyncComponent(() => import('./portal/pages/KnowledgeBasePage.vue'))
const CustomerWorkspacePage = defineAsyncComponent(() => import('./portal/pages/CustomerWorkspacePage.vue'))
const BrandAnalysisPage = defineAsyncComponent(() => import('./portal/pages/BrandAnalysisPage.vue'))
const ApprovalCenterPage = defineAsyncComponent(() => import('./portal/pages/ApprovalCenterPage.vue'))
const AnnouncementManagePage = defineAsyncComponent(() => import('./portal/pages/AnnouncementManagePage.vue'))
const FunctionalFeaturePage = defineAsyncComponent(() => import('./portal/pages/FunctionalFeaturePage.vue'))
const AnnouncementModal = defineAsyncComponent(() => import('./portal/components/AnnouncementModal.vue'))

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()
const isPlatform = computed(() => auth.session?.identity?.identity_type === 'PLATFORM')
const isPreviewActive = computed(() => isCustomerPreviewActive(route, isPlatform.value))
const previewTenantName = computed(() => parsePreviewTenantName(route))
const defaultMenuCode = normalizeMenuCode(auth.allowedMenus[0]?.menu_code || '')

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

function settingsRouteAllowed(menus: MenuInfo[]) {
  return menus.some(menu => (
    (menu.menu_code === SETTINGS_MENU || SETTINGS_CHILD_MENUS.includes(menu.menu_code as typeof SETTINGS_CHILD_MENUS[number]))
    && (menu.can_export || menu.can_update)
  ))
}

const allowedMenuCodes = computed(() => {
  if (isPreviewActive.value) {
    return [...CUSTOMER_PREVIEW_MENU_CODES]
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
  if (isPreviewActive.value) {
    return CUSTOMER_PREVIEW_MENUS
  }
  const filtered = auth.allowedMenus
    .filter(menu => ![USER_CREATE_MENU, USER_LIST_MENU, POSITION_MENU, 'customer.assets', ...hiddenCustomerMenus, ...hiddenPlatformMenus, ...hiddenEnterprisePermissionMenus, ...hiddenUserPermissionMenus, ...hiddenSettingsPermissionMenus].includes(menu.menu_code))
  if (auditRouteAllowed(auth.allowedMenus) && !filtered.some(menu => menu.menu_code === 'platform.audit')) {
    const auditChild = auth.allowedMenus.find(menu => menu.menu_code.startsWith('platform.audit.'))
    if (auditChild) {
      return [{ ...auditChild, menu_code: 'platform.audit', menu_name: '企业管理' }, ...filtered]
    }
  }
  if (settingsRouteAllowed(auth.allowedMenus) && !filtered.some(menu => menu.menu_code === SETTINGS_MENU)) {
    const settingsChild = auth.allowedMenus.find(menu => SETTINGS_CHILD_MENUS.includes(menu.menu_code as typeof SETTINGS_CHILD_MENUS[number]))
    if (settingsChild) {
      return [{ ...settingsChild, menu_code: SETTINGS_MENU, menu_name: '系统配置' }, ...filtered]
    }
  }
  return filtered
})
const userManagementMenu = computed(() => menus.value.find(item => item.menu_code === 'platform.users'))

const isRealtimeMonitorPage = computed(() => activeMenuCode.value === 'customer.realtime')
const isCompetitorPage = computed(() => ['customer.competitor', 'platform.competitor'].includes(activeMenuCode.value))
const isSourcePage = computed(() => ['customer.sources', 'platform.sources'].includes(activeMenuCode.value))
const isReportCenterPage = computed(() => ['customer.reports', 'platform.reports'].includes(activeMenuCode.value))
const isLeadDiagnosisPage = computed(() => activeMenuCode.value === 'platform.lead_diagnosis')
const isSnapshotBackfillPage = computed(() => activeMenuCode.value === 'platform.snapshot_backfill')
const isAlertThresholdsPage = computed(() => activeMenuCode.value === 'platform.alerts')
const isKnowledgePage = computed(() => activeMenuCode.value === 'customer.knowledge')
const isBrandAssetPage = computed(() => activeMenuCode.value === 'platform.audit')
const isApprovalPage = computed(() => activeMenuCode.value === 'platform.approvals')
const isAnnouncementPage = computed(() => activeMenuCode.value === 'platform.announcements')
const isCustomerWorkspacePage = computed(() => activeMenuCode.value === 'customer.workspace')
const isBrandAnalysisPage = computed(() => activeMenuCode.value === 'customer.brand_analysis')
const isDashboardPage = computed(() => ['platform.dashboard', 'customer.workspace'].includes(activeMenuCode.value))

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
  if (isPositionManagementPage.value) return { ...(userManagementMenu.value || menus.value[0]), menu_code: POSITION_MENU, menu_name: '职位管理' } as MenuInfo
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

const pageTitle = computed(() => activeMenu.value?.menu_name || (isPlatform.value ? '平台运营总览' : '客户运营工作台'))
const pageSubtitle = computed(() => {
  if (isPreviewActive.value) {
    return `只读预览「${previewTenantName.value || '客户'}」门户，可切换左侧菜单核对客户可见数据`
  }
  if (isUserCreatePage.value) return '创建账号、分配身份、绑定所属企业，并配置可访问菜单'
  if (isUserListPage.value) return '按公司、姓名、身份和状态筛选账号，支持编辑、禁用、重置密码和恢复'
  if (isPositionManagementPage.value) return '维护运营、销售、交付等职位模板，新增人员时从职位库选择'
  if (isLeadDiagnosisPage.value) return '为潜在客户创建诊断：三时段自动抓取全平台数据，汇总后导出 PDF 发给客户'
  if (isSnapshotBackfillPage.value) return '粘贴 AI 分享链接，自动解析正文与信源并重算排名'
  if (isApprovalPage.value) {
    return '审核销售提交的用户、企业、报告与诊断操作；通过后才会真正生效'
  }
  // 2026-07-31 - 企业管理页副文案像运营总览 - 改为贴列表能力
  if (isBrandAssetPage.value) return '管理客户企业、服务状态与监测配置'
  if (activeMenuCode.value === 'platform.logs') return '审计用户、企业、任务、权限和导出操作'
  if (activeMenuCode.value === 'platform.settings') return '基础参数、调度策略、菜单权限和安全配置'
  if (activeMenuCode.value === 'platform.models') return '展示系统支持的监测平台，以及今日各平台探测成功/失败条数。'
  if (activeMenuCode.value === 'customer.brand_analysis') {
    return '基于已购平台样本的文字诊断：提及率、短板、AI 描述与分端表现'
  }
  // 2026-07-30 - 顶栏副文案全局一句像没换页 - 仅 GEO/竞品/信源/报告/知识库按页区分
  const customerPageSubtitles: Record<string, string> = {
    'customer.realtime': '按平台与问题查看监测结果与推荐排名',
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
    if ((CUSTOMER_PREVIEW_MENU_CODES as readonly string[]).includes(code)) return
    navigateToMenu('customer.workspace', true)
    return
  }
  const allowedCodes = auth.allowedMenus.map(menu => normalizeMenuCode(menu.menu_code))
  if (isMenuBlocked(activeMenuCode.value) || !allowedCodes.includes(activeMenuCode.value)) {
    navigateToMenu(normalizeMenuCode(auth.allowedMenus[0]?.menu_code || ''), true)
  }
  userMenuExpanded.value = activeMenuCode.value.startsWith('platform.users') || activeMenuCode.value === POSITION_MENU
}

async function refreshMenusFromServer() {
  try {
    await auth.refreshSession()
    ensureActiveMenuAllowed()
  } catch {
    ElMessage.warning('会话已失效，请重新登录')
    await auth.logout()
    await router.replace('/login')
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
})
</script>

<template>
  <PortalLayout
    :is-platform="isPlatform"
    :menus="menus"
    :active-menu-code="activeMenuCode"
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
    @toggle-user-submenu="toggleUserSubmenu"
    @select-menu="selectMenu"
    @set-menu-code="navigateToMenu"
    @switch-identity="switchIdentity"
    @logout="logout"
    @open-alerts="navigateToMenu('platform.alerts', true)"
    @exit-preview="exitCustomerPreview"
  >
    <PositionPage v-if="isPositionManagementPage" />

    <UserCreatePage v-else-if="isUserCreatePage" />

    <UserListPage v-else-if="isUserListPage" />

    <BrandAuditPage v-else-if="isBrandAssetPage" ref="brandAuditRef" @brand-updated="onBrandUpdated" />
    <MonitorRealtimePage v-else-if="isRealtimeMonitorPage" />
    <CompetitorAnalysisPage v-else-if="isCompetitorPage" />
    <SourceAnalysisPage v-else-if="isSourcePage" />
    <ReportCenterPage v-else-if="isReportCenterPage" :is-platform="isPlatform && !isPreviewActive" />
    <LeadDiagnosisPage v-else-if="isLeadDiagnosisPage" />
    <SnapshotBackfillOpsPage v-else-if="isSnapshotBackfillPage" />
    <AlertThresholdsPage v-else-if="isAlertThresholdsPage" />
    <KnowledgeBasePage v-else-if="isKnowledgePage" />
    <BrandAnalysisPage v-else-if="isBrandAnalysisPage" />
    <ApprovalCenterPage v-else-if="isApprovalPage" />
    <AnnouncementManagePage v-else-if="isAnnouncementPage" />

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
  </PortalLayout>

  <AnnouncementModal />
  <PlatformAdminDialogs />
</template>
