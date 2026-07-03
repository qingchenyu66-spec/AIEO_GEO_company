from datetime import datetime
from types import SimpleNamespace

from app.services.schedule_context import resolve_monitor_task_source, resolve_task_schedule_context


def test_resolve_task_schedule_context_prefers_lead_diagnosis_batch() -> None:
    task = SimpleNamespace(
        task_id="task-lead",
        monitor_keywords="电梯广告",
        created_at=datetime(2026, 7, 2, 8, 53, 0),
    )
    lead_run = SimpleNamespace(
        schedule_key="20260701-1630",
        schedule_label="2026-07-01 16:30",
        status="completed",
    )
    asset = SimpleNamespace(
        schedule_type="daily_times",
        schedule_times_json=["09:30", "13:30"],
        schedule_frequency=2,
    )

    ctx = resolve_task_schedule_context(task, schedule_run=None, asset=asset, lead_run=lead_run)

    assert ctx["schedule_source"] == "lead_diagnosis"
    assert ctx["schedule_label"] == "2026-07-01 16:30"
    assert ctx["schedule_window_key"] == "20260701-1630"


def test_tenant_task_with_lead_run_is_tenant_monitor_not_lead_diagnosis() -> None:
    task = SimpleNamespace(
        task_id="task-tenant",
        tenant_id=6,
        monitor_keywords="电梯广告",
        created_at=datetime(2026, 7, 2, 8, 53, 0),
    )
    lead_run = SimpleNamespace(
        schedule_key="20260701-1630",
        schedule_label="2026-07-01 16:30",
        status="completed",
    )

    assert resolve_monitor_task_source(task, has_lead_run=True) == "tenant_monitor"

    ctx = resolve_task_schedule_context(task, schedule_run=None, asset=None, lead_run=lead_run)
    assert ctx["schedule_source"] == "run"
    assert ctx["schedule_label"] == "2026-07-01 16:30"
