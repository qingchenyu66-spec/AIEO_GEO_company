"""周报核心监测词：按开通平台分栏、同平台环比、无最弱平台列。"""

from app.services.report_period_comparison_service import (
    _metric_delta,
    enrich_keyword_analytics,
    render_keyword_html,
)


def test_render_weekly_keyword_html_by_platform_sections() -> None:
    analytics = enrich_keyword_analytics(
        {},
        keywords=["机场广告公司哪家好", "户外广告投放"],
        platform_codes=["doubao", "yuanbao"],
        report_type="weekly",
    )
    html = render_keyword_html(analytics, report_type="weekly", client=True)
    assert "data-kw-platform-sections" in html
    assert 'data-kw-platform="doubao"' in html
    assert 'data-kw-platform="yuanbao"' in html
    assert "kw-platform-heading" in html
    assert "最弱平台" not in html
    assert "data-kw-jump" not in html
    assert "机场广告公司哪家好" in html
    assert analytics.get("platform_sections")
    doubao = next(s for s in analytics["platform_sections"] if s["platform"] == "doubao")
    row = doubao["rows"][0]
    assert "current" in row["mention_rate"]
    assert "previous" in row["mention_rate"]
    assert row["mention_rate"]["current"] is not None


def test_render_monthly_keeps_aggregate_table() -> None:
    analytics = enrich_keyword_analytics(
        {},
        keywords=["词A"],
        platform_codes=["doubao"],
        report_type="monthly",
    )
    html = render_keyword_html(analytics, report_type="monthly", client=True)
    assert "data-kw-platform-switch" not in html
    assert "短板监控词 × 平台表现" in html or "matrix" in html or "kw-matrix" in html


def test_pick_weakest_platforms_skips_when_all_similar() -> None:
    from app.services.report_period_comparison_service import _pick_weakest_platform_names

    names = _pick_weakest_platform_names(
        [
            {"name": "豆包", "completed": 10, "mention_rate": 20.0, "avg_rank": 3.0},
            {"name": "DeepSeek", "completed": 10, "mention_rate": 20.5, "avg_rank": 3.1},
        ]
    )
    assert names == []


def test_pick_weakest_platforms_keeps_only_true_laggard() -> None:
    from app.services.report_period_comparison_service import _pick_weakest_platform_names

    names = _pick_weakest_platform_names(
        [
            {"name": "豆包", "completed": 10, "mention_rate": 80.0, "avg_rank": 2.0},
            {"name": "DeepSeek", "completed": 10, "mention_rate": 10.0, "avg_rank": 5.0},
        ]
    )
    assert names == ["DeepSeek"]


def test_weak_top3_prefers_unmentioned() -> None:
    analytics = enrich_keyword_analytics(
        {},
        keywords=["强势词", "未露面词", "中等词"],
        platform_codes=["doubao", "deepseek"],
        report_type="weekly",
    )
    # 调低未露面词两端提及，模拟真未露面
    for section in analytics["platform_sections"]:
        for row in section["rows"]:
            if row["keyword"] == "未露面词":
                row["completed"] = 5
                row["mention_rate"] = {"current": 0.0, "previous": 10.0, "delta": -10, "direction": "declined", "text": "-10"}
                row["status"] = "未露面"
    for row in analytics["rows"]:
        if row["keyword"] == "未露面词":
            row["mention_rate"] = {"current": 40.0, "previous": 40.0, "delta": 0, "direction": "flat", "text": "持平"}
            row["status"] = "良好"
    # 重新按生产逻辑排序断言辅助函数
    from app.services.report_period_comparison_service import _keyword_worst_platform_mention

    worst = {
        r["keyword"]: _keyword_worst_platform_mention(r, analytics["platform_sections"])
        for r in analytics["rows"]
    }
    assert worst["未露面词"] == 0.0
    assert worst["未露面词"] <= min(worst.values())


def test_deck_pack_does_not_merge_different_platform_keyword_tables() -> None:
    """分页合并时不得把豆包/元宝词表行拼成一张总表。"""
    from playwright.sync_api import sync_playwright

    from app.services.report_period_deck_pdf_service import _pack_js

    # 两页各一端，高度都偏短 → mergeSparse 会尝试并页拼表
    html = """<!DOCTYPE html><html><head><style>
    .slide{width:2520px;height:1417px;position:relative;overflow:hidden}
    .pack-body{position:absolute;left:132px;top:210px;width:2260px;max-height:1100px;overflow:hidden;font-size:28px}
    .pack-item{margin:0 0 12px}
    .slide-title{position:absolute;left:140px;top:118px}
    table{width:100%;border-collapse:collapse;font-size:28px}
    td,th{padding:10px;border:1px solid #ccc}
    </style></head><body><main class="deck">
    <section class="slide" data-pack="1" data-merge-group="keywords">
      <h2 class="slide-title">核心监测词表现</h2>
      <div class="pack-body">
        <div class="pack-item kw-platform-panel" data-kw-platform="doubao">
          <h3 class="kw-platform-heading">豆包</h3>
          <table><thead><tr><th>#</th><th>词</th></tr></thead>
          <tbody><tr><td>1</td><td>词A</td></tr><tr><td>2</td><td>词B</td></tr></tbody></table>
        </div>
      </div>
    </section>
    <section class="slide" data-pack="1" data-merge-group="keywords">
      <h2 class="slide-title">核心监测词表现</h2>
      <div class="pack-body">
        <div class="pack-item kw-platform-panel" data-kw-platform="yuanbao">
          <h3 class="kw-platform-heading">元宝</h3>
          <table><thead><tr><th>#</th><th>词</th></tr></thead>
          <tbody><tr><td>1</td><td>词A</td></tr><tr><td>2</td><td>词B</td></tr></tbody></table>
        </div>
      </div>
    </section>
    </main></body></html>"""

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 2520, "height": 1417}, device_scale_factor=1)
            page.set_content(html, wait_until="load")
            page.evaluate(_pack_js())
            info = page.evaluate(
                """() => {
                  const slides = [...document.querySelectorAll('section.slide')];
                  const platforms = [...document.querySelectorAll('[data-kw-platform]')].map(
                    (el) => el.getAttribute('data-kw-platform')
                  );
                  const headings = [...document.querySelectorAll('.kw-platform-heading')].map(
                    (el) => (el.textContent || '').trim()
                  );
                  return {
                    slides: slides.length,
                    tables: document.querySelectorAll('table').length,
                    platforms,
                    headings,
                    rowCounts: [...document.querySelectorAll('table')].map(
                      (t) => (t.tBodies[0] ? t.tBodies[0].rows.length : 0)
                    ),
                  };
                }"""
            )
        finally:
            browser.close()

    assert info["tables"] >= 2, info
    assert "doubao" in info["platforms"], info
    assert "yuanbao" in info["platforms"], info
    assert "豆包" in info["headings"], info
    assert "元宝" in info["headings"], info
    # 不得并成一张 4 行总表
    assert all(c <= 2 for c in info["rowCounts"]), info
