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
