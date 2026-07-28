/** 报告 blob 预览：echarts 内联 + 大画布幻灯片适配 iframe 宽度。 */

let cachedEchartsSource: string | null = null
let cachedEchartsPromise: Promise<string> | null = null

/** 模力诊断/周期 HTML 母版固定宽（与 report_molizhishu/styles.css .deck 一致） */
export const REPORT_SLIDE_WIDTH_PX = 2520

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

/** 预览适配缩放：iframe 窄于母版时等比缩小，不放大。 */
export function computePreviewFitScale(
  viewportWidth: number,
  slideWidth = REPORT_SLIDE_WIDTH_PX,
): number {
  if (!(viewportWidth > 0) || !(slideWidth > 0)) return 1
  return Math.min(1, viewportWidth / slideWidth)
}

/**
 * 仅预览 blob 注入：按 iframe 宽度 scale .deck，打印/导出 HTML 走别的链路不经此函数。
 * 2026-07-27 - 企业诊断在线预览 2520 画布看不全 - 预览等比适配宽度，不改母版
 */
export function injectReportPreviewFit(html: string): string {
  if (!html || html.includes('id="geo-preview-fit-script"')) return html

  const snippet = `
<style id="geo-preview-fit-style">
@media screen {
  html.geo-preview-fit,
  html.geo-preview-fit body {
    margin: 0;
    overflow-x: hidden;
    background: #f5f7fb;
  }
  html.geo-preview-fit .deck {
    position: absolute;
    left: 0;
    top: 0;
    transform-origin: top left;
  }
  html.geo-preview-fit #geo-preview-fit-spacer {
    width: 1px;
    pointer-events: none;
  }
}
@media print {
  html.geo-preview-fit .deck {
    position: static !important;
    transform: none !important;
  }
  html.geo-preview-fit #geo-preview-fit-spacer {
    display: none !important;
  }
}
</style>
<script id="geo-preview-fit-script">
(function () {
  var SLIDE_W = ${REPORT_SLIDE_WIDTH_PX};
  function fit() {
    var deck = document.querySelector(".deck");
    if (!deck) return;
    document.documentElement.classList.add("geo-preview-fit");
    var vw = document.documentElement.clientWidth || window.innerWidth || SLIDE_W;
    var scale = Math.min(1, vw / SLIDE_W);
    if (!(scale > 0)) scale = 1;
    deck.style.transform = "scale(" + scale + ")";
    var naturalH = deck.scrollHeight || deck.offsetHeight || 0;
    var spacer = document.getElementById("geo-preview-fit-spacer");
    if (!spacer) {
      spacer = document.createElement("div");
      spacer.id = "geo-preview-fit-spacer";
      spacer.setAttribute("aria-hidden", "true");
      document.body.appendChild(spacer);
    }
    spacer.style.height = Math.ceil(naturalH * scale) + "px";
    try {
      if (window.echarts && typeof window.echarts.getInstanceByDom === "function") {
        document.querySelectorAll("[_echarts_instance_]").forEach(function (el) {
          var chart = window.echarts.getInstanceByDom(el);
          if (chart && chart.resize) chart.resize();
        });
      }
    } catch (e) {}
  }
  function schedule() {
    window.requestAnimationFrame(fit);
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", schedule);
  } else {
    schedule();
  }
  window.addEventListener("resize", schedule);
  window.addEventListener("load", schedule);
  setTimeout(schedule, 300);
  setTimeout(schedule, 1200);
})();
</script>`

  if (/<\/body>/i.test(html)) {
    return html.replace(/<\/body>/i, `${snippet}</body>`)
  }
  return `${html}${snippet}`
}

export async function prepareReportPreviewHtml(html: string): Promise<string> {
  let next = html
  // 诊断模力稿图表是 PNG data URI，无 echarts；避免每次点开白等 1MB+ 内联
  const needsEcharts = /<script\b[^>]*echarts/i.test(html) || /echarts\.min\.js/i.test(html)
  if (needsEcharts) {
    const origin = window.location.origin
    const localEcharts = `${origin}/report-assets/echarts.min.js`
    next = next
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
  }

  return injectReportPreviewFit(next)
}
