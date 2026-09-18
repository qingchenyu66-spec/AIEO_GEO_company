import { describe, expect, it } from 'vitest'

import {
  REPORT_SLIDE_WIDTH_PX,
  computePreviewFitScale,
  injectReportPreviewFit,
} from './reportPreviewHtml'

describe('reportPreviewHtml fit', () => {
  it('scales down for narrow viewports and never upscales', () => {
    expect(computePreviewFitScale(1260, REPORT_SLIDE_WIDTH_PX)).toBeCloseTo(0.5)
    expect(computePreviewFitScale(3000, REPORT_SLIDE_WIDTH_PX)).toBe(1)
  })

  it('injects width-first fit that does not block on deck pack', () => {
    const html = injectReportPreviewFit('<html><body><div class="deck"></div></body></html>')
    expect(html).toContain('id="geo-preview-fit-script"')
    expect(html).toContain('applyScale(deck)')
    expect(html).toContain('packPending()')
    expect(html).toContain('data-geo-deck-packed')
    // must not early-return before width scale
    expect(html).not.toMatch(
      /if \(document\.getElementById\("geo-deck-pack"\) && document\.documentElement\.dataset\.geoDeckPacked !== "1"\) \{\s*return;/,
    )
  })
})
