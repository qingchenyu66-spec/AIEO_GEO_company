/** ponytail: 预览缩放算法自检（node 可跑） */
import {
  computePreviewFitScale,
  injectReportPreviewBase,
  injectReportPreviewFit,
  REPORT_SLIDE_WIDTH_PX,
} from './reportPreviewHtml'

function assert(cond: unknown, msg: string): asserts cond {
  if (!cond) throw new Error(msg)
}

assert(REPORT_SLIDE_WIDTH_PX === 2520, 'slide width constant')
assert(computePreviewFitScale(1260) === 0.5, 'half width → 0.5')
assert(computePreviewFitScale(3000) === 1, 'wider than slide → no upscale')
assert(computePreviewFitScale(0) === 1, 'bad viewport → 1')

const once = injectReportPreviewFit('<html><body><main class="deck"></main></body></html>')
assert(once.includes('geo-preview-fit-script'), 'inject script')
assert(injectReportPreviewFit(once) === once, 'idempotent')

// 内联 echarts 含 '</body>' 字面量时，必须插到文档末尾，不能截断 <script>
const withFakeBody = injectReportPreviewFit(
  '<html><head><script>var x="</body>";</script></head><body><main class="deck"></main></body></html>',
)
assert(withFakeBody.indexOf('geo-preview-fit-script') > withFakeBody.indexOf('var x='), 'fit after real body')
assert((withFakeBody.match(/<\/script>/gi) || []).length >= 2, 'echarts script still closed')

const withPack = injectReportPreviewFit(
  '<html><body><main class="deck"></main><script id="geo-deck-pack">document.documentElement.dataset.geoDeckPacked="1";</script></body></html>',
)
assert(withPack.indexOf('geo-preview-fit-script') > withPack.indexOf('geo-deck-pack'), 'fit after pack script')
assert(withPack.includes('geoDeckPacked'), 'fit waits for pack flag')

const withBase = injectReportPreviewBase('<html><head></head><body></body></html>', 'https://example.com')
assert(withBase.includes('id="geo-preview-base"'), 'base injected')
assert(withBase.includes('href="https://example.com/"'), 'base href')
assert(injectReportPreviewBase(withBase, 'https://example.com') === withBase, 'base idempotent')

console.log('reportPreviewHtml check ok')
