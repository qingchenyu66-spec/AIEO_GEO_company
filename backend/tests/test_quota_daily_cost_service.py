"""quota_daily_cost_service unit checks (no DB)."""

from datetime import date

from app.services.quota_daily_cost_service import (
    build_month_day_rows,
    heat_level,
    month_range,
)


def test_month_range_july() -> None:
    start, end = month_range(2026, 7)
    assert start == date(2026, 7, 1)
    assert end == date(2026, 8, 1)


def test_build_month_day_rows_fills_zeros() -> None:
    rows = build_month_day_rows(
        year=2026,
        month=2,
        amount_by_day={date(2026, 2, 1): 10.5, date(2026, 2, 10): 1},
        count_by_day={date(2026, 2, 1): 3},
    )
    assert len(rows) == 28
    assert rows[0] == {"date": "2026-02-01", "amount": 10.5, "subtask_count": 3}
    assert rows[1]["amount"] == 0
    assert rows[9]["amount"] == 1.0


def test_heat_level_buckets() -> None:
    assert heat_level(0, 100) == 0
    assert heat_level(10, 100) == 1
    assert heat_level(40, 100) == 2
    assert heat_level(70, 100) == 3
    assert heat_level(100, 100) == 4
