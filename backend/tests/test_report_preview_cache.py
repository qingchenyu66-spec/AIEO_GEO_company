"""报告预览落盘缓存：勿因 @font-face file:// 误杀。"""

from app.services.report_export_service import _preview_html_cache_usable, _stamp_preview_html


def test_preview_cache_allows_font_face_file_uri() -> None:
    fp = "abc123deadbeef01"
    html = _stamp_preview_html(
        "<html><head></head><body>"
        "@font-face{src:url('file:///usr/share/fonts/truetype/wqy/wqy-zenhei.ttc')}"
        "</body></html>",
        fp,
    )
    assert _preview_html_cache_usable(html, fp) is True


def test_preview_cache_rejects_jsdelivr_and_file_src() -> None:
    fp = "abc123deadbeef02"
    bad_cdn = _stamp_preview_html(
        '<html><head></head><body><script src="https://cdn.jsdelivr.net/npm/echarts"></script></body></html>',
        fp,
    )
    assert _preview_html_cache_usable(bad_cdn, fp) is False

    bad_file_img = _stamp_preview_html(
        '<html><head></head><body><img src="file:///tmp/x.png"></body></html>',
        fp,
    )
    assert _preview_html_cache_usable(bad_file_img, fp) is False
