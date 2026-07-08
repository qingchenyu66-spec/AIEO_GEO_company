import { defineConfig, devices } from '@playwright/test'
import dotenv from 'dotenv'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
dotenv.config({ path: path.join(__dirname, '.env.rpa') })

export default defineConfig({
  testDir: './rpa',
  timeout: 120_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [
    ['list'],
    ['html', { open: 'never', outputFolder: path.join(__dirname, 'report/html') }],
    ['json', { outputFile: path.join(__dirname, 'report/results.json') }],
    [path.join(__dirname, 'reporters/markdown-reporter.ts')],
  ],
  use: {
    baseURL: process.env.RPA_BASE_URL || 'http://127.0.0.1:5173',
    ...devices['Desktop Chrome'],
    locale: 'zh-CN',
    timezoneId: 'Asia/Shanghai',
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
    video: 'retain-on-failure',
    actionTimeout: 20_000,
    navigationTimeout: 30_000,
  },
  outputDir: path.join(__dirname, 'test-results'),
})
