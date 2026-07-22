import {
  Activity,
  BarChart3,
  BellRing,
  BookOpen,
  ClipboardCheck,
  Database,
  FileBarChart,
  FileText,
  Gauge,
  LayoutDashboard,
  Layers3,
  Radar,
  Search,
  Settings,
  SlidersHorizontal,
  Stethoscope,
  Upload,
  UserCog,
  Users,
} from '@lucide/vue'
import type { Component } from 'vue'
import type { MenuInfo } from '../../services/auth'

/** 库表 icon 字符串 → 组件（含历史别名） */
const iconMap: Record<string, Component> = {
  Activity,
  BarChart3,
  BellRing,
  BookOpen,
  ClipboardCheck,
  Database,
  FileBarChart,
  FileText,
  Gauge,
  LayoutDashboard,
  Layers3,
  Radar,
  Search,
  Settings,
  SlidersHorizontal,
  Stethoscope,
  Upload,
  UserCog,
  Users,
}

/**
 * 按 menu_code 定稿图标：侧栏缩成图标轨时必须一眼可辨。
 * 优先于库表 icon，避免多菜单共用 Gauge / 未注册名回退成同一图标。
 */
const menuCodeIconMap: Record<string, Component> = {
  'customer.workspace': LayoutDashboard,
  'customer.brand_analysis': Radar,
  'customer.realtime': Search,
  'customer.competitor': BarChart3,
  'customer.sources': Database,
  'customer.reports': FileBarChart,
  'customer.knowledge': BookOpen,
  'platform.dashboard': LayoutDashboard,
  'platform.lead_diagnosis': Stethoscope,
  'platform.reports': FileBarChart,
}

export function menuIcon(menu: MenuInfo) {
  return menuCodeIconMap[menu.menu_code]
    || iconMap[menu.icon]
    || LayoutDashboard
}
