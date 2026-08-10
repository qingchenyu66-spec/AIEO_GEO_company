# -*- coding: utf-8 -*-
"""ponytail: 分析多卡必须拆页；字体抢跑路径应 deferred。"""
from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright

from app.services.report_molizhishu_pdf_service import _pack_js

ROOT = Path(__file__).resolve().parents[1]
PACK = (ROOT / "app/templates/report_molizhishu/deck_pack.js").read_text(encoding="utf-8")


def _cards(n: int) -> str:
    return "".join(f'<div class="pack-item analysis-card" style="height:120px">C{i}</div>' for i in range(n))


HTML = f"""<!DOCTYPE html><html><head><style>
.slide{{width:2520px;height:1417px;position:relative;overflow:hidden}}
.pack-body{{position:absolute;left:132px;top:210px;width:2260px;max-height:1000px;overflow:hidden}}
.pack-item{{margin:0 0 12px;background:#eee}}
.slide-title{{position:absolute;left:140px;top:118px}}
</style></head><body><main class="deck">
<section class="slide" data-pack="1" data-merge-group="analysis">
  <h2 class="slide-title">数据分析与优化建议</h2>
  <div class="pack-body light-content">{_cards(18)}</div>
</section>
</main></body></html>"""


def main() -> None:
    assert "fonts.ready" in PACK
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 2520, "height": 1417})
        page.set_content(HTML, wait_until="load")
        deferred = page.evaluate(PACK)
        assert deferred.get("deferred") is True, deferred
        page.wait_for_function("() => window.__geoDeckPackResult && window.__geoDeckPackResult.slides")
        result = page.evaluate("() => window.__geoDeckPackResult")
        titles = page.locator(".slide-title").all_text_contents()
        browser.close()
    assert result.get("stillClipped", 1) == 0, result
    assert any("(1/" in t for t in titles), titles
    assert any("(2/" in t for t in titles), titles
    # SYNC path (PDF/tests)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 2520, "height": 1417})
        page.set_content(HTML, wait_until="load")
        sync_result = page.evaluate(_pack_js())
        titles2 = page.locator(".slide-title").all_text_contents()
        browser.close()
    assert sync_result.get("deferred") is not True, sync_result
    assert sync_result.get("stillClipped", 1) == 0, sync_result
    assert any("(1/" in t for t in titles2), titles2
    print("OK", "deferred_slides", result.get("slides"), "sync_slides", sync_result.get("slides"), titles2)


if __name__ == "__main__":
    main()
