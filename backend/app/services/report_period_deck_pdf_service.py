"""周期监测报告 16:9 幻灯 PDF：0727 母版 + Playwright 截图拼页。

诊断仍走 report_molizhishu；本链路仅 weekly/monthly/quarterly/annual。
"""

from __future__ import annotations

import base64
import logging
import threading
from functools import lru_cache
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy.orm import Session

from app.services.report_molizhishu_pdf_service import pdf_from_slide_images
from app.services.report_period_comparison_service import (
    assemble_period_report_bundle,
    load_echarts_bundle_text,
)
from app.services.report_period_deck_context_service import (
    PERIOD_DECK_PIPELINE,
    build_period_deck_context,
)
from app.services.report_period_service import PERIOD_COMPARISON_REPORT_TYPES

logger = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "templates" / "report_monitor"
_ASSET_DIR = _TEMPLATE_DIR / "assets"
_SLIDE_WIDTH_PX = 2520
_SLIDE_HEIGHT_PX = 1417
_JPEG_SCREENSHOT_QUALITY = 90

_tls = threading.local()


def _playwright_local():
    if not hasattr(_tls, "browser"):
        _tls.browser = None
        _tls.playwright = None
    return _tls


def _pack_js() -> str:
    return (_TEMPLATE_DIR / "deck_pack.js").read_text(encoding="utf-8")


def _asset_stamp() -> str:
    parts: list[str] = [PERIOD_DECK_PIPELINE]
    for name in (
        "monitor-cover.jpg",
        "monitor-section.jpg",
        "monitor-dark.jpg",
        "monitor-light.jpg",
        "monitor-light-wide.jpg",
        "monitor-thanks.jpg",
    ):
        path = _ASSET_DIR / name
        try:
            st = path.stat()
            parts.append(f"{name}:{st.st_mtime_ns}:{st.st_size}")
        except OSError:
            parts.append(f"{name}:0")
    return "|".join(parts)


@lru_cache(maxsize=4)
def _monitor_asset_urls_cached(stamp: str) -> dict[str, str]:
    del stamp

    def _data_uri(name: str) -> str:
        path = _ASSET_DIR / name
        if not path.is_file():
            raise FileNotFoundError(f"missing monitor master asset: {path}")
        payload = base64.standard_b64encode(path.read_bytes()).decode("ascii")
        return f"data:image/jpeg;base64,{payload}"

    return {
        "cover": _data_uri("monitor-cover.jpg"),
        "section": _data_uri("monitor-section.jpg"),
        "dark": _data_uri("monitor-dark.jpg"),
        "light": _data_uri("monitor-light.jpg"),
        "light_wide": _data_uri("monitor-light-wide.jpg"),
        "thanks": _data_uri("monitor-thanks.jpg"),
    }


def _monitor_asset_urls() -> dict[str, str]:
    return _monitor_asset_urls_cached(_asset_stamp())


def _monitor_asset_http_urls() -> dict[str, str]:
    """预览用同源静态路径（勿 data URI）；由 frontend/public/report-assets/monitor 提供。"""
    return {
        "cover": "/report-assets/monitor/monitor-cover.jpg",
        "section": "/report-assets/monitor/monitor-section.jpg",
        "dark": "/report-assets/monitor/monitor-dark.jpg",
        "light": "/report-assets/monitor/monitor-light.jpg",
        "light_wide": "/report-assets/monitor/monitor-light-wide.jpg",
        "thanks": "/report-assets/monitor/monitor-thanks.jpg",
    }


def _jinja_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
    )


def _parse_report_date(value: Any):
    from datetime import date, datetime

    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def render_period_deck_html_from_bundle(
    bundle: dict[str, Any],
    *,
    embed_assets: bool = True,
) -> str:
    # 2026-07-28 - 预览 11MB 卡死：外链母版图+echarts；PDF 仍内联保证 Playwright set_content 离线可截
    if embed_assets:
        echarts = load_echarts_bundle_text().replace("</script", "<\\/script")
        assets = _monitor_asset_urls()
        echarts_src = ""
    else:
        echarts = ""
        assets = _monitor_asset_http_urls()
        echarts_src = "/report-assets/echarts.min.js"
    context = build_period_deck_context(bundle, echarts_inline=echarts, echarts_src=echarts_src)
    if not embed_assets:
        # 预览禁用 file:// @font-face（blob 加载不了，还会干扰缓存判定）
        context["font_face_css"] = ""
    context["monitor_assets"] = assets
    return _jinja_env().get_template("report.html").render(**context)


def build_period_deck_html(
    db: Session,
    report: dict[str, Any],
    *,
    tenant_id: int,
    embed_assets: bool = True,
) -> str:
    report_type = str(report.get("report_type") or "")
    if report_type not in PERIOD_COMPARISON_REPORT_TYPES:
        raise ValueError(f"unsupported period deck type: {report_type}")
    period_start = _parse_report_date(report.get("period_start"))
    period_end = _parse_report_date(report.get("period_end"))
    if period_start is None or period_end is None:
        raise ValueError("period report missing period_start/period_end")
    generated = _parse_report_date(report.get("generated_at"))
    bundle = assemble_period_report_bundle(
        db,
        tenant_id=tenant_id,
        report_type=report_type,
        period_start=period_start,
        period_end=period_end,
        generated=generated,
    )
    return render_period_deck_html_from_bundle(bundle, embed_assets=embed_assets)


def build_period_deck_pdf(db: Session, report: dict[str, Any], *, tenant_id: int) -> bytes:
    """2026-07-28 - 周期 PDF 改监测幻灯截图，弃用 A4 page.pdf（本函数替代 build_period_report_pdf）。"""

    def _progress(label: str, pct: int | None = None) -> None:
        try:
            from app.services.report_export_job_service import report_export_progress

            report_export_progress(label, pct)
        except Exception:
            pass

    _progress("内容写入中…", 20)
    html = build_period_deck_html(db, report, tenant_id=tenant_id)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("Playwright 未安装，无法生成周期监测报告 PDF") from exc

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
        page.set_content(html, wait_until="load", timeout=180_000)
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
        # 等趋势 echarts 画完（无图则立刻 resolve）
        page.evaluate(
            """() => new Promise((resolve) => {
                const nodes = [...document.querySelectorAll('.echart-canvas')];
                if (!nodes.length) { resolve(); return; }
                const start = Date.now();
                const tick = () => {
                    const ready = nodes.every((el) => el.querySelector('canvas'));
                    if (ready || Date.now() - start > 8000) resolve();
                    else requestAnimationFrame(tick);
                };
                tick();
            })"""
        )
        page.wait_for_timeout(200)
        pack_result = page.evaluate(_pack_js())
        logger.info("period monitor deck pack result=%s", pack_result)
        page.wait_for_timeout(150)

        slides = page.locator("section.slide")
        n = slides.count()
        if n <= 0:
            raise RuntimeError("周期监测报告无可用幻灯片，无法生成 PDF")
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
        "period monitor deck PDF generated title=%s pages=%s pipeline=%s bytes=%s",
        report.get("title"),
        len(page_images),
        PERIOD_DECK_PIPELINE,
        len(pdf_bytes),
    )
    return pdf_bytes
