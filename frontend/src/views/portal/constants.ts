export const USER_CREATE_MENU = 'platform.users.create'
export const USER_CREATE_PLATFORM_MENU = 'platform.users.create.platform'
export const USER_CREATE_CUSTOMER_MENU = 'platform.users.create.customer'
export const USER_LIST_MENU = 'platform.users.list'
export const POSITION_MENU = 'platform.positions'

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
export const hiddenUserPermissionMenus = [USER_CREATE_PLATFORM_MENU, USER_CREATE_CUSTOMER_MENU]

export function normalizeMenuCode(code: string) {
  return code === 'platform.users' ? USER_LIST_MENU : code
}
