import { test } from '@playwright/test'
import { assertNoErrorToast, customerPassword, customerUser, login, openMenu, visitMenus } from './helpers'

test.describe('RPA · 客户端全菜单', () => {
  test.beforeEach(async ({ page }) => {
    await login(page, customerUser, customerPassword)
  })

  test('逐菜单打开并确认无报错', async ({ page }) => {
    await visitMenus(page, 'customer', [
      { code: 'customer.workspace', label: '运营工作台', ready: /健康|工作台|监测/ },
      { code: 'customer.realtime', label: 'GEO实时监测', ready: /监测|任务|矩阵|列表/ },
      { code: 'customer.competitor', label: '品牌洞察', ready: /竞品|洞察|品牌/ },
      { code: 'customer.sources', label: '信源分析', ready: /信源|来源/ },
      { code: 'customer.reports', label: '报告中心', ready: /报告/ },
      { code: 'customer.knowledge', label: '企业知识库', ready: /知识库|上传|文件/ },
    ])
  })

  test('实时监测页切换视图', async ({ page }) => {
    await openMenu(page, 'customer', 'customer.realtime')
    const listTab = page.getByRole('button', { name: /列表/ }).first()
    const matrixTab = page.getByRole('button', { name: /矩阵|热力/ }).first()
    if (await listTab.isVisible().catch(() => false)) {
      await listTab.click()
      await page.waitForTimeout(500)
    }
    if (await matrixTab.isVisible().catch(() => false)) {
      await matrixTab.click()
      await page.waitForTimeout(1000)
    }
    await assertNoErrorToast(page)
  })
})
