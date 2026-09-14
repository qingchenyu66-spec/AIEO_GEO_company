export const USER_CREATE_MENU = 'platform.users.create'
export const USER_CREATE_PLATFORM_MENU = 'platform.users.create.platform'
export const USER_CREATE_CUSTOMER_MENU = 'platform.users.create.customer'
export const USER_LIST_MENU = 'platform.users.list'
export const POSITION_MENU = 'platform.positions'
/** 平台端只读预览客户工作台（不进 sys_menu，靠 query 进入） */
export const CUSTOMER_PREVIEW_MENU = 'platform.customer_preview'

export const SETTINGS_MENU = 'platform.settings'
export const SETTINGS_SECRETS_MENU = 'platform.settings.secrets'
export const SETTINGS_SCHEDULE_MENU = 'platform.settings.schedule'
export const SETTINGS_CACHE_QUEUE_MENU = 'platform.settings.cache_queue'
export const SETTINGS_NOTIFICATION_MENU = 'platform.settings.notification'
export const SETTINGS_MENU_PERM = 'platform.settings.menu'
export const SETTINGS_CHILD_MENUS = [
  SETTINGS_SECRETS_MENU,
  SETTINGS_SCHEDULE_MENU,
  SETTINGS_CACHE_QUEUE_MENU,
  SETTINGS_NOTIFICATION_MENU,
  SETTINGS_MENU_PERM,
] as const

export const ENTERPRISE_CONFIG_MENU = 'customer.enterprise_config'
export const ENTERPRISE_CHILD_MENUS = [
  'customer.enterprise_monitor',
  'customer.enterprise_members',
  'customer.enterprise_credit',
  'customer.enterprise_audit',
] as const

export const hiddenCustomerMenus = ['customer.batch', 'customer.geo', 'customer.sentiment', 'platform.sentiment']

/** 侧栏不单独露出：已收进「算力运营」Tab */
export const sidebarHiddenCreditSubMenus = [
  'platform.tenant_credit_blocks',
  'platform.tenant_credit',
] as const

/**
 * 产品能力 / 已合并入口：不进职位勾选。
 * - 商品卡：企业开通开关管有没有
 * - 企业配置及子项：算力自助企业才有，按客户职位动态给
 * - 旧算力子页：平台职位只勾「算力运营」
 * 保存职位时仍保留历史授权，避免误清。
 */
export const productCapabilityMenusHiddenFromAssignable = [
  'customer.goods_cards',
  ENTERPRISE_CONFIG_MENU,
  ...ENTERPRISE_CHILD_MENUS,
  ...sidebarHiddenCreditSubMenus,
] as const

export const hiddenPlatformMenus = [
  'platform.plans',
  'platform.admins',
  'platform.diagnosis',
  ...sidebarHiddenCreditSubMenus,
]

/** 仍可进侧栏，但不在职位/权限配置里勾选（避免运营端配置里出现客户分析页） */
export const hiddenFromAssignablePermissionMenus = ['platform.competitor', 'platform.sources']
export const hiddenEnterprisePermissionMenus = [
  'platform.audit.list',
  'platform.audit.profile',
  'platform.audit.regions',
  'platform.audit.keywords',
  'platform.audit.models',
  'platform.audit.purge',
  'platform.audit.schedule',
  'platform.audit.competitors',
  'platform.audit.files',
]
export const hiddenEnterpriseConfigPermissionMenus = [...ENTERPRISE_CHILD_MENUS]
export const hiddenUserPermissionMenus = [
  USER_CREATE_PLATFORM_MENU,
  USER_CREATE_CUSTOMER_MENU,
]
export const hiddenSettingsPermissionMenus = [...SETTINGS_CHILD_MENUS]

export function isEnterpriseConfigMenuCode(code: string): boolean {
  return code === ENTERPRISE_CONFIG_MENU
    || (ENTERPRISE_CHILD_MENUS as readonly string[]).includes(code)
}

export function normalizeMenuCode(code: string) {
  return code === 'platform.users' ? USER_LIST_MENU : code
}
