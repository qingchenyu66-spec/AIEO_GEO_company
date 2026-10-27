"""Brand analysis purchased_platforms display fallback."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services.brand_analysis_service import (
    _brand_word_group_platforms,
    _purchased_platforms_for_brand_words,
)


def test_purchased_platforms_prefers_brand_word_groups(monkeypatch):
    asset = SimpleNamespace(monitored_platforms_json=["kimi"])
    monkeypatch.setattr(
        "app.services.brand_analysis_service.get_brand_asset",
        lambda db, tenant_id: asset,
    )
    monkeypatch.setattr(
        "app.services.brand_analysis_service.tenant_purchased_platforms",
        lambda db, tenant_id, asset=None: ["kimi", "yuanbao"],
    )
    monkeypatch.setattr(
        "app.services.brand_analysis_service._brand_word_group_platforms",
        lambda db, tenant_id: ["doubao"],
    )
    assert _purchased_platforms_for_brand_words(MagicMock(), 1) == ["doubao"]


def test_purchased_platforms_falls_back_to_geo_when_no_brand_word_platforms(monkeypatch):
    asset = SimpleNamespace(monitored_platforms_json=["kimi"])
    monkeypatch.setattr(
        "app.services.brand_analysis_service.get_brand_asset",
        lambda db, tenant_id: asset,
    )
    monkeypatch.setattr(
        "app.services.brand_analysis_service.tenant_purchased_platforms",
        lambda db, tenant_id, asset=None: ["kimi", "yuanbao"],
    )
    monkeypatch.setattr(
        "app.services.brand_analysis_service._brand_word_group_platforms",
        lambda db, tenant_id: [],
    )
    assert _purchased_platforms_for_brand_words(MagicMock(), 132) == ["kimi", "yuanbao"]


def test_brand_word_group_platforms_union(monkeypatch):
    groups = [
        SimpleNamespace(status=True, deleted=False, platforms_json=[{"code": "doubao"}]),
        SimpleNamespace(status=True, deleted=False, platforms_json=[{"code": "deepseek"}]),
        SimpleNamespace(status=False, deleted=False, platforms_json=[{"code": "kimi"}]),
    ]
    monkeypatch.setattr(
        "app.services.brand_analysis_service.get_brand_asset",
        lambda db, tenant_id: None,
    )
    monkeypatch.setattr(
        "app.services.brand_analysis_service.list_brand_word_groups",
        lambda db, tenant_id: groups,
    )
    monkeypatch.setattr(
        "app.services.brand_analysis_service.keyword_group_platforms",
        lambda group, asset=None: [
            str(item.get("code") or item).strip()
            for item in (group.platforms_json or [])
            if str(item.get("code") or item).strip()
        ],
    )
    assert _brand_word_group_platforms(MagicMock(), 132) == ["doubao", "deepseek"]
