"""补录后信源日表异步入队自检。"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services.monitor_source_rollup_service import (
    _run_source_daily_after_backfill,
    enqueue_source_daily_after_backfill,
)


def test_enqueue_source_daily_after_backfill_queues_celery():
    with (
        patch("app.core.config.settings") as settings,
        patch("app.tasks.snapshot_backfill.refresh_source_daily_after_backfill_task") as task,
    ):
        settings.celery_enabled = True
        out = enqueue_source_daily_after_backfill(
            tenant_id=1,
            task_id="t1",
            previous_stat_date="2026-08-01",
            new_stat_date="2026-08-02",
        )
    assert out == "queued"
    task.delay.assert_called_once_with(1, "t1", "2026-08-01", "2026-08-02")


def test_run_source_daily_after_backfill_skips_tenant_mismatch():
    db = MagicMock()
    db.scalar.return_value = SimpleNamespace(task_id="t1", tenant_id=9)
    with patch(
        "app.services.monitor_source_rollup_service.refresh_source_daily_after_subtask_backfill"
    ) as refresh:
        _run_source_daily_after_backfill(
            db,
            tenant_id=1,
            task_id="t1",
            previous_stat_date="2026-08-01",
            new_stat_date="2026-08-02",
        )
    refresh.assert_not_called()
