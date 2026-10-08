<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Building2, ChevronDown, LogOut, Menu, PanelLeft, ShieldCheck, Smartphone, Star, X } from '@lucide/vue'
import type { Component } from 'vue'
import type { MenuInfo } from '../../services/auth'
import AppBrandLogo from '../../components/AppBrandLogo.vue'
import NotificationBell from './components/NotificationBell.vue'
import {
  POSITION_MENU,
  USER_CREATE_MENU,
  USER_LIST_MENU,
} from './constants'

const SIDEBAR_PIN_KEY = 'geo.portal.sidebarPinned'

defineProps<{
  isPlatform: boolean
  menus: MenuInfo[]
  pinnedMenuCount: number
  menuFavoritesEnabled: boolean
  isMenuPinned: (menuCode: string) => boolean
  activeMenuCode: string
  userMenuExpanded: boolean
  hasUserCreateMenu: boolean
  hasUserListMenu: boolean
  hasPositionMenu: boolean
  pageTitle: string
  pageSubtitle: string
  identityDisplayName: (identity?: { position_name?: string | null; identity_name?: string | null }) => string
  portalIdentityName: string
  portalIdentitySubtitle: string
  sessionUserName: string
  sessionUsername: string
  sessionDisplayInitial: string
  identityCount: number
  identities: Array<{ id: number; identity_type: string; position_name?: string | null; identity_name?: string | null }>
  currentIdentityId?: number
  menuIcon: (menu: MenuInfo) => Component
  immersive?: boolean
  fullscreen?: boolean
  pendingApprovalCount?: number
  previewMode?: boolean
  brandLogoSrc?: string
}>()

const emit = defineEmits<{
  toggleUserSubmenu: []
  toggleMenuPin: [menuCode: string]
  selectMenu: [menu: MenuInfo]
  setMenuCode: [code: string]
  switchIdentity: [identityId: number]
  logout: []
  openAlerts: []
  exitPreview: []
}>()

const sidebarPinned = ref(false)
const mobileNavOpen = ref(false)
const router = useRouter()

function toggleMobileNav() {
  mobileNavOpen.value = !mobileNavOpen.value
}

function closeMobileNav() {
  mobileNavOpen.value = false
}

function onSidebarClick(event: MouseEvent) {
  if (!mobileNavOpen.value) return
  const target = event.target as HTMLElement | null
  if (!target) return
  if (target.closest('.nav-favorite-btn, .nav-parent, .portal-mobile-nav-close')) return
  if (target.closest('.nav-item, .sub-nav-item')) closeMobileNav()
}

function onMobileNavKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') closeMobileNav()
}

function onMobileNavResize() {
  if (window.innerWidth > 900) closeMobileNav()
}

onMounted(() => {
  try {
    sidebarPinned.value = localStorage.getItem(SIDEBAR_PIN_KEY) === '1'
  } catch {
    sidebarPinned.value = false
  }
  window.addEventListener('keydown', onMobileNavKeydown)
  window.addEventListener('resize', onMobileNavResize)
})

onUnmounted(() => {
  window.removeEventListener('keydown', onMobileNavKeydown)
  window.removeEventListener('resize', onMobileNavResize)
})

function toggleSidebarPin() {
  sidebarPinned.value = !sidebarPinned.value
  try {
    localStorage.setItem(SIDEBAR_PIN_KEY, sidebarPinned.value ? '1' : '0')
  } catch {
    /* ignore */
  }
}

function onUserMenuCommand(command: string) {
  if (command === 'account') {
    void router.push('/account')
    return
  }
  if (command === 'logout') {
    emit('logout')
    return
  }
  // 2026-08-20 - 顶栏变轻 - 职位切换收进账号菜单
  if (command.startsWith('identity:')) {
    const id = Number(command.slice('identity:'.length))
    if (Number.isFinite(id)) emit('switchIdentity', id)
  }
}
</script>

<template>
  <div
    class="app-shell portal-shell"
    :class="{
      'portal-fullscreen': fullscreen,
      'portal-sidebar-expanded': userMenuExpanded,
      'portal-sidebar-pinned': sidebarPinned,
      'portal-mobile-nav-open': mobileNavOpen,
    }"
  >
    <button
      v-if="mobileNavOpen && !fullscreen"
      type="button"
      class="portal-mobile-nav-backdrop"
      aria-label="关闭菜单"
      @click="closeMobileNav"
    />
    <aside v-if="!fullscreen" id="portal-sidebar" class="sidebar" @click="onSidebarClick">
      <div class="brand">
        <!-- 2026-08-20 - 对齐生产：无 brand-head；固定钮 absolute 不占流，悬停不拽方标 -->
        <div class="brand-mark brand-mark--logo" aria-hidden="true">
          <AppBrandLogo variant="icon" alt="" :src="brandLogoSrc" />
        </div>
        <div>
          <strong>GEO Monitor</strong>
          <span>{{ previewMode ? '客户门户预览' : (isPlatform ? '平台运营端' : '客户企业端') }}</span>
        </div>
        <button
          type="button"
          class="sidebar-pin"
          :class="{ active: sidebarPinned }"
          :title="sidebarPinned ? '收起菜单栏' : '固定展开菜单栏'"
          :aria-pressed="sidebarPinned"
          aria-label="固定或收起侧栏"
          @click="toggleSidebarPin"
        >
          <PanelLeft />
        </button>
      </div>
      <!-- 2026-08-20 - 侧栏身份白胶囊已去掉（用户确认可删） -->
      <nav class="nav" aria-label="主导航">
        <div v-if="previewMode && !menus.length" class="nav-item" style="pointer-events:none;opacity:.7">
          <span>菜单加载中…</span>
        </div>
        <template v-for="(menu, index) in menus" :key="menu.menu_code">
          <div
            v-if="menuFavoritesEnabled && pinnedMenuCount > 0 && index === pinnedMenuCount"
            class="nav-favorites-divider"
            aria-hidden="true"
          />
          <template v-if="menu.menu_code === 'platform.users'">
            <button
              type="button"
              class="nav-item nav-parent"
              :class="{ active: activeMenuCode.startsWith('platform.users') || activeMenuCode === POSITION_MENU, expanded: userMenuExpanded }"
              :aria-expanded="userMenuExpanded"
              aria-controls="portal-user-submenu"
              @click="emit('toggleUserSubmenu')"
            >
              <component :is="menuIcon(menu)" class="nav-icon" aria-hidden="true" />
              <span>{{ menu.menu_name }}</span>
              <span
                v-if="menuFavoritesEnabled"
                role="button"
                tabindex="0"
                class="nav-favorite-btn"
                :class="{ active: isMenuPinned(menu.menu_code) }"
                :title="isMenuPinned(menu.menu_code) ? '取消置顶' : '置顶'"
                :aria-label="isMenuPinned(menu.menu_code) ? '取消置顶' : '置顶'"
                @click.stop="emit('toggleMenuPin', menu.menu_code)"
                @keydown.enter.prevent.stop="emit('toggleMenuPin', menu.menu_code)"
                @keydown.space.prevent.stop="emit('toggleMenuPin', menu.menu_code)"
              >
                <Star :fill="isMenuPinned(menu.menu_code) ? 'currentColor' : 'none'" />
              </span>
              <ChevronDown class="nav-caret" aria-hidden="true" />
            </button>
            <div v-if="userMenuExpanded" id="portal-user-submenu" class="sub-nav" role="group" aria-label="用户管理子菜单">
              <button
                v-if="hasUserCreateMenu"
                type="button"
                class="sub-nav-item"
                :class="{ active: activeMenuCode === USER_CREATE_MENU }"
                :aria-current="activeMenuCode === USER_CREATE_MENU ? 'page' : undefined"
                @click="emit('setMenuCode', USER_CREATE_MENU)"
              >用户新增</button>
              <button
                v-if="hasUserListMenu"
                type="button"
                class="sub-nav-item"
                :class="{ active: activeMenuCode === USER_LIST_MENU }"
                :aria-current="activeMenuCode === USER_LIST_MENU ? 'page' : undefined"
                @click="emit('setMenuCode', USER_LIST_MENU)"
              >用户列表</button>
              <button
                v-if="hasPositionMenu"
                type="button"
                class="sub-nav-item"
                :class="{ active: activeMenuCode === POSITION_MENU }"
                :aria-current="activeMenuCode === POSITION_MENU ? 'page' : undefined"
                @click="emit('setMenuCode', POSITION_MENU)"
              >职位管理</button>
            </div>
          </template>
          <button
            v-else
            type="button"
            class="nav-item"
            :class="{ active: menu.menu_code === activeMenuCode }"
            :aria-current="menu.menu_code === activeMenuCode ? 'page' : undefined"
            @click="emit('selectMenu', menu)"
          >
            <component :is="menuIcon(menu)" class="nav-icon" aria-hidden="true" />
            <span>{{ menu.menu_name }}</span>
            <b
              v-if="menu.menu_code === 'platform.approvals' && (pendingApprovalCount ?? 0) > 0"
              class="nav-badge"
              :aria-label="`${pendingApprovalCount} 条待审批`"
            >{{ (pendingApprovalCount ?? 0) > 99 ? '99+' : pendingApprovalCount }}</b>
            <span
              v-if="menuFavoritesEnabled"
              role="button"
              tabindex="0"
              class="nav-favorite-btn"
              :class="{ active: isMenuPinned(menu.menu_code) }"
              :title="isMenuPinned(menu.menu_code) ? '取消置顶' : '置顶'"
              :aria-label="isMenuPinned(menu.menu_code) ? '取消置顶' : '置顶'"
              @click.stop="emit('toggleMenuPin', menu.menu_code)"
              @keydown.enter.prevent.stop="emit('toggleMenuPin', menu.menu_code)"
              @keydown.space.prevent.stop="emit('toggleMenuPin', menu.menu_code)"
            >
              <Star :fill="isMenuPinned(menu.menu_code) ? 'currentColor' : 'none'" />
            </span>
          </button>
        </template>
      </nav>
    </aside>
    <section class="workspace">
      <header v-if="!fullscreen" class="topbar">
        <button
          type="button"
          class="portal-mobile-nav-btn"
          :aria-expanded="mobileNavOpen"
          aria-controls="portal-sidebar"
          :aria-label="mobileNavOpen ? '关闭菜单' : '打开菜单'"
          @click="toggleMobileNav"
        >
          <X v-if="mobileNavOpen" />
          <Menu v-else />
        </button>
        <div class="crumb">{{ pageTitle }}</div>
        <div class="top-actions">
          <!-- 2026-07-30 - 预览退出抢视线/像退出登录 - 顶栏次要按钮「返回企业管理」，去蓝条 -->
          <button
            v-if="previewMode"
            type="button"
            class="preview-exit-btn"
            @click="emit('exitPreview')"
          >返回企业管理</button>
          <NotificationBell @open-alerts="emit('openAlerts')" />
          <el-dropdown trigger="click" @command="onUserMenuCommand">
            <button type="button" class="user-menu-trigger" aria-label="账号菜单">
              <div class="user-chip user-chip--avatar-only">
                <span>{{ sessionDisplayInitial }}</span>
              </div>
              <ChevronDown class="user-menu-caret" aria-hidden="true" />
            </button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item disabled class="user-menu-identity-label">
                  {{ sessionUserName }} · {{ sessionUsername }}
                </el-dropdown-item>
                <template v-if="identityCount > 1">
                  <el-dropdown-item divided disabled>切换职位</el-dropdown-item>
                  <el-dropdown-item
                    v-for="identity in identities"
                    :key="identity.id"
                    :command="`identity:${identity.id}`"
                    :disabled="identity.id === currentIdentityId"
                  >
                    <ShieldCheck v-if="identity.identity_type === 'PLATFORM'" />
                    <Building2 v-else />
                    {{ identityDisplayName(identity) }}
                  </el-dropdown-item>
                </template>
                <el-dropdown-item divided command="account">
                  <Smartphone />
                  账号与安全
                </el-dropdown-item>
                <el-dropdown-item command="logout">
                  <LogOut />
                  退出登录
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </header>
      <main class="content portal-content" :class="{ 'portal-content-immersive': immersive }">
        <div v-if="!immersive" class="page-head">
          <div class="page-head-main">
            <h1>{{ pageTitle }}</h1>
            <p>{{ pageSubtitle }}</p>
          </div>
          <div class="page-head-aside">
            <div id="portal-page-head-extra" class="page-head-extra" />
            <span class="live-status"><i></i> 数据服务正常</span>
          </div>
        </div>
        <slot />
      </main>
    </section>
  </div>
</template>
