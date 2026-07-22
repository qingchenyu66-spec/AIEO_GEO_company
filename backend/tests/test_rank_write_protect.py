"""Scheme C: rank write-protect + awaiting-upstream helpers."""
from datetime import datetime, timedelta
from types import SimpleNamespace

from app.services.monitor_service import (
    _merge_remote_rank_fields,
    _subtask_awaiting_upstream_rank,
)


def test_merge_does_not_clobber_local_rank_with_null() -> None:
    subtask = SimpleNamespace(
        mention_position=5,
        mention_context="local ctx",
        all_rankings_json=[{"name": "鸿联九五", "rank": 5}],
        competitor_rankings_json=[{"name": "竞品A", "rank": 1}],
    )
    _merge_remote_rank_fields(
        subtask,
        {
            "mentionPosition": None,
            "mentionContext": None,
            "allRankings": [],
            "competitorRankings": [],
            "status": "processing",
        },
    )
    assert subtask.mention_position == 5
    assert subtask.mention_context == "local ctx"
    assert subtask.all_rankings_json == [{"name": "鸿联九五", "rank": 5}]
    assert subtask.competitor_rankings_json == [{"name": "竞品A", "rank": 1}]


def test_merge_keeps_local_rank_when_remote_non_null() -> None:
    """本地已有位次为准；模力非空只作替补，不得覆盖。"""
    subtask = SimpleNamespace(
        mention_position=5,
        mention_context="old",
        all_rankings_json=[{"name": "旧", "rank": 5}],
        competitor_rankings_json=[{"name": "竞品A", "rank": 2}],
    )
    _merge_remote_rank_fields(
        subtask,
        {
            "mentionPosition": 2,
            "mentionContext": "new ctx",
            "allRankings": [{"name": "鸿联九五", "rank": 2}],
            "competitorRankings": [{"name": "竞品B", "rank": 1}],
        },
    )
    assert subtask.mention_position == 5
    assert subtask.mention_context == "old"
    assert subtask.all_rankings_json == [{"name": "旧", "rank": 5}]
    assert subtask.competitor_rankings_json == [{"name": "竞品A", "rank": 2}]


def test_merge_uses_remote_rank_only_when_local_empty() -> None:
    subtask = SimpleNamespace(
        mention_position=None,
        mention_context=None,
        all_rankings_json=[],
        competitor_rankings_json=[],
    )
    _merge_remote_rank_fields(
        subtask,
        {
            "mentionPosition": 2,
            "mentionContext": "remote ctx",
            "allRankings": [{"name": "鸿联九五", "rank": 2}],
            "competitorRankings": [{"name": "竞品B", "rank": 1}],
        },
    )
    assert subtask.mention_position == 2
    assert subtask.mention_context == "remote ctx"
    assert subtask.all_rankings_json == [{"name": "鸿联九五", "rank": 2}]
    assert subtask.competitor_rankings_json == [{"name": "竞品B", "rank": 1}]


def test_awaiting_upstream_rank_when_processing_and_empty() -> None:
    now = datetime(2026, 7, 20, 12, 0, 0)
    subtask = SimpleNamespace(
        prompt="呼叫中心外包公司推荐",
        answer_content="推荐鸿联九五等公司",
        mention_position=None,
        all_rankings_json=[],
        updated_at=now - timedelta(hours=1),
        raw_result_json={"status": "processing"},
    )
    assert _subtask_awaiting_upstream_rank(subtask, now=now) is True


def test_not_awaiting_when_local_rank_exists() -> None:
    now = datetime(2026, 7, 20, 12, 0, 0)
    subtask = SimpleNamespace(
        prompt="呼叫中心外包公司推荐",
        answer_content="推荐鸿联九五",
        mention_position=3,
        all_rankings_json=[],
        updated_at=now - timedelta(hours=1),
        raw_result_json={"status": "processing"},
    )
    assert _subtask_awaiting_upstream_rank(subtask, now=now) is False


def test_not_awaiting_when_past_grace() -> None:
    now = datetime(2026, 7, 20, 12, 0, 0)
    subtask = SimpleNamespace(
        prompt="呼叫中心外包公司推荐",
        answer_content="推荐鸿联九五",
        mention_position=None,
        all_rankings_json=[],
        updated_at=now - timedelta(hours=7),
        raw_result_json={"status": "processing"},
    )
    assert _subtask_awaiting_upstream_rank(subtask, now=now) is False
