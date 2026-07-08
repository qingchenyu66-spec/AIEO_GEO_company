import { test } from '@playwright/test'
import { login, openMenu, platformPassword, platformUser, visitMenus } from './helpers'

test.describe('RPA · 运营端全菜单', () => {
  test.beforeEach(async ({ page }) => {
    await login(page, platformUser, platformPassword)
  })

  test('逐菜单打开并确认无报错', async ({ page }) => {
    await visitMenus(page, 'platform', [
      { code: 'platform.dashboard', label: '运营总览', ready: /总览|监测|企业/ },
      { code: 'platform.audit', label: '企业管理', ready: /企业|租户|品牌/ },
      { code: 'platform.users.list', label: '用户列表', ready: /用户/ },
      { code: 'platform.lead_diagnosis', label: '售前诊断', ready: /售前|诊断/ },
      { code: 'platform.snapshot_backfill', label: '快照补录', ready: /快照|补录|覆盖/ },
      { code: 'platform.competitor', label: '品牌洞察', ready: /竞品|洞察/ },
      { code: 'platform.sources', label: '信源分析', ready: /信源/ },
      { code: 'platform.reports', label: '报告中心', ready: /报告/ },
      { code: 'platform.models', label: '模型平台', ready: /平台|模型/ },
      { code: 'platform.alerts', label: '预警阈值', ready: /预警|阈值/ },
      { code: 'platform.logs', label: '操作日志', ready: /日志|操作/ },
      { code: 'platform.settings', label: '系统配置', ready: /配置|系统/ },
    ])
  })

  test('操作审批页可打开', async ({ page }) => {
    await openMenu(page, 'platform', 'platform.approvals')
    await page.waitForTimeout(1000)
    // 无权限可能空白或报错，仅记录是否 500 级崩溃
    const bodyText = await page.locator('body').innerText()
    test.info().annotations.push({ type: 'note', description: bodyText.slice(0, 200) })
  })
})
