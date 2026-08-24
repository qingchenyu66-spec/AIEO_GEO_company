"""售前诊断 HTML 导出（无 Playwright）。"""

from __future__ import annotations

from typing import Any

from app.services.report_molizhishu_pdf_service import render_molizhishu_report_html

__all__ = ["build_molizhishu_html", "render_molizhishu_report_html"]


def build_molizhishu_html(
    payload: dict[str, Any],
    platform_names: dict[str, str] | None = None,
    *,
    theme: str = "b",
) -> str:
    """返回完整 HTML 字符串，供浏览器预览或另存为 .html。

    2026-08-20 - 诊断预览/HTML 走 AI 可见度驾驶舱（模板 G）；旧幻灯 render_molizhishu_report_html 仅 dev 脚本保留
    """
    from app.services.report_diagnosis_cockpit_service import render_diagnosis_cockpit_html

    return render_diagnosis_cockpit_html(payload, platform_names, theme=theme)
