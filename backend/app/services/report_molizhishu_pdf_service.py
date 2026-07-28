"""模力指数风格浅色售前诊断 PDF：HTML 模板 + Playwright 渲染。"""

from __future__ import annotations

import base64
import logging
import threading
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.services.report_molizhishu_context_service import build_molizhishu_report_context
from app.services.report_molizhishu_theme import resolve_theme, theme_scope

logger = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "templates" / "report_molizhishu"
_ASSET_DIR = _TEMPLATE_DIR / "assets"

# 横版母版尺寸（与 IDEA PPT 页一致）；PDF 点阵 = px * 72/96
_SLIDE_WIDTH_PX = 2520
_SLIDE_HEIGHT_PX = 1417
_PDF_PAGE_W_PT = _SLIDE_WIDTH_PX * 72 / 96
_PDF_PAGE_H_PT = _SLIDE_HEIGHT_PX * 72 / 96
# 指纹用：改导出链路时 bump，避免命中旧缓存
# jpeg-pages-v5：核心页禁止 KPI 裁切；结论过多拆续页；封面 chip 换行
_PDF_PIPELINE = "jpeg-pages-v5"
_JPEG_SCREENSHOT_QUALITY = 90

_tls = threading.local()


def _playwright_local():
    if not hasattr(_tls, "browser"):
        _tls.browser = None
        _tls.playwright = None
    return _tls


def _pack_js() -> str:
    return (_TEMPLATE_DIR / "deck_pack.js").read_text(encoding="utf-8")


def _idea_asset_stamp() -> str:
    parts: list[str] = [_PDF_PIPELINE]
    for name in ("idea-cover.jpg", "idea-section.jpg", "idea-dark.jpg", "idea-light.jpg", "idea-thanks.jpg"):
        path = _ASSET_DIR / name
        try:
            st = path.stat()
            parts.append(f"{name}:{st.st_mtime_ns}:{st.st_size}")
        except OSError:
            parts.append(f"{name}:0")
    return "|".join(parts)


@lru_cache(maxsize=4)
def _idea_asset_urls_cached(stamp: str) -> dict[str, str]:
    """Embed masters as data URIs.

    Playwright ``set_content`` blocks ``file://`` images; absolute file URIs
    also break HTML preview. Data URIs work for both PDF and portal preview.
    stamp 变化时自动换缓存，避免母版替换后进程内仍用旧图。
    亮底用新母版 JPG（0723）；截图侧 JPEG 只编码一次。
    """
    del stamp  # only used as lru key

    def _data_uri(name: str) -> str:
        path = _ASSET_DIR / name
        if not path.is_file():
            raise FileNotFoundError(f"missing report master asset: {path}")
        mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
        payload = base64.standard_b64encode(path.read_bytes()).decode("ascii")
        return f"data:{mime};base64,{payload}"

    return {
        "cover": _data_uri("idea-cover.jpg"),
        "section": _data_uri("idea-section.jpg"),
        "dark": _data_uri("idea-dark.jpg"),
        "light": _data_uri("idea-light.jpg"),
        "thanks": _data_uri("idea-thanks.jpg"),
    }


def _idea_asset_urls() -> dict[str, str]:
    return _idea_asset_urls_cached(_idea_asset_stamp())


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
        context["idea_assets"] = _idea_asset_urls()
        context["theme_id"] = theme_obj.id
        context["theme_label"] = theme_obj.label
        context["theme_css"] = theme_obj.css_block()
        template = _jinja_env().get_template("report.html")
        return template.render(**context)


def pdf_from_slide_images(image_pages: list[bytes]) -> bytes:
    """把逐页截图打进 PDF（JPEG 优先，体积约为 PNG 无损的 1/5～1/10）。

    不用 Chromium ``page.pdf()``，避免母版再被压成脏 JPEG；截图侧只编码一次。
    """
    if not image_pages:
        raise ValueError("no slide pages to assemble")
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=(_PDF_PAGE_W_PT, _PDF_PAGE_H_PT))
    for raw in image_pages:
        c.drawImage(
            ImageReader(BytesIO(raw)),
            0,
            0,
            width=_PDF_PAGE_W_PT,
            height=_PDF_PAGE_H_PT,
            preserveAspectRatio=False,
            mask="auto",
        )
        c.showPage()
    c.save()
    return buf.getvalue()


# 兼容旧名
pdf_from_slide_pngs = pdf_from_slide_images


def build_molizhishu_pdf(
    payload: dict[str, Any],
    platform_names: dict[str, str] | None = None,
    *,
    theme: str = "b",
) -> bytes:
    def _progress(label: str, pct: int | None = None) -> None:
        try:
            from app.services.report_export_job_service import report_export_progress

            report_export_progress(label, pct)
        except Exception:
            pass

    _progress("内容写入中…", 20)
    html = render_molizhishu_report_html(payload, platform_names, theme=theme)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("Playwright 未安装，无法生成诊断报告 PDF") from exc

    # ponytail: 线程内复用 Chromium，避免每次 launch/close 多等数秒～十余秒
    _progress("PDF渲染中…", 35)
    local = _playwright_local()
    if local.browser is None or not local.browser.is_connected():
        if local.playwright is not None:
            try:
                local.playwright.stop()
            except Exception:
                pass
        local.playwright = sync_playwright().start()
        local.browser = local.playwright.chromium.launch(headless=True)

    page = local.browser.new_page(
        viewport={"width": _SLIDE_WIDTH_PX, "height": _SLIDE_HEIGHT_PX},
        device_scale_factor=1,
    )
    page_images: list[bytes] = []
    try:
        page.set_content(html, wait_until="load", timeout=120_000)
        page.evaluate(
            """() => Promise.all([
                document.fonts.ready,
                ...[...document.images].map((img) =>
                    img.complete
                        ? Promise.resolve()
                        : new Promise((resolve) => {
                            img.addEventListener('load', resolve, { once: true });
                            img.addEventListener('error', resolve, { once: true });
                          })
                ),
            ])"""
        )
        page.wait_for_timeout(200)
        pack_result = page.evaluate(_pack_js())
        logger.info("molizhishu deck pack result=%s", pack_result)
        page.wait_for_timeout(150)

        slides = page.locator("section.slide")
        n = slides.count()
        if n <= 0:
            raise RuntimeError("诊断报告无可用幻灯片，无法生成 PDF")
        _progress("PDF渲染中…", 70)
        for i in range(n):
            page_images.append(
                slides.nth(i).screenshot(
                    type="jpeg",
                    quality=_JPEG_SCREENSHOT_QUALITY,
                    animations="disabled",
                )
            )

        _progress("PDF生成中…", 90)
        pdf_bytes = pdf_from_slide_images(page_images)
    finally:
        page.close()
    logger.info(
        "molizhishu-style diagnosis PDF generated for %s pages=%s pipeline=%s bytes=%s",
        payload.get("title"),
        len(page_images),
        _PDF_PIPELINE,
        len(pdf_bytes),
    )
    return pdf_bytes
