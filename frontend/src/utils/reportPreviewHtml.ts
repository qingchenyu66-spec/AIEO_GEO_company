/** 报告 blob 预览：同源静态资源 + 大画布幻灯片适配 iframe 宽度。 */

/** 模力诊断/周期 HTML 母版固定宽（与 report_molizhishu/styles.css .deck 一致） */
export const REPORT_SLIDE_WIDTH_PX = 2520

/** 进入报告中心时预取母版图与 echarts，减轻客户首点预览等待。 */
export function prefetchReportPreviewAssets(origin = typeof window !== 'undefined' ? window.location.origin : ''): void {
  if (!origin || typeof document === 'undefined') return
  const urls = [
    `${origin}/report-assets/echarts.min.js`,
    `${origin}/report-assets/monitor/monitor-cover.jpg`,
    `${origin}/report-assets/monitor/monitor-light.jpg`,
    `${origin}/report-assets/monitor/monitor-dark.jpg`,
    `${origin}/report-assets/monitor/monitor-light-wide.jpg`,
    `${origin}/report-assets/monitor/monitor-thanks.jpg`,
  ]
  for (const href of urls) {
    if (document.querySelector(`link[data-geo-prefetch="${href}"]`)) continue
    const link = document.createElement('link')
    link.rel = 'prefetch'
    link.as = href.endsWith('.js') ? 'script' : 'image'
    link.href = href
    link.dataset.geoPrefetch = href
    document.head.appendChild(link)
  }
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
 * blob 文档相对路径会解析到 blob: 源；注入 base 指向站点根，母版图/echarts 才能走缓存。
 * 2026-07-28 - 预览外链资源依赖同源绝对解析
 */
export function injectReportPreviewBase(html: string, origin = typeof window !== 'undefined' ? window.location.origin : ''): string {
  if (!html || !origin || html.includes('id="geo-preview-base"')) return html
  const tag = `<base id="geo-preview-base" href="${origin}/">`
  if (/<head[^>]*>/i.test(html)) {
    return html.replace(/<head([^>]*)>/i, `<head$1>${tag}`)
  }
  return `${tag}${html}`
}

/**
 * 仅预览 blob 注入：按 iframe 宽度 scale .deck，打印/导出 HTML 走别的链路不经此函数。
 * 2026-07-27 - 企业诊断在线预览 2520 画布看不全 - 预览等比适配宽度，不改母版
 * 2026-09-18 - 等 deck_pack/字体就绪才 scale 导致首屏裁切半晌；宽度立即缩，高度等拆页后再量
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
  var packedObserver = null;
  function packPending() {
    return !!(document.getElementById("geo-deck-pack") && document.documentElement.dataset.geoDeckPacked !== "1");
  }
  function applyScale(deck) {
    document.documentElement.classList.add("geo-preview-fit");
    var vw = document.documentElement.clientWidth || window.innerWidth || SLIDE_W;
    var scale = Math.min(1, vw / SLIDE_W);
    if (!(scale > 0)) scale = 1;
    deck.style.transform = "scale(" + scale + ")";
    return scale;
  }
  function applySpacer(deck, scale) {
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
  function watchPacked() {
    if (packedObserver || !packPending()) return;
    packedObserver = new MutationObserver(function () {
      if (!packPending()) {
        packedObserver.disconnect();
        packedObserver = null;
        schedule();
      }
    });
    packedObserver.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-geo-deck-packed"],
    });
  }
  function fit() {
    var deck = document.querySelector(".deck");
    if (!deck) return;
    var scale = applyScale(deck);
    // 拆页前高度会偏；宽度必须先缩，否则首屏只露 2520 画布一角
    if (packPending()) {
      watchPacked();
      return;
    }
    applySpacer(deck, scale);
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

  // 2026-07-28 - 周期预览整页变 echarts 源码 - 内联包里有 '</body>' 字符串，
  // replace 首个会插进 <script> 中间、后续 JS 当正文；只认最后一个真 </body>
  const closeAt = html.toLowerCase().lastIndexOf('</body>')
  if (closeAt >= 0) {
    return `${html.slice(0, closeAt)}${snippet}${html.slice(closeAt)}`
  }
  return `${html}${snippet}`
}

export async function prepareReportPreviewHtml(html: string): Promise<string> {
  let next = html
  const origin = typeof window !== 'undefined' ? window.location.origin : ''
  const localEcharts = `${origin}/report-assets/echarts.min.js`

  // 2026-07-28 - 弃用把 1MB echarts 塞进 blob：改同源 script src + base，可缓存、预览从 11MB 降到百 KB 级
  next = next
    .replace(/https?:\/\/cdn\.jsdelivr\.net\/npm\/echarts@[^"'\s]+/g, localEcharts)
    .replace(/src=(["'])assets\/echarts\.min\.js\1/g, `src=$1${localEcharts}$1`)
    .replace(
      /src=(["'])\/report-assets\/echarts\.min\.js\1/g,
      `src=$1${localEcharts}$1`,
    )

  next = injectReportPreviewBase(next, origin)
  return injectReportPreviewFit(next)
}
