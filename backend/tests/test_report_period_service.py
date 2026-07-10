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
