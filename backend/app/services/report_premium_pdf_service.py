"""Premium 深色简报 PDF：HTML 模板 + Playwright 渲染。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.services.report_premium_context_service import build_premium_report_context
from app.services.report_premium_font_service import build_font_face_css

logger = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "templates" / "report_premium"


def _jinja_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
    )


def render_premium_report_html(payload: dict[str, Any]) -> str:
    context = build_premium_report_context(payload)
    context["font_face_css"] = build_font_face_css()
    template = _jinja_env().get_template("report.html")
    return template.render(**context)


def build_premium_pdf(payload: dict[str, Any]) -> bytes:
    html = render_premium_report_html(payload)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("Playwright 未安装，无法生成 Premium PDF") from exc

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 1123, "height": 794})
            page.set_content(html, wait_until="load", timeout=60_000)
            page.evaluate("() => document.fonts.ready")
            page.wait_for_timeout(500)
            pdf_bytes = page.pdf(
                format="A4",
                landscape=True,
                print_background=True,
                margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
                prefer_css_page_size=True,
            )
        finally:
            browser.close()
    return pdf_bytes
