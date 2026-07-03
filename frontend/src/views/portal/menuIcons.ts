import {
  BarChart3, BellRing, ClipboardCheck,
  Database, FileBarChart, Gauge, Layers3, Search, Settings,
  SlidersHorizontal, Stethoscope, Upload, UserCog, Users,
} from '@lucide/vue'
import type { Component } from 'vue'
import type { MenuInfo } from '../../services/auth'

const iconMap: Record<string, Component> = {
  BarChart3, BellRing, ClipboardCheck, Database,
  FileBarChart, Gauge, Layers3, Search, Settings, SlidersHorizontal, Stethoscope, Upload, UserCog, Users,
}

export function menuIcon(menu: MenuInfo) {
  return iconMap[menu.icon] || Gauge
}
