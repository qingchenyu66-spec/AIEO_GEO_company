/** 报告 blob 预览：把 echarts script src 内联，避免 iframe 再打 CDN/同源二次请求失败。 */

let cachedEchartsSource: string | null = null
let cachedEchartsPromise: Promise<string> | null = null

function looksLikeEchartsBundle(text: string): boolean {
  const head = text.slice(0, 400).toLowerCase()
  if (head.includes('<!doctype') || head.includes('<html')) {
    return false
  }
  // SPA fallback / 错误页常伪装 200；真包体量远大于 index.html
  return text.includes('echarts') && text.length > 50_000
}

async function loadEchartsSourceText(): Promise<string> {
  if (cachedEchartsSource) return cachedEchartsSource
  if (!cachedEchartsPromise) {
    cachedEchartsPromise = fetch(`${window.location.origin}/report-assets/echarts.min.js`, {
      cache: 'no-cache',
    })
      .then(async (res) => {
        if (!res.ok) throw new Error(`echarts asset ${res.status}`)
        const text = await res.text()
        if (!looksLikeEchartsBundle(text)) {
          throw new Error('echarts asset is not a JS bundle (SPA fallback?)')
        }
        cachedEchartsSource = text
        return text
      })
      .catch((err) => {
        cachedEchartsPromise = null
        throw err
      })
  }
  return cachedEchartsPromise
}

export async function prepareReportPreviewHtml(html: string): Promise<string> {
  const origin = window.location.origin
  const localEcharts = `${origin}/report-assets/echarts.min.js`
  let next = html
    .replace(/https?:\/\/cdn\.jsdelivr\.net\/npm\/echarts@[^"'\\s]+/g, localEcharts)
    .replace(/src=(["'])assets\/echarts\.min\.js\1/g, `src=$1${localEcharts}$1`)

  try {
    const code = await loadEchartsSourceText()
    const safe = code.replace(/<\/script/gi, '<\\/script')
    next = next.replace(
      /<script\b[^>]*\bsrc=["'][^"']*echarts[^"']*["'][^>]*>\s*<\/script>/gi,
      `<script>${safe}</script>`,
    )
  } catch {
    // 退化：保留同源 script src（需 dist/report-assets 真实存在）
  }
  return next
}
