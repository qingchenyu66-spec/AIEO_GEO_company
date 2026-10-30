"""Unit tests for scheduled report period windows."""

from datetime import date

from app.services.report_period_comparison_service import (
    _comparison_highlights,
    _trend_bucket_slots,
    previous_period_bounds,
)
from app.services.report_period_service import (
    annual_period,
    bounds_from_period_key,
    due_scheduled_report_types,
    manual_export_title,
    manual_span_period_key,
    monthly_period,
    period_bounds,
    period_key,
    period_label,
    quarterly_period,
    resolve_manual_export_bounds,
    weekly_period,
)


def test_weekly_period_previous_monday_to_sunday() -> None:
    start, end = weekly_period(date(2026, 7, 13))
    assert start == date(2026, 7, 6)
    assert end == date(2026, 7, 12)
    assert start.weekday() == 0
    assert end.weekday() == 6


def test_monthly_period_previous_natural_month() -> None:
    start, end = monthly_period(date(2026, 4, 1))
    assert start == date(2026, 3, 1)
    assert end == date(2026, 3, 31)


def test_quarterly_period_previous_quarter() -> None:
    start, end = quarterly_period(date(2026, 4, 1))
    assert start == date(2026, 1, 1)
    assert end == date(2026, 3, 31)


def test_annual_period_previous_year() -> None:
    start, end = annual_period(date(2026, 1, 1))
    assert start == date(2025, 1, 1)
    assert end == date(2025, 12, 31)


def test_due_types_on_monday() -> None:
    assert due_scheduled_report_types(date(2026, 7, 13)) == ["weekly"]


def test_due_types_on_first_of_quarter() -> None:
    due = due_scheduled_report_types(date(2026, 4, 1))
    assert due == ["monthly", "quarterly"]


def test_due_types_on_jan_first() -> None:
    due = due_scheduled_report_types(date(2026, 1, 1))
    assert due == ["monthly", "quarterly", "annual"]


def test_period_key_formats() -> None:
    start, end = period_bounds("weekly", date(2026, 7, 13))
    assert period_key("weekly", start, end) == "weekly:2026-07-06_2026-07-12"
    start, end = period_bounds("monthly", date(2026, 4, 1))
    assert period_key("monthly", start, end) == "monthly:2026-03"
    start, end = period_bounds("quarterly", date(2026, 4, 1))
    assert period_key("quarterly", start, end) == "quarterly:2026-Q1"
    start, end = period_bounds("annual", date(2026, 1, 1))
    assert period_key("annual", start, end) == "annual:2025"


def test_bounds_from_period_key_roundtrip() -> None:
    from app.services.report_period_service import bounds_from_period_key

    start, end = period_bounds("annual", date(2026, 1, 1))
    key = period_key("annual", start, end)
    assert bounds_from_period_key("annual", key) == (start, end)
    start, end = period_bounds("weekly", date(2026, 7, 13))
    key = period_key("weekly", start, end)
    assert bounds_from_period_key("weekly", key) == (start, end)


def test_custom_range_keeps_dates_and_matches_previous_length() -> None:
    start, end = date(2026, 10, 1), date(2026, 10, 18)
    key = period_key("custom", start, end)
    assert key == "custom:2026-10-01_2026-10-18"
    assert bounds_from_period_key("custom", key) == (start, end)
    assert bounds_from_period_key("custom", key + ":20261029180000") == (start, end)
    assert period_label("custom", start, end) == "2026-10-01 至 2026-10-18"
    prev_start, prev_end = previous_period_bounds("custom", start, end)
    assert prev_end == date(2026, 9, 30)
    assert (prev_end - prev_start).days == (end - start).days
    assert "custom" not in due_scheduled_report_types(date(2026, 10, 5))


def test_manual_export_keeps_chosen_dates() -> None:
    today = date(2026, 10, 30)
    start, end = resolve_manual_export_bounds("weekly", date(2026, 8, 3), date(2026, 8, 12), today=today)
    assert (start, end) == (date(2026, 8, 3), date(2026, 8, 12))
    capped_start, capped_end = resolve_manual_export_bounds(
        "monthly", date(2026, 10, 9), date(2026, 10, 31), today=today,
    )
    assert (capped_start, capped_end) == (date(2026, 10, 9), date(2026, 10, 30))
    assert bounds_from_period_key("monthly", "monthly:2026-08-03_2026-08-12:20261030090100") == (
        date(2026, 8, 3),
        date(2026, 8, 12),
    )
    assert bounds_from_period_key("monthly", "monthly:2026-08") == (date(2026, 8, 1), date(2026, 8, 31))


def test_manual_span_compares_equal_length_and_charts_by_day() -> None:
    start, end = date(2026, 10, 1), date(2026, 10, 9)
    assert manual_span_period_key("weekly:2026-10-01_2026-10-09:20261030091943")
    assert not manual_span_period_key("weekly:2026-09-28_2026-10-04")
    assert not manual_span_period_key("monthly:2026-10")

    hand_prev = previous_period_bounds("custom", start, end)
    assert hand_prev == (date(2026, 9, 22), date(2026, 9, 30))
    assert (hand_prev[1] - hand_prev[0]).days == (end - start).days
    auto_month_prev = previous_period_bounds("monthly", start, end)
    assert auto_month_prev == (date(2026, 9, 1), date(2026, 9, 30))
    auto_week_prev = previous_period_bounds("weekly", date(2026, 9, 28), date(2026, 10, 4))
    assert auto_week_prev == (date(2026, 9, 21), date(2026, 9, 27))

    assert len(_trend_bucket_slots("custom", start, end)) == 9
    month_slots = _trend_bucket_slots("monthly", start, end)
    assert [slot["label"] for slot in month_slots] != [slot["label"] for slot in _trend_bucket_slots("custom", start, end)]
    assert all(slot["start"].month == 10 for slot in month_slots)

    title = manual_export_title("monthly", start, end)
    assert title == "GEO 监测月报（2026-10-01 至 2026-10-09）"
    lines = _comparison_highlights(
        "custom",
        {"avg_rank": 2.0, "mention_rate": 10.0},
        {"avg_rank": 3.0, "mention_rate": 8.0},
        70,
        60,
    )
    assert lines
    assert all("本周" not in line and "本月" not in line for line in lines)
    assert any("本段" in line for line in lines)
    week_lines = _comparison_highlights(
        "weekly",
        {"avg_rank": 2.0, "mention_rate": 10.0},
        {"avg_rank": 3.0, "mention_rate": 8.0},
        70,
        60,
    )
    assert any("本周" in line for line in week_lines)
