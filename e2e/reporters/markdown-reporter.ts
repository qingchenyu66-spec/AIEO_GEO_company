import fs from 'node:fs'
import path from 'node:path'
import type { FullConfig, FullResult, Reporter, Suite, TestCase, TestResult } from '@playwright/test/reporter'

class MarkdownReporter implements Reporter {
  private rows: Array<{ title: string; status: string; duration: number; error?: string }> = []
  private startedAt = ''

  onBegin(config: FullConfig, suite: Suite) {
    this.startedAt = new Date().toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })
    void config
    void suite
  }

  onTestEnd(test: TestCase, result: TestResult) {
    this.rows.push({
      title: test.titlePath().join(' › '),
      status: result.status,
      duration: result.duration,
      error: result.errors[0]?.message,
    })
  }

  onEnd(result: FullResult) {
    const passed = this.rows.filter(row => row.status === 'passed').length
    const failed = this.rows.filter(row => row.status === 'failed').length
    const skipped = this.rows.filter(row => row.status === 'skipped').length
    const total = this.rows.length
    const lines = [
      '# GEO Monitor RPA 测试报告',
      '',
      `- 执行时间：${this.startedAt}`,
      `- 总用例：${total} | 通过：${passed} | 失败：${failed} | 跳过：${skipped}`,
      `- 整体状态：**${result.status}**`,
      '',
      '| 用例 | 结果 | 耗时(ms) | 备注 |',
      '|------|------|----------|------|',
    ]
    for (const row of this.rows) {
      const note = row.error ? row.error.split('\n')[0].slice(0, 120) : ''
      lines.push(`| ${row.title} | **${row.status}** | ${Math.round(row.duration)} | ${note} |`)
    }
    lines.push('', '详细 trace / 截图见 `e2e/report/html` 与 `e2e/test-results`。')
    const outDir = path.join(process.cwd(), 'report')
    fs.mkdirSync(outDir, { recursive: true })
    fs.writeFileSync(path.join(outDir, 'rpa-test-report.md'), lines.join('\n'), 'utf8')
  }
}

export default MarkdownReporter
