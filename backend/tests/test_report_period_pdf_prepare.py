"""Self-check: period report HTML inlines echarts for preview/PDF."""

from app.services.report_period_comparison_service import (
    ECHARTS_CDN,
    ECHARTS_PORTAL_SRC,
    inline_echarts_scripts,
)
from app.services.report_period_pdf_service import prepare_period_html_for_playwright


def test_inline_echarts_scripts_replaces_portal_src(tmp_path, monkeypatch):
    assets = tmp_path / "assets"
    assets.mkdir()
    # 足够大，跳过重新下载；内容要含 echarts 字样方便断言
    fake = "/* echarts */\n" + ("x" * 2000) + "\nwindow.__GEO_ECHARTS_FAKE__=1;"
    (assets / "echarts.min.js").write_text(fake, encoding="utf-8")
    monkeypatch.setattr(
        "app.services.report_period_comparison_service.ECHARTS_STATIC_DIR",
        tmp_path,
    )
    html = f'<script src="{ECHARTS_PORTAL_SRC}"></script><div id="trendMentionChart"></div>'
    prepared = inline_echarts_scripts(html)
    assert ECHARTS_PORTAL_SRC not in prepared
    assert "echarts.min.js" not in prepared
    assert "__GEO_ECHARTS_FAKE__" in prepared
    assert prepared.startswith("<script>")


def test_prepare_period_html_for_playwright_inlines_cdn_src(tmp_path, monkeypatch):
    assets = tmp_path / "assets"
    assets.mkdir()
    fake = "/* echarts */\n" + ("y" * 2000) + "\nwindow.__GEO_ECHARTS_PDF__=1;"
    (assets / "echarts.min.js").write_text(fake, encoding="utf-8")
    monkeypatch.setattr(
        "app.services.report_period_comparison_service.ECHARTS_STATIC_DIR",
        tmp_path,
    )
    html = f'<script src="{ECHARTS_CDN}"></script>'
    prepared = prepare_period_html_for_playwright(html)
    assert ECHARTS_CDN not in prepared
    assert "__GEO_ECHARTS_PDF__" in prepared


def test_inline_echarts_scripts_is_idempotent(tmp_path, monkeypatch):
    assets = tmp_path / "assets"
    assets.mkdir()
    fake = "/* echarts */\n" + ("z" * 2000) + "\nwindow.__GEO_ECHARTS_ONCE__=1;"
    (assets / "echarts.min.js").write_text(fake, encoding="utf-8")
    monkeypatch.setattr(
        "app.services.report_period_comparison_service.ECHARTS_STATIC_DIR",
        tmp_path,
    )
    html = f'<script src="{ECHARTS_PORTAL_SRC}"></script>'
    once = inline_echarts_scripts(html)
    twice = inline_echarts_scripts(once)
    assert once == twice
    assert once.count("__GEO_ECHARTS_ONCE__") == 1
