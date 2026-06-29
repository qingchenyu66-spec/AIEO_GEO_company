<script setup lang="ts">
import { computed, defineAsyncComponent, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Activity, BarChart3, BellRing, BookOpen, Building2, ChevronDown, ClipboardCheck,
  Database, FileBarChart, Gauge, HelpCircle, Layers3, Link2, LogOut, Search, Settings,
  ShieldCheck, SlidersHorizontal, UserCog, Users,
} from '@lucide/vue'
import type { Component } from 'vue'
import { getInstanceByDom, graphic, init, use, type ECharts } from 'echarts/core'
import { BarChart, GaugeChart, LineChart, PieChart } from 'echarts/charts'
import { GraphicComponent, GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { useAuthStore } from '../stores/auth'
import type { IdentityType, MenuInfo } from '../services/auth'
import {
  createManagedUser, createManagementPosition, createTenant, deleteManagedUser, deleteManagementPosition, deleteTenant, getManagedUsers, getManagementMenus, getManagementPositions, getManagementRoles, getTenants,
  getOperationLogs, getSystemConfigs, resetManagedUserPassword, restoreManagedUser, restoreTenant, setManagedUserStatus, updateManagedUser, updateManagementPosition,
  updateTenant, type ManagedUser, type OperationLogRecord, type PositionInfo, type RoleInfo, type SystemConfigRecord, type TenantInfo,
} from '../services/management'
import {
  getMonitorSummary, getMonitorTaskDetail, getMonitorTasks, syncMonitorTask,
  type MonitorSubtask, type MonitorSummary, type MonitorTask,
} from '../services/monitor'
import {
  createCompetitor, deleteCompetitor, getBrandAsset, saveBrandAsset, updateCompetitor,
  type BrandAsset, type BrandCompetitor, type BrandKeywordGroup,
} from '../services/brand'
import { getKnowledgeFiles, uploadKnowledgeFile, type KnowledgeFileRecord } from '../services/knowledge'

const PositionPage = defineAsyncComponent(() => import('./portal/PositionPage.vue'))
const PlatformDashboardPage = defineAsyncComponent(() => import('./portal/PlatformDashboardPage.vue'))
const UserCreatePage = defineAsyncComponent(() => import('./portal/UserCreatePage.vue'))
const UserListPage = defineAsyncComponent(() => import('./portal/UserListPage.vue'))

use([BarChart, GaugeChart, LineChart, PieChart, GraphicComponent, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer])

const auth = useAuthStore()
const router = useRouter()
const isPlatform = computed(() => auth.session?.identity.identity_type === 'PLATFORM')
const USER_CREATE_MENU = 'platform.users.create'
const USER_CREATE_PLATFORM_MENU = 'platform.users.create.platform'
const USER_CREATE_CUSTOMER_MENU = 'platform.users.create.customer'
const USER_LIST_MENU = 'platform.users.list'
const POSITION_MENU = 'platform.positions'
const normalizeMenuCode = (code: string) => code === 'platform.users' ? USER_LIST_MENU : code
const hiddenCustomerMenus = ['customer.batch', 'customer.geo']
const hiddenEnterprisePermissionMenus = [
  'platform.audit.list',
  'platform.audit.profile',
  'platform.audit.keywords',
  'platform.audit.models',
  'platform.audit.schedule',
  'platform.audit.competitors',
  'platform.audit.files',
]
const hiddenUserPermissionMenus = [USER_CREATE_PLATFORM_MENU, USER_CREATE_CUSTOMER_MENU]
const activeMenuCode = ref(normalizeMenuCode(auth.allowedMenus[0]?.menu_code || ''))
const userMenuExpanded = ref(activeMenuCode.value.startsWith('platform.users') || activeMenuCode.value === POSITION_MENU)
const managementUsers = ref<ManagedUser[]>([])
const assignMenus = reactive<Record<IdentityType, MenuInfo[]>>({ PLATFORM: [], CUSTOMER: [] })
const roles = reactive<Record<IdentityType, RoleInfo[]>>({ PLATFORM: [], CUSTOMER: [] })
const positions = reactive<Record<IdentityType, PositionInfo[]>>({ PLATFORM: [], CUSTOMER: [] })
const positionRows = ref<PositionInfo[]>([])
const editingPosition = ref<PositionInfo | null>(null)
const positionDialog = ref(false)
const savingPosition = ref(false)
const positionForm = reactive({
  position_name: '',
  identity_type: 'PLATFORM' as IdentityType,
  role_code: '',
  description: '',
  menu_ids: [] as number[],
  status: true,
})
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
const loadingUsers = ref(false)
const loadingKnowledgeFiles = ref(false)
const uploadingKnowledgeFile = ref(false)
const creatingUser = ref(false)
const editingUser = ref<ManagedUser | null>(null)
const editDialog = ref(false)
const passwordDialog = ref(false)
const tenantDialog = ref(false)
const resetPassword = ref('Geo@2026')
const tenantForm = reactive({ name: '', code: '', service_start_date: '', service_end_date: '' })
const knowledgeFiles = ref<KnowledgeFileRecord[]>([])
const userFilters = reactive({
  keyword: '',
  tenant_id: null as number | null,
  identity_type: '' as IdentityType | '',
  enabled: '' as '' | 'true' | 'false',
  deleted: false,
})

const iconMap: Record<string, Component> = {
  Activity, BarChart3, BellRing, BookOpen, Building2, ClipboardCheck, Database,
  FileBarChart, Gauge, Layers3, Link2, Search, Settings, SlidersHorizontal, UserCog, Users,
}

const menus = computed(() => auth.allowedMenus
  .filter(menu => ![USER_CREATE_MENU, USER_LIST_MENU, POSITION_MENU, 'customer.assets', ...hiddenCustomerMenus, ...hiddenEnterprisePermissionMenus, ...hiddenUserPermissionMenus].includes(menu.menu_code))
  .map(menu => menu.menu_code.endsWith('.sources') ? { ...menu, menu_name: '信源分析' } : menu))
const userManagementMenu = computed(() => menus.value.find(item => item.menu_code === 'platform.users'))
const hasUserCreateMenu = computed(() => auth.allowedMenus.some(item => item.menu_code === USER_CREATE_MENU) && creatableIdentityTypes.value.length > 0)
const hasUserListMenu = computed(() => auth.allowedMenus.some(item => item.menu_code === USER_LIST_MENU || item.menu_code === 'platform.users'))
const hasPositionMenu = computed(() => auth.allowedMenus.some(item => item.menu_code === POSITION_MENU))
const canCreatePlatformUser = computed(() => Boolean(menuGrant(USER_CREATE_PLATFORM_MENU)?.can_create))
const canCreateCustomerUser = computed(() => Boolean(menuGrant(USER_CREATE_CUSTOMER_MENU)?.can_create))
const creatableIdentityTypes = computed(() => {
  const types: IdentityType[] = []
  if (canCreatePlatformUser.value) types.push('PLATFORM')
  if (canCreateCustomerUser.value) types.push('CUSTOMER')
  return types
})
const positionFormMenus = computed(() => assignMenus[positionForm.identity_type] || [])
const isUserCreatePage = computed(() => activeMenuCode.value === USER_CREATE_MENU)
const isUserListPage = computed(() => activeMenuCode.value === USER_LIST_MENU)
const isUserManagementPage = computed(() => isUserCreatePage.value || isUserListPage.value)
const isPositionManagementPage = computed(() => activeMenuCode.value === POSITION_MENU)
const isRealtimeMonitorPage = computed(() => activeMenuCode.value === 'customer.realtime')
const isBrandAssetPage = computed(() => activeMenuCode.value === 'platform.audit')
const isDashboardPage = computed(() => ['platform.dashboard', 'customer.workspace'].includes(activeMenuCode.value))
const monitorSummaryMenuCodes = new Set([
  'platform.dashboard',
  'platform.sentiment',
  'platform.competitor',
  'platform.sources',
  'platform.diagnosis',
  'platform.reports',
  'customer.workspace',
  'customer.sentiment',
  'customer.sources',
  'customer.diagnosis',
  'customer.competitor',
  'customer.reports',
  'customer.knowledge',
])
const shouldLoadMonitorSummary = computed(() => monitorSummaryMenuCodes.has(activeMenuCode.value))
const enterprisePermissionCodeMap = {
  list: 'platform.audit.list',
  profile: 'platform.audit.profile',
  keywords: 'platform.audit.keywords',
  platforms: 'platform.audit.models',
  schedule: 'platform.audit.schedule',
  competitors: 'platform.audit.competitors',
  files: 'platform.audit.files',
} as const
type EnterpriseTab = 'profile' | 'keywords' | 'platforms' | 'schedule' | 'competitors' | 'files'
function menuGrant(code: string) {
  return auth.allowedMenus.find(menu => menu.menu_code === code)
}
function permissionGroupTitle(type: IdentityType, key: string) {
  const platformTitles: Record<string, string> = {
    dashboard: '运营总览',
    audit: '企业管理',
    users: '用户管理',
    diagnosis: '品牌诊断',
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
function permissionGroupNote(type: IdentityType, key: string) {
  if (type === 'CUSTOMER') return key === 'knowledge' ? '客户侧唯一允许上传的位置，其余模块以展示、查看和导出为主。' : '客户侧菜单默认面向展示，不开放企业资料和任务创建入口。'
  if (key === 'audit') return '企业资料、监测词、购买模型、监控计划和竞品配置可在这里拆分授权。'
  if (key === 'users') return '包含用户新增、用户列表和职位管理，通常只给管理员或负责人。'
  if (key === 'diagnosis') return '品牌诊断由运营人工处理，可基于企业、平台和监测结果生成诊断建议。'
  if (key === 'system') return '系统配置、操作日志、模型平台等后台维护能力。'
  return '平台运营端用于内部管理，可按职位控制新建、编辑、禁用和导出。'
}
function permissionGroupKey(menu: MenuInfo) {
  if (menu.identity_type === 'CUSTOMER') {
    if (['customer.workspace'].includes(menu.menu_code)) return 'workspace'
    if (['customer.realtime', 'customer.sentiment', 'customer.links'].includes(menu.menu_code)) return 'monitor'
    if (['customer.diagnosis', 'customer.competitor', 'customer.sources', 'customer.reports'].includes(menu.menu_code)) return 'analysis'
    if (menu.menu_code === 'customer.knowledge') return 'knowledge'
    return 'other'
  }
  if (menu.menu_code === 'platform.dashboard') return 'dashboard'
  if (menu.menu_code.startsWith('platform.audit')) return 'audit'
  if (menu.menu_code.startsWith('platform.users') || menu.menu_code === POSITION_MENU) return 'users'
  if (menu.menu_code === 'platform.diagnosis') return 'diagnosis'
  if (['platform.plans', 'platform.admins', 'platform.models', 'platform.alerts', 'platform.logs', 'platform.settings'].includes(menu.menu_code)) return 'system'
  return 'other'
}
function permissionGroupsFor(type: IdentityType, selectedMenuIds: number[] = []) {
  const order = type === 'PLATFORM'
    ? ['dashboard', 'audit', 'users', 'diagnosis', 'system', 'other']
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
function permissionGroupsForForm(type: IdentityType, form: typeof userForm | typeof editForm) {
  return permissionGroupsFor(type, form.identity_configs[type].menu_ids)
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
const activeMenu = computed(() => {
  const userMenu = userManagementMenu.value
  if (isUserCreatePage.value && userMenu) return { ...userMenu, menu_code: USER_CREATE_MENU, menu_name: '用户新增' } as MenuInfo
  if (isUserListPage.value && userMenu) return { ...userMenu, menu_code: USER_LIST_MENU, menu_name: '用户列表' } as MenuInfo
  if (isPositionManagementPage.value) return { ...(userManagementMenu.value || menus.value[0]), menu_code: POSITION_MENU, menu_name: '职位管理' } as MenuInfo
  return menus.value.find(item => item.menu_code === activeMenuCode.value) || menus.value[0]
})
const pageTitle = computed(() => activeMenu.value?.menu_name || (isPlatform.value ? '平台运营总览' : '客户运营工作台'))
const pageSubtitle = computed(() => {
  if (isUserCreatePage.value) return '创建账号、分配身份、绑定所属企业，并配置可访问菜单'
  if (isUserListPage.value) return '按公司、姓名、身份和状态筛选账号，支持编辑、禁用、重置密码和恢复'
  if (isPositionManagementPage.value) return '维护运营、销售、交付等职位模板，新增人员时从职位库选择'
  return isPlatform.value ? '企业运营、任务消耗、平台运行与风险情况' : '品牌曝光、推荐排名、信源分析与监测趋势'
})
const monitorSummary = ref<MonitorSummary | null>(null)
const loadingSummary = ref(false)
const syncingMonitorResults = ref(false)
let monitorSummaryTimer: number | null = null
let lastSummaryErrorAt = 0
const terminalTaskStatuses = new Set(['completed', 'partial_completed', 'failed', 'stopped'])
const stats = computed(() => {
  const summary = monitorSummary.value
  if (isPlatform.value) {
    return [
      ['企业客户', String(summary?.tenant_count ?? tenants.value.length), '来自企业库'],
      ['监测任务', String(summary?.task_count ?? 0), `${summary?.subtask_count ?? 0} 个子任务`],
      ['接口消耗', `${summary?.total_cost ?? 0}`, '模力真实扣费'],
      ['异常预警', String(summary?.failed_count ?? 0), '失败或待复核'],
    ]
  }
  return [
    ['总检测次数', String(summary?.subtask_count ?? 0), '累计检测结果'],
    ['品牌曝光率', `${summary?.mention_rate ?? 0}%`, '品牌被提及占比'],
    ['平均推荐排名', summary?.avg_rank ? String(summary.avg_rank) : '-', '越靠前越好'],
    ['监控词', String(monitorKeywordList.value.length), '当前监测范围'],
  ]
})
const chartTrend = computed(() => {
  const rows = monitorSummary.value?.daily_trend || []
  return rows.filter(item => item.value > 0)
})
const platformRanking = computed(() => monitorSummary.value?.platform_stats || [])
const selectedSourcePlatform = ref('all')
const sourceKeywordFilter = ref('')
const sourceStartDate = ref('')
const sourceEndDate = ref('')
const allSourceRanking = computed(() => monitorSummary.value?.source_stats || [])
const recentSubtasks = computed(() => monitorSummary.value?.recent_subtasks || [])
const platformLabelMap: Record<string, string> = {
  doubao: '豆包',
  doubao_mobile: '豆包（移动端）',
  deepseek: 'DeepSeek',
  deepseek_mobile: 'DeepSeek（移动端）',
  yuanbao: '元宝',
  kimi: 'Kimi',
  qianwen: '通义千问',
  quark: '夸克',
  baiduai: '百度 AI+',
  weibo_zhisou: '微博智搜',
  wenxinyiyan: '文心一言',
}
const monitorModeLabelMap: Record<string, string> = {
  search: '搜索检测',
  chat: '问答检测',
  web: '网页检测',
}
const monitorStatusLabelMap: Record<string, string> = {
  pending: '排队中',
  processing: '检测中',
  completed: '已完成',
  partial_completed: '部分完成',
  failed: '失败',
  stopped: '已停止',
}
const sentimentLabelMap: Record<string, string> = {
  positive: '正面',
  neutral: '中性',
  negative: '负面',
}
const supportedPlatforms = [
  { code: 'deepseek', name: 'DeepSeek' },
  { code: 'doubao', name: '豆包' },
  { code: 'yuanbao', name: '元宝' },
  { code: 'kimi', name: 'Kimi' },
  { code: 'qianwen', name: '通义千问' },
  { code: 'quark', name: '夸克' },
  { code: 'baiduai', name: '百度 AI+' },
  { code: 'weibo_zhisou', name: '微博智搜' },
  { code: 'wenxinyiyan', name: '文心一言' },
  { code: 'doubao_mobile', name: '豆包（移动端）' },
  { code: 'deepseek_mobile', name: 'DeepSeek（移动端）' },
]
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
const monitorResultPlatformOptions = computed(() => {
  const rows = monitorDetail.value?.subtasks || []
  return [...new Set(rows.map(item => item.platform).filter(Boolean))]
})
const monitorResultStatusOptions = computed(() => {
  const rows = monitorDetail.value?.subtasks || []
  return [...new Set(rows.map(item => item.status).filter(Boolean))]
})
const filteredMonitorSubtasks = computed(() => {
  const keyword = monitorResultFilters.keyword.trim().toLowerCase()
  return (monitorDetail.value?.subtasks || []).filter(item => {
    const platformMatched = monitorResultFilters.platform === 'all' || item.platform === monitorResultFilters.platform
    const statusMatched = monitorResultFilters.status === 'all' || item.status === monitorResultFilters.status
    const text = `${item.prompt || ''} ${item.answer_content || ''} ${item.mention_context || ''} ${(item.reference_list || []).map(source => source.title || source.site || source.url || '').join(' ')}`.toLowerCase()
    const keywordMatched = !keyword || text.includes(keyword)
    return platformMatched && statusMatched && keywordMatched
  })
})
const platformCoverage = computed(() => {
  const known = monitorSummary.value?.platform_stats || []
  const purchasedCodes = brandAsset.value?.monitored_platforms?.length ? brandAsset.value.monitored_platforms : []
  const codes = purchasedCodes.length ? purchasedCodes : known.map(item => item.platform)
  return codes.map((code, index) => {
    const row = known.find(item => item.platform === code)
    return {
      code,
      name: platformLabelMap[code] || code,
      rate: row?.mention_rate ?? 0,
      total: row?.total ?? 0,
      status: row?.completed ? '已返回' : index < 5 ? '监测中' : '待接入',
    }
  })
})
const customerPlatformServices = computed(() => {
  const purchased = new Set(brandAsset.value?.monitored_platforms || [])
  return supportedPlatforms.map(platform => ({
    ...platform,
    purchased: purchased.has(platform.code),
  }))
})
const purchasedPlatformCount = computed(() => customerPlatformServices.value.filter(item => item.purchased).length)
const sourcePlatformTabs = computed(() => {
  const counts = new Map<string, number>()
  allSourceRanking.value.forEach(source => {
    ;(source.platforms || []).forEach(platform => counts.set(platform, (counts.get(platform) || 0) + source.count))
  })
  return [
    { code: 'all', name: '全部信源', count: allSourceRanking.value.reduce((sum, source) => sum + source.count, 0) },
    ...Array.from(counts.entries())
      .map(([code, count]) => ({ code, name: platformLabelMap[code] || code, count }))
      .sort((a, b) => b.count - a.count),
  ]
})
const sourceRanking = computed(() => {
  const keyword = sourceKeywordFilter.value.trim().toLowerCase()
  const start = sourceStartDate.value ? new Date(`${sourceStartDate.value} 00:00:00`).getTime() : null
  const end = sourceEndDate.value ? new Date(`${sourceEndDate.value} 23:59:59`).getTime() : null
  return allSourceRanking.value.filter(source => {
    const platformMatched = selectedSourcePlatform.value === 'all' || (source.platforms || []).includes(selectedSourcePlatform.value)
    const text = `${source.title || ''} ${(source.keywords || []).join(' ')} ${(source.questions || []).join(' ')}`.toLowerCase()
    const keywordMatched = !keyword || text.includes(keyword)
    const sourceTime = source.latest_time ? new Date(source.latest_time).getTime() : null
    const startMatched = !start || (sourceTime && sourceTime >= start)
    const endMatched = !end || (sourceTime && sourceTime <= end)
    return platformMatched && keywordMatched && startMatched && endMatched
  })
})
const sourceCategoryLabels: Record<string, string> = {
  official: '官网/企业库',
  media: '行业媒体',
  qa: '问答社区',
  social: '社交媒体',
  encyclopedia: '百科',
}
function sourceCategory(source: { title?: string; url?: string }) {
  const text = `${source.title || ''} ${source.url || ''}`.toLowerCase()
  if (text.includes('baike') || text.includes('百科')) return 'encyclopedia'
  if (text.includes('zhihu') || text.includes('知乎') || text.includes('问答')) return 'qa'
  if (text.includes('weibo') || text.includes('微博') || text.includes('douyin') || text.includes('小红书')) return 'social'
  if (text.includes('sohu') || text.includes('163.com') || text.includes('媒体') || text.includes('新闻') || text.includes('资讯')) return 'media'
  return 'official'
}
const sourceTrendRows = computed(() => {
  const now = new Date()
  return Array.from({ length: 7 }).map((_, index) => {
    const day = new Date(now)
    day.setDate(now.getDate() - (6 - index))
    const label = `${String(day.getMonth() + 1).padStart(2, '0')}-${String(day.getDate()).padStart(2, '0')}`
    const value = sourceRanking.value.reduce((sum, source) => {
      if (!source.latest_time) return sum
      const sourceDate = new Date(source.latest_time)
      const matched = sourceDate.getFullYear() === day.getFullYear() && sourceDate.getMonth() === day.getMonth() && sourceDate.getDate() === day.getDate()
      return matched ? sum + source.count : sum
    }, 0)
    return { label, value }
  })
})
const sourceStructureRows = computed(() => platformRanking.value.slice(0, 6).map(platform => {
  const platformSources = sourceRanking.value.filter(source => (source.platforms || []).includes(platform.platform))
  const total = Math.max(1, platformSources.reduce((sum, source) => sum + source.count, 0))
  const categoryMap = platformSources.reduce((map, source) => {
    const category = sourceCategory(source)
    map[category] = (map[category] || 0) + source.count
    return map
  }, {} as Record<string, number>)
  return {
    platform: platform.platform,
    total,
    categories: Object.keys(sourceCategoryLabels).map(type => ({
      type,
      value: Math.round(((categoryMap[type] || 0) / total) * 100),
    })),
  }
}))
const contentPreferenceRows = computed(() => {
  const rows = [
    { name: '案例研究', keys: ['案例', '客户', '项目'] },
    { name: '产品指南', keys: ['产品', '服务', '功能'] },
    { name: '问答内容', keys: ['怎么样', '什么', '推荐', '对比'] },
    { name: '行业报告', keys: ['报告', '行业', '趋势'] },
    { name: '新闻资讯', keys: ['新闻', '资讯', '媒体'] },
  ].map(row => {
    const value = sourceRanking.value.reduce((sum, source) => {
      const text = `${source.title || ''} ${(source.questions || []).join(' ')}`.toLowerCase()
      return sum + (row.keys.some(key => text.includes(key.toLowerCase())) ? source.count : 0)
    }, 0)
    return { name: row.name, value }
  })
  const total = rows.reduce((sum, row) => sum + row.value, 0) || 1
  return rows.map(row => ({ ...row, percent: Math.round((row.value / total) * 100) }))
})
const monitorKeywordList = computed(() => [...new Set([...(brandAsset.value?.monitor_keywords || []), ...(brandAsset.value?.product_keywords || [])])].filter(Boolean))
const monitorKeywordTooltip = computed(() => monitorKeywordList.value.length ? monitorKeywordList.value.join('、') : '当前企业暂未配置监控词')
const statTooltipMap = computed<Record<string, string>>(() => ({
  总检测次数: '计算方式：监测问题数 × 已购买模型平台数。每个平台回答一个问题，计为 1 条检测结果。',
  品牌曝光率: '计算方式：已返回结果中提及品牌的数量 ÷ 已返回结果总量 × 100%。任务同步过程中会按最新返回结果重新计算。',
  平均推荐排名: '计算方式：所有已提及品牌结果的排名位置求平均。数值越小，说明推荐位置越靠前。',
  监控词: `当前监控词：${monitorKeywordTooltip.value}`,
}))
const sentimentTotal = computed(() => Object.values(monitorSummary.value?.sentiment_counts || {}).reduce((sum, value) => sum + value, 0))
const positiveRate = computed(() => {
  const total = sentimentTotal.value
  return total ? Math.round(((monitorSummary.value?.sentiment_counts?.['正面'] || 0) / total) * 100) : 0
})
const negativeRate = computed(() => {
  const total = sentimentTotal.value
  return total ? Math.round(((monitorSummary.value?.sentiment_counts?.['负面'] || 0) / total) * 100) : 0
})
const sourceTotalCount = computed(() => sourceRanking.value.reduce((sum, item) => sum + item.count, 0))
const recentQuestionGroups = computed(() => {
  const expectedPlatforms = brandAsset.value?.monitored_platforms?.length
    ? brandAsset.value.monitored_platforms
    : platformRanking.value.map(item => item.platform)
  const groups = new Map<string, {
    prompt: string
    tenant_name?: string | null
    platforms: string[]
    missing_platforms: string[]
    statuses: string[]
    completed: number
    total: number
    expected_total: number
    best_rank: number | null
    latest_time: string | null
  }>()
  recentSubtasks.value.forEach(item => {
    const prompt = item.prompt || '未命名检测问题'
    const row = groups.get(prompt) || {
      prompt,
      tenant_name: item.tenant_name,
      platforms: [],
      missing_platforms: [],
      statuses: [],
      completed: 0,
      total: 0,
      expected_total: expectedPlatforms.length || 0,
      best_rank: null,
      latest_time: null,
    }
    row.total += 1
    if (item.status === 'completed' || item.status === 'partial_completed') row.completed += 1
    if (item.platform && !row.platforms.includes(item.platform)) row.platforms.push(item.platform)
    if (item.status && !row.statuses.includes(item.status)) row.statuses.push(item.status)
    if (item.mention_position && (!row.best_rank || item.mention_position < row.best_rank)) row.best_rank = item.mention_position
    const itemTime = item.updated_at || null
    if (itemTime && (!row.latest_time || new Date(itemTime).getTime() > new Date(row.latest_time).getTime())) {
      row.latest_time = itemTime
    }
    groups.set(prompt, row)
  })
  return Array.from(groups.values()).map(row => ({
    ...row,
    expected_total: row.expected_total || row.platforms.length,
    missing_platforms: expectedPlatforms.filter(platform => !row.platforms.includes(platform)),
  }))
    .sort((a, b) => new Date(b.latest_time || 0).getTime() - new Date(a.latest_time || 0).getTime())
    .slice(0, 6)
})
const sentimentWords = computed(() => {
  const keywordMap = ['产品', '服务', '价格', '交付', '案例', '排名', '推荐', '引用', '口碑', '风险', '优势', '不足', '竞品', '体验', '响应']
  const text = recentSubtasks.value.map(item => `${item.prompt || ''} ${item.answer_content || ''} ${item.mention_context || ''}`).join(' ')
  const rows = keywordMap
    .map(word => ({ word, heat: (text.match(new RegExp(word, 'g')) || []).length }))
    .filter(item => item.heat > 0)
    .sort((a, b) => b.heat - a.heat)
  return rows.slice(0, 16)
})
const competitorCompareRows = computed(() => {
  const brandName = brandAsset.value?.brand_name || '艾迪亚'
  const rankingRows = recentSubtasks.value.flatMap(item => [
    ...((item.competitor_rankings || []) as any[]),
    ...((item.all_rankings || []) as any[]),
  ])
  const brandRows = new Map<string, { name: string; mention: number; rankTotal: number; rankCount: number; source: number }>()
  const addRank = (name: string, rank: number | null, source = 0) => {
    const key = name.trim()
    if (!key) return
    const row = brandRows.get(key) || { name: key, mention: 0, rankTotal: 0, rankCount: 0, source: 0 }
    row.mention += 1
    row.source += source
    if (rank) {
      row.rankTotal += rank
      row.rankCount += 1
    }
    brandRows.set(key, row)
  }
  recentSubtasks.value.forEach(item => {
    if (item.mention_position && brandName) addRank(brandName, item.mention_position, item.reference_count || item.reference_list?.length || 0)
  })
  rankingRows.forEach((item: any) => {
    const name = String(item.name || item.brandName || item.brand || item.keyword || '')
    const rank = Number(item.rank || item.position || item.rankNo || item.mentionPosition || 0) || null
    addRank(name, rank)
  })
  brandCompetitors.value.forEach(item => {
    if (!brandRows.has(item.name)) brandRows.set(item.name, { name: item.name, mention: 0, rankTotal: 0, rankCount: 0, source: 0 })
  })
  return Array.from(brandRows.values()).map(item => ({
    name: item.name,
    mention: item.mention,
    rank: item.rankCount ? Number((item.rankTotal / item.rankCount).toFixed(1)) : null,
    source: item.source,
    sentiment: item.name === brandName ? positiveRate.value : null,
  }))
})
const operationLogs = computed(() => operationLogRows.value.map(row => [row.created_at, row.operator_name, row.action_type, row.description, row.risk_level]))
const systemSettings = computed(() => systemConfigRows.value.map(row => [row.config_name, row.config_value, row.scope, row.status]))
const taskProgress = computed(() => {
  const total = monitorSummary.value?.subtask_count || 0
  const done = monitorSummary.value?.completed_count || 0
  return total ? Math.round((done / total) * 100) : 0
})
const functionalPage = computed(() => {
  const code = activeMenuCode.value
  const common = {
    kpis: [
      { label: '监测任务', value: String(monitorSummary.value?.task_count || 0), note: `${monitorSummary.value?.subtask_count || 0} 个子任务` },
      { label: '品牌提及率', value: `${monitorSummary.value?.mention_rate || 0}%`, note: '真实返回统计' },
      { label: '平均排名', value: monitorSummary.value?.avg_rank ? String(monitorSummary.value.avg_rank) : '-', note: '越小越靠前' },
      { label: '信源数量', value: String(sourceTotalCount.value || sourceRanking.value.length), note: '可点击溯源' },
    ],
  }
  const map: Record<string, any> = {
    'customer.batch': {
      title: '批量监控',
      subtitle: '按平台端配置定时巡检，客户只查看进度、结果和导出。',
      mode: 'tasks',
      actions: ['查看历史任务', '导出明细', '生成报告'],
      ...common,
    },
    'customer.geo': {
      title: 'GEO监测中心',
      subtitle: '按关键词、模型平台、推荐排名和历史检测查看真实监测结果。',
      mode: 'geo',
      actions: ['查看快照', '导出结果', '生成报告'],
      ...common,
    },
    'customer.sentiment': {
      title: '舆情监控',
      subtitle: '展示正面、中性、负面占比和风险建议。',
      mode: 'sentiment',
      actions: ['查看负面内容', '导出舆情报告'],
      ...common,
    },
    'customer.links': {
      title: '信源分析',
      subtitle: '检查官网、商城、媒体和问答来源是否被 AI 引用。',
      mode: 'sources',
      actions: ['打开信源', '加入报告'],
      ...common,
    },
    'customer.diagnosis': {
      title: '品牌诊断',
      subtitle: '把健康分、竞品差距、引用短板和优化建议集中展示。',
      mode: 'diagnosis',
      actions: ['查看建议', '生成诊断报告'],
      ...common,
    },
    'customer.competitor': {
      title: '竞品分析',
      subtitle: '按提及率、平均排名、信源数量和曝光差距对比竞品。',
      mode: 'competitor',
      actions: ['对比详情', '导出竞品报告'],
      ...common,
    },
    'customer.sources': {
      title: '信源分析',
      subtitle: '查看信源质量、原文链接和网页快照。',
      mode: 'sources',
      actions: ['打开信源', '导出信源'],
      ...common,
    },
    'customer.reports': {
      title: '报告中心',
      subtitle: '预览报告结论、图表、明细和建议，可导出 PDF / Word。',
      mode: 'report',
      actions: ['预览报告', '导出 PDF', '导出 Word'],
      ...common,
    },
    'customer.knowledge': {
      title: '企业知识库',
      subtitle: '客户侧仅允许上传文章类文件，平台端可查看各公司上传记录。',
      mode: 'knowledge',
      actions: ['上传 PDF / Word', '查看文件记录'],
      ...common,
    },
    'platform.plans': { title: '套餐额度', subtitle: '按企业查看接口消耗、额度余量和预警阈值。', mode: 'platform', actions: ['导出额度', '查看消耗'], ...common },
    'platform.admins': { title: '管理员账号', subtitle: '平台管理员、职位分配、权限配置和安全状态。', mode: 'platform', actions: ['新增管理员', '分配权限'], ...common },
    'platform.sentiment': { title: '舆情监控', subtitle: '运营端统一查看企业正负面内容、词云、处置依据和专项报告。', mode: 'sentiment', actions: ['导出舆情', '生成专项报告'], ...common },
    'platform.competitor': { title: '竞品分析', subtitle: '按企业品牌和竞品库做提及率、排名、来源和口碑对标。', mode: 'competitor', actions: ['导出竞品报告', '查看差距'], ...common },
    'platform.sources': { title: '信源分析', subtitle: '查看各模型信源、来源质量、跳转链接和快照证据。', mode: 'sources', actions: ['导出信源', '加入报告'], ...common },
    'platform.diagnosis': { title: '品牌诊断', subtitle: '运营人员选择企业和模型平台后，基于监测结果生成诊断依据与建议。', mode: 'diagnosis', actions: ['保存诊断', '生成报告'], ...common },
    'platform.models': { title: '模型平台', subtitle: '维护支持平台、移动端平台、模式和可用状态。', mode: 'platforms', actions: ['导出平台', '查看状态'], ...common },
    'platform.alerts': { title: '预警阈值', subtitle: '配置排名下滑、负面占比、失败率和额度预警。', mode: 'platform', actions: ['导出规则', '查看日志'], ...common },
    'platform.reports': { title: '报告中心', subtitle: '运营端生成、预览、编辑并导出客户报告。', mode: 'report', actions: ['生成预览', '导出 PDF', '导出 Word'], ...common },
    'platform.logs': { title: '操作日志', subtitle: '审计用户、企业、任务、权限和导出操作。', mode: 'logs', actions: ['导出日志', '筛选操作'], ...common },
    'platform.settings': { title: '系统配置', subtitle: '基础参数、数据上传接口、菜单权限和安全策略。', mode: 'settings', actions: ['导出配置', '操作日志'], ...common },
  }
  return map[code] || map['customer.realtime']
})

const userForm = reactive({
  username: '',
  password: 'Geo@2026',
  display_name: '',
  identity_types: [] as IdentityType[],
  identity_configs: {
    PLATFORM: {
      role_code: '',
      identity_name: '平台运营专员',
      position_id: null as number | null,
      tenant_id: null as number | null,
      tenant_name: '',
      menu_ids: [] as number[],
    },
    CUSTOMER: {
      role_code: '',
      identity_name: '客户企业成员',
      position_id: null as number | null,
      tenant_id: null as number | null,
      tenant_name: '',
      menu_ids: [] as number[],
    },
  },
})

const editForm = reactive({
  display_name: '',
  identity_types: [] as IdentityType[],
  identity_configs: {
    PLATFORM: {
      role_code: '',
      identity_name: '平台运营专员',
      position_id: null as number | null,
      tenant_id: null as number | null,
      tenant_name: '',
      menu_ids: [] as number[],
    },
    CUSTOMER: {
      role_code: '',
      identity_name: '客户企业成员',
      position_id: null as number | null,
      tenant_id: null as number | null,
      tenant_name: '',
      menu_ids: [] as number[],
    },
  },
})

const monitorTasks = ref<MonitorTask[]>([])
const monitorDetail = ref<{ task: MonitorTask; subtasks: MonitorSubtask[] } | null>(null)
const loadingMonitor = ref(false)
const monitorResultFilters = reactive({
  platform: 'all',
  status: 'all',
  keyword: '',
})
const operationLogRows = ref<OperationLogRecord[]>([])
const systemConfigRows = ref<SystemConfigRecord[]>([])
const trendChartRef = ref<HTMLDivElement | null>(null)
const exposureRankChartRef = ref<HTMLDivElement | null>(null)
const sentimentChartRef = ref<HTMLDivElement | null>(null)
const sentimentTrendChartRef = ref<HTMLDivElement | null>(null)
const diagnosisChartRef = ref<HTMLDivElement | null>(null)
const competitorChartRef = ref<HTMLDivElement | null>(null)
const sourceStructureChartRef = ref<HTMLDivElement | null>(null)
const sourceTrendChartRef = ref<HTMLDivElement | null>(null)
const chartInstances: ECharts[] = []
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

const sentimentPieRows = computed(() => {
  const counts = monitorSummary.value?.sentiment_counts || {}
  return Object.entries(counts)
    .filter(([, value]) => value > 0)
    .map(([name, value]) => ({ name, value }))
})

const diagnosisScore = computed(() => {
  if (!monitorSummary.value || !sentimentTotal.value) return 0
  const mentionScore = Math.min(100, monitorSummary.value.mention_rate || 0)
  const rankScore = monitorSummary.value.avg_rank ? Math.max(0, 100 - monitorSummary.value.avg_rank * 12) : 0
  return Math.round(mentionScore * 0.45 + positiveRate.value * 0.35 + rankScore * 0.2)
})

function getChart(el: HTMLDivElement | null) {
  if (!el) return null
  const current = getInstanceByDom(el)
  if (current) return current
  const instance = init(el)
  chartInstances.push(instance)
  return instance
}

function renderCharts() {
  nextTick(() => {
    const trendChart = getChart(trendChartRef.value)
    if (trendChart) {
      trendChart.setOption({
        color: ['#25b7d3'],
        grid: { left: 38, right: 18, top: 34, bottom: 32 },
        tooltip: { trigger: 'axis', formatter: (params: any) => {
          const item = params?.[0]
          return item ? `${item.name}<br/>曝光次数：${item.value}` : ''
        } },
        xAxis: { type: 'category', data: chartTrend.value.map(item => item.label), axisTick: { show: false } },
        yAxis: { type: 'value', splitLine: { lineStyle: { color: '#e8eff7' } } },
        series: [{ type: 'line', smooth: true, symbolSize: 8, data: chartTrend.value.map(item => item.value), label: { show: true, position: 'top', color: '#174078', fontWeight: 700 }, lineStyle: { width: 4 }, areaStyle: { color: new graphic.LinearGradient(0, 0, 0, 1, [{ offset: 0, color: 'rgba(37,183,211,.28)' }, { offset: 1, color: 'rgba(37,183,211,0)' }]) } }],
      })
    }

    const exposureRankChart = getChart(exposureRankChartRef.value)
    if (exposureRankChart) {
      const rows = platformRanking.value.slice(0, 8).reverse()
      exposureRankChart.setOption({
        color: ['#35c58f'],
        grid: { left: 86, right: 42, top: 18, bottom: 24 },
        tooltip: {
          trigger: 'axis',
          axisPointer: { type: 'shadow' },
          formatter: (params: any) => {
            const item = params?.[0]
            return item ? `${item.name}<br/>曝光率：${item.value}%` : ''
          },
        },
        xAxis: { type: 'value', max: 100, axisLabel: { formatter: '{value}%' }, splitLine: { lineStyle: { color: '#e8eff7' } } },
        yAxis: { type: 'category', data: rows.map(item => platformLabelMap[item.platform] || item.platform), axisTick: { show: false } },
        series: [{ type: 'bar', data: rows.map(item => item.mention_rate), barWidth: 16, label: { show: true, position: 'right', formatter: '{c}%', color: '#17324d', fontWeight: 700 }, itemStyle: { borderRadius: [0, 8, 8, 0], color: new graphic.LinearGradient(0, 0, 1, 0, [{ offset: 0, color: '#38a3ff' }, { offset: 1, color: '#35d39b' }]) } }],
      })
    }

    const pieChart = getChart(sentimentChartRef.value)
    if (pieChart) {
      pieChart.setOption({
        color: ['#58ddb0', '#4b8dff', '#ff6b7d', '#aab8c7'],
        tooltip: { trigger: 'item' },
        legend: { bottom: 0, itemWidth: 10, itemHeight: 10, textStyle: { color: '#23415f' } },
        series: [{ type: 'pie', radius: ['54%', '76%'], center: ['50%', '44%'], data: sentimentPieRows.value, label: { formatter: '{b} {d}%', color: '#17324d', fontWeight: 700 }, labelLine: { length: 10, length2: 8 } }],
        graphic: [{ type: 'text', left: 'center', top: '38%', style: { text: `${positiveRate.value}%\n正面占比`, textAlign: 'center', fill: '#10233f', fontSize: 22, fontWeight: 800, lineHeight: 30 } }],
      })
    }

    const trendMini = getChart(sentimentTrendChartRef.value)
    if (trendMini) {
      trendMini.setOption({
        color: ['#40d4c6'],
        grid: { left: 20, right: 12, top: 18, bottom: 20 },
        tooltip: { trigger: 'axis' },
        xAxis: { type: 'category', data: chartTrend.value.map(item => item.label), show: false },
        yAxis: { type: 'value', show: false },
        series: [{ type: 'line', smooth: true, symbolSize: 7, areaStyle: { color: 'rgba(64,212,198,.16)' }, data: chartTrend.value.map(item => item.value) }],
      })
    }

    const diagnosisChart = getChart(diagnosisChartRef.value)
    if (diagnosisChart) {
      diagnosisChart.setOption({
        series: [{ type: 'gauge', min: 0, max: 100, radius: '92%', axisLine: { lineStyle: { width: 14, color: [[0.35, '#ff6b7d'], [0.7, '#f6c85f'], [1, '#52d4a4']] } }, pointer: { width: 4 }, detail: { valueAnimation: true, formatter: '{value}分', fontSize: 28, fontWeight: 800, color: '#10233f' }, data: [{ value: diagnosisScore.value }] }],
      })
    }

    const compareChart = getChart(competitorChartRef.value)
    if (compareChart) {
      compareChart.setOption({
        color: ['#36cfc9'],
        grid: { left: 90, right: 30, top: 20, bottom: 20 },
        tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
        xAxis: { type: 'value', minInterval: 1, splitLine: { lineStyle: { color: '#e8eff7' } } },
        yAxis: { type: 'category', data: competitorCompareRows.value.map(item => item.name), axisTick: { show: false } },
        series: [{ type: 'bar', data: competitorCompareRows.value.map(item => item.mention), label: { show: true, position: 'right' }, itemStyle: { borderRadius: [0, 8, 8, 0], color: new graphic.LinearGradient(0, 0, 1, 0, [{ offset: 0, color: '#2f74ff' }, { offset: 1, color: '#49d8b7' }]) } }],
      })
    }

    const sourceStructureChart = getChart(sourceStructureChartRef.value)
    if (sourceStructureChart) {
      const categoryKeys = Object.keys(sourceCategoryLabels)
      sourceStructureChart.setOption({
        color: ['#326fea', '#20b8c9', '#35c58f', '#f0b84e', '#9b7ae7'],
        grid: { left: 88, right: 46, top: 18, bottom: 34 },
        tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, formatter: (params: any[]) => `${params?.[0]?.name || ''}<br/>${params.map(item => `${item.marker}${item.seriesName}：${item.value}%`).join('<br/>')}` },
        legend: { bottom: 0, itemWidth: 22, itemHeight: 5, textStyle: { color: '#526b89' } },
        xAxis: { type: 'value', max: 100, show: false },
        yAxis: { type: 'category', data: sourceStructureRows.value.map(item => platformLabelMap[item.platform] || item.platform), axisTick: { show: false }, axisLine: { show: false }, axisLabel: { color: '#55708f', fontWeight: 700 } },
        series: categoryKeys.map(type => ({
          name: sourceCategoryLabels[type],
          type: 'bar',
          stack: 'source',
          barWidth: 16,
          data: sourceStructureRows.value.map(row => row.categories.find(item => item.type === type)?.value || 0),
          itemStyle: { borderRadius: type === categoryKeys[categoryKeys.length - 1] ? [0, 8, 8, 0] : 0 },
        })),
      })
    }

    const sourceTrendChart = getChart(sourceTrendChartRef.value)
    if (sourceTrendChart) {
      sourceTrendChart.setOption({
        color: ['#2f74ea'],
        grid: { left: 34, right: 18, top: 26, bottom: 28 },
        tooltip: { trigger: 'axis' },
        xAxis: { type: 'category', data: sourceTrendRows.value.map(item => item.label), axisTick: { show: false }, axisLine: { show: false }, axisLabel: { color: '#6d84a1' } },
        yAxis: { type: 'value', show: false },
        series: [{
          type: 'line',
          smooth: true,
          symbolSize: 8,
          data: sourceTrendRows.value.map(item => item.value),
          label: { show: true, position: 'top', color: '#174078', fontWeight: 700 },
          lineStyle: { width: 4 },
          areaStyle: { color: new graphic.LinearGradient(0, 0, 0, 1, [{ offset: 0, color: 'rgba(47,116,234,.23)' }, { offset: 1, color: 'rgba(47,116,234,0)' }]) },
        }],
      })
    }
  })
}

function menuIcon(menu: MenuInfo) {
  return iconMap[menu.icon] || Gauge
}

function errorMessage(error: any) {
  const detail = error.response?.data?.detail
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
    return detail.map((item: any) => {
      const field = String(item.loc?.slice(-1)[0] || '字段')
      return `${fieldMap[field] || field}：${translate(item.msg || '')}`
    }).join('；')
  }
  if (typeof detail === 'string') return detail
  return error.message || '操作失败，请稍后重试'
}

function wait(ms: number) {
  return new Promise(resolve => window.setTimeout(resolve, ms))
}

async function withRetry<T>(loader: () => Promise<T>, retries = 2): Promise<T> {
  let lastError: unknown
  for (let index = 0; index <= retries; index += 1) {
    try {
      return await loader()
    } catch (error) {
      lastError = error
      if (index < retries) await wait(350 * (index + 1))
    }
  }
  throw lastError
}

async function loadUserManagement() {
  if (!isPlatform.value || !isUserManagementPage.value) return
  loadingUsers.value = isUserListPage.value
  try {
    const tenantRows = await withRetry(() => getTenants())
    tenants.value = tenantRows
    await loadAssignableOptions()
    if (isUserListPage.value) {
      managementUsers.value = await withRetry(() => getManagedUsers({
        keyword: userFilters.keyword.trim() || undefined,
        tenant_id: userFilters.tenant_id,
        identity_type: userFilters.identity_type,
        enabled: userFilters.enabled === '' ? null : userFilters.enabled === 'true',
        deleted: userFilters.deleted,
      }))
    }
  } catch (error: any) {
    ElMessage.error(`用户管理基础数据加载失败：${errorMessage(error)}`)
  } finally {
    loadingUsers.value = false
  }
}

async function loadMonitorTasks() {
  if (!isRealtimeMonitorPage.value) return
  loadingMonitor.value = true
  try {
    const [, tasks] = await Promise.all([
      loadBrandAssetData(),
      withRetry(() => getMonitorTasks()),
    ])
    monitorTasks.value = tasks
    const firstTaskId = !monitorDetail.value ? monitorTasks.value[0]?.task_id : ''
    if (firstTaskId) {
      window.setTimeout(() => {
        if (isRealtimeMonitorPage.value && !monitorDetail.value) selectMonitorTask(firstTaskId)
      }, 40)
    }
  } catch (error: any) {
    ElMessage.error(`检测任务加载失败：${errorMessage(error)}`)
  } finally {
    loadingMonitor.value = false
  }
}

async function syncPendingTasksFromSummary(summary: MonitorSummary) {
  if (syncingMonitorResults.value) return false
  const pendingTasks = (summary.recent_tasks || [])
    .filter(task => !terminalTaskStatuses.has(task.status))
    .slice(0, 5)
  if (!pendingTasks.length) return false
  syncingMonitorResults.value = true
  try {
    await Promise.allSettled(pendingTasks.map(task => withRetry(() => syncMonitorTask(task.task_id), 1)))
    return true
  } finally {
    syncingMonitorResults.value = false
  }
}

async function loadMonitorSummary(syncRemote = false) {
  if (!shouldLoadMonitorSummary.value && !syncRemote) return
  loadingSummary.value = true
  try {
    const summary = await withRetry(() => getMonitorSummary())
    monitorSummary.value = summary
    if (syncRemote) {
      const synced = await syncPendingTasksFromSummary(summary)
      if (synced) {
        monitorSummary.value = await withRetry(() => getMonitorSummary())
      }
    }
  } catch (error: any) {
    const now = Date.now()
    if (!monitorSummary.value && now - lastSummaryErrorAt > 120000) {
      ElMessage.warning(`首页数据暂时加载较慢，已保留当前页面：${errorMessage(error)}`)
      lastSummaryErrorAt = now
    } else {
      console.warn('首页真实数据加载失败', error)
    }
  } finally {
    loadingSummary.value = false
  }
}

async function loadPlatformSystemData() {
  if (!isPlatform.value) return
  const code = activeMenuCode.value
  try {
    if (code === 'platform.logs') operationLogRows.value = await withRetry(() => getOperationLogs())
    if (code === 'platform.settings') systemConfigRows.value = await withRetry(() => getSystemConfigs())
  } catch (error: any) {
    ElMessage.error(`平台配置数据读取失败：${errorMessage(error)}`)
  }
}

async function loadKnowledgeFiles() {
  const shouldLoad = activeMenuCode.value === 'customer.knowledge'
    || (isPlatform.value && isBrandAssetPage.value && enterpriseDetailMode.value && Boolean(brandForm.tenant_id))
  if (!shouldLoad) return
  loadingKnowledgeFiles.value = true
  try {
    knowledgeFiles.value = await withRetry(() => getKnowledgeFiles(isPlatform.value ? brandForm.tenant_id : null))
  } catch (error: any) {
    ElMessage.error(`知识库文件加载失败：${errorMessage(error)}`)
  } finally {
    loadingKnowledgeFiles.value = false
  }
}

async function handleKnowledgeUpload(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  uploadingKnowledgeFile.value = true
  try {
    await uploadKnowledgeFile(file, isPlatform.value ? brandForm.tenant_id : null)
    ElMessage.success('文件已上传')
    await loadKnowledgeFiles()
  } catch (error: any) {
    ElMessage.error(`文件上传失败：${errorMessage(error)}`)
  } finally {
    uploadingKnowledgeFile.value = false
  }
}

function formatFileSize(size: number) {
  if (size >= 1024 * 1024) return `${(size / 1024 / 1024).toFixed(1)}MB`
  if (size >= 1024) return `${(size / 1024).toFixed(1)}KB`
  return `${size}B`
}

function formatDateTime(value?: string | null) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  const pad = (num: number) => String(num).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function textToList(value: string) {
  return value.split(/[\n,，;；]/).map(item => item.trim()).filter(Boolean)
}

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

async function loadBrandAssetData() {
  if (!isBrandAssetPage.value && !isRealtimeMonitorPage.value && !(isDashboardPage.value && !isPlatform.value)) return
  loadingBrand.value = true
  try {
    if (isPlatform.value && isBrandAssetPage.value && !tenants.value.length) {
      tenants.value = await withRetry(() => getTenants())
    }
    if (isPlatform.value && isBrandAssetPage.value && !enterpriseDetailMode.value) {
      return
    }
    const response = await withRetry(() => getBrandAsset(isPlatform.value ? brandForm.tenant_id : null))
    brandAsset.value = response.asset
    brandCompetitors.value = response.competitors
    fillBrandForm(response.asset, response.tenant_id)
    if (!response.asset && isPlatform.value) {
      brandForm.company_full_name = tenants.value.find(item => item.id === response.tenant_id)?.name || ''
    }
    fillCompetitorRows(response.competitors)
  } catch (error: any) {
    ElMessage.error(`品牌资产加载失败：${errorMessage(error)}`)
  } finally {
    loadingBrand.value = false
  }
}

async function loadEnterpriseList() {
  if (!isPlatform.value || !isBrandAssetPage.value) return
  loadingBrand.value = true
  try {
    tenants.value = await withRetry(() => getTenants())
  } catch (error: any) {
    ElMessage.error(`企业列表加载失败：${errorMessage(error)}`)
  } finally {
    loadingBrand.value = false
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
  } catch (error: any) {
    ElMessage.error(`企业详情加载失败：${errorMessage(error)}`)
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
  } catch (error: any) {
    ElMessage.error(`品牌资产保存失败：${errorMessage(error)}`)
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
  } catch (error: any) {
    ElMessage.error(`企业新增失败：${errorMessage(error)}`)
  } finally {
    loadingBrand.value = false
  }
}

async function removeTenant(tenant: TenantInfo) {
  const actionLabel = stopTenantActionLabel(tenant)
  await ElMessageBox.confirm(`确认${actionLabel}「${tenant.name}」吗？操作后客户账号将停用，定时监测不再提交，历史数据仍保留。`, actionLabel, { type: 'warning' })
  loadingBrand.value = true
  try {
    await deleteTenant(tenant.id)
    await loadEnterpriseList()
    ElMessage.success(`企业已${actionLabel}`)
  } catch (error: any) {
    ElMessage.error(`${actionLabel}失败：${errorMessage(error)}`)
  } finally {
    loadingBrand.value = false
  }
}

async function restoreTenantService(tenant: TenantInfo) {
  await ElMessageBox.confirm(`确认恢复「${tenant.name}」的服务吗？恢复后客户账号将重新启用；如果服务开始日期还没到，企业仍会保持未开始状态。`, '恢复服务', { type: 'warning' })
  loadingBrand.value = true
  try {
    await restoreTenant(tenant.id)
    await loadEnterpriseList()
    ElMessage.success('企业服务已恢复')
  } catch (error: any) {
    ElMessage.error(`恢复服务失败：${errorMessage(error)}`)
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
  } catch (error: any) {
    ElMessage.error(`竞品保存失败：${errorMessage(error)}`)
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
  await ElMessageBox.confirm('确认移除这个竞品吗？后续提交检测任务将不再带上它。', '移除竞品', { type: 'warning' })
  loadingBrand.value = true
  try {
    await deleteCompetitor(row.id, brandForm.tenant_id)
    await loadBrandAssetData()
    ElMessage.success('竞品已移除')
  } catch (error: any) {
    ElMessage.error(`竞品移除失败：${errorMessage(error)}`)
  } finally {
    loadingBrand.value = false
  }
}

async function selectMonitorTask(taskId: string) {
  loadingMonitor.value = true
  try {
    monitorDetail.value = await withRetry(() => getMonitorTaskDetail(taskId))
  } catch (error: any) {
    ElMessage.error(`任务详情加载失败：${errorMessage(error)}`)
  } finally {
    loadingMonitor.value = false
  }
}

function resetUserFilters() {
  userFilters.keyword = ''
  userFilters.tenant_id = null
  userFilters.identity_type = ''
  userFilters.enabled = ''
  userFilters.deleted = false
  loadUserManagement()
}

async function loadAssignableOptions() {
  // 两种身份都预加载，勾选后可以立即展示对应角色和菜单。
  const [platformMenus, platformRoles, platformPositions, customerMenus, customerRoles, customerPositions] = await Promise.all([
    withRetry(() => getManagementMenus('PLATFORM')),
    withRetry(() => getManagementRoles('PLATFORM')),
    withRetry(() => getManagementPositions('PLATFORM')),
    withRetry(() => getManagementMenus('CUSTOMER')),
    withRetry(() => getManagementRoles('CUSTOMER')),
    withRetry(() => getManagementPositions('CUSTOMER')),
  ])
  assignMenus.PLATFORM = platformMenus
  assignMenus.CUSTOMER = customerMenus
  roles.PLATFORM = platformRoles
  roles.CUSTOMER = customerRoles
  positions.PLATFORM = platformPositions
  positions.CUSTOMER = customerPositions
  if (!userForm.identity_configs.PLATFORM.role_code) userForm.identity_configs.PLATFORM.role_code = defaultRoleForIdentityType('PLATFORM')
  if (!userForm.identity_configs.CUSTOMER.role_code) userForm.identity_configs.CUSTOMER.role_code = defaultRoleForIdentityType('CUSTOMER')
  if (!userForm.identity_configs.PLATFORM.position_id) applyPositionToConfig('PLATFORM', userForm, platformPositions[0]?.id || null)
  if (!userForm.identity_configs.CUSTOMER.position_id) applyPositionToConfig('CUSTOMER', userForm, customerPositions[0]?.id || null)
  if (!userForm.identity_configs.PLATFORM.menu_ids.length) userForm.identity_configs.PLATFORM.menu_ids = platformMenus.map(item => item.id)
  if (!userForm.identity_configs.CUSTOMER.menu_ids.length) userForm.identity_configs.CUSTOMER.menu_ids = customerMenus.map(item => item.id)
  if (!userForm.identity_configs.CUSTOMER.tenant_id && tenants.value[0]) userForm.identity_configs.CUSTOMER.tenant_id = tenants.value[0].id
  syncUserFormCreatableIdentities()
}

function applyPositionToConfig(type: IdentityType, form: typeof userForm | typeof editForm, positionId: number | null) {
  const config = form.identity_configs[type]
  config.position_id = positionId
  const position = positions[type].find(item => item.id === positionId)
  if (!position) return
  config.role_code = position.role_code
  config.identity_name = position.position_name
  config.menu_ids = position.menu_ids.length ? [...position.menu_ids] : assignMenus[type].map(item => item.id)
}

function resetPositionForm(type: IdentityType = positionForm.identity_type) {
  editingPosition.value = null
  positionForm.position_name = ''
  positionForm.identity_type = type
  positionForm.role_code = defaultRoleForIdentityType(type)
  positionForm.description = ''
  positionForm.menu_ids = []
  positionForm.status = true
}

function openCreatePosition(type: IdentityType = 'PLATFORM') {
  resetPositionForm(type)
  positionDialog.value = true
}

function editPosition(row: PositionInfo) {
  editingPosition.value = row
  positionForm.position_name = row.position_name
  positionForm.identity_type = row.identity_type
  positionForm.role_code = row.role_code
  positionForm.description = row.description || ''
  positionForm.menu_ids = [...row.menu_ids]
  positionForm.status = true
  positionDialog.value = true
}

async function loadPositionManagement() {
  if (!isPlatform.value || !isPositionManagementPage.value) return
  await loadAssignableOptions()
  positionRows.value = [...positions.PLATFORM, ...positions.CUSTOMER]
  if (!positionForm.role_code) resetPositionForm(positionForm.identity_type)
}

async function savePosition() {
  if (!positionForm.position_name.trim()) {
    ElMessage.warning('请填写职位名称')
    return
  }
  if (!positionForm.role_code) {
    ElMessage.warning('职位底层权限未初始化，请刷新后重试')
    return
  }
  savingPosition.value = true
  try {
    const payload = {
      position_name: positionForm.position_name.trim(),
      identity_type: positionForm.identity_type,
      role_code: positionForm.role_code,
      description: positionForm.description.trim() || null,
      menu_ids: positionForm.menu_ids,
      status: positionForm.status,
    }
    if (editingPosition.value) {
      await updateManagementPosition(editingPosition.value.id, payload)
      ElMessage.success('职位已更新')
    } else {
      await createManagementPosition(payload)
      ElMessage.success('职位已新增')
    }
    positions.PLATFORM = await withRetry(() => getManagementPositions('PLATFORM'))
    positions.CUSTOMER = await withRetry(() => getManagementPositions('CUSTOMER'))
    positionRows.value = [...positions.PLATFORM, ...positions.CUSTOMER]
    positionDialog.value = false
    resetPositionForm(positionForm.identity_type)
  } catch (error: any) {
    ElMessage.error(errorMessage(error))
  } finally {
    savingPosition.value = false
  }
}

async function removePosition(row: PositionInfo) {
  try {
    await ElMessageBox.confirm(`确认删除职位「${row.position_name}」吗？如果已有人员使用该职位，系统会阻止删除。`, '删除职位', { type: 'warning' })
    await deleteManagementPosition(row.id)
    ElMessage.success('职位已删除')
    positions.PLATFORM = await withRetry(() => getManagementPositions('PLATFORM'))
    positions.CUSTOMER = await withRetry(() => getManagementPositions('CUSTOMER'))
    positionRows.value = [...positions.PLATFORM, ...positions.CUSTOMER]
    if (editingPosition.value?.id === row.id) resetPositionForm(row.identity_type)
  } catch (error: any) {
    if (error === 'cancel') return
    ElMessage.error(errorMessage(error))
  }
}

function syncUserFormCreatableIdentities() {
  const allowed = creatableIdentityTypes.value
  userForm.identity_types = userForm.identity_types.filter(type => allowed.includes(type))
  if (!userForm.identity_types.length && allowed.length) userForm.identity_types = [allowed[0]]
}

watch([isUserCreatePage, creatableIdentityTypes], ([isCreatePage]) => {
  if (isCreatePage) syncUserFormCreatableIdentities()
}, { immediate: true })

function canSelectEditIdentity(type: IdentityType) {
  const alreadyOwned = editingUser.value?.identities.some(identity => identity.identity_type === type)
  if (alreadyOwned) return true
  return type === 'PLATFORM' ? canCreatePlatformUser.value : canCreateCustomerUser.value
}

async function submitUser() {
  syncUserFormCreatableIdentities()
  if (!userForm.username || !userForm.display_name || !userForm.password || !userForm.identity_types.length) {
    ElMessage.warning(creatableIdentityTypes.value.length ? '请补全账号、姓名、密码，并至少勾选一个登录身份' : '当前职位没有新增用户身份的权限')
    return
  }
  if (userForm.identity_types.includes('PLATFORM') && !canCreatePlatformUser.value) {
    ElMessage.warning('当前职位无权新增平台运营端用户')
    return
  }
  if (userForm.identity_types.includes('CUSTOMER') && !canCreateCustomerUser.value) {
    ElMessage.warning('当前职位无权新增客户企业端用户')
    return
  }
  if (userForm.username.trim().length < 3) {
    ElMessage.warning('登录账号至少填写 3 个字符')
    return
  }
  if (userForm.display_name.trim().length < 2) {
    ElMessage.warning('用户姓名至少填写 2 个字符')
    return
  }
  if (userForm.password.length < 6) {
    ElMessage.warning('初始密码至少填写 6 个字符')
    return
  }
  if (userForm.identity_types.includes('CUSTOMER')) {
    const customerConfig = userForm.identity_configs.CUSTOMER
    if (!customerConfig.tenant_id && !customerConfig.tenant_name.trim()) {
      ElMessage.warning('客户企业端身份需要选择或输入所属企业')
      return
    }
  }
  const identities = userForm.identity_types.map((type) => {
    const config = userForm.identity_configs[type]
    return {
      identity_type: type,
      role_code: config.role_code,
      identity_name: config.identity_name || null,
      position_id: config.position_id,
      tenant_id: type === 'CUSTOMER' ? config.tenant_id : null,
      tenant_name: type === 'CUSTOMER' && !config.tenant_id ? config.tenant_name.trim() : null,
      menu_ids: [],
    }
  })
  if (identities.some(item => !item.role_code || !item.position_id)) {
    ElMessage.warning('请补全已勾选身份的职位')
    return
  }
  creatingUser.value = true
  try {
    await createManagedUser({
      username: userForm.username,
      password: userForm.password,
      display_name: userForm.display_name,
      identities,
    })
    ElMessage.success('用户已新增，并完成菜单权限分配')
    userForm.username = ''
    userForm.display_name = ''
    activeMenuCode.value = USER_LIST_MENU
    userMenuExpanded.value = true
    await loadUserManagement()
  } catch (error: any) {
    ElMessage.error(errorMessage(error))
  } finally {
    creatingUser.value = false
  }
}

function identityPayloadFromForm(form: typeof userForm | typeof editForm) {
  return form.identity_types.map((type) => {
    const config = form.identity_configs[type]
    return {
      identity_type: type,
      role_code: config.role_code,
      identity_name: config.identity_name || null,
      position_id: config.position_id,
      tenant_id: type === 'CUSTOMER' ? config.tenant_id : null,
      tenant_name: type === 'CUSTOMER' && !config.tenant_id ? config.tenant_name.trim() : null,
      menu_ids: [],
    }
  })
}

function validateEditForm() {
  if (!editForm.display_name.trim() || editForm.display_name.trim().length < 2) {
    ElMessage.warning('用户姓名至少填写 2 个字符')
    return false
  }
  if (!editForm.identity_types.length) {
    ElMessage.warning('至少保留一个登录身份')
    return false
  }
  if (editForm.identity_types.includes('CUSTOMER')) {
    const customerConfig = editForm.identity_configs.CUSTOMER
    if (!customerConfig.tenant_id && !customerConfig.tenant_name.trim()) {
      ElMessage.warning('客户企业端身份需要选择或输入所属企业')
      return false
    }
  }
  if (editForm.identity_types.some(type => !editForm.identity_configs[type].position_id || !editForm.identity_configs[type].role_code)) {
    ElMessage.warning('请补全已勾选身份的职位')
    return false
  }
  return true
}

async function openEditUser(user: ManagedUser) {
  await loadAssignableOptions()
  editingUser.value = user
  editForm.display_name = user.display_name
  editForm.identity_types = user.identities.map(identity => identity.identity_type)
  for (const type of ['PLATFORM', 'CUSTOMER'] as IdentityType[]) {
    const current = user.identities.find(identity => identity.identity_type === type)
    editForm.identity_configs[type].role_code = current?.role_code || roles[type][0]?.role_code || ''
    editForm.identity_configs[type].position_id = current?.position_id || positions[type].find(item => item.role_code === editForm.identity_configs[type].role_code)?.id || null
    editForm.identity_configs[type].identity_name = current?.identity_name || (type === 'PLATFORM' ? '平台运营专员' : '客户企业成员')
    editForm.identity_configs[type].tenant_id = current?.tenant_id || (type === 'CUSTOMER' ? tenants.value[0]?.id || null : null)
    editForm.identity_configs[type].tenant_name = ''
    editForm.identity_configs[type].menu_ids = positions[type].find(item => item.id === editForm.identity_configs[type].position_id)?.menu_ids || []
  }
  editDialog.value = true
}

async function saveEditUser() {
  if (!editingUser.value || !validateEditForm()) return
  try {
    await updateManagedUser(editingUser.value.id, {
      display_name: editForm.display_name,
      identities: identityPayloadFromForm(editForm),
    })
    ElMessage.success('用户信息和权限已更新')
    editDialog.value = false
    await loadUserManagement()
  } catch (error: any) {
    ElMessage.error(errorMessage(error))
  }
}

function openPasswordDialog(user: ManagedUser) {
  editingUser.value = user
  resetPassword.value = 'Geo@2026'
  passwordDialog.value = true
}

async function submitResetPassword() {
  if (!editingUser.value) return
  if (resetPassword.value.length < 6) {
    ElMessage.warning('新密码至少填写 6 个字符')
    return
  }
  try {
    await resetManagedUserPassword(editingUser.value.id, resetPassword.value)
    ElMessage.success('密码已重置')
    passwordDialog.value = false
  } catch (error: any) {
    ElMessage.error(errorMessage(error))
  }
}

async function toggleUserStatus(user: ManagedUser) {
  try {
    await setManagedUserStatus(user.id, !user.status)
    ElMessage.success(user.status ? '账号已禁用' : '账号已启用')
    await loadUserManagement()
  } catch (error: any) {
    ElMessage.error(errorMessage(error))
  }
}

async function deleteUser(user: ManagedUser) {
  try {
    await ElMessageBox.confirm(
      `确认删除「${user.display_name}」吗？删除后账号不可登录，默认列表不再展示，可在“已删除账号”中恢复。`,
      '删除用户',
      { confirmButtonText: '确认删除', cancelButtonText: '取消', type: 'warning' },
    )
    await deleteManagedUser(user.id)
    ElMessage.success('账号已删除，可在已删除账号中恢复')
    await loadUserManagement()
  } catch (error: any) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(errorMessage(error))
  }
}

async function restoreUser(user: ManagedUser) {
  try {
    await restoreManagedUser(user.id)
    ElMessage.success('账号已恢复')
    userFilters.deleted = false
    await loadUserManagement()
  } catch (error: any) {
    ElMessage.error(errorMessage(error))
  }
}

async function switchIdentity(identityId: number) {
  if (identityId === auth.session?.identity.id) return
  await auth.switchIdentity(identityId)
  activeMenuCode.value = normalizeMenuCode(auth.allowedMenus[0]?.menu_code || '')
  userMenuExpanded.value = activeMenuCode.value.startsWith('platform.users') || activeMenuCode.value === POSITION_MENU
  ElMessage.success(`已切换至${identityDisplayName(auth.session?.identity)}`)
  await router.replace(auth.portalPath)
}

function selectMenu(menu: MenuInfo) {
  activeMenuCode.value = normalizeMenuCode(menu.menu_code)
  userMenuExpanded.value = menu.menu_code === 'platform.users' ? true : false
}

function toggleUserSubmenu() {
  userMenuExpanded.value = !userMenuExpanded.value
}

function identityDisplayName(identity?: { position_name?: string | null; identity_name?: string | null; position_id?: number | null; role_code?: string; identity_type?: IdentityType }) {
  if (!identity) return ''
  if (identity.position_name) return identity.position_name
  if (identity.position_id && identity.identity_type) {
    const position = positions[identity.identity_type].find(item => item.id === identity.position_id)
    if (position) return position.position_name
  }
  return identity.identity_name || (identity.identity_type === 'PLATFORM' ? '平台运营端' : '客户企业端')
}

function defaultRoleForIdentityType(type: IdentityType) {
  return type === 'PLATFORM'
    ? (roles.PLATFORM.find(role => role.role_code === 'PLATFORM_OPERATOR')?.role_code || roles.PLATFORM[0]?.role_code || '')
    : (roles.CUSTOMER.find(role => role.role_code === 'TENANT_ADMIN')?.role_code || roles.CUSTOMER[0]?.role_code || '')
}

function ensureActiveMenuAllowed() {
  const allowedCodes = auth.allowedMenus.map(menu => normalizeMenuCode(menu.menu_code))
  if (!allowedCodes.includes(activeMenuCode.value)) {
    activeMenuCode.value = normalizeMenuCode(auth.allowedMenus[0]?.menu_code || '')
  }
  userMenuExpanded.value = activeMenuCode.value.startsWith('platform.users') || activeMenuCode.value === POSITION_MENU
}

async function refreshMenusFromServer() {
  try {
    await auth.refreshSession()
    ensureActiveMenuAllowed()
  } catch {
    auth.logout()
    router.replace('/login')
  }
}

function logout() {
  auth.logout()
  router.replace('/login')
}

function demoAction(action: string) {
  ElMessage.success(`${action}：演示动作已触发，正式项目可在这里接入导出、上传或详情接口`)
}

function navigateToMenu(menuCode: string) {
  activeMenuCode.value = normalizeMenuCode(menuCode)
}

watch(activeMenuCode, loadUserManagement)
watch(activeMenuCode, loadPositionManagement)
watch(activeMenuCode, loadMonitorTasks)
watch(activeMenuCode, () => loadMonitorSummary(isDashboardPage.value))
watch(activeMenuCode, loadKnowledgeFiles)
watch(activeMenuCode, loadPlatformSystemData)
watch([activeMenuCode, monitorSummary, brandAsset, brandCompetitors, selectedSourcePlatform, sourceKeywordFilter, sourceStartDate, sourceEndDate], renderCharts, { deep: true })
watch(sourcePlatformTabs, tabs => {
  if (!tabs.some(tab => tab.code === selectedSourcePlatform.value)) {
    selectedSourcePlatform.value = 'all'
  }
})

const regionOptions = [
  { code: '', name: '全部区域' },
  { code: '110000', name: '北京' },
  { code: '120000', name: '天津' },
  { code: '130000', name: '河北' },
  { code: '140000', name: '山西' },
  { code: '150000', name: '内蒙古' },
  { code: '210000', name: '辽宁' },
  { code: '220000', name: '吉林' },
  { code: '230000', name: '黑龙江' },
  { code: '310000', name: '上海' },
  { code: '320000', name: '江苏' },
  { code: '330000', name: '浙江' },
  { code: '340000', name: '安徽' },
  { code: '350000', name: '福建' },
  { code: '360000', name: '江西' },
  { code: '370000', name: '山东' },
  { code: '410000', name: '河南' },
  { code: '420000', name: '湖北' },
  { code: '430000', name: '湖南' },
  { code: '440000', name: '广东' },
  { code: '450000', name: '广西' },
  { code: '460000', name: '海南' },
  { code: '500000', name: '重庆' },
  { code: '510000', name: '四川' },
  { code: '520000', name: '贵州' },
  { code: '530000', name: '云南' },
  { code: '540000', name: '西藏' },
  { code: '610000', name: '陕西' },
  { code: '620000', name: '甘肃' },
  { code: '630000', name: '青海' },
  { code: '640000', name: '宁夏' },
  { code: '650000', name: '新疆' },
  { code: '710000', name: '台湾' },
  { code: '810000', name: '香港' },
  { code: '820000', name: '澳门' },
]
watch(activeMenuCode, () => {
  if (isBrandAssetPage.value) {
    enterpriseDetailMode.value = false
    loadEnterpriseList()
  } else if (!isRealtimeMonitorPage.value) {
    loadBrandAssetData()
  }
})
watch(() => positionForm.identity_type, (type) => {
  positionForm.role_code = defaultRoleForIdentityType(type)
  positionForm.menu_ids = positionForm.menu_ids.filter(menuId => positionFormMenus.value.some(menu => menu.id === menuId))
})
onMounted(refreshMenusFromServer)
onMounted(loadUserManagement)
onMounted(loadPositionManagement)
onMounted(loadMonitorTasks)
onMounted(() => {
  if (shouldLoadMonitorSummary.value) loadMonitorSummary(isDashboardPage.value)
  monitorSummaryTimer = window.setInterval(() => {
    if (document.visibilityState === 'visible' && shouldLoadMonitorSummary.value) {
      loadMonitorSummary(isDashboardPage.value)
    }
  }, 30000)
})
onMounted(loadKnowledgeFiles)
onMounted(loadPlatformSystemData)
onMounted(() => {
  renderCharts()
  window.addEventListener('resize', renderCharts)
})
onMounted(() => {
  if (isBrandAssetPage.value) loadEnterpriseList()
  else loadBrandAssetData()
})
onUnmounted(() => {
  if (monitorSummaryTimer) window.clearInterval(monitorSummaryTimer)
  window.removeEventListener('resize', renderCharts)
  chartInstances.forEach(instance => instance.dispose())
})
</script>

<template>
  <div class="app-shell portal-shell">
    <aside class="sidebar">
      <div class="brand"><div class="brand-mark">G</div><div><strong>GEO Monitor</strong><span>{{ isPlatform ? '平台运营端' : '客户企业端' }}</span></div></div>
      <div class="portal-tag"><ShieldCheck v-if="isPlatform" /><Building2 v-else /><span><b>{{ identityDisplayName(auth.session?.identity) }}</b><small>{{ auth.session?.identity.tenant_name || 'GEO Monitor 平台' }}</small></span></div>
      <nav class="nav">
        <template v-for="menu in menus" :key="menu.menu_code">
        <template v-if="menu.menu_code === 'platform.users'">
          <button
            type="button"
            class="nav-item nav-parent"
            :class="{ active: activeMenuCode.startsWith('platform.users') || activeMenuCode === POSITION_MENU, expanded: userMenuExpanded }"
            @click="toggleUserSubmenu"
          >
            <component :is="menuIcon(menu)" class="nav-icon" /><span>{{ menu.menu_name }}</span><ChevronDown class="nav-caret" />
          </button>
          <div v-if="userMenuExpanded" class="sub-nav">
            <a
              v-if="hasUserCreateMenu"
              href="#"
              class="sub-nav-item"
              :class="{ active: activeMenuCode === USER_CREATE_MENU }"
              @click.prevent="activeMenuCode = USER_CREATE_MENU"
            >用户新增</a>
            <a
              v-if="hasUserListMenu"
              href="#"
              class="sub-nav-item"
              :class="{ active: activeMenuCode === USER_LIST_MENU }"
              @click.prevent="activeMenuCode = USER_LIST_MENU"
            >用户列表</a>
            <a
              v-if="hasPositionMenu"
              href="#"
              class="sub-nav-item"
              :class="{ active: activeMenuCode === POSITION_MENU }"
              @click.prevent="activeMenuCode = POSITION_MENU"
            >职位管理</a>
          </div>
        </template>
        <a
          v-else
          href="#"
          class="nav-item"
          :class="{ active: menu.menu_code === activeMenuCode }"
          @click.prevent="selectMenu(menu)"
        >
          <component :is="menuIcon(menu)" class="nav-icon" /><span>{{ menu.menu_name }}</span>
        </a>
        </template>
      </nav>
    </aside>
    <section class="workspace">
      <header class="topbar">
        <div class="crumb">GEO Monitor / {{ pageTitle }}</div>
        <div class="top-actions">
          <el-dropdown v-if="(auth.session?.identities.length || 0) > 1" trigger="click" @command="switchIdentity">
            <button class="identity-switch"><span><small>当前职位</small><b>{{ identityDisplayName(auth.session?.identity) }}</b></span><ChevronDown /></button>
            <template #dropdown><el-dropdown-menu><el-dropdown-item v-for="identity in auth.session?.identities" :key="identity.id" :command="identity.id" :disabled="identity.id === auth.session?.identity.id"><ShieldCheck v-if="identity.identity_type === 'PLATFORM'" /><Building2 v-else />{{ identityDisplayName(identity) }}</el-dropdown-item></el-dropdown-menu></template>
          </el-dropdown>
          <div class="user-chip"><span>{{ auth.session?.user.display_name.slice(0, 1) }}</span><div><b>{{ auth.session?.user.display_name }}</b><small>{{ auth.session?.user.username }}</small></div></div>
          <button class="icon-action" title="退出登录" @click="logout"><LogOut /></button>
        </div>
      </header>
      <main class="content portal-content">
        <div class="page-head"><div><h1>{{ pageTitle }}</h1><p>{{ pageSubtitle }}</p></div><span class="live-status"><i></i> 数据服务正常</span></div>

        <PositionPage
          v-if="isPositionManagementPage"
          :position-rows="positionRows"
          :open-create-position="openCreatePosition"
          :edit-position="editPosition"
          :remove-position="removePosition"
        />

        <UserCreatePage
          v-else-if="isUserCreatePage"
          :user-form="userForm"
          :can-create-platform-user="canCreatePlatformUser"
          :can-create-customer-user="canCreateCustomerUser"
          :creatable-identity-types="creatableIdentityTypes"
          :positions="positions"
          :tenants="tenants"
          :creating-user="creatingUser"
          :apply-position-to-config="applyPositionToConfig"
          :permission-groups-for-form="permissionGroupsForForm"
          :menu-icon="menuIcon"
          :submit-user="submitUser"
        />

        <UserListPage
          v-else-if="isUserListPage"
          :loading-users="loadingUsers"
          :management-users="managementUsers"
          :user-filters="userFilters"
          :tenants="tenants"
          :load-user-management="loadUserManagement"
          :reset-user-filters="resetUserFilters"
          :identity-display-name="identityDisplayName"
          :open-edit-user="openEditUser"
          :open-password-dialog="openPasswordDialog"
          :toggle-user-status="toggleUserStatus"
          :delete-user="deleteUser"
          :restore-user="restoreUser"
          @create-user="activeMenuCode = USER_CREATE_MENU"
        />

        <section v-else-if="isBrandAssetPage" class="brand-page">
          <article v-if="!enterpriseDetailMode" class="panel enterprise-list-panel">
            <div class="panel-head">
              <div>
                <h2>企业列表</h2>
                <p>先选择客户企业，再进入详情维护品牌资产、竞品库和自动监测配置。</p>
              </div>
              <div class="detail-actions">
                <button class="filter-reset-btn" :disabled="loadingBrand" @click="loadEnterpriseList">刷新企业</button>
                <button class="primary-btn small-btn" @click="tenantDialog = true">新增企业</button>
              </div>
            </div>
            <div class="enterprise-filter-bar">
              <label>
                <span>企业名称</span>
                <input v-model="enterpriseFilters.keyword" placeholder="输入企业名称 / 编码筛选" />
              </label>
              <label>
                <span>服务状态</span>
                <select v-model="enterpriseFilters.expiry">
                  <option value="all">全部企业</option>
                  <option value="active">服务中</option>
                  <option value="pending">未开始服务</option>
                  <option value="expired">服务已到期</option>
                  <option value="stopped">已停止服务</option>
                </select>
              </label>
              <button class="filter-reset-btn" @click="enterpriseFilters.keyword = ''; enterpriseFilters.expiry = 'active'">重置</button>
            </div>
            <div class="enterprise-table">
              <div v-for="tenant in filteredTenants" :key="tenant.id" class="enterprise-row" :class="{ stopped: !tenant.status || isTenantExpired(tenant) || isTenantPending(tenant) }">
                <div class="enterprise-main">
                  <b>{{ tenant.name }}</b>
                  <small>{{ tenantServicePeriod(tenant) }}</small>
                </div>
                <div class="enterprise-metrics">
                  <span><small>监测企业</small><b>{{ tenant.name }}</b></span>
                  <span><small>服务状态</small><b class="status-pill" :class="{ dark: !tenant.status || isTenantExpired(tenant) || isTenantPending(tenant) }">{{ tenantServiceLabel(tenant) }}</b></span>
                  <span><small>自动监测</small><b>每日 3 次</b></span>
                </div>
                <div class="enterprise-actions">
                  <button class="filter-reset-btn" @click="openEnterpriseInfo(tenant)">详情</button>
                  <button class="filter-search-btn" @click="openEnterpriseDetail(tenant)">编辑</button>
                  <button class="filter-reset-btn" @click="openEnterpriseDetail(tenant); demoAction('已打开企业诊断配置')">诊断</button>
                  <button v-if="canStopTenantService(tenant)" class="danger-text-btn" @click="removeTenant(tenant)">{{ stopTenantActionLabel(tenant) }}</button>
                  <button v-else-if="canRestoreTenantService(tenant)" class="filter-search-btn" @click="restoreTenantService(tenant)">恢复服务</button>
                </div>
              </div>
              <div v-if="!loadingBrand && !filteredTenants.length" class="mini-empty">暂无符合筛选条件的企业。</div>
            </div>
          </article>

          <article v-else class="panel brand-asset-panel">
            <div class="panel-head">
              <div>
                <h2>企业资料与监控配置</h2>
                <p>平台运营端维护客户企业、品牌词和竞品库，系统按配置定时提交监测任务。</p>
              </div>
              <div class="detail-actions">
                <button class="filter-reset-btn" @click="backToEnterpriseList">返回列表</button>
                <button v-if="canEditEnterpriseTab(enterpriseDetailTab)" class="primary-btn small-btn" :disabled="loadingBrand" @click="() => submitBrandAsset()">保存当前配置</button>
              </div>
            </div>
            <div class="enterprise-detail-tabs">
              <button v-for="tab in visibleEnterpriseTabs" :key="tab.code" :class="{ active: enterpriseDetailTab === tab.code }" @click="enterpriseDetailTab = tab.code">{{ tab.name }}</button>
            </div>
            <div v-if="enterpriseDetailTab === 'profile'" class="brand-form-grid">
              <label><span>企业全称</span><input v-model="brandForm.company_full_name" :disabled="!canEditEnterpriseTab('profile')" placeholder="例如 北京艾亿欧科技有限公司" /></label>
              <label><span>服务开始日期</span><input v-model="brandForm.service_start_date" :disabled="!canEditEnterpriseTab('profile')" type="date" /></label>
              <label><span>服务结束日期</span><input v-model="brandForm.service_end_date" :disabled="!canEditEnterpriseTab('profile')" type="date" /></label>
              <label><span>官网 / 主站</span><input v-model="brandForm.official_url" :disabled="!canEditEnterpriseTab('profile')" placeholder="https://..." /></label>
              <label>
                <span>企业状态</span>
                <div class="readonly-status" :class="{ stopped: !enterpriseFormServiceActive }">{{ enterpriseFormServiceLabel }}</div>
              </label>
              <label class="region-field"><span>服务地区</span><select v-model="brandForm.region_code" :disabled="!canEditEnterpriseTab('profile')"><option v-for="region in regionOptions" :key="region.code" :value="region.code">{{ region.name }}</option></select></label>
              <label class="form-field-full"><span>品牌说明</span><textarea v-model="brandForm.description" :disabled="!canEditEnterpriseTab('profile')" rows="4" placeholder="用于内部识别，不直接展示给客户"></textarea></label>
            </div>
            <div v-if="enterpriseDetailTab === 'profile' && canEditEnterpriseTab('profile')" class="section-save-actions keyword-save-actions">
              <button class="filter-search-btn" :disabled="loadingBrand" @click="submitBrandAsset('企业资料已保存')">保存企业资料</button>
            </div>
            <section v-if="enterpriseDetailTab === 'keywords'" class="keyword-group-panel">
              <div class="panel-head">
                <div>
                  <h2>监测词组配置</h2>
                  <p>一个监测关键词绑定多个露出词。监测关键词用于生成问题，露出词用于判断回答里是否有效提及。</p>
                </div>
                <button v-if="canEditEnterpriseTab('keywords')" class="filter-search-btn" @click="addKeywordGroup">新增词组</button>
              </div>
              <div class="keyword-group-list">
                <div v-for="(group, index) in keywordGroupRows" :key="group.id || `kw-${index}`" class="keyword-group-card">
                  <div class="keyword-group-main">
                    <label><span>监测关键词</span><input v-model="group.monitor_keyword" :disabled="!canEditEnterpriseTab('keywords')" placeholder="例如 北京艾迪亚控股集团有限公司" /></label>
                    <label><span>状态</span><select v-model="group.status" :disabled="!canEditEnterpriseTab('keywords')"><option :value="true">启用</option><option :value="false">停用</option></select></label>
                    <button v-if="canEditEnterpriseTab('keywords')" class="danger-text-btn" @click="removeKeywordGroup(index)">删除</button>
                  </div>
                  <div class="exposure-term-box">
                    <span>露出词</span>
                    <div class="exposure-tags">
                      <i v-for="(term, termIndex) in group.exposure_terms" :key="`${index}-${term}`">
                        {{ term }}
                        <button v-if="canEditEnterpriseTab('keywords')" @click="removeExposureTerm(group, termIndex)">×</button>
                      </i>
                      <input
                        placeholder="输入后回车添加"
                        :disabled="!canEditEnterpriseTab('keywords')"
                        @keyup.enter="addExposureTerm(group, ($event.target as HTMLInputElement).value); ($event.target as HTMLInputElement).value = ''"
                      />
                    </div>
                  </div>
                </div>
                <div v-if="!keywordGroupRows.length" class="mini-empty">暂无监测词组，请先新增一个。</div>
              </div>
              <div class="section-save-actions keyword-save-actions">
                <button v-if="canEditEnterpriseTab('keywords')" class="filter-search-btn" :disabled="loadingBrand" @click="submitBrandAsset('监测词配置已保存')">保存监测词配置</button>
              </div>
            </section>
            <section v-if="enterpriseDetailTab === 'platforms'" class="schedule-box">
              <div class="panel-head">
                <div>
                  <h2 class="title-with-help">
                    购买模型与监测范围
                    <el-tooltip placement="top" effect="light" content="问题来源：企业全称生成4个基础问题；监测关键词每个生成2个行业问题；竞品每个生成2个对比问题；企业别名每个生成1个口碑问题。系统去重后最多取50个问题，再乘以勾选的平台数生成子任务。">
                      <HelpCircle />
                    </el-tooltip>
                  </h2>
                  <p>后续定时任务只提交这里勾选的平台，每家企业可以不同。</p>
                </div>
                <div class="section-save-actions">
                  <span>{{ brandForm.monitored_platforms.length }} 个平台</span>
                  <button v-if="canEditEnterpriseTab('platforms')" class="filter-search-btn" :disabled="loadingBrand" @click="submitBrandAsset('平台配置已保存')">保存平台配置</button>
                </div>
              </div>
              <div class="platform-check-grid">
                <label v-for="platform in supportedPlatforms" :key="platform.code" class="platform-check">
                  <input v-model="brandForm.monitored_platforms" type="checkbox" :value="platform.code" :disabled="!canEditEnterpriseTab('platforms')" />
                  <span>{{ platform.name }}</span>
                </label>
              </div>
            </section>
            <section v-if="enterpriseDetailTab === 'schedule'" class="schedule-box">
              <div class="panel-head">
                <div><h2>自动监测计划</h2><p>用于后续调度器按企业配置自动提交检测任务。</p></div>
                <button v-if="canEditEnterpriseTab('schedule')" class="filter-search-btn" :disabled="loadingBrand" @click="submitBrandAsset('监测计划已保存')">保存监测计划</button>
              </div>
              <div class="schedule-type-grid">
                <label><input v-model="brandForm.schedule_type" type="radio" value="daily_times" :disabled="!canEditEnterpriseTab('schedule')" /><span>每天</span></label>
                <label><input v-model="brandForm.schedule_type" type="radio" value="weekly" :disabled="!canEditEnterpriseTab('schedule')" /><span>每周</span></label>
                <label><input v-model="brandForm.schedule_type" type="radio" value="monthly" :disabled="!canEditEnterpriseTab('schedule')" /><span>每月</span></label>
              </div>
              <div class="brand-form-grid">
                <div class="schedule-time-picker">
                  <div class="schedule-time-title">
                    <span>执行时间</span>
                    <button v-if="canEditEnterpriseTab('schedule')" class="filter-reset-btn" @click="addScheduleTime">新增时间</button>
                  </div>
                  <div class="schedule-time-list">
                    <div v-for="(_, index) in brandForm.schedule_times" :key="`schedule-time-${index}`">
                      <input v-model="brandForm.schedule_times[index]" type="time" step="300" :disabled="!canEditEnterpriseTab('schedule')" />
                      <button v-if="canEditEnterpriseTab('schedule')" class="danger-text-btn" @click="removeScheduleTime(index)">删除</button>
                    </div>
                  </div>
                  <div v-if="!brandForm.schedule_times.length" class="mini-empty compact-empty">暂无执行时间，请点击“新增时间”配置。</div>
                </div>
                <label v-if="brandForm.schedule_type === 'weekly'"><span>每周执行日</span><select v-model="brandForm.schedule_weekdays" :disabled="!canEditEnterpriseTab('schedule')" multiple><option :value="1">周一</option><option :value="2">周二</option><option :value="3">周三</option><option :value="4">周四</option><option :value="5">周五</option><option :value="6">周六</option><option :value="7">周日</option></select></label>
                <label v-if="brandForm.schedule_type === 'monthly'"><span>每月执行日期</span><textarea v-model="brandForm.schedule_month_days_text" :disabled="!canEditEnterpriseTab('schedule')" rows="3" placeholder="一行一个，例如 1、15、28"></textarea></label>
              </div>
            </section>
          </article>

          <section v-if="enterpriseDetailMode && ['competitors', 'files'].includes(enterpriseDetailTab)" class="brand-layout">
            <article v-if="enterpriseDetailTab === 'competitors'" class="panel competitor-panel">
              <div class="panel-head">
                <div><h2>竞品监控库</h2><p>只维护竞品名称，系统提交任务时自动带入竞品用于排名、提及率和对比分析。</p></div>
              </div>
              <div class="competitor-tag-editor">
                <div class="competitor-add-row">
                  <input v-model="competitorNameInput" :disabled="!canEditEnterpriseTab('competitors')" placeholder="输入竞品名称，例如 新榜" @keyup.enter="addCompetitorTag" />
                  <button v-if="canEditEnterpriseTab('competitors')" class="filter-search-btn" @click="addCompetitorTag">新增竞品</button>
                </div>
                <div class="competitor-tags">
                  <span v-for="(row, index) in competitorRows" :key="row.id || `new-${index}`">
                    {{ row.name || '未命名竞品' }}
                    <button v-if="canEditEnterpriseTab('competitors')" @click="removeCompetitorRow(row, index)">×</button>
                  </span>
                </div>
                <div v-if="!competitorRows.length" class="mini-empty">还没有竞品。建议先录入 3-5 个核心竞品，方便后续自动对比。</div>
              </div>
            </article>
            <article v-if="enterpriseDetailTab === 'files'" class="panel competitor-panel">
              <div class="panel-head">
                <div><h2>客户上传文件</h2><p>查看当前企业从客户端上传的 PDF、Word、Markdown 或 TXT 原文件记录。</p></div>
                <span>{{ knowledgeFiles.length }} 个文件</span>
              </div>
              <div class="knowledge-files">
                <div v-if="loadingKnowledgeFiles" class="mini-empty">文件列表加载中...</div>
                <div v-for="file in knowledgeFiles" :key="file.id">
                  <b>{{ file.original_name }}</b>
                  <span>{{ file.file_ext.toUpperCase() }} · {{ formatFileSize(file.file_size) }} · 已上传</span>
                </div>
                <div v-if="!loadingKnowledgeFiles && !knowledgeFiles.length" class="mini-empty">该企业暂未上传文件。</div>
              </div>
            </article>
          </section>
        </section>

        <section v-else-if="isRealtimeMonitorPage" class="monitor-page">
          <article class="panel monitor-submit-panel">
            <div class="panel-head">
              <div><h2>定时监测结果</h2><p>系统按平台端配置自动检测，客户侧只查看结果、快照和趋势，不开放手动提交。</p></div>
              <span>平台自动巡检</span>
            </div>
            <div class="monitor-brand-card">
              <div>
                <span>当前监测企业</span>
                <b>{{ brandAsset?.company_full_name || '未配置品牌资产' }}</b>
                <small>主品牌：{{ brandAsset?.brand_name || '-' }} · 简称：{{ brandAsset?.brand_short_name || '-' }}</small>
              </div>
              <div>
                <span>自动带入</span>
                <b>{{ brandCompetitors.length }} 个竞品</b>
                <small>{{ brandCompetitors.slice(0, 4).map(item => item.name).join(' / ') || '请先维护竞品库' }}</small>
              </div>
            </div>
            <div class="monitor-schedule-grid">
              <div><b>09:30</b><span>早间曝光巡检</span></div>
              <div><b>14:30</b><span>午间排名复核</span></div>
              <div><b>20:30</b><span>晚间结果汇总</span></div>
              <div><b>平台范围</b><span>{{ platformCoverage.map(item => item.name).join(' / ') }}</span></div>
            </div>
          </article>

          <section class="monitor-layout">
            <article class="panel monitor-task-list">
              <div class="panel-head"><h2>本地任务</h2><span>{{ monitorTasks.length }} 条</span></div>
              <button v-for="task in monitorTasks" :key="task.task_id" class="monitor-task-item" :class="{ active: monitorDetail?.task.task_id === task.task_id }" @click="selectMonitorTask(task.task_id)">
                <b>{{ task.monitor_keywords || '未填品牌词' }}</b>
                <small>{{ monitorStatusLabelMap[task.status] || task.status }} · {{ task.completed_items }}/{{ task.total_items }}</small>
                <em>{{ task.platforms.map(item => platformLabelMap[item.platform] || item.platform).join('、') }}</em>
              </button>
              <div v-if="!loadingMonitor && !monitorTasks.length" class="mini-empty">暂无任务，先提交一次检测。</div>
            </article>

            <article class="panel monitor-result-panel">
              <div class="panel-head">
                <div><h2>检测结果</h2><p>{{ monitorDetail ? '模型回答、推荐排名、信源与快照' : '选择任务后查看详情' }}</p></div>
                <button class="filter-search-btn" :disabled="loadingMonitor" @click="loadMonitorTasks">刷新列表</button>
              </div>
              <template v-if="monitorDetail">
                <div class="monitor-result-filters">
                  <label>
                    <span>平台</span>
                    <select v-model="monitorResultFilters.platform">
                      <option value="all">全部平台</option>
                      <option v-for="platform in monitorResultPlatformOptions" :key="platform" :value="platform">{{ platformLabelMap[platform] || platform }}</option>
                    </select>
                  </label>
                  <label>
                    <span>状态</span>
                    <select v-model="monitorResultFilters.status">
                      <option value="all">全部状态</option>
                      <option v-for="status in monitorResultStatusOptions" :key="status" :value="status">{{ monitorStatusLabelMap[status] || status }}</option>
                    </select>
                  </label>
                  <label class="monitor-filter-keyword">
                    <span>关键词</span>
                    <input v-model="monitorResultFilters.keyword" placeholder="搜问题、回答、信源" />
                  </label>
                  <button type="button" @click="monitorResultFilters.platform = 'all'; monitorResultFilters.status = 'all'; monitorResultFilters.keyword = ''">重置</button>
                  <em>{{ filteredMonitorSubtasks.length }} / {{ monitorDetail.subtasks.length }} 条</em>
                </div>
                <div class="monitor-summary">
                  <span>状态 <b>{{ monitorStatusLabelMap[monitorDetail.task.status] || monitorDetail.task.status }}</b></span>
                  <span>完成 <b>{{ monitorDetail.task.completed_items }}/{{ monitorDetail.task.total_items }}</b></span>
                  <span>失败 <b>{{ monitorDetail.task.failed_items }}</b></span>
                  <span v-if="monitorDetail.task.last_error">错误 <b>{{ monitorDetail.task.last_error }}</b></span>
                </div>
                <div v-for="subtask in filteredMonitorSubtasks" :key="subtask.subtask_id" class="monitor-subtask-card">
                  <div class="subtask-head">
                    <div><b>{{ platformLabelMap[subtask.platform || ''] || subtask.platform || '-' }} / {{ monitorModeLabelMap[subtask.mode || ''] || subtask.mode || '-' }}</b><small>{{ subtask.prompt }}</small></div>
                    <span>{{ monitorStatusLabelMap[subtask.status || ''] || subtask.status || '-' }}</span>
                  </div>
                  <div class="subtask-metrics">
                    <span>提及排名：{{ subtask.mention_position || '未提及' }}</span>
                    <span>情感：{{ sentimentLabelMap[subtask.sentiment || ''] || '暂无' }}</span>
                    <span>费用：{{ subtask.amount ?? '待返回' }}</span>
                    <a v-if="subtask.page_screenshot" :href="subtask.page_screenshot" target="_blank">打开快照</a>
                    <span v-else class="muted-metric">快照：未返回</span>
                  </div>
                  <p v-if="subtask.mention_context" class="mention-context">{{ subtask.mention_context }}</p>
                  <pre v-if="subtask.answer_content" class="answer-preview">{{ subtask.answer_content }}</pre>
                  <div v-if="subtask.reference_list.length" class="source-list">
                    <b>信源列表</b>
                    <a v-for="source in subtask.reference_list.slice(0, 6)" :key="`${subtask.subtask_id}-${source.index}-${source.url}`" :href="source.url" target="_blank">{{ source.title || source.site || source.url }}</a>
                  </div>
                  <p v-if="subtask.error_message" class="danger-copy">{{ subtask.error_message }}</p>
                </div>
                <div v-if="!filteredMonitorSubtasks.length" class="mini-empty">没有匹配当前筛选条件的检测结果。</div>
              </template>
              <div v-else class="mini-empty">提交或选择任务后，这里会展示模型回答、排名、来源和快照。</div>
            </article>
          </section>
        </section>

        <template v-else>
          <template v-if="isDashboardPage">
          <PlatformDashboardPage
            v-if="isPlatform"
            :platform-label-map="platformLabelMap"
            :monitor-status-label-map="monitorStatusLabelMap"
            :navigate-to="navigateToMenu"
          />
          <template v-else>
          <section class="portal-hero">
            <div>
              <span class="hero-kicker">{{ isPlatform ? '平台运营端 · 真实接口数据' : '品牌监测总览' }}</span>
              <h2>{{ isPlatform ? '企业 GEO 监测运营总览' : '企业 AI 可见度指挥舱' }}</h2>
              <p>{{ isPlatform ? '按企业、模型平台、任务状态和接口消耗汇总真实监测数据。' : '汇总品牌曝光、推荐排名、信源分析与风险变化，辅助判断品牌在主流模型中的可见度。' }}</p>
            </div>
            <div class="hero-sync" :class="{ loading: loadingSummary }">
              <Activity />
              <span>{{ syncingMonitorResults ? '远端同步中' : loadingSummary ? '数据更新中' : '数据已校验' }}</span>
            </div>
          </section>

          <section v-if="!isPlatform" class="customer-service-panel panel">
            <div class="panel-head">
              <div>
                <h2>模型平台覆盖</h2>
                <p>展示当前品牌在主流模型平台中的监测覆盖情况。</p>
              </div>
              <span>{{ purchasedPlatformCount }} / {{ customerPlatformServices.length }} 已购买</span>
            </div>
            <div class="customer-platform-grid">
              <div v-for="platform in customerPlatformServices" :key="platform.code" class="customer-platform-card" :class="{ purchased: platform.purchased }">
                <span>{{ platform.purchased ? '服务中' : '未开通' }}</span>
                <b>{{ platform.name }}</b>
              </div>
            </div>
          </section>

          <section class="portal-stats">
            <article v-for="item in stats" :key="item[0]">
              <span class="stat-title">
                {{ item[0] }}
                <el-tooltip v-if="statTooltipMap[item[0]]" placement="top" effect="light" :content="statTooltipMap[item[0]]">
                  <HelpCircle />
                </el-tooltip>
              </span>
              <strong>{{ item[1] }}</strong>
              <small>{{ item[2] }}</small>
            </article>
          </section>

          <section class="portal-main">
            <article class="panel trend-panel">
              <div class="panel-head"><h2>曝光次数趋势</h2><span>最近 7 天品牌被提及次数</span></div>
              <div v-if="chartTrend.length" ref="trendChartRef" class="echart-box trend-echart"></div>
              <div v-else class="mini-empty chart-empty">暂无真实趋势数据，定时任务完成后自动展示。</div>
            </article>

            <article class="panel">
              <div class="panel-head"><h2>曝光率排行图</h2><span>{{ platformRanking.length }} 个平台</span></div>
              <div v-if="platformRanking.length" ref="exposureRankChartRef" class="echart-box exposure-rank-echart"></div>
              <div v-else class="mini-empty">真实任务还在处理中，完成后这里会展示平台曝光排行。</div>
            </article>
          </section>

          <section class="portal-main insight-main">
            <article class="panel source-analysis-panel">
              <div class="panel-head">
                <div><h2>信源分析</h2><p>按平台查看信源、监控词和引用次数</p></div>
                <span>{{ sourceRanking.length }} 条信源</span>
              </div>
              <div v-if="sourcePlatformTabs.length > 1" class="source-platform-tabs">
                <button
                  v-for="tab in sourcePlatformTabs"
                  :key="tab.code"
                  :class="{ active: selectedSourcePlatform === tab.code }"
                  @click="selectedSourcePlatform = tab.code"
                >
                  {{ tab.name }} <em>{{ tab.count }}</em>
                </button>
              </div>
              <div v-if="sourceRanking.length" class="source-scroll-body">
                <div class="source-rank-grid source-rich-grid">
                  <a v-for="source in sourceRanking" :key="source.url" :href="source.url" target="_blank">
                    <b>{{ source.title }}</b>
                    <span class="source-meta"><strong>{{ source.count }}</strong> 次引用</span>
                    <div class="source-chip-row">
                      <i v-for="platform in (source.platforms || []).slice(0, 4)" :key="`${source.url}-${platform}`">{{ platformLabelMap[platform] || platform }}</i>
                    </div>
                    <div class="source-keywords">
                      <small v-for="keyword in (source.keywords || []).slice(0, 3)" :key="`${source.url}-${keyword}`">{{ keyword }}</small>
                    </div>
                  </a>
                </div>
              </div>
              <div v-else class="mini-empty">待模型返回信源后展示，可直接点击跳转。</div>
            </article>

            <article class="panel">
              <div class="panel-head"><h2>最近检测</h2><span>{{ recentQuestionGroups.length }} 组问题</span></div>
              <div v-if="recentQuestionGroups.length" class="recent-check-list grouped-check-list">
                <div v-for="item in recentQuestionGroups" :key="item.prompt">
                  <div class="recent-question-head">
                    <b>{{ item.prompt }}</b>
                    <em>{{ item.platforms.length }}/{{ item.expected_total }} 已返回</em>
                  </div>
                  <div class="recent-platform-tags">
                    <i v-for="platform in item.platforms.slice(0, 6)" :key="`${item.prompt}-${platform}`">{{ platformLabelMap[platform] || platform }}</i>
                  </div>
                  <div v-if="item.missing_platforms.length" class="recent-missing-platforms">
                    待返回：{{ item.missing_platforms.slice(0, 5).map(platform => platformLabelMap[platform] || platform).join('、') }}{{ item.missing_platforms.length > 5 ? '等' : '' }}
                  </div>
                  <small>{{ item.tenant_name || '当前企业' }} / {{ item.best_rank ? `最佳第${item.best_rank}位` : '未返回排名' }} / {{ formatDateTime(item.latest_time) }}</small>
                </div>
              </div>
              <div v-else class="mini-empty">暂无已完成结果，当前真实任务正在处理中。</div>
            </article>
          </section>
          </template>
          </template>

          <section v-else class="feature-page">
            <article class="feature-hero panel">
              <div>
                <span class="hero-kicker">{{ isPlatform ? '平台运营端' : '客户企业端' }}</span>
                <h2>{{ functionalPage.title }}</h2>
                <p>{{ functionalPage.subtitle }}</p>
              </div>
              <div class="feature-actions">
                <button v-for="action in functionalPage.actions" :key="action" :class="action.includes('导出') || action.includes('生成') || action.includes('上传') ? 'primary-btn small-btn' : 'filter-reset-btn'" @click="demoAction(action)">{{ action }}</button>
              </div>
            </article>

            <section class="portal-stats">
              <article v-for="item in functionalPage.kpis" :key="item.label">
                <span>{{ item.label }}</span>
                <strong>{{ item.value }}</strong>
                <small>{{ item.note }}</small>
              </article>
            </section>

            <section class="feature-grid">
              <article class="panel feature-primary">
                <div class="panel-head">
                  <h2>{{ functionalPage.mode === 'sentiment' ? '情感占比' : functionalPage.mode === 'diagnosis' ? '品牌健康分' : functionalPage.mode === 'report' ? '报告预览' : functionalPage.mode === 'knowledge' ? '文章文件上传' : functionalPage.mode === 'sources' ? '信源明细' : '业务明细' }}</h2>
                  <span>真实数据</span>
                </div>

                <div v-if="functionalPage.mode === 'sources'" class="source-table-workbench">
                  <div class="source-tip">
                    <HelpCircle />
                    <span>AI 大模型结果存在动态变化，不同时间、不同平台的信源结果会有差异；本页展示已同步的真实检测结果。</span>
                  </div>
                  <div class="source-analytics-grid">
                    <section class="source-analysis-card source-structure-card">
                      <div class="panel-head"><h2>信源结构对比</h2><span>不同模型引用来源占比</span></div>
                      <div v-if="sourceStructureRows.length" ref="sourceStructureChartRef" class="echart-box source-structure-echart"></div>
                      <div v-else class="mini-empty chart-empty">暂无信源结构数据。</div>
                    </section>
                    <section class="source-analysis-card">
                      <div class="panel-head"><h2>高频信源排行</h2><span>近30天引用次数</span></div>
                      <div v-if="sourceRanking.length" class="source-top-list">
                        <div v-for="(source, index) in sourceRanking.slice(0, 5)" :key="source.url">
                          <i>{{ index + 1 }}</i>
                          <b>{{ source.title }}</b>
                          <strong>{{ source.count }}</strong>
                        </div>
                      </div>
                      <div v-else class="mini-empty">暂无高频信源。</div>
                    </section>
                    <section class="source-analysis-card">
                      <div class="panel-head"><h2>信源引用趋势</h2><span>近7日新增引用</span></div>
                      <div v-if="sourceTrendRows.some(item => item.value > 0)" ref="sourceTrendChartRef" class="echart-box source-trend-echart"></div>
                      <div v-else class="mini-empty chart-empty">暂无信源趋势数据。</div>
                    </section>
                    <section class="source-analysis-card">
                      <div class="panel-head"><h2>内容类型偏好</h2><span>按引用占比</span></div>
                      <div class="content-preference-list">
                        <div v-for="item in contentPreferenceRows" :key="item.name">
                          <span>{{ item.name }}</span>
                          <i><b :style="{ width: `${item.percent}%` }"></b></i>
                          <em>{{ item.percent }}%</em>
                        </div>
                      </div>
                    </section>
                  </div>

                  <div v-if="sourcePlatformTabs.length > 1" class="source-platform-cards">
                    <button
                      v-for="tab in sourcePlatformTabs"
                      :key="tab.code"
                      :class="{ active: selectedSourcePlatform === tab.code }"
                      @click="selectedSourcePlatform = tab.code"
                    >
                      <Link2 />
                      <b>{{ tab.name }}</b>
                      <span>{{ tab.count }} 次引用</span>
                    </button>
                  </div>
                  <div class="source-query-bar">
                    <input v-model="sourceKeywordFilter" placeholder="输入来源 / 监控词 / 问题关键词搜索" />
                    <input v-model="sourceStartDate" type="date" />
                    <span>→</span>
                    <input v-model="sourceEndDate" type="date" />
                    <button class="filter-search-btn">查询</button>
                    <button class="filter-reset-btn" @click="sourceKeywordFilter = ''; sourceStartDate = ''; sourceEndDate = ''; selectedSourcePlatform = 'all'">重置</button>
                  </div>
                  <div v-if="sourceRanking.length" class="source-data-table">
                    <div class="source-data-head">
                      <span>序号</span><span>信源 / 关联问题</span><span>被引用平台</span><span>监控词</span><span>最近检测时间</span><span>引用次数</span><span>操作</span>
                    </div>
                    <div v-for="(source, index) in sourceRanking" :key="source.url" class="source-data-row">
                      <span>{{ index + 1 }}</span>
                      <div>
                        <b>{{ source.title }}</b>
                        <small>{{ (source.questions || []).slice(0, 2).join('；') || '暂无关联问题' }}</small>
                      </div>
                      <div class="source-table-tags">
                        <i v-for="platform in (source.platforms || [])" :key="`${source.url}-${platform}`">{{ platformLabelMap[platform] || platform }}</i>
                      </div>
                      <div class="source-table-tags muted-tags">
                        <i v-for="keyword in (source.keywords || []).slice(0, 4)" :key="`${source.url}-${keyword}`">{{ keyword }}</i>
                      </div>
                      <span>{{ formatDateTime(source.latest_time) }}</span>
                      <strong>{{ source.count }}</strong>
                      <div class="source-actions">
                        <a :href="source.url" target="_blank">快照凭证</a>
                        <a :href="source.url" target="_blank">转到平台</a>
                      </div>
                    </div>
                  </div>
                  <div v-else class="mini-empty">暂无符合条件的信源。</div>
                </div>

                <div v-else-if="functionalPage.mode === 'sentiment'" class="sentiment-workbench">
                  <section class="sentiment-layout">
                    <div v-if="sentimentPieRows.length" ref="sentimentChartRef" class="echart-box sentiment-echart"></div>
                    <div v-else class="mini-empty chart-empty">暂无情感统计结果。</div>
                    <div class="diagnosis-bars">
                      <div><span>正面内容</span><i><b :style="{ width: `${positiveRate}%` }"></b></i><em>{{ positiveRate }}%</em></div>
                      <div><span>中性内容</span><i><b :style="{ width: `${Math.max(0, 100 - positiveRate - negativeRate)}%` }"></b></i><em>{{ Math.max(0, 100 - positiveRate - negativeRate) }}%</em></div>
                      <div><span>负面风险</span><i><b class="warn-bar" :style="{ width: `${negativeRate}%` }"></b></i><em>{{ negativeRate }}%</em></div>
                      <div><span>信源数量</span><i><b :style="{ width: `${Math.min(100, (sourceTotalCount || sourceRanking.length) * 10)}%` }"></b></i><em>{{ sourceTotalCount || sourceRanking.length }}</em></div>
                    </div>
                    <div v-if="chartTrend.length" ref="sentimentTrendChartRef" class="echart-box sentiment-trend-echart"></div>
                  </section>
                  <section class="word-cloud-card">
                    <span v-for="item in sentimentWords" :key="item.word" :style="{ fontSize: `${14 + item.heat / 8}px`, opacity: `${0.56 + item.heat / 200}` }">{{ item.word }}</span>
                    <em v-if="!sentimentWords.length">暂无可提取的高频词，等待真实回答返回。</em>
                  </section>
                </div>

                <div v-else-if="functionalPage.mode === 'diagnosis'" class="diagnosis-workbench">
                  <div v-if="diagnosisScore" ref="diagnosisChartRef" class="echart-box diagnosis-echart"></div>
                  <div v-else class="mini-empty chart-empty">暂无可诊断的真实结果。</div>
                  <div class="diagnosis-bars">
                    <div><span>品牌提及率</span><i><b :style="{ width: `${monitorSummary?.mention_rate || 0}%` }"></b></i><em>{{ monitorSummary?.mention_rate || 0 }}%</em></div>
                    <div><span>平均排名</span><i><b :style="{ width: `${monitorSummary?.avg_rank ? Math.max(12, 100 - monitorSummary.avg_rank * 12) : 0}%` }"></b></i><em>{{ monitorSummary?.avg_rank || '-' }}</em></div>
                    <div><span>负面风险</span><i><b class="warn-bar" :style="{ width: `${negativeRate}%` }"></b></i><em>{{ negativeRate }}%</em></div>
                    <div><span>信源数量</span><i><b :style="{ width: `${Math.min(100, (sourceTotalCount || sourceRanking.length) * 10)}%` }"></b></i><em>{{ sourceTotalCount || sourceRanking.length }}</em></div>
                  </div>
                  <div class="diagnosis-basis">
                    <h3>诊断依据</h3>
                    <p>依据已配置监测平台、品牌词、竞品库、模型回答排名、信源数量、情感倾向和历史任务完成情况综合判断。</p>
                    <div><span>诊断平台</span><b>{{ platformCoverage.map(item => item.name).join('、') }}</b></div>
                    <div><span>纳入竞品</span><b>{{ brandCompetitors.map(item => item.name).join('、') || '暂未配置竞品' }}</b></div>
                  </div>
                </div>

                <div v-else-if="functionalPage.mode === 'platforms'" class="platform-orbit-card">
                  <div class="orbit-center">AI<br />平台矩阵</div>
                  <div v-for="(item, index) in platformCoverage.slice(0, 6)" :key="item.code" class="orbit-platform-card" :class="`orbit-pos-${index}`">
                    <b>{{ item.name }}</b>
                    <span>{{ item.status }} · {{ item.rate }}%</span>
                  </div>
                </div>

                <div v-else-if="functionalPage.mode === 'report'" class="report-preview">
                  <h3>{{ brandAsset?.brand_name || '艾迪亚' }} GEO 监测诊断报告</h3>
                  <p>本周期共完成 {{ monitorSummary?.subtask_count || 0 }} 个检测子任务，品牌提及率 {{ monitorSummary?.mention_rate || 0 }}%，平均推荐排名 {{ monitorSummary?.avg_rank || '-' }}。主要优化方向集中在高权威信源、竞品对比内容和移动端结果稳定性。</p>
                  <div class="report-table">
                    <span>平台</span><span>提及率</span><span>平均排名</span><span>建议动作</span>
                    <template v-for="item in platformRanking.slice(0, 4)" :key="item.platform">
                      <b>{{ platformLabelMap[item.platform] || item.platform }}</b><b>{{ item.mention_rate }}%</b><b>{{ item.avg_rank || '-' }}</b><b>补充可引用内容</b>
                    </template>
                  </div>
                </div>

                <div v-else-if="functionalPage.mode === 'competitor'" class="competitor-compare-panel">
                  <div v-if="competitorCompareRows.some(row => row.mention > 0)" ref="competitorChartRef" class="echart-box competitor-echart"></div>
                  <div v-else class="mini-empty chart-empty">暂无真实竞品排名结果，定时监测完成后展示对比图。</div>
                  <div class="gap-cards">
                    <div><span>TOP 竞品</span><b>{{ competitorCompareRows[1]?.name || '暂无' }}</b></div>
                    <div><span>竞品数量</span><b>{{ brandCompetitors.length }} 个</b></div>
                    <div><span>依据来源</span><b>企业竞品库与模力返回排名</b></div>
                  </div>
                </div>

                <div v-else-if="functionalPage.mode === 'logs'" class="ops-table">
                  <div class="ops-head"><span>时间</span><span>操作人</span><span>类型</span><span>描述</span><span>风险</span></div>
                  <div v-for="row in operationLogs" :key="row.join('-')" class="ops-row">
                    <span>{{ row[0] }}</span><b>{{ row[1] }}</b><span>{{ row[2] }}</span><em>{{ row[3] }}</em><i>{{ row[4] }}</i>
                  </div>
                </div>

                <div v-else-if="functionalPage.mode === 'settings'" class="ops-table settings-table">
                  <div class="ops-head"><span>配置项</span><span>当前值</span><span>作用范围</span><span>状态</span></div>
                  <div v-for="row in systemSettings" :key="row[0]" class="ops-row">
                    <b>{{ row[0] }}</b><span>{{ row[1] }}</span><em>{{ row[2] }}</em><i>{{ row[3] }}</i>
                  </div>
                </div>

                <div v-else-if="functionalPage.mode === 'knowledge'" class="knowledge-upload">
                  <label class="upload-drop" :class="{ disabled: uploadingKnowledgeFile }">
                    <input type="file" accept=".pdf,.doc,.docx,.md,.txt" :disabled="uploadingKnowledgeFile" @change="handleKnowledgeUpload" />
                    <BookOpen />
                    <b>{{ uploadingKnowledgeFile ? '上传中...' : '上传文章类文件' }}</b>
                    <span>支持 PDF / Word / Markdown / TXT，只保存原文件和上传记录，不做解析入库。</span>
                  </label>
                  <div class="knowledge-files">
                    <div v-if="loadingKnowledgeFiles" class="mini-empty">文件列表加载中...</div>
                    <div v-for="file in knowledgeFiles" :key="file.id">
                      <b>{{ file.original_name }}</b>
                      <span>{{ file.file_ext.toUpperCase() }} · {{ formatFileSize(file.file_size) }} · 已上传</span>
                    </div>
                    <div v-if="!loadingKnowledgeFiles && !knowledgeFiles.length" class="mini-empty">暂无上传文件，客户可在这里上传 PDF / Word 等文章资料。</div>
                  </div>
                </div>

                <div v-else class="feature-table">
                  <div class="feature-table-head"><span>平台</span><span>问题</span><span>排名</span><span>状态</span><span>快照</span></div>
                  <div v-for="item in recentSubtasks.slice(0, 8)" :key="item.subtask_id" class="feature-table-row">
                    <span>{{ platformLabelMap[item.platform] || item.platform }}</span>
                    <b>{{ item.prompt }}</b>
                    <span>{{ item.mention_position ? `第${item.mention_position}位` : '-' }}</span>
                    <em>{{ monitorStatusLabelMap[item.status || ''] || item.status || '-' }}</em>
                    <a v-if="item.page_screenshot" :href="item.page_screenshot" target="_blank">打开</a>
                    <span v-else>待返回</span>
                  </div>
                  <div v-if="!recentSubtasks.length" class="mini-empty">暂无检测明细，真实任务完成后自动显示。</div>
                </div>
              </article>

              <aside class="feature-side">
                <article class="panel">
                  <div class="panel-head"><h2>模型平台</h2><span>{{ platformCoverage.length }} 个</span></div>
                  <div class="model-chip-list">
                    <span v-for="item in platformCoverage" :key="item.code"><b>{{ item.name }}</b><em>{{ item.total }} 条</em></span>
                  </div>
                </article>
                <article v-if="functionalPage.mode !== 'sources'" class="panel">
                  <div class="panel-head"><h2>信源分析</h2><span>可筛选跳转</span></div>
                  <div v-if="sourcePlatformTabs.length > 1" class="source-platform-tabs compact-tabs">
                    <button
                      v-for="tab in sourcePlatformTabs"
                      :key="tab.code"
                      :class="{ active: selectedSourcePlatform === tab.code }"
                      @click="selectedSourcePlatform = tab.code"
                    >
                      {{ tab.name }} <em>{{ tab.count }}</em>
                    </button>
                  </div>
                  <div class="compact-source-list">
                    <a v-for="source in sourceRanking" :key="source.url" :href="source.url" target="_blank">
                      <b>{{ source.title }}</b>
                      <span>{{ (source.platforms || []).map(platform => platformLabelMap[platform] || platform).join('、') || '未知平台' }}</span>
                      <em>{{ source.count }}</em>
                    </a>
                    <div v-if="!sourceRanking.length" class="mini-empty">暂无来源。</div>
                  </div>
                </article>
                <article v-else class="panel">
                  <div class="panel-head"><h2>筛选口径</h2><span>{{ sourceRanking.length }} 条</span></div>
                  <div class="model-chip-list">
                    <span v-for="keyword in monitorKeywordList.slice(0, 8)" :key="keyword"><b>{{ keyword }}</b><em>监控词</em></span>
                  </div>
                  <p class="feature-note">来源列表按已购买模型平台和当前企业监控词聚合，可点击平台卡片快速切换。</p>
                </article>
                <article class="panel">
                  <div class="panel-head"><h2>任务进度</h2><span>{{ taskProgress }}%</span></div>
                  <div class="progress-lg"><b :style="{ width: `${taskProgress}%` }"></b></div>
                  <p class="feature-note">已完成 {{ monitorSummary?.completed_count || 0 }} / {{ monitorSummary?.subtask_count || 0 }} 个子任务，失败 {{ monitorSummary?.failed_count || 0 }} 个。</p>
                </article>
              </aside>
            </section>
          </section>
        </template>
      </main>
    </section>

    <el-dialog v-model="positionDialog" width="920px" :title="editingPosition ? '编辑职位' : '新增职位'" class="user-maintain-dialog">
      <div class="form-grid">
        <label><span>职位名称</span><input v-model="positionForm.position_name" placeholder="例如 运营、销售、交付" /></label>
        <label><span>适用端</span><select v-model="positionForm.identity_type"><option value="PLATFORM">平台运营端</option><option value="CUSTOMER">客户企业端</option></select></label>
        <label><span>状态</span><select v-model="positionForm.status"><option :value="true">启用</option><option :value="false">停用</option></select></label>
        <label class="form-field-full"><span>职位说明</span><textarea v-model="positionForm.description" rows="3" placeholder="说明这个职位适合哪些人员、默认能做哪些事"></textarea></label>
      </div>
      <div class="permission-head">
        <b>职位默认菜单权限</b>
        <small>新增人员选择该职位时，会默认带出这里勾选的菜单。</small>
      </div>
      <div class="permission-box permission-group-box" :class="`permission-${positionForm.identity_type.toLowerCase()}`">
        <div class="permission-side-note">
          <b>{{ positionForm.identity_type === 'PLATFORM' ? '平台运营端' : '客户企业端' }}</b>
          <span>{{ positionForm.identity_type === 'PLATFORM' ? '内部人员后台权限，按职位决定能管理哪些模块。' : '客户侧工作台权限，默认以展示和导出为主。' }}</span>
        </div>
        <div v-for="group in permissionGroupsFor(positionForm.identity_type, positionForm.menu_ids)" :key="group.key" class="permission-group">
          <div class="permission-group-head">
            <div><b>{{ group.title }}</b><small>{{ group.note }}</small></div>
            <span>{{ group.checked }}/{{ group.menus.length }}</span>
          </div>
          <label v-for="menu in group.menus" :key="menu.id" class="permission-item">
            <input v-model="positionForm.menu_ids" type="checkbox" :value="menu.id" />
            <component :is="menuIcon(menu)" />
            <span>{{ menu.menu_name }}</span>
          </label>
        </div>
      </div>
      <template #footer>
        <button class="plain-btn" @click="positionDialog = false">取消</button>
        <button class="primary-btn" :disabled="savingPosition" @click="savePosition">{{ editingPosition ? '保存职位修改' : '新增职位' }}</button>
      </template>
    </el-dialog>

    <el-dialog v-model="editDialog" width="860px" title="编辑用户与权限" class="user-maintain-dialog">
      <div class="form-grid">
        <label><span>登录账号</span><input :value="editingUser?.username" disabled /></label>
        <label><span>用户姓名<el-tooltip content="至少 2 个字符，展示在用户列表和登录身份信息里" placement="top"><HelpCircle /></el-tooltip></span><input v-model="editForm.display_name" /></label>
      </div>
      <div class="identity-checks">
        <label v-if="canSelectEditIdentity('PLATFORM')" class="identity-check-card">
          <input v-model="editForm.identity_types" type="checkbox" value="PLATFORM" />
          <ShieldCheck />
          <span><b>平台运营端</b><small>允许进入本公司后台</small></span>
        </label>
        <label v-if="canSelectEditIdentity('CUSTOMER')" class="identity-check-card">
          <input v-model="editForm.identity_types" type="checkbox" value="CUSTOMER" />
          <Building2 />
          <span><b>客户企业端</b><small>允许进入客户侧工作台</small></span>
        </label>
      </div>
      <div v-for="type in editForm.identity_types" :key="type" class="identity-config-box">
        <div class="permission-head">
          <b>{{ type === 'PLATFORM' ? '平台运营端权限' : '客户企业端权限' }}</b>
          <small>{{ type === 'PLATFORM' ? '允许新建、编辑、禁用和导出' : '客户侧默认只读展示，可导出' }}</small>
        </div>
        <div class="form-grid">
          <label><span>职位</span><select v-model.number="editForm.identity_configs[type].position_id" :disabled="!positions[type].length" @change="applyPositionToConfig(type, editForm, editForm.identity_configs[type].position_id)"><option disabled :value="null">{{ positions[type].length ? '请选择职位' : '职位加载中或暂无职位' }}</option><option v-for="position in positions[type]" :key="position.id" :value="position.id">{{ position.position_name }}</option></select></label>
          <label v-if="type === 'CUSTOMER'"><span>选择已有企业</span><select v-model.number="editForm.identity_configs.CUSTOMER.tenant_id"><option :value="null">{{ tenants.length ? '不选择，手动输入' : '暂无企业，手动输入' }}</option><option v-for="tenant in tenants" :key="tenant.id" :value="tenant.id">{{ tenant.name }}</option></select></label>
          <label v-if="type === 'CUSTOMER'"><span>新企业名称</span><input v-model="editForm.identity_configs.CUSTOMER.tenant_name" :disabled="Boolean(editForm.identity_configs.CUSTOMER.tenant_id)" placeholder="没有企业时直接输入" /></label>
        </div>
        <div class="permission-box permission-group-box" :class="`permission-${type.toLowerCase()}`">
          <div class="permission-side-note">
            <b>{{ type === 'PLATFORM' ? '平台运营端' : '客户企业端' }}</b>
            <span>{{ type === 'PLATFORM' ? '本公司内部后台菜单。' : '客户登录后可见的展示菜单。' }}</span>
          </div>
          <div v-for="group in permissionGroupsForForm(type, editForm)" :key="group.key" class="permission-group">
            <div class="permission-group-head">
              <div><b>{{ group.title }}</b><small>{{ group.note }}</small></div>
              <span>{{ group.checked }}/{{ group.menus.length }}</span>
            </div>
            <label v-for="menu in group.menus" :key="menu.id" class="permission-item">
              <input :checked="editForm.identity_configs[type].menu_ids.includes(menu.id)" type="checkbox" disabled />
              <component :is="menuIcon(menu)" />
              <span>{{ menu.menu_name }}</span>
            </label>
          </div>
        </div>
        <p class="feature-note">权限由职位决定，如需调整请到“用户管理 / 职位管理”中修改职位权限。</p>
      </div>
      <template #footer>
        <button class="plain-btn" @click="editDialog = false">取消</button>
        <button class="primary-btn" @click="saveEditUser">保存修改</button>
      </template>
    </el-dialog>

    <el-dialog v-model="enterpriseInfoDialog" width="720px" title="企业详情">
      <div v-if="enterpriseInfoLoading" class="mini-empty">企业详情加载中...</div>
      <div v-else class="enterprise-info-dialog">
        <section>
          <h3>{{ enterpriseInfoTenant?.name }}</h3>
          <p>{{ enterpriseInfoTenant ? tenantServicePeriod(enterpriseInfoTenant) : '-' }}</p>
          <div class="info-grid">
            <span><small>服务状态</small><b>{{ enterpriseInfoTenant ? tenantServiceLabel(enterpriseInfoTenant) : '-' }}</b></span>
            <span><small>官网</small><b>{{ enterpriseInfoAsset?.official_url || '-' }}</b></span>
            <span><small>购买模型</small><b>{{ (enterpriseInfoAsset?.monitored_platforms || []).map(item => platformLabelMap[item] || item).join('、') || '-' }}</b></span>
          </div>
        </section>
        <section>
          <h4>监测关键词</h4>
          <div class="info-tags"><span v-for="item in enterpriseInfoAsset?.monitor_keywords || []" :key="item">{{ item }}</span><em v-if="!enterpriseInfoAsset?.monitor_keywords?.length">未配置</em></div>
        </section>
        <section>
          <h4>露出词</h4>
          <div class="info-tags"><span v-for="item in enterpriseInfoAsset?.aliases || []" :key="item">{{ item }}</span><em v-if="!enterpriseInfoAsset?.aliases?.length">未配置</em></div>
        </section>
        <section>
          <h4>竞品监控</h4>
          <div class="info-tags"><span v-for="item in enterpriseInfoCompetitors" :key="item.id">{{ item.name }}</span><em v-if="!enterpriseInfoCompetitors.length">未配置</em></div>
        </section>
      </div>
      <template #footer>
        <button class="plain-btn" @click="enterpriseInfoDialog = false">关闭</button>
        <button v-if="enterpriseInfoTenant" class="primary-btn" @click="enterpriseInfoDialog = false; openEnterpriseDetail(enterpriseInfoTenant)">进入编辑</button>
      </template>
    </el-dialog>

    <el-dialog v-model="tenantDialog" width="520px" title="新增企业">
      <div class="form-grid password-grid">
        <label><span>企业名称</span><input v-model="tenantForm.name" placeholder="例如 北京某某科技有限公司" /></label>
        <label><span>服务开始日期</span><input v-model="tenantForm.service_start_date" type="date" /></label>
        <label><span>服务结束日期</span><input v-model="tenantForm.service_end_date" type="date" /></label>
      </div>
      <template #footer>
        <button class="plain-btn" @click="tenantDialog = false">取消</button>
        <button class="primary-btn" :disabled="loadingBrand" @click="submitTenant">确认新增</button>
      </template>
    </el-dialog>

    <el-dialog v-model="passwordDialog" width="460px" title="重置密码">
      <div class="form-grid password-grid">
        <label><span>用户</span><input :value="editingUser ? `${editingUser.display_name}（${editingUser.username}）` : ''" disabled /></label>
        <label><span>新密码<el-tooltip content="至少 6 个字符，重置后用户需使用新密码登录" placement="top"><HelpCircle /></el-tooltip></span><input v-model="resetPassword" /></label>
      </div>
      <template #footer>
        <button class="plain-btn" @click="passwordDialog = false">取消</button>
        <button class="primary-btn" @click="submitResetPassword">确认重置</button>
      </template>
    </el-dialog>
  </div>
</template>
