"""周期监测幻灯：母版资产与页型映射自检。"""

from pathlib import Path

from app.services.report_period_deck_context_service import PERIOD_DECK_PIPELINE, build_period_deck_context
from app.services.report_period_deck_pdf_service import _ASSET_DIR, _monitor_asset_urls, _TEMPLATE_DIR


def test_monitor_master_assets_exist() -> None:
    names = (
        "monitor-cover.jpg",
        "monitor-section.jpg",
        "monitor-dark.jpg",
        "monitor-light.jpg",
        "monitor-light-wide.jpg",
        "monitor-thanks.jpg",
    )
    for name in names:
        path = _ASSET_DIR / name
        assert path.is_file(), name
        assert path.stat().st_size > 10_000, name


def test_monitor_asset_data_uris() -> None:
    urls = _monitor_asset_urls()
    assert set(urls) == {"cover", "section", "dark", "light", "light_wide", "thanks"}
    for key, uri in urls.items():
        assert uri.startswith("data:image/jpeg;base64,"), key


def test_period_deck_context_page_types() -> None:
    bundle = {
        "brand_name": "测品牌",
        "report_type": "weekly",
        "period_lbl": "2026-07-14 ~ 2026-07-20",
        "comparison": {
            "previous_period_label": "上期",
            "kpis": {
                "health_score": {"current": 80, "previous": 70, "direction": "up", "text": "+10"},
                "mention_rate": {"current": 55.0, "previous": 50.0, "direction": "up", "text": "+5.0pp"},
                "avg_rank": {"current": 2.5, "previous": 3.0, "direction": "up", "text": "提升 0.5"},
                "top3_rate": {"current": 40.0, "previous": 35.0, "direction": "up", "text": "+5.0pp"},
                "completed_count": {"current": 12},
            },
            "platform_rows": [],
            "highlights": ["测试结论一条"],
        },
        "snapshot": {"kpis": {"completed_count": 12}},
        "preface": {"period_range": "2026-07-14 ~ 2026-07-20", "lead": "前言"},
        "content_modules": {"disclaimer": {"body": "声明"}},
        "trend": {"points": [], "title": "日趋势"},
        "keyword_analytics": {"rows": []},
        "competitor_analytics": {},
        "competitors": ["竞品A"],
        "platform_codes": ["deepseek"],
        "generated": None,
    }
    ctx = build_period_deck_context(bundle)
    assert ctx["pipeline"] == PERIOD_DECK_PIPELINE
    assert ctx["kpi_slide_title"] == "核心指标 · 环比上周"
    assert "kpi-grid" in ctx["kpi_html"]
    assert (_TEMPLATE_DIR / "report.html").is_file()

    monthly = dict(bundle)
    monthly["report_type"] = "monthly"
    assert build_period_deck_context(monthly)["kpi_slide_title"] == "核心指标 · 环比上月"
    assert build_period_deck_context(monthly)["matrix_subtitle"] == ""


def test_period_deck_pdf_fast_knobs() -> None:
    """ponytail: 周期导出走 page.pdf，勿回退到逐页 JPEG 截图。"""
    from app.services.report_period_deck_pdf_service import (
        _ECHARTS_READY_TIMEOUT_MS,
        _PDF_EXPORT_MODE,
        _merge_slide_pdfs,
    )

    assert _PDF_EXPORT_MODE == "page-pdf"
    assert _ECHARTS_READY_TIMEOUT_MS <= 4000
    assert PERIOD_DECK_PIPELINE.startswith("monitor-deck-v21")
    # 最小自检：两页合并后仍是合法 PDF
    from pypdf import PdfWriter
    from io import BytesIO

    def _one_page() -> bytes:
        w = PdfWriter()
        w.add_blank_page(width=100, height=100)
        buf = BytesIO()
        w.write(buf)
        return buf.getvalue()

    merged = _merge_slide_pdfs([_one_page(), _one_page()])
    assert merged[:4] == b"%PDF"
    assert len(merged) > 100


def test_resolve_report_asset_path_monitor_and_echarts() -> None:
    from app.services.report_period_deck_pdf_service import _resolve_report_asset_path

    cover = _resolve_report_asset_path("/report-assets/monitor/monitor-cover.jpg?v=1")
    assert cover is not None and cover.is_file()
    assert cover.name == "monitor-cover.jpg"
    # echarts 可能在 public；没有也不应抛错
    _resolve_report_asset_path("/report-assets/echarts.min.js")
    assert _resolve_report_asset_path("/other/x.jpg") is None
    assert _resolve_report_asset_path("/report-assets/../secrets.txt") is None


def test_inject_pdf_base_href() -> None:
    from app.services.report_period_deck_pdf_service import _PDF_ASSET_ORIGIN, _inject_pdf_base_href

    html = "<html><head><title>t</title></head><body></body></html>"
    out = _inject_pdf_base_href(html)
    assert f'href="{_PDF_ASSET_ORIGIN}/"' in out
    assert out.count("<base") == 1
    assert _inject_pdf_base_href(out).count("<base") == 1
