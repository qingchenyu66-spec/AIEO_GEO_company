<script setup lang="ts">
import { Building2, ChevronDown, LogOut, ShieldCheck } from '@lucide/vue'
import type { Component } from 'vue'
import type { MenuInfo } from '../../services/auth'
import AppBrandLogo from '../../components/AppBrandLogo.vue'
import NotificationBell from './components/NotificationBell.vue'
import {
  POSITION_MENU,
  USER_CREATE_MENU,
  USER_LIST_MENU,
} from './constants'

defineProps<{
  isPlatform: boolean
  menus: MenuInfo[]
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
}>()

const emit = defineEmits<{
  toggleUserSubmenu: []
  selectMenu: [menu: MenuInfo]
  setMenuCode: [code: string]
  switchIdentity: [identityId: number]
  logout: []
  openAlerts: []
}>()
</script>

<template>
  <div
    class="app-shell portal-shell"
    :class="{
      'portal-fullscreen': fullscreen,
      'portal-sidebar-expanded': userMenuExpanded,
    }"
  >
    <aside v-if="!fullscreen" class="sidebar">
      <div class="brand">
        <div class="brand-mark"><AppBrandLogo variant="icon" /></div>
        <div><strong>GEO Monitor</strong><span>{{ isPlatform ? '平台运营端' : '客户企业端' }}</span></div>
      </div>
      <div class="portal-tag">
        <ShieldCheck v-if="isPlatform" />
        <Building2 v-else />
        <span>
          <b>{{ portalIdentityName }}</b>
          <small>{{ portalIdentitySubtitle }}</small>
        </span>
      </div>
      <nav class="nav" aria-label="主导航">
        <template v-for="menu in menus" :key="menu.menu_code">
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
          </button>
        </template>
      </nav>
    </aside>
    <section class="workspace">
      <header v-if="!fullscreen" class="topbar">
        <div class="crumb">GEO Monitor / {{ pageTitle }}</div>
        <div class="top-actions">
          <NotificationBell @open-alerts="emit('openAlerts')" />
          <el-dropdown v-if="identityCount > 1" trigger="click" @command="(id: number) => emit('switchIdentity', id)">
            <button type="button" class="identity-switch">
              <span><small>当前职位</small><b>{{ identityDisplayName(identities.find(i => i.id === currentIdentityId)) }}</b></span>
              <ChevronDown />
            </button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item
                  v-for="identity in identities"
                  :key="identity.id"
                  :command="identity.id"
                  :disabled="identity.id === currentIdentityId"
                >
                  <ShieldCheck v-if="identity.identity_type === 'PLATFORM'" />
                  <Building2 v-else />
                  {{ identityDisplayName(identity) }}
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
          <div class="user-chip">
            <span>{{ sessionDisplayInitial }}</span>
            <div><b>{{ sessionUserName }}</b><small>{{ sessionUsername }}</small></div>
          </div>
          <button type="button" class="icon-action" title="退出登录" aria-label="退出登录" @click="emit('logout')">
            <LogOut />
          </button>
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
