from app.services.announcement_sanitize import sanitize_announcement_html
from app.schemas.announcement import AnnouncementUpsertRequest
import pytest


def test_sanitize_keeps_basic_markup() -> None:
    html = sanitize_announcement_html('<p>你好 <strong>加粗</strong></p><ul><li>一项</li></ul>')
    assert "<strong>" in html
    assert "加粗" in html
    assert "<li>" in html


def test_sanitize_strips_script() -> None:
    html = sanitize_announcement_html('<p>ok</p><script>alert(1)</script><a href="javascript:alert(1)">x</a>')
    assert "script" not in html.lower()
    assert "javascript" not in html.lower()


def test_sanitize_allows_http_link_and_img() -> None:
    html = sanitize_announcement_html(
        '<p><a href="https://example.com/a">链接</a></p><img src="/api/v1/announcements/media/1" alt="图">'
    )
    assert 'href="https://example.com/a"' in html
    assert 'src="/api/v1/announcements/media/1"' in html


def test_sanitize_keeps_font_size_and_family() -> None:
    html = sanitize_announcement_html(
        '<p><span style="font-size: 18px; font-family: &quot;Microsoft YaHei&quot;, sans-serif">标题</span></p>'
    )
    assert "font-size: 18px" in html
    assert "Microsoft YaHei" in html


def test_sanitize_strips_dangerous_style() -> None:
    html = sanitize_announcement_html(
        '<p><span style="font-size: 18px; background: url(javascript:alert(1))">x</span></p>'
    )
    assert "font-size: 18px" in html
    assert "url(" not in html.lower()
    assert "javascript" not in html.lower()


def test_sanitize_allows_text_and_background_color() -> None:
    html = sanitize_announcement_html(
        '<p><span style="color: #0f172a; background-color: rgb(241, 245, 249)">强调</span></p>'
    )
    assert "color: #0f172a" in html
    assert "background-color: rgb(241, 245, 249)" in html


def test_sanitize_allows_basic_table() -> None:
    html = sanitize_announcement_html(
        '<table style="width: 100%; border-collapse: collapse">'
        "<thead><tr>"
        '<th style="background-color: #334155; color: #ffffff; padding: 8px">场景</th>'
        "<th>推荐方式</th>"
        "</tr></thead>"
        "<tbody><tr><td colspan=\"2\">整行</td></tr></tbody>"
        "</table>"
    )
    assert "<table" in html
    assert "<thead>" in html
    assert "<th" in html
    assert "background-color: #334155" in html
    assert 'colspan="2"' in html
    assert "整行" in html


def test_sanitize_strips_table_event_and_bad_span() -> None:
    html = sanitize_announcement_html(
        '<table onclick="alert(1)"><tr><td colspan="999">x</td></tr></table>'
    )
    assert "onclick" not in html.lower()
    assert "colspan" not in html.lower()


def test_audience_rejects_customer_all_with_tenants() -> None:
    with pytest.raises(Exception):
        AnnouncementUpsertRequest(
            title="t",
            body_html="<p>x</p>",
            targets=["customer_all", "customer_tenants"],
            tenant_ids=[1],
            action="draft",
        )


def test_audience_requires_tenant_ids() -> None:
    with pytest.raises(Exception):
        AnnouncementUpsertRequest(
            title="t",
            body_html="<p>x</p>",
            targets=["customer_tenants"],
            tenant_ids=[],
            action="draft",
        )
