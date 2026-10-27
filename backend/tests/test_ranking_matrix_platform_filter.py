from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services.monitor_service import (
    matrix_filter_platforms_for_retired,
    matrix_platform_visible,
    merge_matrix_purchased_platforms,
)


def test_matrix_platform_visible_allows_configured_platforms() -> None:
    purchased = ["doubao_mobile", "deepseek", "kimi"]
    assert matrix_platform_visible("doubao_mobile", purchased) is True
    assert matrix_platform_visible("wenxinyiyan", purchased) is False


def test_matrix_platform_visible_allows_all_when_unconfigured() -> None:
    assert matrix_platform_visible("kimi", []) is True
    assert matrix_platform_visible(None, []) is True


def test_matrix_filter_platforms_for_retired_opens_window_when_enabled() -> None:
    configured = ["doubao", "kimi"]
    assert matrix_filter_platforms_for_retired(
        configured, include_retired=False, observer_allow=None
    ) == configured
    assert matrix_filter_platforms_for_retired(
        configured, include_retired=True, observer_allow=None
    ) == []
    assert matrix_filter_platforms_for_retired(
        configured, include_retired=True, observer_allow=frozenset({"kimi", "yuanbao"})
    ) == ["yuanbao", "kimi"]


def test_merge_matrix_purchased_platforms_unions_history_when_retired() -> None:
    assert merge_matrix_purchased_platforms(
        ["doubao"], ["kimi", "doubao"], include_retired=False
    ) == ["doubao"]
    merged = merge_matrix_purchased_platforms(
        ["doubao"], ["kimi", "wenxinyiyan"], include_retired=True
    )
    assert "doubao" in merged
    assert "kimi" in merged
    assert "wenxinyiyan" in merged
    narrowed = merge_matrix_purchased_platforms(
        ["doubao"],
        ["kimi", "wenxinyiyan"],
        include_retired=True,
        observer_allow=frozenset({"kimi"}),
    )
    assert narrowed == ["kimi"]


def test_tenant_keyword_group_platforms_including_inactive(monkeypatch) -> None:
    from app.services.monitor_service import tenant_keyword_group_platforms_including_inactive

    groups = [
        SimpleNamespace(status=True, deleted=False, platforms_json=[{"code": "qianwen"}]),
        SimpleNamespace(status=False, deleted=False, platforms_json=[{"code": "doubao"}]),
        SimpleNamespace(status=True, deleted=True, platforms_json=[{"code": "kimi"}]),
    ]
    monkeypatch.setattr(
        "app.services.brand_service.list_keyword_groups",
        lambda db, tenant_id: [g for g in groups if not g.deleted],
    )
    monkeypatch.setattr(
        "app.services.brand_service.keyword_group_platforms",
        lambda group, asset=None: [
            str(item.get("code") or item).strip()
            for item in (group.platforms_json or [])
            if str(item.get("code") or item).strip()
        ],
    )
    assert tenant_keyword_group_platforms_including_inactive(MagicMock(), 15) == ["doubao", "qianwen"]
