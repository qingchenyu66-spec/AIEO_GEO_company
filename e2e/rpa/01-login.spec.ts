import { test } from '@playwright/test'
import { customerPassword, customerUser, login, platformPassword, platformUser } from './helpers'

test.describe('RPA · 登录', () => {
  test('运营账号登录进入 platform', async ({ page }) => {
    await login(page, platformUser, platformPassword)
    await page.waitForURL('**/platform**')
  })

  test('客户账号登录进入 customer', async ({ page }) => {
    await login(page, customerUser, customerPassword)
    await page.waitForURL('**/customer**')
  })
})
