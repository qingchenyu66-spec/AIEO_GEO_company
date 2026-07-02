"""Tests for competitor analytics helpers."""

from types import SimpleNamespace

from app.services.competitor_analytics_service import _competitor_aliases, _tracked_entities


def test_tracked_entities_handles_orm_competitor_with_empty_aliases():
    competitor = SimpleNamespace(name="竞品A", aliases_json=[])
    rows = _tracked_entities(None, [competitor])
    assert rows == [{"name": "竞品A", "is_brand": False}]


def test_tracked_entities_handles_dict_competitor():
    rows = _tracked_entities(None, [{"name": "竞品B", "aliases": ["别名B"]}])
    assert {"name": "竞品B", "is_brand": False} in rows
    assert {"name": "别名B", "is_brand": False} in rows


def test_competitor_aliases_preserves_empty_list_for_orm():
    competitor = SimpleNamespace(aliases_json=[])
    assert _competitor_aliases(competitor) == []
