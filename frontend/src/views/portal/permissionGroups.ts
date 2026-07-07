import type { IdentityType, MenuInfo } from '../../services/auth'
import { generateInitialPassword } from '../../utils/password'
import { POSITION_MENU } from './constants'

export function permissionGroupTitle(type: IdentityType, key: string) {
  const platformTitles: Record<string, string> = {
    dashboard: '运营总览',
    audit: '企业管理',
    analysis: '分析报告',
    users: '用户管理',
    diagnosis: '品牌诊断',
    backfill: '快照补录',
    system: '系统管理',
    other: '其他权限',
  }
  const customerTitles: Record<string, string> = {
    workspace: '数据概览',
    monitor: '监测展示',
    analysis: '分析报告',
    knowledge: '企业知识库',
    other: '其他权限',
  }
  return type === 'PLATFORM' ? platformTitles[key] || key : customerTitles[key] || key
}

export function permissionGroupNote(type: IdentityType, key: string) {
  if (type === 'CUSTOMER') {
    return key === 'knowledge'
      ? '客户侧仅在知识库开放上传，其余模块以展示、查看和导出为主。'
      : '客户侧菜单默认面向展示，不开放企业资料和任务创建入口。'
  }
  if (key === 'audit') return '企业资料、监测词、购买模型、监控计划和竞品配置可在这里拆分授权。'
  if (key === 'analysis') return '报告中心支持查看/导出、生成与编辑发布；客户侧默认仅查看已发布报告。'
  if (key === 'users') return '包含用户新增、用户列表、职位管理和操作审批；销售通常仅可查看自己的申请，运营/管理员可审批。'
  if (key === 'diagnosis') return '品牌诊断与售前诊断：前者基于签约企业监测数据，后者面向潜在客户交付 PDF。'
  if (key === 'backfill') return '抓取失败或需覆盖更正时，运营粘贴分享链接与回答正文；可单独授权查看与提交。'
  if (key === 'system') return '系统配置、操作日志、模型平台等后台维护能力。'
  return '平台运营端用于内部管理，可按职位控制新增、编辑、禁用和导出。'
}

export function permissionGroupKey(menu: MenuInfo) {
  if (menu.identity_type === 'CUSTOMER') {
    if (['customer.workspace'].includes(menu.menu_code)) return 'workspace'
    if (['customer.realtime', 'customer.links'].includes(menu.menu_code)) return 'monitor'
    if (['customer.diagnosis', 'customer.competitor', 'customer.sources', 'customer.reports'].includes(menu.menu_code)) return 'analysis'
    if (menu.menu_code === 'customer.knowledge') return 'knowledge'
    return 'other'
  }
  if (menu.menu_code === 'platform.dashboard') return 'dashboard'
  if (menu.menu_code.startsWith('platform.audit')) return 'audit'
  if (menu.menu_code.startsWith('platform.users') || menu.menu_code === POSITION_MENU || menu.menu_code === 'platform.approvals') return 'users'
  if (menu.menu_code === 'platform.diagnosis' || menu.menu_code === 'platform.lead_diagnosis') return 'diagnosis'
  if (menu.menu_code === 'platform.snapshot_backfill') return 'backfill'
  if (['platform.competitor', 'platform.sources', 'platform.reports'].includes(menu.menu_code)) return 'analysis'
  if (['platform.models', 'platform.alerts', 'platform.logs', 'platform.settings'].includes(menu.menu_code)) return 'system'
  return 'other'
}

export function permissionGroupsFor(
  type: IdentityType,
  assignMenus: Record<IdentityType, MenuInfo[]>,
  selectedMenuIds: number[] = [],
) {
  const order = type === 'PLATFORM'
    ? ['dashboard', 'audit', 'analysis', 'users', 'diagnosis', 'backfill', 'system', 'other']
    : ['workspace', 'monitor', 'analysis', 'knowledge', 'other']
  const buckets: Record<string, MenuInfo[]> = {}
  for (const menu of assignMenus[type]) {
    const key = permissionGroupKey(menu)
    if (!buckets[key]) buckets[key] = []
    buckets[key].push(menu)
  }
  return order
    .filter(key => buckets[key]?.length)
    .map(key => ({
      key,
      title: permissionGroupTitle(type, key),
      note: permissionGroupNote(type, key),
      menus: buckets[key].sort((a, b) => a.sort_order - b.sort_order || a.id - b.id),
      checked: buckets[key].filter(menu => selectedMenuIds.includes(menu.id)).length,
    }))
}

export type IdentityConfigForm = {
  role_code: string
  identity_name: string
  position_id: number | null
  tenant_id: number | null
  tenant_name: string
  menu_ids: number[]
}

export type UserIdentityForm = {
  display_name: string
  identity_types: IdentityType[]
  identity_configs: Record<IdentityType, IdentityConfigForm>
}

export function permissionGroupsForForm(
  type: IdentityType,
  assignMenus: Record<IdentityType, MenuInfo[]>,
  form: UserIdentityForm,
) {
  return permissionGroupsFor(type, assignMenus, form.identity_configs[type].menu_ids)
}

export function createEmptyIdentityForm(): UserIdentityForm {
  const emptyConfig = (): IdentityConfigForm => ({
    role_code: '',
    identity_name: '',
    position_id: null,
    tenant_id: null,
    tenant_name: '',
    menu_ids: [],
  })
  return {
    display_name: '',
    identity_types: [],
    identity_configs: {
      PLATFORM: { ...emptyConfig(), identity_name: '平台运营成员' },
      CUSTOMER: { ...emptyConfig(), identity_name: '客户企业成员' },
    },
  }
}

export function createUserCreateForm() {
  const base = createEmptyIdentityForm()
  return {
    username: '',
    password: generateInitialPassword(),
    display_name: base.display_name,
    identity_types: base.identity_types,
    identity_configs: base.identity_configs,
  }
}
