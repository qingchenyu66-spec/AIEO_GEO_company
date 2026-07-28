"""公告正文长度与粘贴图上传自检。"""

from app.schemas.announcement import AnnouncementUpsertRequest


def test_announcement_body_html_allows_large_payload() -> None:
    # 2026-07-28 - 超 20 万字曾被拒；现上限 1_000_000
    body = "<p>" + ("字" * 250_000) + "</p>"
    payload = AnnouncementUpsertRequest(
        title="测",
        body_html=body,
        targets=["platform_all"],
        action="draft",
    )
    assert len(payload.body_html) > 200_000
