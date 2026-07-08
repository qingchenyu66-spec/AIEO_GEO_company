"""Unit tests for scheduled report period windows."""

from datetime import date

from app.services.report_period_service import (
    annual_period,
    due_scheduled_report_types,
    monthly_period,
    period_bounds,
    period_key,
    quarterly_period,
    weekly_period,
)


def test_weekly_period_saturday_to_friday() -> None:
    start, end = weekly_period(date(2026, 7, 10))
    assert start == date(2026, 7, 4)
    assert end == date(2026, 7, 10)
    assert start.weekday() == 5
    assert end.weekday() == 4


def test_monthly_period_natural_month() -> None:
    start, end = monthly_period(date(2026, 7, 31))
    assert start == date(2026, 7, 1)
    assert end == date(2026, 7, 31)


def test_quarterly_period_q3() -> None:
    start, end = quarterly_period(date(2026, 9, 30))
    assert start == date(2026, 7, 1)
    assert end == date(2026, 9, 30)


def test_annual_period() -> None:
    start, end = annual_period(date(2026, 12, 31))
    assert start == date(2026, 1, 1)
    assert end == date(2026, 12, 31)


def test_due_types_on_friday_only() -> None:
    assert due_scheduled_report_types(date(2026, 7, 10)) == ["weekly"]


def test_due_types_on_month_end_quarter_end() -> None:
    due = due_scheduled_report_types(date(2026, 3, 31))
    assert due == ["monthly", "quarterly"]


def test_due_types_on_year_end() -> None:
    due = due_scheduled_report_types(date(2026, 12, 31))
    assert due == ["monthly", "quarterly", "annual"]


def test_period_key_formats() -> None:
    start, end = period_bounds("weekly", date(2026, 7, 10))
    assert period_key("weekly", start, end) == "weekly:2026-07-04_2026-07-10"
    start, end = period_bounds("monthly", date(2026, 7, 31))
    assert period_key("monthly", start, end) == "monthly:2026-07"
    start, end = period_bounds("quarterly", date(2026, 9, 30))
    assert period_key("quarterly", start, end) == "quarterly:2026-Q3"
    start, end = period_bounds("annual", date(2026, 12, 31))
    assert period_key("annual", start, end) == "annual:2026"


def test_bounds_from_period_key_roundtrip() -> None:
    from app.services.report_period_service import bounds_from_period_key

    start, end = period_bounds("annual", date(2025, 12, 31))
    key = period_key("annual", start, end)
    assert bounds_from_period_key("annual", key) == (start, end)
    start, end = period_bounds("weekly", date(2026, 7, 3))
    key = period_key("weekly", start, end)
    assert bounds_from_period_key("weekly", key) == (start, end)
