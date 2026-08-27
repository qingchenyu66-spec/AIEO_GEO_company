"""Gap backfill placeholders must not appear in ops pending-sync dashboard."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.models.monitor import GeoMonitorSubtask, GeoMonitorTask
from app.services.monitor_service import (
    GAP_BACKFILL_SOURCE,
    _is_gap_backfill_subtask,
    _is_gap_backfill_task,
    list_pending_monitor_task_ids,
    summarize_monitor_task_for_ops,
)


def _gap_subtask() -> GeoMonitorSubtask:
    return GeoMonitorSubtask(
        subtask_id="bfs-test-1",
        task_id="bft-test",
        platform="doubao",
        mode="fast",
        prompt="礼品公司推荐",
        status="failed",
        error_message="到期漏跑/无自动监测，待快照补录",
        raw_result_json={"source": GAP_BACKFILL_SOURCE, "schedule_window_key": "20260820-0930"},
    )


def test_is_gap_backfill_subtask():
    assert _is_gap_backfill_subtask(_gap_subtask())
    real = GeoMonitorSubtask(
        subtask_id="real-1",
        task_id="real-task",
        platform="doubao",
        mode="fast",
        prompt="q",
        status="failed",
        error_message="upstream timeout",
        raw_result_json={"status": "failed"},
    )
    assert not _is_gap_backfill_subtask(real)


def test_is_gap_backfill_task_by_request_json():
    task = GeoMonitorTask(
        task_id="bft-test",
        tenant_id=1,
        created_by=1,
        monitor_keywords="kw",
        status="failed",
        raw_request_json={"source": GAP_BACKFILL_SOURCE},
        raw_response_json={},
    )
    task.subtasks = [_gap_subtask()]
    assert _is_gap_backfill_task(task)


def test_summarize_ops_skips_gap_subtasks_in_breakdown():
    task = GeoMonitorTask(
        task_id="real-mixed",
        tenant_id=1,
        created_by=1,
        monitor_keywords="kw",
        status="processing",
        total_items=2,
        completed_items=1,
        failed_items=1,
        prompts_json=["a", "b"],
        platforms_json=[{"platform": "doubao", "mode": "fast"}],
        raw_request_json={"tenant_id": 1},
        raw_response_json={},
    )
    real_done = GeoMonitorSubtask(
        subtask_id="real-done",
        task_id="real-mixed",
        platform="doubao",
        mode="fast",
        prompt="a",
        status="completed",
        answer_content="ok",
        raw_result_json={},
    )
    task.subtasks = [real_done, _gap_subtask()]
    summary = summarize_monitor_task_for_ops(task, platform_names={"doubao": "豆包"})
    doubao = next(item for item in summary["platform_breakdown"] if item["code"] == "doubao")
    assert doubao["failed"] == 0
    assert doubao["completed"] == 1


def test_list_pending_excludes_gap_backfill_sql():
    db = MagicMock()
    db.scalars.return_value = []
    list_pending_monitor_task_ids(db, limit=10)
    stmt = db.scalars.call_args.args[0]
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": False}))
    assert "json_extract" in compiled.lower()
