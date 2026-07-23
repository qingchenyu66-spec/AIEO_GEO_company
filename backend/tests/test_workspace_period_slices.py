"""ponytail: 切周期时收录明细按区间取数；有排名优先、近日期优先。"""
from datetime import date, datetime

from app.services.monitor_service import _workspace_period_snapshots, _workspace_schedule_key_bounds


def test_workspace_period_snapshots_uses_range_not_latest_day_only() -> None:
    candidates = [
        {"detect_day": "2026-07-19", "subtask_id": "a", "updated_at": "2026-07-19T16:00:00"},
        {"detect_day": "2026-07-19", "subtask_id": "a2", "updated_at": "2026-07-19T15:00:00"},
        {"detect_day": "2026-07-10", "subtask_id": "b", "updated_at": "2026-07-10T12:00:00"},
        {"detect_day": "2026-06-30", "subtask_id": "c", "updated_at": "2026-06-30T12:00:00"},
    ]
    month = _workspace_period_snapshots(
        candidates,
        trend_start=datetime(2026, 7, 1),
        trend_end=datetime(2026, 7, 19, 23, 59, 59),
        range_end=datetime(2026, 7, 19, 23, 59, 59),
        limit=24,
    )
    week = _workspace_period_snapshots(
        candidates,
        trend_start=datetime(2026, 7, 13),
        trend_end=datetime(2026, 7, 19, 23, 59, 59),
        range_end=datetime(2026, 7, 19, 23, 59, 59),
        limit=24,
    )
    assert [row["subtask_id"] for row in month] == ["a", "a2", "b"]
    assert [row["subtask_id"] for row in week] == ["a", "a2"]
    assert {row["detect_day"] for row in month} == {"2026-07-19", "2026-07-10"}
    assert {row["detect_day"] for row in week} == {"2026-07-19"}


def test_workspace_period_snapshots_prefers_ranked_then_recent() -> None:
    candidates = [
        {"detect_day": "2026-07-19", "subtask_id": "unranked_y", "brand_rank": None, "updated_at": "2026-07-19T18:00:00"},
        {"detect_day": "2026-07-18", "subtask_id": "ranked_old", "brand_rank": 1, "updated_at": "2026-07-18T10:00:00"},
        {"detect_day": "2026-07-19", "subtask_id": "ranked_y", "brand_rank": 2, "updated_at": "2026-07-19T16:00:00"},
        {"detect_day": "2026-07-10", "subtask_id": "ranked_older", "brand_rank": 3, "updated_at": "2026-07-10T12:00:00"},
    ]
    rows = _workspace_period_snapshots(
        candidates,
        trend_start=datetime(2026, 7, 1),
        trend_end=datetime(2026, 7, 19, 23, 59, 59),
        range_end=datetime(2026, 7, 19, 23, 59, 59),
        limit=2,
    )
    assert [row["subtask_id"] for row in rows] == ["ranked_y", "ranked_old"]


def test_workspace_period_snapshots_ranked_excludes_unranked() -> None:
    candidates = [
        {"detect_day": "2026-07-19", "subtask_id": "unranked_y", "brand_rank": None, "updated_at": "2026-07-19T18:00:00"},
        {"detect_day": "2026-07-19", "subtask_id": "ranked_y", "brand_rank": 2, "updated_at": "2026-07-19T16:00:00"},
    ]
    rows = _workspace_period_snapshots(
        candidates,
        trend_start=datetime(2026, 7, 1),
        trend_end=datetime(2026, 7, 19, 23, 59, 59),
        range_end=datetime(2026, 7, 19, 23, 59, 59),
        limit=10,
        rank_scope="ranked",
    )
    assert [row["subtask_id"] for row in rows] == ["ranked_y"]


def test_workspace_period_snapshots_all_keeps_unranked_by_recency() -> None:
    candidates = [
        {"detect_day": "2026-07-19", "subtask_id": "unranked_y", "brand_rank": None, "updated_at": "2026-07-19T18:00:00"},
        {"detect_day": "2026-07-18", "subtask_id": "ranked_old", "brand_rank": 1, "updated_at": "2026-07-18T10:00:00"},
        {"detect_day": "2026-07-19", "subtask_id": "ranked_y", "brand_rank": 2, "updated_at": "2026-07-19T16:00:00"},
    ]
    rows = _workspace_period_snapshots(
        candidates,
        trend_start=datetime(2026, 7, 1),
        trend_end=datetime(2026, 7, 19, 23, 59, 59),
        range_end=datetime(2026, 7, 19, 23, 59, 59),
        limit=2,
        rank_scope="all",
    )
    assert [row["subtask_id"] for row in rows] == ["unranked_y", "ranked_y"]


def test_workspace_schedule_key_bounds_align_business_days() -> None:
    start_key, end_excl = _workspace_schedule_key_bounds(date(2026, 7, 13), date(2026, 7, 19))
    assert start_key == "20260713"
    assert end_excl == "20260720"
    assert "20260713-0930-kw20" >= start_key
    assert "20260719-1630-kw20" < end_excl
    assert "20260701-0930-kw20" < start_key
    assert "20260720-0930-kw20" >= end_excl
