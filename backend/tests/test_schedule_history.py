"""改时段生效日前缺口期望回放旧计划。"""

from datetime import date, time
from types import SimpleNamespace

from app.services.schedule_history import (
    SCHEDULE_CUTOVER_DATE,
    schedule_times_for_asset_on_day,
)


def test_schedule_times_before_cutover_uses_old_plan() -> None:
    asset = SimpleNamespace(
        tenant_id=142,
        schedule_type="daily_times",
        schedule_frequency=3,
        schedule_times_json=["02:23", "08:08", "15:18"],
    )
    day = date(2026, 8, 27)
    assert day < SCHEDULE_CUTOVER_DATE
    times = schedule_times_for_asset_on_day(asset, day)  # type: ignore[arg-type]
    assert times == [time(9, 0), time(14, 0), time(20, 30)]


def test_schedule_times_on_or_after_cutover_uses_current() -> None:
    asset = SimpleNamespace(
        tenant_id=142,
        schedule_type="daily_times",
        schedule_frequency=3,
        schedule_times_json=["02:23", "08:08", "15:18"],
    )
    times = schedule_times_for_asset_on_day(asset, SCHEDULE_CUTOVER_DATE)  # type: ignore[arg-type]
    assert times == [time(2, 23), time(8, 8), time(15, 18)]


def test_schedule_times_unknown_tenant_uses_current() -> None:
    asset = SimpleNamespace(
        tenant_id=99999,
        schedule_type="daily_times",
        schedule_frequency=2,
        schedule_times_json=["10:00", "18:00"],
    )
    times = schedule_times_for_asset_on_day(asset, date(2026, 8, 1))  # type: ignore[arg-type]
    assert times == [time(10, 0), time(18, 0)]
