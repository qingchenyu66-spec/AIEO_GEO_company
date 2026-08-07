"""周期监测报告 16:9 幻灯 PDF：0727 母版 + 逐页 page.pdf 合并。

诊断仍走 report_molizhishu；本链路仅 weekly/monthly/quarterly/annual。
"""

from __future__ import annotations

import base64
import logging
import re
import threading
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from pypdf import PdfReader, PdfWriter
from sqlalchemy.orm import Session

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
_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_REPO_ROOT = _BACKEND_ROOT.parent
_PUBLIC_REPORT_ASSETS = _REPO_ROOT / "frontend" / "public" / "report-assets"
_SLIDE_WIDTH_PX = 2520
_SLIDE_HEIGHT_PX = 1417
# 2026-07-29 - A：逐页 Chromium page.pdf，弃用 element JPEG 截图（已弃用 scale/q 旋钮）
_PDF_EXPORT_MODE = "page-pdf"
_ECHARTS_READY_TIMEOUT_MS = 3000
# Playwright set_content 用假源，配合 route 喂 /report-assets
_PDF_ASSET_ORIGIN = "http://geo-report.local"
_CHROMIUM_LAUNCH_ARGS = (
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--no-sandbox",
    "--font-render-hinting=none",
    "--disable-extensions",
    "--disable-background-networking",
    "--mute-audio",
)

_tls = threading.local()


def _playwright_local():
    if not hasattr(_tls, "browser"):
        _tls.browser = None
        _tls.playwright = None
    return _tls


def _ensure_chromium(sync_playwright):
    """复用线程内 Chromium；挂掉则重启。"""
    local = _playwright_local()
    if local.browser is not None and local.browser.is_connected():
        return local.browser
    if local.playwright is not None:
        try:
            local.playwright.stop()
        except Exception:
            pass
    local.playwright = sync_playwright().start()
    # 2026-07-29 - 无头加速参数；ceiling：无 GPU 时个别字体 hint 略糙，可调回默认 launch
    local.browser = local.playwright.chromium.launch(
        headless=True,
        args=list(_CHROMIUM_LAUNCH_ARGS),
    )
    return local.browser


def _resolve_report_asset_path(url_path: str) -> Path | None:
    """把 /report-assets/... 映射到仓库静态文件或模板母版目录。"""
    from urllib.parse import unquote, urlparse

    path = unquote(urlparse(url_path).path if "://" in url_path else url_path)
    path = path.split("?", 1)[0]
    if not path.startswith("/report-assets/"):
        return None
    rel = path[len("/report-assets/") :].lstrip("/")
    if not rel or ".." in rel.split("/"):
        return None
    candidates: list[Path] = [_PUBLIC_REPORT_ASSETS / rel]
    if rel.startswith("monitor/"):
        candidates.append(_ASSET_DIR / rel.split("/", 1)[1])
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _inject_pdf_base_href(html: str) -> str:
    """预览 HTML 用根路径资源；set_content 需 base，才能被 route 接到。"""
    if re.search(r"<base\b", html, flags=re.I):
        return html
    marker = f'<base href="{_PDF_ASSET_ORIGIN}/">'
    head = re.search(r"(<head[^>]*>)", html, flags=re.I)
    if head:
        return f"{html[: head.end()]}\n{marker}{html[head.end() :]}"
    return f"{marker}\n{html}"


def _merge_slide_pdfs(parts: list[bytes]) -> bytes:
    """多页单页 PDF 合并为一份；空列表直接失败。"""
    if not parts:
        raise ValueError("empty slide pdf parts")
    writer = PdfWriter()
    for blob in parts:
        reader = PdfReader(BytesIO(blob))
        for page in reader.pages:
            writer.add_page(page)
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def _install_report_asset_routes(page) -> None:
    import mimetypes

    def _on_asset(route) -> None:
        request_url = route.request.url
        asset = _resolve_report_asset_path(request_url)
        if asset is None:
            route.fulfill(status=404, body=b"missing report asset")
            return
        mime = mimetypes.guess_type(str(asset))[0] or "application/octet-stream"
        route.fulfill(path=str(asset), content_type=mime)

    def _on_other(route) -> None:
        # 2026-07-29 - 假源未路由的请求会挂死 fonts/images wait；立刻 404
        route.fulfill(status=404, body=b"")

    # Playwright 后注册优先：先兜底，再挂 /report-assets
    page.route(f"{_PDF_ASSET_ORIGIN}/**", _on_other)
    page.route(f"{_PDF_ASSET_ORIGIN}/report-assets/**", _on_asset)


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
    # 2026-07-28 - 压图后用 mtime 破浏览器旧大图缓存
    try:
        ver = str(int((_ASSET_DIR / "monitor-cover.jpg").stat().st_mtime))
    except OSError:
        ver = "1"
    q = f"?v={ver}"
    return {
        "cover": f"/report-assets/monitor/monitor-cover.jpg{q}",
        "section": f"/report-assets/monitor/monitor-section.jpg{q}",
        "dark": f"/report-assets/monitor/monitor-dark.jpg{q}",
        "light": f"/report-assets/monitor/monitor-light.jpg{q}",
        "light_wide": f"/report-assets/monitor/monitor-light-wide.jpg{q}",
        "thanks": f"/report-assets/monitor/monitor-thanks.jpg{q}",
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
    context.setdefault("completion_mode", False)
    context.setdefault("completion_sections", [])
    return _jinja_env().get_template("report.html").render(**context)


def build_completion_deck_html(
    payload: dict[str, Any],
    platform_names: dict[str, str] | None = None,
    *,
    embed_assets: bool = True,
) -> str:
    """结项报告：周报 16:9 母版 + 现有结项正文章节整包入幻灯。"""
    # 2026-08-07 - 结项改用监测周报模板，内容从完整版 HTML 抽出不砍块
    from app.services.report_completion_html_service import (
        COMPLETION_DECK_PIPELINE,
        build_completion_deck_meta,
        build_completion_report_html,
        extract_completion_deck_sections,
    )
    from app.services.report_premium_font_service import build_font_face_css

    platform_names = platform_names or {}
    full_html = build_completion_report_html(payload, platform_names)
    sections = extract_completion_deck_sections(full_html)
    meta = build_completion_deck_meta(payload, platform_names)
    if embed_assets:
        assets = _monitor_asset_urls()
        font_css = build_font_face_css()
    else:
        assets = _monitor_asset_http_urls()
        font_css = ""
    context = {
        "page_title": meta["page_title"],
        "font_face_css": font_css,
        "pipeline": COMPLETION_DECK_PIPELINE,
        "brand_name": meta["brand_name"],
        "type_label": meta["type_label"],
        "period_range": meta["period_range"],
        "generated_at": meta["generated_at"],
        "competitor_text": meta["competitor_text"],
        "platform_chip_rows": meta["platform_chip_rows"],
        "monitor_assets": assets,
        "completion_mode": True,
        "completion_sections": sections,
        "echarts_inline": "",
        "echarts_src": "",
        # 非结项分支占位，避免模板缺变量
        "kpi_slide_title": "",
        "kpi_html": "",
        "sample_meta_html": "",
        "conclusions_html": "",
        "preface_html": "",
        "preface_subtitle": "",
        "has_trend": False,
        "trend_subtitle": "",
        "trend_head_html": "",
        "trend_table_html": "",
        "keyword_html": "",
        "keyword_subtitle": "",
        "has_matrix": False,
        "matrix_html": "",
        "matrix_subtitle": "",
        "competitor_html": "",
        "competitor_head_html": "",
        "competitor_actions_html": "",
        "competitor_table_html": "",
        "competitor_subtitle": "",
        "platform_html": "",
        "platform_subtitle": "",
        "has_tail": False,
        "tail_parts": [],
        "tail_part_titles": [],
        "tail_title": "",
        "tail_subtitle": "",
        "has_disclaimer": False,
        "disclaimer_html": "",
        "disclaimer_subtitle": "",
    }
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


def build_period_deck_pdf(
    db: Session,
    report: dict[str, Any],
    *,
    tenant_id: int,
    theme: str = "b",
) -> bytes:
    """2026-07-28 - 周期 PDF 改监测幻灯截图，弃用 A4 page.pdf（本函数替代 build_period_report_pdf）。

    2026-07-29 - 复用报告中心预览 HTML（落盘指纹缓存），避免导出再 embed+assemble 一套；
    Playwright 经 route 喂 /report-assets，不再灌 11MB data URI。

    2026-07-29 - A：逐页只显示当前 slide → Chromium page.pdf → pypdf 合并；
    已弃用 element JPEG 截图（全分辨率/降采样都过慢）。
    """

    def _progress(label: str, pct: int | None = None) -> None:
        try:
            from app.services.report_export_job_service import report_export_progress

            report_export_progress(label, pct)
        except Exception:
            pass

    del tenant_id  # 预览链路从 report.tenant_id 解析；保留形参兼容旧调用
    _progress("内容写入中…", 20)
    # 懒导入避免与 report_export_service 循环依赖
    from app.services.report_export_service import read_or_build_report_html_preview

    html = read_or_build_report_html_preview(db, report, theme=theme)
    html = _inject_pdf_base_href(html)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("Playwright 未安装，无法生成周期监测报告 PDF") from exc

    _progress("PDF渲染中…", 35)
    browser = _ensure_chromium(sync_playwright)

    page = browser.new_page(
        viewport={"width": _SLIDE_WIDTH_PX, "height": _SLIDE_HEIGHT_PX},
        device_scale_factor=1,
    )
    page_pdfs: list[bytes] = []
    try:
        _install_report_asset_routes(page)
        page.emulate_media(media="screen")
        # domcontentloaded 后靠 images/fonts Promise；外链 echarts/母版由 route 提供
        page.set_content(html, wait_until="domcontentloaded", timeout=180_000)
        # 外链 echarts 需等全局就绪，再等图/canvas
        page.evaluate(
            """() => new Promise((resolve) => {
                if (window.echarts) { resolve(); return; }
                const start = Date.now();
                const tick = () => {
                    if (window.echarts || Date.now() - start > 8000) resolve();
                    else requestAnimationFrame(tick);
                };
                tick();
            })"""
        )
        # 2026-07-29 - fonts/images 无超时会卡死导出；8s 封顶
        page.evaluate(
            """() => Promise.race([
                Promise.all([
                    document.fonts.ready,
                    ...[...document.images].map((img) =>
                        img.complete
                            ? Promise.resolve()
                            : new Promise((resolve) => {
                                img.addEventListener('load', resolve, { once: true });
                                img.addEventListener('error', resolve, { once: true });
                              })
                    ),
                ]),
                new Promise((resolve) => setTimeout(resolve, 8000)),
            ])"""
        )
        # 等趋势 echarts 画完（无图则立刻 resolve）
        page.evaluate(
            f"""() => new Promise((resolve) => {{
                const nodes = [...document.querySelectorAll('.echart-canvas')];
                if (!nodes.length) {{ resolve(); return; }}
                const start = Date.now();
                const tick = () => {{
                    const ready = nodes.every((el) => el.querySelector('canvas'));
                    if (ready || Date.now() - start > {_ECHARTS_READY_TIMEOUT_MS}) resolve();
                    else requestAnimationFrame(tick);
                }};
                tick();
            }})"""
        )
        # 预览 HTML 已内嵌 deck_pack（等 fonts 后异步跑）；此处强制同步重跑，避免字体加载前量高导致裁切
        # 2026-08-07 - 结项字号加大后，抢跑 pack 会 stillClipped
        page.evaluate(
            """() => {
                window.__GEO_DECK_PACK_SYNC__ = true;
                delete document.documentElement.dataset.geoDeckPacked;
            }"""
        )
        pack_result = page.evaluate(_pack_js())
        logger.info("period monitor deck pack result=%s", pack_result)

        # 收口 deck 边距，避免 page.pdf 多出空白页边
        page.evaluate(
            f"""() => {{
                if (document.getElementById('geo-pdf-page-mode')) return;
                const style = document.createElement('style');
                style.id = 'geo-pdf-page-mode';
                style.textContent = `
                  html, body {{
                    margin: 0 !important;
                    padding: 0 !important;
                    overflow: hidden !important;
                    width: {_SLIDE_WIDTH_PX}px !important;
                    height: {_SLIDE_HEIGHT_PX}px !important;
                  }}
                  main.deck {{
                    margin: 0 !important;
                    padding: 0 !important;
                    gap: 0 !important;
                    width: {_SLIDE_WIDTH_PX}px !important;
                  }}
                `;
                document.head.appendChild(style);
            }}"""
        )

        n = page.locator("section.slide").count()
        if n <= 0:
            raise RuntimeError("周期监测报告无可用幻灯片，无法生成 PDF")
        for i in range(n):
            pct = 70 + int(20 * (i / max(n, 1)))
            _progress(f"PDF渲染中（{i + 1}/{n}）…", pct)
            # 只留当前页，避免整份长文档被打进单页 PDF
            page.evaluate(
                """(idx) => {
                    const slides = Array.from(document.querySelectorAll('section.slide'));
                    slides.forEach((s, j) => {
                        if (j === idx) s.style.removeProperty('display');
                        else s.style.setProperty('display', 'none', 'important');
                    });
                    window.scrollTo(0, 0);
                }""",
                i,
            )
            page.evaluate(
                "() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)))"
            )
            page_pdfs.append(
                page.pdf(
                    width=f"{_SLIDE_WIDTH_PX}px",
                    height=f"{_SLIDE_HEIGHT_PX}px",
                    print_background=True,
                    margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
                )
            )
        _progress("PDF生成中…", 90)
        pdf_bytes = _merge_slide_pdfs(page_pdfs)
    finally:
        page.close()

    logger.info(
        "period monitor deck PDF generated title=%s pages=%s pipeline=%s mode=%s bytes=%s",
        report.get("report_title") or report.get("title"),
        len(page_pdfs),
        PERIOD_DECK_PIPELINE,
        _PDF_EXPORT_MODE,
        len(pdf_bytes),
    )
    return pdf_bytes
