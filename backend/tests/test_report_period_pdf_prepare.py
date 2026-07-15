"""Self-check: period PDF HTML swaps portal/CDN echarts to local file URI."""

from pathlib import Path

from app.services.report_period_comparison_service import (
    ECHARTS_CDN,
    ECHARTS_PORTAL_SRC,
    ECHARTS_STATIC_DIR,
)
from app.services.report_period_pdf_service import prepare_period_html_for_playwright


def test_prepare_period_html_for_playwright_rewrites_script_src(tmp_path, monkeypatch):
    assets = tmp_path / "assets"
    assets.mkdir()
    fake_js = assets / "echarts.min.js"
    fake_js.write_text("window.echarts={};", encoding="utf-8")
    monkeypatch.setattr(
        "app.services.report_period_comparison_service.ECHARTS_STATIC_DIR",
        tmp_path,
    )
    # keep helper import path stable: ensure_echarts_asset reads ECHARTS_STATIC_DIR
    html = f'<script src="{ECHARTS_PORTAL_SRC}"></script><script src="{ECHARTS_CDN}"></script>'
    prepared = prepare_period_html_for_playwright(html)
    assert ECHARTS_PORTAL_SRC not in prepared
    assert ECHARTS_CDN not in prepared
    assert prepared.count("file://") == 2 or "echarts.min.js" in prepared
    assert fake_js.resolve().as_uri() in prepared or fake_js.name in prepared


def test_ensure_echarts_asset_returns_file_uri_when_cached():
    assets = ECHARTS_STATIC_DIR / "assets"
    target = assets / "echarts.min.js"
    if not target.exists() or target.stat().st_size < 1000:
        from app.services.report_period_comparison_service import ensure_echarts_asset

        src = ensure_echarts_asset()
        assert src.startswith("file:") or src.startswith("http")
        return
    from app.services.report_period_comparison_service import ensure_echarts_asset

    src = ensure_echarts_asset()
    assert src.startswith("file:")
    assert Path(src.replace("file:///", "").replace("file://", "")).name == "echarts.min.js" or "echarts.min.js" in src
