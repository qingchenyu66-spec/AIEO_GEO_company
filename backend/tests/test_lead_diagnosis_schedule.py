"""Tests for lead diagnosis rolling nine-round schedule."""

from __future__ import annotations

from datetime import date, datetime

from app.core.lead_diagnosis_config import DEFAULT_LEAD_SCHEDULE_TIMES
from app.models.lead_diagnosis import LeadDiagnosis
from app.services.lead_diagnosis_service import (
    _iter_schedule_slot_rounds,
    _plan_end_date,
    _schedule_calendar_days,
)


def _lead(*, diagnosis_date: date, created_at: datetime, schedule_days: int = 3) -> LeadDiagnosis:
    return LeadDiagnosis(
        brand_name="测试品牌",
        prompts_json=["问题1"],
        competitors_json=[],
        region_codes_json=[],
        schedule_times_json=list(DEFAULT_LEAD_SCHEDULE_TIMES),
        schedule_days=schedule_days,
        diagnosis_date=diagnosis_date,
        status="collecting",
        created_at=created_at,
    )


def test_noon_create_skips_morning_and_extends_to_fourth_day() -> None:
    lead = _lead(
        diagnosis_date=date(2026, 7, 7),
        created_at=datetime(2026, 7, 7, 12, 0, 0),
    )
    rounds = list(_iter_schedule_slot_rounds(lead))
    assert len(rounds) == 9
    assert rounds[0] == (date(2026, 7, 7), "14:30")
    assert rounds[1] == (date(2026, 7, 7), "20:30")
    assert rounds[-1] == (date(2026, 7, 10), "09:30")
    assert _plan_end_date(lead) == date(2026, 7, 10)
    assert _schedule_calendar_days(lead) == 4


def test_morning_create_keeps_three_calendar_days() -> None:
    lead = _lead(
        diagnosis_date=date(2026, 7, 7),
        created_at=datetime(2026, 7, 7, 8, 0, 0),
    )
    rounds = list(_iter_schedule_slot_rounds(lead))
    assert len(rounds) == 9
    assert rounds[0] == (date(2026, 7, 7), "09:30")
    assert rounds[-1] == (date(2026, 7, 9), "20:30")
    assert _plan_end_date(lead) == date(2026, 7, 9)
    assert _schedule_calendar_days(lead) == 3


def test_custom_schedule_days_five_produces_fifteen_rounds() -> None:
    lead = _lead(
        diagnosis_date=date(2026, 7, 7),
        created_at=datetime(2026, 7, 7, 8, 0, 0),
        schedule_days=5,
    )
    rounds = list(_iter_schedule_slot_rounds(lead))
    assert len(rounds) == 15
    assert rounds[0] == (date(2026, 7, 7), "09:30")
    assert rounds[-1] == (date(2026, 7, 11), "20:30")
    assert _plan_end_date(lead) == date(2026, 7, 11)
