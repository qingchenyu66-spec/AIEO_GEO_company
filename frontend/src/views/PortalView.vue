<script setup lang="ts">
import { computed, defineAsyncComponent, onMounted, provide, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '../stores/auth'
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
import { PortalAnalyticsKey, PlatformAdminKey } from './portal/injectionKeys'
import PlatformAdminDialogs from './portal/PlatformAdminDialogs.vue'
import { menuIcon } from './portal/menuIcons'
import {
  USER_CREATE_MENU,
  USER_LIST_MENU,
  POSITION_MENU,
  hiddenCustomerMenus,
  hiddenEnterprisePermissionMenus,
  hiddenUserPermissionMenus,
  normalizeMenuCode,
} from './portal/constants'
import { platformLabelMap, monitorStatusLabelMap } from './portal/portalMaps'
import { usePortalMenu } from './portal/usePortalMenu'
import '../styles/menu-config.css'

const PositionPage = defineAsyncComponent(() => import('./portal/PositionPage.vue'))
const PlatformDashboardPage = defineAsyncComponent(() => import('./portal/PlatformDashboardPage.vue'))
const UserCreatePage = defineAsyncComponent(() => import('./portal/UserCreatePage.vue'))
const UserListPage = defineAsyncComponent(() => import('./portal/UserListPage.vue'))
const BrandAuditPage = defineAsyncComponent(() => import('./portal/pages/BrandAuditPage.vue'))
const MonitorRealtimePage = defineAsyncComponent(() => import('./portal/pages/MonitorRealtimePage.vue'))
const SentimentMonitorPage = defineAsyncComponent(() => import('./portal/pages/SentimentMonitorPage.vue'))
const CustomerWorkspacePage = defineAsyncComponent(() => import('./portal/pages/CustomerWorkspacePage.vue'))
const FunctionalFeaturePage = defineAsyncComponent(() => import('./portal/pages/FunctionalFeaturePage.vue'))

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()
const isPlatform = computed(() => auth.session?.identity?.identity_type === 'PLATFORM')
const defaultMenuCode = normalizeMenuCode(auth.allowedMenus[0]?.menu_code || '')
const { activeMenuCode, navigateToMenu } = usePortalMenu(router, route, defaultMenuCode)
const userMenuExpanded = ref(activeMenuCode.value.startsWith('platform.users') || activeMenuCode.value === POSITION_MENU)
const brandAuditRef = ref<{ resetDetailMode?: () => void } | null>(null)

const menus = computed(() => auth.allowedMenus
  .filter(menu => ![USER_CREATE_MENU, USER_LIST_MENU, POSITION_MENU, 'customer.assets', ...hiddenCustomerMenus, ...hiddenEnterprisePermissionMenus, ...hiddenUserPermissionMenus].includes(menu.menu_code))
  .map(menu => menu.menu_code.endsWith('.sources') ? { ...menu, menu_name: '信源分析' } : menu))
const userManagementMenu = computed(() => menus.value.find(item => item.menu_code === 'platform.users'))

const isRealtimeMonitorPage = computed(() => activeMenuCode.value === 'customer.realtime')
const isSentimentMonitorPage = computed(() => ['customer.sentiment', 'platform.sentiment'].includes(activeMenuCode.value))
const isBrandAssetPage = computed(() => activeMenuCode.value === 'platform.audit')
const isDashboardPage = computed(() => ['platform.dashboard', 'customer.workspace'].includes(activeMenuCode.value))

const brandAsset = ref<BrandAsset | null>(null)
const brandCompetitors = ref<BrandCompetitor[]>([])

const platformAdmin = usePlatformAdmin({ auth, isPlatform, activeMenuCode, userMenuExpanded })
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

const hasUserCreateMenu = computed(() => auth.allowedMenus.some(item => item.menu_code === USER_CREATE_MENU) && creatableIdentityTypes.value.length > 0)
const hasUserListMenu = computed(() => auth.allowedMenus.some(item => item.menu_code === USER_LIST_MENU || item.menu_code === 'platform.users'))
const hasPositionMenu = computed(() => auth.allowedMenus.some(item => item.menu_code === POSITION_MENU))

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
  if (isUserCreatePage.value) return '创建账号、分配身份、绑定所属企业，并配置可访问菜单'
  if (isUserListPage.value) return '按公司、姓名、身份和状态筛选账号，支持编辑、禁用、重置密码和恢复'
  if (isPositionManagementPage.value) return '维护运营、销售、交付等职位模板，新增人员时从职位库选择'
  return isPlatform.value ? '企业运营、任务消耗、平台运行与风险情况' : '品牌曝光、推荐排名、信源分析与监测趋势'
})

async function loadBrandAssetData() {
  try {
    let tenantId: number | null = null
    if (isPlatform.value) {
      if (!tenants.value.length) {
        tenants.value = await withRetry(() => getTenants())
      }
      tenantId = tenants.value[0]?.id ?? null
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
  const allowedCodes = auth.allowedMenus.map(menu => normalizeMenuCode(menu.menu_code))
  if (!allowedCodes.includes(activeMenuCode.value)) {
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
    auth.logout()
    router.replace('/login')
  }
}

function logout() {
  auth.logout()
  router.replace('/login')
}

watch(activeMenuCode, (newCode, oldCode) => {
  if (oldCode === 'platform.audit' && newCode !== 'platform.audit') {
    brandAuditRef.value?.resetDetailMode?.()
  }
  if (!isBrandAssetPage.value && !isRealtimeMonitorPage.value) {
    loadBrandAssetData()
  }
})
onMounted(refreshMenusFromServer)
onMounted(() => {
  if (!isBrandAssetPage.value && !isRealtimeMonitorPage.value) loadBrandAssetData()
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
    :portal-identity-name="identityDisplayName(auth.session?.identity)"
    :portal-identity-subtitle="auth.session?.identity?.tenant_name || 'GEO Monitor 平台'"
    :session-user-name="auth.session?.user.display_name || ''"
    :session-username="auth.session?.user.username || ''"
    :session-display-initial="auth.session?.user.display_name?.slice(0, 1) || ''"
    :identity-count="auth.session?.identities.length || 0"
    :identities="auth.session?.identities || []"
    :current-identity-id="auth.session?.identity?.id"
    :menu-icon="menuIcon"
    @toggle-user-submenu="toggleUserSubmenu"
    @select-menu="selectMenu"
    @set-menu-code="navigateToMenu"
    @switch-identity="switchIdentity"
    @logout="logout"
  >
    <PositionPage v-if="isPositionManagementPage" />

    <UserCreatePage v-else-if="isUserCreatePage" />

    <UserListPage v-else-if="isUserListPage" />

    <BrandAuditPage v-else-if="isBrandAssetPage" ref="brandAuditRef" @brand-updated="onBrandUpdated" />
    <MonitorRealtimePage v-else-if="isRealtimeMonitorPage" />
    <SentimentMonitorPage v-else-if="isSentimentMonitorPage" />

    <template v-else>
      <template v-if="isDashboardPage">
        <PlatformDashboardPage
          v-if="isPlatform"
          :platform-label-map="platformLabelMap"
          :monitor-status-label-map="monitorStatusLabelMap"
          :navigate-to="navigateToMenu"
        />
        <CustomerWorkspacePage v-else />
      </template>
      <FunctionalFeaturePage v-else @open-menu-config="openMenuConfigDialog" />
    </template>
  </PortalLayout>

  <PlatformAdminDialogs />
</template>
