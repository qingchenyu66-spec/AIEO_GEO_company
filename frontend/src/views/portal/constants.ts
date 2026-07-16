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

export const hiddenCustomerMenus = ['customer.batch', 'customer.geo', 'customer.sentiment', 'platform.sentiment']
export const hiddenPlatformMenus = ['platform.plans', 'platform.admins', 'platform.diagnosis', 'platform.audit.models']
export const hiddenEnterprisePermissionMenus = [
  'platform.audit.list',
  'platform.audit.profile',
  'platform.audit.keywords',
  'platform.audit.schedule',
  'platform.audit.competitors',
  'platform.audit.files',
]
export const hiddenUserPermissionMenus = [
  USER_CREATE_PLATFORM_MENU,
  USER_CREATE_CUSTOMER_MENU,
]
export const hiddenSettingsPermissionMenus = [...SETTINGS_CHILD_MENUS]

export function normalizeMenuCode(code: string) {
  return code === 'platform.users' ? USER_LIST_MENU : code
}
