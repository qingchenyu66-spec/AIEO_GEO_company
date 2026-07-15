/** vite build 前保证 public/report-assets/echarts.min.js 存在（从本机 echarts 包复制）。 */
import { copyFileSync, existsSync, mkdirSync, statSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const src = join(root, 'node_modules', 'echarts', 'dist', 'echarts.min.js')
const destDir = join(root, 'public', 'report-assets')
const dest = join(destDir, 'echarts.min.js')

if (!existsSync(src)) {
  console.error(`[ensure-report-echarts] missing ${src}`)
  process.exit(1)
}
mkdirSync(destDir, { recursive: true })
if (!existsSync(dest) || statSync(dest).size < 50_000) {
  copyFileSync(src, dest)
  console.log(`[ensure-report-echarts] wrote ${dest}`)
} else {
  console.log(`[ensure-report-echarts] ok ${dest}`)
}
