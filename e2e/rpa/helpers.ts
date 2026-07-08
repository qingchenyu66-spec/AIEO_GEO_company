import { expect, type Page } from '@playwright/test'

export const platformUser = process.env.RPA_PLATFORM_USER || 'platform'
export const platformPassword = process.env.RPA_PLATFORM_PASSWORD || 'Admin@2026'
export const customerUser = process.env.RPA_CUSTOMER_USER || 'jinoutuliao'
export const customerPassword = process.env.RPA_CUSTOMER_PASSWORD || 'Geo@2026'
export const rpaTenantId = process.env.RPA_TENANT_ID || '15'

/** 等待 Element Plus 错误提示消失或确认不存在 */
export async function assertNoErrorToast(page: Page) {
  const error = page.locator('.el-message.el-message--error')
  const count = await error.count()
  if (count > 0) {
    const text = await error.first().textContent()
    throw new Error(`页面出现错误提示: ${text?.trim()}`)
  }
}

export async function login(
  page: Page,
  username: string,
  password: string,
  options?: { identityLabel?: RegExp | string },
) {
  await page.goto('/login')
  await page.locator('#username').fill(username)
  await page.locator('#password').fill(password)
  await page.getByRole('button', { name: '登录系统' }).click()

  const identityDialog = page.locator('.identity-dialog')
  if (await identityDialog.isVisible({ timeout: 5000 }).catch(() => false)) {
    if (options?.identityLabel) {
      await page.locator('.identity-option').filter({ hasText: options.identityLabel }).click()
    } else {
      await page.locator('.identity-option').first().click()
    }
    await page.locator('.identity-enter').click()
  }

  await page.waitForURL(/\/(platform|customer)/, { timeout: 20_000 })
  await expect(page.locator('.portal-shell, .portal-layout, main.portal')).toBeVisible({ timeout: 20_000 })
}

export async function openMenu(
  page: Page,
  portal: 'platform' | 'customer',
  menuCode: string,
  query: Record<string, string> = {},
) {
  const params = new URLSearchParams({ menu: menuCode, ...query })
  if (portal === 'platform' && !params.has('tenant_id')) {
    params.set('tenant_id', rpaTenantId)
  }
  await page.goto(`/${portal}?${params.toString()}`)
  await page.waitForLoadState('networkidle')
  await page.waitForTimeout(800)
}

export async function visitMenus(
  page: Page,
  portal: 'platform' | 'customer',
  menus: Array<{ code: string; label: string; ready?: RegExp | string }>,
) {
  for (const menu of menus) {
    await openMenu(page, portal, menu.code)
    if (menu.ready) {
      await expect(page.getByText(menu.ready).first()).toBeVisible({ timeout: 20_000 })
    } else {
      await expect(page.locator('.portal-shell')).toBeVisible()
    }
    await assertNoErrorToast(page)
  }
}
