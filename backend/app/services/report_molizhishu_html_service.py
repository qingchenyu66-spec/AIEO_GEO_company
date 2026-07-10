from app.services.report_molizhishu_pdf_service import render_molizhishu_report_html

__all__ = ["build_molizhishu_html", "render_molizhishu_report_html"]


def build_molizhishu_html(
    payload: dict[str, Any],
    platform_names: dict[str, str] | None = None,
    *,
    theme: str = "b",
) -> str:
    """返回完整 HTML 字符串，供浏览器预览或另存为 .html。"""
    return render_molizhishu_report_html(payload, platform_names, theme=theme)
