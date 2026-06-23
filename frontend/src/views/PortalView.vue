<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Activity, BarChart3, BellRing, BookOpen, Building2, ChevronDown, ClipboardCheck,
  Database, FileBarChart, Gauge, HelpCircle, Layers3, Link2, LogOut, Search, Settings,
  ShieldCheck, SlidersHorizontal, UserCog, Users,
} from '@lucide/vue'
import type { Component } from 'vue'
import { useAuthStore } from '../stores/auth'
import type { IdentityType, MenuInfo } from '../services/auth'
import {
  createManagedUser, createTenant, deleteManagedUser, deleteTenant, getManagedUsers, getManagementMenus, getManagementRoles, getTenants,
  resetManagedUserPassword, restoreManagedUser, setManagedUserStatus, updateManagedUser,
  type ManagedUser, type RoleInfo, type TenantInfo,
} from '../services/management'
import {
  getMonitorTaskDetail, getMonitorTasks,
  type MonitorSubtask, type MonitorTask,
} from '../services/monitor'
import {
  createCompetitor, deleteCompetitor, getBrandAsset, saveBrandAsset, updateCompetitor,
  type BrandAsset, type BrandCompetitor,
} from '../services/brand'

const auth = useAuthStore()
const router = useRouter()
const isPlatform = computed(() => auth.session?.identity.identity_type === 'PLATFORM')
const USER_CREATE_MENU = 'platform.users.create'
const USER_LIST_MENU = 'platform.users.list'
const normalizeMenuCode = (code: string) => code === 'platform.users' ? USER_LIST_MENU : code
const activeMenuCode = ref(normalizeMenuCode(auth.allowedMenus[0]?.menu_code || ''))
const userMenuExpanded = ref(activeMenuCode.value.startsWith('platform.users'))
const managementUsers = ref<ManagedUser[]>([])
const assignMenus = reactive<Record<IdentityType, MenuInfo[]>>({ PLATFORM: [], CUSTOMER: [] })
const roles = reactive<Record<IdentityType, RoleInfo[]>>({ PLATFORM: [], CUSTOMER: [] })
const tenants = ref<TenantInfo[]>([])
const enterpriseDetailMode = ref(false)
const loadingUsers = ref(false)
const creatingUser = ref(false)
const editingUser = ref<ManagedUser | null>(null)
const editDialog = ref(false)
const passwordDialog = ref(false)
const tenantDialog = ref(false)
const resetPassword = ref('Geo@2026')
const tenantForm = reactive({ name: '', code: '' })
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

const menus = computed(() => auth.allowedMenus.filter(menu => ![USER_CREATE_MENU, USER_LIST_MENU, 'customer.assets'].includes(menu.menu_code)))
const userManagementMenu = computed(() => menus.value.find(item => item.menu_code === 'platform.users'))
const isUserCreatePage = computed(() => activeMenuCode.value === USER_CREATE_MENU)
const isUserListPage = computed(() => activeMenuCode.value === USER_LIST_MENU)
const isUserManagementPage = computed(() => isUserCreatePage.value || isUserListPage.value)
const isRealtimeMonitorPage = computed(() => activeMenuCode.value === 'customer.realtime')
const isBrandAssetPage = computed(() => activeMenuCode.value === 'platform.audit')
const activeMenu = computed(() => {
  const userMenu = userManagementMenu.value
  if (isUserCreatePage.value && userMenu) return { ...userMenu, menu_code: USER_CREATE_MENU, menu_name: '用户新增' } as MenuInfo
  if (isUserListPage.value && userMenu) return { ...userMenu, menu_code: USER_LIST_MENU, menu_name: '用户列表' } as MenuInfo
  return menus.value.find(item => item.menu_code === activeMenuCode.value) || menus.value[0]
})
const pageTitle = computed(() => activeMenu.value?.menu_name || (isPlatform.value ? '平台运营总览' : '客户运营工作台'))
const pageSubtitle = computed(() => {
  if (isUserCreatePage.value) return '创建账号、分配身份、绑定所属企业，并配置可访问菜单'
  if (isUserListPage.value) return '按公司、姓名、身份和状态筛选账号，支持编辑、禁用、重置密码和恢复'
  return isPlatform.value ? '企业运营、任务消耗、平台运行与风险情况' : '品牌曝光、推荐排名、引用来源与监测趋势'
})
const stats = computed(() => isPlatform.value
  ? [['企业客户', '1,286', '+126'], ['待审核企业', '18', '平均 12 分钟'], ['平台任务消耗', '64%', '额度充足'], ['风险预警', '7', '需及时处理']]
  : [['总检测次数', '128,430', '+18.6%'], ['品牌总曝光率', '76.8%', '+6.4%'], ['平均推荐排名', '3.2', '2 个平台需关注'], ['可用模型平台', '11', '运行正常']])

const userForm = reactive({
  username: '',
  password: 'Geo@2026',
  display_name: '',
  identity_types: ['PLATFORM'] as IdentityType[],
  identity_configs: {
    PLATFORM: {
      role_code: '',
      identity_name: '平台运营专员',
      tenant_id: null as number | null,
      tenant_name: '',
      menu_ids: [] as number[],
    },
    CUSTOMER: {
      role_code: '',
      identity_name: '客户企业成员',
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
      tenant_id: null as number | null,
      tenant_name: '',
      menu_ids: [] as number[],
    },
    CUSTOMER: {
      role_code: '',
      identity_name: '客户企业成员',
      tenant_id: null as number | null,
      tenant_name: '',
      menu_ids: [] as number[],
    },
  },
})

const monitorTasks = ref<MonitorTask[]>([])
const monitorDetail = ref<{ task: MonitorTask; subtasks: MonitorSubtask[] } | null>(null)
const loadingMonitor = ref(false)
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
const loadingBrand = ref(false)
const brandForm = reactive({
  tenant_id: null as number | null,
  company_full_name: '',
  brand_name: '',
  brand_short_name: '',
  monitor_keywords_text: '',
  aliases_text: '',
  product_keywords_text: '',
  official_url: '',
  description: '',
  schedule_type: 'daily_times' as 'daily_times' | 'fixed_times' | 'weekly' | 'monthly',
  schedule_times_text: '09:30\n14:30\n20:30',
  schedule_frequency: 3,
  schedule_weekdays: [] as number[],
  schedule_month_days_text: '',
})

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

async function loadUserManagement() {
  if (!isPlatform.value || !isUserManagementPage.value) return
  loadingUsers.value = isUserListPage.value
  try {
    const tenantRows = await getTenants()
    tenants.value = tenantRows
    await loadAssignableOptions()
    if (isUserListPage.value) {
      managementUsers.value = await getManagedUsers({
        keyword: userFilters.keyword.trim() || undefined,
        tenant_id: userFilters.tenant_id,
        identity_type: userFilters.identity_type,
        enabled: userFilters.enabled === '' ? null : userFilters.enabled === 'true',
        deleted: userFilters.deleted,
      })
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
    await loadBrandAssetData()
    monitorTasks.value = await getMonitorTasks()
    if (!monitorDetail.value && monitorTasks.value[0]) {
      monitorDetail.value = await getMonitorTaskDetail(monitorTasks.value[0].task_id)
    }
  } catch (error: any) {
    ElMessage.error(`检测任务加载失败：${errorMessage(error)}`)
  } finally {
    loadingMonitor.value = false
  }
}

function textToList(value: string) {
  return value.split(/[\n,，;；]/).map(item => item.trim()).filter(Boolean)
}

function numberList(value: string, min: number, max: number) {
  return textToList(value)
    .map(item => Number(item))
    .filter(item => Number.isInteger(item) && item >= min && item <= max)
}

function fillBrandForm(asset: BrandAsset | null, tenantId: number | null = null) {
  brandForm.tenant_id = tenantId
  brandForm.company_full_name = asset?.company_full_name || ''
  brandForm.brand_name = asset?.brand_name || ''
  brandForm.brand_short_name = asset?.brand_short_name || ''
  brandForm.monitor_keywords_text = (asset?.monitor_keywords || []).join('\n')
  brandForm.aliases_text = (asset?.aliases || []).join('\n')
  brandForm.product_keywords_text = (asset?.product_keywords || []).join('\n')
  brandForm.official_url = asset?.official_url || ''
  brandForm.description = asset?.description || ''
  brandForm.schedule_type = asset?.schedule_type || 'daily_times'
  brandForm.schedule_times_text = (asset?.schedule_times?.length ? asset.schedule_times : ['09:30', '14:30', '20:30']).join('\n')
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
  if (!competitorRows.value.length) addCompetitorRow()
}

async function loadBrandAssetData() {
  if (!isBrandAssetPage.value && !isRealtimeMonitorPage.value) return
  loadingBrand.value = true
  try {
    if (isPlatform.value && isBrandAssetPage.value && !tenants.value.length) {
      tenants.value = await getTenants()
    }
    if (isPlatform.value && isBrandAssetPage.value && !enterpriseDetailMode.value) {
      return
    }
    const response = await getBrandAsset(isPlatform.value ? brandForm.tenant_id : null)
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
    tenants.value = await getTenants()
  } catch (error: any) {
    ElMessage.error(`企业列表加载失败：${errorMessage(error)}`)
  } finally {
    loadingBrand.value = false
  }
}

async function openEnterpriseDetail(tenant: TenantInfo) {
  enterpriseDetailMode.value = true
  brandForm.tenant_id = tenant.id
  brandForm.company_full_name = tenant.name
  await loadBrandAssetData()
}

function backToEnterpriseList() {
  enterpriseDetailMode.value = false
  brandAsset.value = null
  brandCompetitors.value = []
  competitorRows.value = []
  fillBrandForm(null, null)
}

async function submitBrandAsset() {
  if (!brandForm.company_full_name.trim() || !brandForm.brand_name.trim()) {
    ElMessage.warning('请先填写企业全称和品牌主词')
    return
  }
  loadingBrand.value = true
  try {
    const response = await saveBrandAsset({
      tenant_id: brandForm.tenant_id,
      company_full_name: brandForm.company_full_name.trim(),
      brand_name: brandForm.brand_name.trim(),
      brand_short_name: brandForm.brand_short_name.trim() || null,
      monitor_keywords: textToList(brandForm.monitor_keywords_text),
      aliases: textToList(brandForm.aliases_text),
      product_keywords: textToList(brandForm.product_keywords_text),
      official_url: brandForm.official_url.trim() || null,
      description: brandForm.description.trim() || null,
      schedule_type: brandForm.schedule_type,
      schedule_times: textToList(brandForm.schedule_times_text),
      schedule_frequency: brandForm.schedule_frequency,
      schedule_weekdays: brandForm.schedule_weekdays,
      schedule_month_days: numberList(brandForm.schedule_month_days_text, 1, 31),
    })
    brandAsset.value = response.asset
    brandCompetitors.value = response.competitors
    fillBrandForm(response.asset, response.tenant_id)
    fillCompetitorRows(response.competitors)
    ElMessage.success('品牌资产已保存')
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
    const tenant = await createTenant({ name: tenantForm.name.trim(), code: tenantForm.code.trim() || null })
    tenantForm.name = ''
    tenantForm.code = ''
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
  await ElMessageBox.confirm(`确认删除企业「${tenant.name}」吗？历史任务会保留，但企业将不再出现在列表。`, '删除企业', { type: 'warning' })
  loadingBrand.value = true
  try {
    await deleteTenant(tenant.id)
    await loadEnterpriseList()
    ElMessage.success('企业已删除')
  } catch (error: any) {
    ElMessage.error(`企业删除失败：${errorMessage(error)}`)
  } finally {
    loadingBrand.value = false
  }
}

function addCompetitorRow() {
  competitorRows.value.push({
    id: null,
    name: '',
    short_name: '',
    aliases_text: '',
    website_url: '',
    category: '直接竞品',
  })
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
      short_name: row.short_name.trim() || null,
      aliases: textToList(row.aliases_text),
      website_url: row.website_url.trim() || null,
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
    monitorDetail.value = await getMonitorTaskDetail(taskId)
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
  const [platformMenus, platformRoles, customerMenus, customerRoles] = await Promise.all([
    getManagementMenus('PLATFORM'),
    getManagementRoles('PLATFORM'),
    getManagementMenus('CUSTOMER'),
    getManagementRoles('CUSTOMER'),
  ])
  assignMenus.PLATFORM = platformMenus
  assignMenus.CUSTOMER = customerMenus
  roles.PLATFORM = platformRoles
  roles.CUSTOMER = customerRoles
  if (!userForm.identity_configs.PLATFORM.role_code) userForm.identity_configs.PLATFORM.role_code = platformRoles[0]?.role_code || ''
  if (!userForm.identity_configs.CUSTOMER.role_code) userForm.identity_configs.CUSTOMER.role_code = customerRoles[0]?.role_code || ''
  if (!userForm.identity_configs.PLATFORM.menu_ids.length) userForm.identity_configs.PLATFORM.menu_ids = platformMenus.map(item => item.id)
  if (!userForm.identity_configs.CUSTOMER.menu_ids.length) userForm.identity_configs.CUSTOMER.menu_ids = customerMenus.map(item => item.id)
  if (!userForm.identity_configs.CUSTOMER.tenant_id && tenants.value[0]) userForm.identity_configs.CUSTOMER.tenant_id = tenants.value[0].id
}

async function submitUser() {
  if (!userForm.username || !userForm.display_name || !userForm.password || !userForm.identity_types.length) {
    ElMessage.warning('请补全账号、姓名、密码，并至少勾选一个登录身份')
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
      identity_name: config.identity_name,
      tenant_id: type === 'CUSTOMER' ? config.tenant_id : null,
      tenant_name: type === 'CUSTOMER' && !config.tenant_id ? config.tenant_name.trim() : null,
      menu_ids: config.menu_ids,
    }
  })
  if (identities.some(item => !item.role_code || !item.identity_name)) {
    ElMessage.warning('请补全已勾选身份的角色和身份名称')
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
      identity_name: config.identity_name,
      tenant_id: type === 'CUSTOMER' ? config.tenant_id : null,
      tenant_name: type === 'CUSTOMER' && !config.tenant_id ? config.tenant_name.trim() : null,
      menu_ids: config.menu_ids,
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
    editForm.identity_configs[type].identity_name = current?.identity_name || (type === 'PLATFORM' ? '平台运营专员' : '客户企业成员')
    editForm.identity_configs[type].tenant_id = current?.tenant_id || (type === 'CUSTOMER' ? tenants.value[0]?.id || null : null)
    editForm.identity_configs[type].tenant_name = ''
    editForm.identity_configs[type].menu_ids = current?.menu_ids?.length ? [...current.menu_ids] : assignMenus[type].map(item => item.id)
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
  userMenuExpanded.value = activeMenuCode.value.startsWith('platform.users')
  ElMessage.success(`已切换至${auth.session?.identity.identity_name}`)
  await router.replace(auth.portalPath)
}

function selectMenu(menu: MenuInfo) {
  activeMenuCode.value = normalizeMenuCode(menu.menu_code)
  userMenuExpanded.value = menu.menu_code === 'platform.users' ? true : false
}

function toggleUserSubmenu() {
  userMenuExpanded.value = !userMenuExpanded.value
}

function roleDisplayName(roleCode: string) {
  return roles.PLATFORM.find(role => role.role_code === roleCode)?.role_name
    || roles.CUSTOMER.find(role => role.role_code === roleCode)?.role_name
    || roleCode
}

function logout() {
  auth.logout()
  router.replace('/login')
}

watch(activeMenuCode, loadUserManagement)
watch(activeMenuCode, loadMonitorTasks)
watch(activeMenuCode, () => {
  if (isBrandAssetPage.value) {
    enterpriseDetailMode.value = false
    loadEnterpriseList()
  } else {
    loadBrandAssetData()
  }
})
onMounted(loadUserManagement)
onMounted(loadMonitorTasks)
onMounted(() => {
  if (isBrandAssetPage.value) loadEnterpriseList()
  else loadBrandAssetData()
})
</script>

<template>
  <div class="app-shell portal-shell">
    <aside class="sidebar">
      <div class="brand"><div class="brand-mark">G</div><div><strong>GEO Monitor</strong><span>{{ isPlatform ? '平台运营端' : '客户企业端' }}</span></div></div>
      <div class="portal-tag"><ShieldCheck v-if="isPlatform" /><Building2 v-else /><span><b>{{ auth.session?.identity.identity_name }}</b><small>{{ auth.session?.identity.tenant_name || 'GEO Monitor 平台' }}</small></span></div>
      <nav class="nav">
        <template v-for="menu in menus" :key="menu.menu_code">
        <template v-if="menu.menu_code === 'platform.users'">
          <button
            type="button"
            class="nav-item nav-parent"
            :class="{ active: activeMenuCode.startsWith('platform.users'), expanded: userMenuExpanded }"
            @click="toggleUserSubmenu"
          >
            <component :is="menuIcon(menu)" class="nav-icon" /><span>{{ menu.menu_name }}</span><ChevronDown class="nav-caret" />
          </button>
          <div v-if="userMenuExpanded" class="sub-nav">
            <a
              href="#"
              class="sub-nav-item"
              :class="{ active: activeMenuCode === USER_CREATE_MENU }"
              @click.prevent="activeMenuCode = USER_CREATE_MENU"
            >用户新增</a>
            <a
              href="#"
              class="sub-nav-item"
              :class="{ active: activeMenuCode === USER_LIST_MENU }"
              @click.prevent="activeMenuCode = USER_LIST_MENU"
            >用户列表</a>
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
            <button class="identity-switch"><span><small>当前身份</small><b>{{ auth.session?.identity.identity_name }}</b></span><ChevronDown /></button>
            <template #dropdown><el-dropdown-menu><el-dropdown-item v-for="identity in auth.session?.identities" :key="identity.id" :command="identity.id" :disabled="identity.id === auth.session?.identity.id"><ShieldCheck v-if="identity.identity_type === 'PLATFORM'" /><Building2 v-else />{{ identity.identity_name }}</el-dropdown-item></el-dropdown-menu></template>
          </el-dropdown>
          <div class="user-chip"><span>{{ auth.session?.user.display_name.slice(0, 1) }}</span><div><b>{{ auth.session?.user.display_name }}</b><small>{{ auth.session?.user.username }}</small></div></div>
          <button class="icon-action" title="退出登录" @click="logout"><LogOut /></button>
        </div>
      </header>
      <main class="content portal-content">
        <div class="page-head"><div><h1>{{ pageTitle }}</h1><p>{{ pageSubtitle }}</p></div><span class="live-status"><i></i> 数据服务正常</span></div>

        <section v-if="isUserCreatePage" class="user-page user-create-page">
          <article class="panel user-create-panel">
            <div class="panel-head"><h2>新增用户与权限分配</h2><span>菜单来自数据库</span></div>
            <div class="form-grid">
              <label>
                <span>登录账号<el-tooltip content="至少 3 个字符，建议使用英文、数字或下划线，例如 zhangsan_01" placement="top"><HelpCircle /></el-tooltip></span>
                <input v-model="userForm.username" placeholder="例如 zhangsan_01" />
              </label>
              <label>
                <span>用户姓名<el-tooltip content="至少 2 个字符，用真实姓名或业务昵称，方便后续分辨创建人" placement="top"><HelpCircle /></el-tooltip></span>
                <input v-model="userForm.display_name" placeholder="例如 张三" />
              </label>
              <label>
                <span>初始密码<el-tooltip content="至少 6 个字符，首次演示可用默认密码，正式环境建议强制首次登录修改" placement="top"><HelpCircle /></el-tooltip></span>
                <input v-model="userForm.password" placeholder="至少 6 位" />
              </label>
            </div>
            <div class="identity-checks">
              <label class="identity-check-card">
                <input v-model="userForm.identity_types" type="checkbox" value="PLATFORM" />
                <ShieldCheck />
                <span><b>平台运营端</b><small>可进入本公司后台，按菜单权限管理客户和系统</small></span>
              </label>
              <label class="identity-check-card">
                <input v-model="userForm.identity_types" type="checkbox" value="CUSTOMER" />
                <Building2 />
                <span><b>客户企业端</b><small>可进入客户侧工作台，查看检测、诊断和报告</small></span>
              </label>
            </div>

            <div v-for="type in userForm.identity_types" :key="type" class="identity-config-box">
              <div class="permission-head">
                <b>{{ type === 'PLATFORM' ? '平台运营端权限' : '客户企业端权限' }}</b>
                <small>{{ type === 'PLATFORM' ? '允许新建、编辑、禁用和导出' : '客户侧默认只读展示，可导出' }}</small>
              </div>
              <div class="form-grid">
                <label><span>角色<el-tooltip content="角色决定默认菜单和数据范围，平台管理员看全部，运营专员只看自己创建的数据" placement="top"><HelpCircle /></el-tooltip></span><select v-model="userForm.identity_configs[type].role_code" :disabled="!roles[type].length"><option disabled value="">{{ roles[type].length ? '请选择角色' : '角色加载中或暂无角色' }}</option><option v-for="role in roles[type]" :key="role.role_code" :value="role.role_code">{{ role.role_name }}</option></select></label>
                <label><span>身份名称<el-tooltip content="登录后身份选择弹窗中展示的名称，例如平台运营专员、客户企业管理员" placement="top"><HelpCircle /></el-tooltip></span><input v-model="userForm.identity_configs[type].identity_name" /></label>
                <label v-if="type === 'CUSTOMER'"><span>选择已有企业<el-tooltip content="如果客户公司已经存在，直接从这里选择；没有则选择手动输入" placement="top"><HelpCircle /></el-tooltip></span><select v-model.number="userForm.identity_configs.CUSTOMER.tenant_id"><option :value="null">{{ tenants.length ? '不选择，手动输入' : '暂无企业，手动输入' }}</option><option v-for="tenant in tenants" :key="tenant.id" :value="tenant.id">{{ tenant.name }}</option></select></label>
                <label v-if="type === 'CUSTOMER'"><span>新企业名称<el-tooltip content="仅在没有选择已有企业时填写，保存后系统会自动创建这家公司" placement="top"><HelpCircle /></el-tooltip></span><input v-model="userForm.identity_configs.CUSTOMER.tenant_name" :disabled="Boolean(userForm.identity_configs.CUSTOMER.tenant_id)" placeholder="没有企业时直接输入" /></label>
              </div>
              <div class="permission-box">
                <label v-for="menu in assignMenus[type]" :key="menu.id" class="permission-item">
                  <input v-model="userForm.identity_configs[type].menu_ids" type="checkbox" :value="menu.id" />
                  <component :is="menuIcon(menu)" />
                  <span>{{ menu.menu_name }}</span>
                </label>
              </div>
            </div>
            <button class="primary-btn" :disabled="creatingUser" @click="submitUser">新增用户并保存权限</button>
          </article>
        </section>

        <section v-else-if="isUserListPage" class="user-page user-list-page">
          <article class="panel managed-users-panel">
            <div class="panel-head user-list-head">
              <div>
                <h2>用户列表</h2>
                <p>集中管理平台账号、客户账号、双身份账号和账号状态</p>
              </div>
              <div class="user-list-actions">
                <span>{{ loadingUsers ? '加载中' : `共 ${managementUsers.length} 人` }}</span>
                <button class="primary-btn small-btn" @click="activeMenuCode = USER_CREATE_MENU">新增用户</button>
              </div>
            </div>
            <div class="user-filter-bar">
              <label>
                <span>搜索</span>
                <input v-model="userFilters.keyword" placeholder="姓名 / 账号 / 身份名称" @keyup.enter="loadUserManagement" />
              </label>
              <label>
                <span>所属公司</span>
                <select v-model.number="userFilters.tenant_id">
                  <option :value="null">全部公司</option>
                  <option v-for="tenant in tenants" :key="tenant.id" :value="tenant.id">{{ tenant.name }}</option>
                </select>
              </label>
              <label>
                <span>身份</span>
                <select v-model="userFilters.identity_type">
                  <option value="">全部身份</option>
                  <option value="PLATFORM">平台运营端</option>
                  <option value="CUSTOMER">客户企业端</option>
                </select>
              </label>
              <label>
                <span>状态</span>
                <select v-model="userFilters.enabled">
                  <option value="">全部状态</option>
                  <option value="true">启用</option>
                  <option value="false">停用</option>
                </select>
              </label>
              <label class="deleted-filter">
                <input v-model="userFilters.deleted" type="checkbox" />
                <span>已删除账号</span>
              </label>
              <button class="filter-search-btn" @click="loadUserManagement">查询</button>
              <button class="filter-reset-btn" @click="resetUserFilters">重置</button>
            </div>
            <div class="managed-user-list">
              <div v-if="!loadingUsers && !managementUsers.length" class="empty-users">
                <Users />
                <b>暂无匹配用户</b>
                <span>当前筛选条件下没有账号。可以重置筛选，或新增一个用户。</span>
                <div>
                  <button class="filter-reset-btn" @click="resetUserFilters">重置筛选</button>
                  <button class="filter-search-btn" @click="activeMenuCode = USER_CREATE_MENU">新增用户</button>
                </div>
              </div>
              <div v-for="user in managementUsers" :key="user.id" class="managed-user-card" :class="{ deleted: user.deleted }">
                <div><b>{{ user.display_name }}</b><small>{{ user.username }}</small></div>
                <span :class="{ disabled: !user.status || user.deleted, deleted: user.deleted }">{{ user.deleted ? '已删除' : user.status ? '启用' : '停用' }}</span>
                <p v-for="identity in user.identities" :key="identity.id">{{ identity.identity_name }} · {{ roleDisplayName(identity.role_code) }}<em v-if="identity.tenant_name"> · {{ identity.tenant_name }}</em></p>
                <div class="managed-user-actions">
                  <template v-if="!user.deleted">
                    <button @click="openEditUser(user)">编辑/权限</button>
                    <button @click="openPasswordDialog(user)">重置密码</button>
                    <button :class="{ danger: user.status }" @click="toggleUserStatus(user)">{{ user.status ? '禁用' : '启用' }}</button>
                    <button class="danger" @click="deleteUser(user)">删除</button>
                  </template>
                  <button v-else @click="restoreUser(user)">恢复账号</button>
                </div>
              </div>
            </div>
          </article>
        </section>

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
            <div class="enterprise-table">
              <div class="enterprise-table-head">
                <span>企业名称</span><span>企业编码</span><span>监测配置</span><span>自动监测</span><span>操作</span>
              </div>
              <div v-for="tenant in tenants" :key="tenant.id" class="enterprise-row">
                <div><b>{{ tenant.name }}</b><small>ID：{{ tenant.id }}</small></div>
                <span>{{ tenant.code }}</span>
                <span class="status-pill">待进入详情确认</span>
                <span>每日 3 次</span>
                <div class="enterprise-actions">
                  <button class="filter-search-btn" @click="openEnterpriseDetail(tenant)">编辑</button>
                  <button class="danger-text-btn" @click="removeTenant(tenant)">删除</button>
                </div>
              </div>
              <div v-if="!loadingBrand && !tenants.length" class="mini-empty">暂无企业。请先在用户新增中创建客户企业账号，或后续补企业新增入口。</div>
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
                <button class="primary-btn small-btn" :disabled="loadingBrand" @click="submitBrandAsset">保存品牌资产</button>
              </div>
            </div>
            <div class="tenant-select-row">
              <div>
                <b>当前维护企业</b>
                <small>{{ tenants.find(item => item.id === brandForm.tenant_id)?.name || brandForm.company_full_name }}，企业主体在列表中选择，详情页不允许切换，避免误改其他客户配置。</small>
              </div>
              <div>
                <b>客户侧权限</b>
                <small>客户只展示检测结果和文件上传，不开放企业资料、竞品库和手动提交检测。</small>
              </div>
            </div>
            <div class="brand-form-grid">
              <label><span>企业全称</span><input v-model="brandForm.company_full_name" placeholder="例如 北京艾亿欧科技有限公司" /></label>
              <label><span>品牌主词</span><input v-model="brandForm.brand_name" placeholder="例如 AIEO" /></label>
              <label><span>企业 / 品牌简称</span><input v-model="brandForm.brand_short_name" placeholder="例如 艾亿欧" /></label>
              <label><span>官网 / 主站</span><input v-model="brandForm.official_url" placeholder="https://..." /></label>
              <label><span>监控词</span><textarea v-model="brandForm.monitor_keywords_text" rows="4" placeholder="一行一个，例如 GEO优化、AI平台推广监测"></textarea></label>
              <label><span>别名 / 曾用名</span><textarea v-model="brandForm.aliases_text" rows="4" placeholder="一行一个，包含企业简称、品牌别称"></textarea></label>
              <label><span>产品词 / 业务词</span><textarea v-model="brandForm.product_keywords_text" rows="4" placeholder="一行一个，例如 品牌诊断、报告交付"></textarea></label>
              <label><span>品牌说明</span><textarea v-model="brandForm.description" rows="4" placeholder="用于内部识别，不直接展示给客户"></textarea></label>
            </div>
            <section class="schedule-box">
              <div class="panel-head">
                <div><h2>自动监测计划</h2><p>用于后续调度器按企业配置自动提交检测任务。</p></div>
              </div>
              <div class="schedule-type-grid">
                <label><input v-model="brandForm.schedule_type" type="radio" value="daily_times" /><span>每天几次</span></label>
                <label><input v-model="brandForm.schedule_type" type="radio" value="fixed_times" /><span>指定时间</span></label>
                <label><input v-model="brandForm.schedule_type" type="radio" value="weekly" /><span>每周</span></label>
                <label><input v-model="brandForm.schedule_type" type="radio" value="monthly" /><span>每月</span></label>
              </div>
              <div class="brand-form-grid">
                <label v-if="brandForm.schedule_type === 'daily_times'"><span>每天执行次数</span><input v-model.number="brandForm.schedule_frequency" type="number" min="1" max="24" /></label>
                <label v-if="brandForm.schedule_type !== 'daily_times'"><span>执行时间</span><textarea v-model="brandForm.schedule_times_text" rows="3" placeholder="一行一个，例如 09:30"></textarea></label>
                <label v-if="brandForm.schedule_type === 'weekly'"><span>每周执行日</span><select v-model="brandForm.schedule_weekdays" multiple><option :value="1">周一</option><option :value="2">周二</option><option :value="3">周三</option><option :value="4">周四</option><option :value="5">周五</option><option :value="6">周六</option><option :value="7">周日</option></select></label>
                <label v-if="brandForm.schedule_type === 'monthly'"><span>每月执行日期</span><textarea v-model="brandForm.schedule_month_days_text" rows="3" placeholder="一行一个，例如 1、15、28"></textarea></label>
              </div>
            </section>
          </article>

          <section v-if="enterpriseDetailMode" class="brand-layout">
            <article class="panel competitor-panel">
              <div class="panel-head">
                <div><h2>竞品监控库</h2><p>竞品名称和简称会随检测任务提交，用于排名、提及率和对比分析。</p></div>
                <button class="filter-search-btn" @click="addCompetitorRow">新增一行</button>
              </div>
              <div class="competitor-table">
                <div class="competitor-table-head">
                  <span>竞品名称</span><span>竞品简称</span><span>别名</span><span>官网 / 店铺链接</span><span>操作</span>
                </div>
                <div v-for="(row, index) in competitorRows" :key="row.id || `new-${index}`" class="competitor-row">
                  <input v-model="row.name" placeholder="竞品名称" />
                  <input v-model="row.short_name" placeholder="竞品简称" />
                  <input v-model="row.aliases_text" placeholder="别名，逗号或换行分隔" />
                  <input v-model="row.website_url" placeholder="官网 / 店铺链接，可选" />
                  <div>
                    <button class="filter-search-btn" :disabled="row.saving" @click="saveCompetitorRow(row)">保存</button>
                    <button class="danger-text-btn" @click="removeCompetitorRow(row, index)">删除</button>
                  </div>
                </div>
                <div v-if="!competitorRows.length" class="mini-empty">还没有竞品。建议先录入 3-5 个核心竞品，方便后续自动对比。</div>
              </div>
            </article>
          </section>
        </section>

        <section v-else-if="isRealtimeMonitorPage" class="monitor-page">
          <article class="panel monitor-submit-panel">
            <div class="panel-head">
              <div><h2>定时监测结果</h2><p>系统按平台端配置自动检测，客户侧只查看结果、快照和趋势，不开放手动提交。</p></div>
              <span>每日 3 次</span>
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
              <div><b>平台范围</b><span>豆包 / DeepSeek / 元宝 / Kimi / 通义 / 百度AI+</span></div>
            </div>
          </article>

          <section class="monitor-layout">
            <article class="panel monitor-task-list">
              <div class="panel-head"><h2>本地任务</h2><span>{{ monitorTasks.length }} 条</span></div>
              <button v-for="task in monitorTasks" :key="task.task_id" class="monitor-task-item" :class="{ active: monitorDetail?.task.task_id === task.task_id }" @click="selectMonitorTask(task.task_id)">
                <b>{{ task.monitor_keywords || '未填品牌词' }}</b>
                <small>{{ task.status }} · {{ task.completed_items }}/{{ task.total_items }}</small>
                <em>{{ task.platforms.map(item => item.platform).join('、') }}</em>
              </button>
              <div v-if="!loadingMonitor && !monitorTasks.length" class="mini-empty">暂无任务，先提交一次检测。</div>
            </article>

            <article class="panel monitor-result-panel">
              <div class="panel-head">
                <div><h2>检测结果</h2><p>{{ monitorDetail?.task.task_id || '选择任务后查看详情' }}</p></div>
                <button class="filter-search-btn" :disabled="loadingMonitor" @click="loadMonitorTasks">刷新列表</button>
              </div>
              <template v-if="monitorDetail">
                <div class="monitor-summary">
                  <span>状态 <b>{{ monitorDetail.task.status }}</b></span>
                  <span>完成 <b>{{ monitorDetail.task.completed_items }}/{{ monitorDetail.task.total_items }}</b></span>
                  <span>失败 <b>{{ monitorDetail.task.failed_items }}</b></span>
                  <span v-if="monitorDetail.task.last_error">错误 <b>{{ monitorDetail.task.last_error }}</b></span>
                </div>
                <div v-for="subtask in monitorDetail.subtasks" :key="subtask.subtask_id" class="monitor-subtask-card">
                  <div class="subtask-head">
                    <div><b>{{ subtask.platform }} / {{ subtask.mode }}</b><small>{{ subtask.prompt }}</small></div>
                    <span>{{ subtask.status }}</span>
                  </div>
                  <div class="subtask-metrics">
                    <span>提及排名：{{ subtask.mention_position || '未提及' }}</span>
                    <span>情感：{{ subtask.sentiment || '暂无' }}</span>
                    <span>费用：{{ subtask.amount ?? '待返回' }}</span>
                    <a v-if="subtask.page_screenshot" :href="subtask.page_screenshot" target="_blank">打开快照</a>
                  </div>
                  <p v-if="subtask.mention_context" class="mention-context">{{ subtask.mention_context }}</p>
                  <pre v-if="subtask.answer_content" class="answer-preview">{{ subtask.answer_content }}</pre>
                  <div v-if="subtask.reference_list.length" class="source-list">
                    <b>引用来源</b>
                    <a v-for="source in subtask.reference_list.slice(0, 6)" :key="`${subtask.subtask_id}-${source.index}-${source.url}`" :href="source.url" target="_blank">{{ source.title || source.site || source.url }}</a>
                  </div>
                  <p v-if="subtask.error_message" class="danger-copy">{{ subtask.error_message }}</p>
                </div>
              </template>
              <div v-else class="mini-empty">提交或选择任务后，这里会展示模型回答、排名、来源和快照。</div>
            </article>
          </section>
        </section>

        <template v-else>
          <section class="portal-stats"><article v-for="item in stats" :key="item[0]"><span>{{ item[0] }}</span><strong>{{ item[1] }}</strong><small>{{ item[2] }}</small></article></section>
          <section class="portal-main">
            <article class="panel trend-panel"><div class="panel-head"><h2>核心指标趋势</h2><span>最近 7 天</span></div><div class="bar-chart"><div v-for="(height, index) in [52,64,58,76,84,79,91]" :key="index" class="bar-column"><span>{{ height }}</span><i :style="{ height: `${height}%` }"></i><small>{{ ['周一','周二','周三','周四','周五','周六','今日'][index] }}</small></div></div></article>
            <article class="panel"><div class="panel-head"><h2>{{ isPlatform ? '待处理事项' : '模型曝光排行' }}</h2><span>实时更新</span></div><div class="rank-list"><div v-for="(name, index) in (isPlatform ? ['企业审核 18 项','高风险预警 7 项','套餐额度提醒 12 项','异常任务 4 项'] : ['豆包 82.4%','DeepSeek 78.9%','通义千问 71.6%','百度 AI+ 68.2%'])" :key="name"><b>{{ index + 1 }}</b><span>{{ name }}</span><i :style="{ width: `${88-index*12}%` }"></i></div></div></article>
          </section>
        </template>
      </main>
    </section>

    <el-dialog v-model="editDialog" width="860px" title="编辑用户与权限" class="user-maintain-dialog">
      <div class="form-grid">
        <label><span>登录账号</span><input :value="editingUser?.username" disabled /></label>
        <label><span>用户姓名<el-tooltip content="至少 2 个字符，展示在用户列表和登录身份信息里" placement="top"><HelpCircle /></el-tooltip></span><input v-model="editForm.display_name" /></label>
      </div>
      <div class="identity-checks">
        <label class="identity-check-card">
          <input v-model="editForm.identity_types" type="checkbox" value="PLATFORM" />
          <ShieldCheck />
          <span><b>平台运营端</b><small>允许进入本公司后台</small></span>
        </label>
        <label class="identity-check-card">
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
          <label><span>角色</span><select v-model="editForm.identity_configs[type].role_code" :disabled="!roles[type].length"><option disabled value="">{{ roles[type].length ? '请选择角色' : '角色加载中或暂无角色' }}</option><option v-for="role in roles[type]" :key="role.role_code" :value="role.role_code">{{ role.role_name }}</option></select></label>
          <label><span>身份名称</span><input v-model="editForm.identity_configs[type].identity_name" /></label>
          <label v-if="type === 'CUSTOMER'"><span>选择已有企业</span><select v-model.number="editForm.identity_configs.CUSTOMER.tenant_id"><option :value="null">{{ tenants.length ? '不选择，手动输入' : '暂无企业，手动输入' }}</option><option v-for="tenant in tenants" :key="tenant.id" :value="tenant.id">{{ tenant.name }}</option></select></label>
          <label v-if="type === 'CUSTOMER'"><span>新企业名称</span><input v-model="editForm.identity_configs.CUSTOMER.tenant_name" :disabled="Boolean(editForm.identity_configs.CUSTOMER.tenant_id)" placeholder="没有企业时直接输入" /></label>
        </div>
        <div class="permission-box">
          <label v-for="menu in assignMenus[type]" :key="menu.id" class="permission-item">
            <input v-model="editForm.identity_configs[type].menu_ids" type="checkbox" :value="menu.id" />
            <component :is="menuIcon(menu)" />
            <span>{{ menu.menu_name }}</span>
          </label>
        </div>
      </div>
      <template #footer>
        <button class="plain-btn" @click="editDialog = false">取消</button>
        <button class="primary-btn" @click="saveEditUser">保存修改</button>
      </template>
    </el-dialog>

    <el-dialog v-model="tenantDialog" width="520px" title="新增企业">
      <div class="form-grid password-grid">
        <label><span>企业名称</span><input v-model="tenantForm.name" placeholder="例如 北京某某科技有限公司" /></label>
        <label><span>企业编码</span><input v-model="tenantForm.code" placeholder="不填则系统自动生成" /></label>
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
