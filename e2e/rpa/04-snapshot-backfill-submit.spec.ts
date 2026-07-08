import { expect, test } from '@playwright/test'
import { assertNoErrorToast, login, openMenu, platformPassword, platformUser } from './helpers'

test.describe('RPA · 快照补录提交', () => {
  test.beforeEach(async ({ page }) => {
    await login(page, platformUser, platformPassword)
    await openMenu(page, 'platform', 'platform.snapshot_backfill')
  })

  test('填写品牌排名数字并提交（回归 trim bug）', async ({ page }) => {
    const actionBtn = page.locator('.snapshot-backfill-card-action').first()
    const hasCard = await actionBtn.isVisible({ timeout: 15_000 }).catch(() => false)
    test.skip(!hasCard, '当前账号无补录权限或列表为空')

    await actionBtn.click()
    const dialog = page.locator('.snapshot-backfill-dialog')
    await expect(dialog).toBeVisible()

    const urlInput = dialog.locator('input[type="url"]')
    const answerInput = dialog.locator('textarea')
    const rankInput = dialog.locator('input[type="number"]')

    await urlInput.fill('https://img.molizhishu.com/screenshots/rpa-test/example.png')
    await answerInput.fill(`RPA 测试补录正文 ${Date.now()}\n品牌A 排名第一\n品牌B 排名第二`)

    // 模拟人工填写排名「1」——此前会触发 number + trim 崩溃
    await rankInput.fill('1')

    const submitBtn = dialog.getByRole('button', { name: /提交并覆盖|提交补录/ })
    await expect(submitBtn).toBeEnabled()
    await submitBtn.click()

    await expect(dialog).toBeHidden({ timeout: 30_000 })
    await assertNoErrorToast(page)
  })

  test('打开补录弹窗并取消', async ({ page }) => {
    const actionBtn = page.locator('.snapshot-backfill-card-action').first()
    test.skip(!(await actionBtn.isVisible({ timeout: 10_000 }).catch(() => false)), '无补录卡片')

    await actionBtn.click()
    const dialog = page.locator('.snapshot-backfill-dialog')
    await expect(dialog).toBeVisible()
    await dialog.getByRole('button', { name: '取消' }).click()
    await expect(dialog).toBeHidden()
  })
})
