"""Tests for competitor analytics helpers."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services.competitor_analytics_service import (
    _competitor_aliases,
    _dedupe_preserve_order,
    _inclusive_day_keys,
    _include_in_sentiment_leaderboard,
    _names_match,
    _platform_tab_counts_for_task_ids,
    _tracked_entities,
)


def test_platform_tab_counts_empty_task_ids():
    assert _platform_tab_counts_for_task_ids(MagicMock(), []) == {}


def test_platform_tab_counts_groups_by_platform():
    db = MagicMock()
    db.execute.return_value.all.return_value = [
        ("doubao", 10),
        ("doubao_mobile", 78),
        ("deepseek", 5),
        ("", 3),
    ]
    out = _platform_tab_counts_for_task_ids(db, ["t1", "t2"], prompt_filter="q")
    assert out == {"doubao": 10, "doubao_mobile": 78, "deepseek": 5}
    db.execute.assert_called_once()


def test_tracked_entities_handles_orm_competitor_with_empty_aliases():
    competitor = SimpleNamespace(name="竞品A", aliases_json=[])
    rows = _tracked_entities(None, [competitor])
    assert rows == [{"name": "竞品A", "is_brand": False, "match_terms": ["竞品A"]}]


def test_tracked_entities_handles_dict_competitor():
    rows = _tracked_entities(None, [{"name": "竞品B", "aliases": ["别名B"]}])
    assert rows == [{
        "name": "竞品B",
        "is_brand": False,
        "match_terms": ["竞品B", "别名B"],
    }]


def test_tracked_entities_uses_brand_match_terms_without_extra_series():
    asset = SimpleNamespace(
        brand_name="艾迪亚控股集团有限公司",
        brand_short_name="艾迪亚",
        company_full_name="艾迪亚控股集团有限公司",
    )
    rows = _tracked_entities(asset, [])
    assert len(rows) == 1
    assert rows[0]["is_brand"] is True
    assert rows[0]["name"] == "艾迪亚控股集团有限公司"
    assert "艾迪亚" in rows[0]["match_terms"]


def test_names_match_rejects_boyan_prefix_collision():
    """推荐列表「保研机构」不得把所有「保研*」竞品都算提及。"""
    assert not _names_match("保研岛", "保研机构")
    assert not _names_match("保研人", "保研机构")
    assert not _names_match("保研录", "保研机构")
    assert not _names_match("保研岛", "保研人")
    assert _names_match("保研岛", "保研岛机构")
    assert _names_match("艾迪亚", "艾迪亚控股集团")
    assert _names_match("儒思HR", "儒思")


def test_competitor_aliases_preserves_empty_list_for_orm():
    competitor = SimpleNamespace(aliases_json=[])
    assert _competitor_aliases(competitor) == []


def test_dedupe_preserve_order_keeps_first_occurrence():
    assert _dedupe_preserve_order(["本品牌", "竞品A", "竞品A", "竞品B"]) == ["本品牌", "竞品A", "竞品B"]


def test_sentiment_leaderboard_excludes_all_neutral_competitor():
    row = {
        "name": "蓝色光标",
        "is_brand": False,
        "sentiment_sample": 2,
        "positive_rate": 0.0,
        "negative_rate": 0.0,
    }
    assert _include_in_sentiment_leaderboard(row) is False


def test_sentiment_leaderboard_keeps_competitor_with_polar_sentiment():
    row = {
        "name": "竞品A",
        "is_brand": False,
        "sentiment_sample": 10,
        "positive_rate": 12.5,
        "negative_rate": 0.0,
    }
    assert _include_in_sentiment_leaderboard(row) is True


def test_inclusive_day_keys_fills_month_span():
    keys = _inclusive_day_keys(
        datetime(2026, 7, 1, 0, 0, 0),
        datetime(2026, 7, 13, 23, 59, 59),
    )
    assert keys[0] == "2026-07-01"
    assert keys[-1] == "2026-07-13"
    assert len(keys) == 13
    assert "2026-07-04" in keys  # empty monitoring days still get a point
