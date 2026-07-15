"""周期报告 V2 环比 HTML → PDF（Playwright，与桌面样例同版式）。"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.services.report_period_service import PERIOD_COMPARISON_REPORT_TYPES as PERIOD_EXPORT_TYPES

_PRINT_CSS = """
@media print {
  .page {
    max-width: none !important;
    margin: 0 !important;
    border-radius: 0 !important;
    overflow: visible !important;
    box-shadow: none !important;
  }
  .content { padding: 20px 24px !important; }
  h2, h3, h4 {
    break-after: avoid !important;
    page-break-after: avoid !important;
  }
  section#platform,
  section#kpi,
  section#conclusions,
  section#preface,
  section#toc,
  section#disclaimer,
  .print-keep-section,
  .kw-weak,
  .kw-matrix,
  .comp-insights,
  .trend-summary,
  .note,
  .warn,
  .card-box,
  .preface-grid {
    break-inside: avoid !important;
    page-break-inside: avoid !important;
  }
  section#platform table,
  .trend-section > table,
  .competitor-section > table,
  .kw-matrix table,
  .matrix-table,
  .source-table-box table {
    break-inside: avoid !important;
    page-break-inside: avoid !important;
  }
  section#keywords > table {
    break-inside: auto !important;
    page-break-inside: auto !important;
  }
  thead { display: table-header-group !important; }
  tr {
    break-inside: avoid !important;
    page-break-inside: avoid !important;
  }
  .kpi-grid { grid-template-columns: repeat(4, 1fr) !important; break-inside: avoid !important; }
  .trend-charts { grid-template-columns: 1fr !important; gap: 12px !important; break-inside: avoid !important; }
  .trend-chart-box,
  .comp-trend-box,
  .card-box:has(.echart-canvas) {
    min-width: 0 !important;
    width: 100% !important;
    overflow: hidden !important;
    break-inside: avoid !important;
    page-break-inside: avoid !important;
  }
  .echart-canvas,
  .echart-canvas-wide {
    width: 100% !important;
    max-width: 100% !important;
    box-sizing: border-box !important;
    break-inside: avoid !important;
    page-break-inside: avoid !important;
  }
  .echart-canvas { height: 260px !important; min-height: 260px !important; }
  .echart-canvas-wide { height: 300px !important; min-height: 300px !important; }
}
"""

A4_CONTENT_PX = 794


def prepare_period_html_for_playwright(html: str) -> str:
    """把预览用同源/CDN 路径换成本地 file://，否则 set_content 下 echarts 永远加载失败。"""
    from app.services.report_period_comparison_service import (
        ECHARTS_CDN,
        ECHARTS_PORTAL_SRC,
        ensure_echarts_asset,
    )

    local = ensure_echarts_asset()
    return html.replace(ECHARTS_PORTAL_SRC, local).replace(ECHARTS_CDN, local)


def _wait_charts_ready(page) -> None:
    try:
        page.evaluate("() => document.fonts.ready")
    except Exception:
        pass
    try:
        # ponytail: 图表挂不上就继续出 PDF，比卡死到 timeout 更可交付
        page.wait_for_function(
            """
            () => {
              const boxes = document.querySelectorAll('.echart-canvas');
              if (!boxes.length) return true;
              if (!window.echarts) return false;
              const canvases = document.querySelectorAll('canvas');
              return canvases.length >= boxes.length;
            }
            """,
            timeout=15_000,
        )
        page.wait_for_timeout(500)
    except Exception:
        page.wait_for_timeout(200)


def _inject_print_layout(page) -> None:
    page.emulate_media(media="print")
    page.add_style_tag(content=_PRINT_CSS)
    page.evaluate(
        """
        () => {
          if (!window.echarts) return;
          document.querySelectorAll('.echart-canvas').forEach((el) => {
            const inst = echarts.getInstanceByDom(el);
            if (inst) inst.resize();
          });
        }
        """
    )
    page.wait_for_timeout(300)


def build_period_report_pdf(
    db: Session,
    report: dict[str, Any],
    *,
    tenant_id: int,
) -> bytes:
    report_type = str(report.get("report_type") or "")
    if report_type not in PERIOD_EXPORT_TYPES:
        raise ValueError(f"unsupported report type: {report_type}")

    from app.services.report_period_comparison_service import build_period_report_html_for_export

    html = prepare_period_html_for_playwright(
        build_period_report_html_for_export(db, report, tenant_id=tenant_id)
    )
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("Playwright 未安装，无法生成周期报告 PDF") from exc

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": A4_CONTENT_PX, "height": 1600})
            # networkidle 会等外链/挂死请求；本地 file:// echarts + load 即可
            page.set_content(html, wait_until="load", timeout=60_000)
            _wait_charts_ready(page)
            _inject_print_layout(page)
            return page.pdf(
                format="A4",
                landscape=False,
                print_background=True,
                margin={"top": "12mm", "right": "10mm", "bottom": "12mm", "left": "10mm"},
                prefer_css_page_size=False,
                scale=1.0,
            )
        finally:
            browser.close()
