"""Unit tests for failed-subtask auto-retry gates."""

from app.models.monitor import GeoMonitorSubtask, GeoMonitorTask
from app.services.monitor_auto_retry_service import (
    GEO_AUTO_RETRY_META,
    is_auto_retry_task,
    subtask_failure_awaits_or_in_auto_retry,
    subtask_hard_failed,
)
from app.services.monitor_service import subtask_needs_snapshot_backfill


def test_hard_failed_and_await_gate() -> None:
    st = GeoMonitorSubtask(
        subtask_id="s1",
        task_id="t1",
        platform="deepseek_mobile",
        mode="standard",
        prompt="q",
        status="failed",
        raw_result_json={},
    )
    assert subtask_hard_failed(st) is True
    assert subtask_failure_awaits_or_in_auto_retry(st) is True
    assert subtask_needs_snapshot_backfill(st) is False

    st.auto_retry_count = 1
    st.auto_retry_status = "pending"
    assert subtask_failure_awaits_or_in_auto_retry(st) is True
    assert subtask_needs_snapshot_backfill(st) is False

    st.auto_retry_status = "failed"
    assert subtask_failure_awaits_or_in_auto_retry(st) is False
    assert subtask_needs_snapshot_backfill(st) is True


def test_succeeded_retry_not_backfill() -> None:
    st = GeoMonitorSubtask(
        subtask_id="s2",
        task_id="t1",
        platform="deepseek_mobile",
        mode="standard",
        prompt="q",
        status="completed",
        answer_content="ok",
        mention_position=1,
        raw_result_json={},
        auto_retry_count=1,
        auto_retry_status="succeeded",
    )
    assert subtask_hard_failed(st) is False
    assert subtask_needs_snapshot_backfill(st) is False


def test_is_auto_retry_task_detects_meta() -> None:
    task = GeoMonitorTask(
        task_id="retry-1",
        status="pending",
        total_items=1,
        completed_items=0,
        failed_items=0,
        prompts_json=["q"],
        platforms_json=[{"platform": "deepseek_mobile"}],
        raw_request_json={GEO_AUTO_RETRY_META: {"of_task_id": "origin"}},
        raw_response_json={},
    )
    assert is_auto_retry_task(task) is True
    task.raw_request_json = {}
    assert is_auto_retry_task(task) is False
