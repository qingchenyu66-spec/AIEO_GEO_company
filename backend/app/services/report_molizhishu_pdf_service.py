"""模力指数风格浅色售前诊断 PDF：HTML 模板 + Playwright 渲染。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.services.report_molizhishu_context_service import build_molizhishu_report_context
from app.services.report_molizhishu_theme import resolve_theme, theme_scope

logger = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "templates" / "report_molizhishu"


def _jinja_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
    )


def render_molizhishu_report_html(
    payload: dict[str, Any],
    platform_names: dict[str, str] | None = None,
    *,
    theme: str = "b",
) -> str:
    theme_obj = resolve_theme(theme)
    with theme_scope(theme_obj.id):
        context = build_molizhishu_report_context(payload, platform_names)
        context["theme_id"] = theme_obj.id
        context["theme_label"] = theme_obj.label
        context["theme_css"] = theme_obj.css_block()
        template = _jinja_env().get_template("report.html")
        return template.render(**context)


def build_molizhishu_pdf(
    payload: dict[str, Any],
    platform_names: dict[str, str] | None = None,
    *,
    theme: str = "b",
) -> bytes:
    html = render_molizhishu_report_html(payload, platform_names, theme=theme)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("Playwright 未安装，无法生成模力风格 PDF") from exc

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 1200, "height": 1600})
            page.set_content(html, wait_until="load", timeout=60_000)
            page.evaluate("() => document.fonts.ready")
            page.wait_for_timeout(400)
            pdf_bytes = page.pdf(
                format="A4",
                landscape=False,
                print_background=True,
                margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
                prefer_css_page_size=False,
                scale=0.95,
            )
        finally:
            browser.close()
    logger.info("molizhishu-style diagnosis PDF generated for %s", payload.get("title"))
    return pdf_bytes
