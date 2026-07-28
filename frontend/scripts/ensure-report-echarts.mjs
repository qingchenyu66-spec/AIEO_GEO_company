/** vite build 前保证 public/report-assets：echarts + 周期监测母版图。 */
import { copyFileSync, existsSync, mkdirSync, readdirSync, statSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const destDir = join(root, 'public', 'report-assets')
mkdirSync(destDir, { recursive: true })

const echartsSrc = join(root, 'node_modules', 'echarts', 'dist', 'echarts.min.js')
const echartsDest = join(destDir, 'echarts.min.js')
if (!existsSync(echartsSrc)) {
  console.error(`[ensure-report-echarts] missing ${echartsSrc}`)
  process.exit(1)
}
if (!existsSync(echartsDest) || statSync(echartsDest).size < 50_000) {
  copyFileSync(echartsSrc, echartsDest)
  console.log(`[ensure-report-echarts] wrote ${echartsDest}`)
} else {
  console.log(`[ensure-report-echarts] ok ${echartsDest}`)
}

// 2026-07-28 - 周期预览外链母版图，勿把 JPEG base64 塞进 HTML
const monitorSrcDir = join(root, '..', 'backend', 'app', 'templates', 'report_monitor', 'assets')
const monitorDestDir = join(destDir, 'monitor')
mkdirSync(monitorDestDir, { recursive: true })
if (!existsSync(monitorSrcDir)) {
  console.error(`[ensure-report-echarts] missing monitor assets ${monitorSrcDir}`)
  process.exit(1)
}
for (const name of readdirSync(monitorSrcDir)) {
  if (!name.endsWith('.jpg')) continue
  const from = join(monitorSrcDir, name)
  const to = join(monitorDestDir, name)
  if (!existsSync(to) || statSync(to).size !== statSync(from).size) {
    copyFileSync(from, to)
    console.log(`[ensure-report-echarts] wrote monitor/${name}`)
  }
}
console.log(`[ensure-report-echarts] monitor assets ok ${monitorDestDir}`)
