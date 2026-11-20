from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services.schedule_context import planned_task_datetimes
from app.services.brand_analysis_service import _subtask_event_at


def test_backfill_preserves_original_weekly_plan_time():
    task = SimpleNamespace(task_id="weekly", created_at=datetime(2026, 10, 19, 10))
    run = SimpleNamespace(schedule_key="bw20261019-0900-kw7")
    with patch("app.services.schedule_context.schedule_runs_for_tasks", return_value={"weekly": run}), patch(
        "app.services.schedule_context.lead_diagnosis_runs_for_tasks", return_value={}
    ):
        planned = planned_task_datetimes(MagicMock(), [task])["weekly"]
    item = SimpleNamespace(
        _planned_at=planned,
        task=task,
        remote_time=1795082220000,
        updated_at=datetime(2026, 11, 19, 15, 17),
    )
    assert _subtask_event_at(item) == datetime(2026, 10, 19, 9)
    assert item.updated_at == datetime(2026, 11, 19, 15, 17)


def test_unscheduled_task_uses_creation_time_not_backfill_time():
    task = SimpleNamespace(task_id="manual", created_at=datetime(2026, 10, 1, 9))
    with patch("app.services.schedule_context.schedule_runs_for_tasks", return_value={}), patch(
        "app.services.schedule_context.lead_diagnosis_runs_for_tasks", return_value={}
    ):
        assert planned_task_datetimes(MagicMock(), [task])["manual"] == task.created_at
    assert _subtask_event_at(SimpleNamespace(task=task, updated_at=datetime(2026, 11, 19))) == task.created_at
