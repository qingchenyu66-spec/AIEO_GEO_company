"""售前诊断 run 状态与监测任务终态对齐。"""

from types import SimpleNamespace

from app.services.lead_diagnosis_service import _run_status_from_terminal_task


def test_run_status_from_terminal_task_completed():
    status, err = _run_status_from_terminal_task(
        SimpleNamespace(completed_items=3, last_error=None)
    )
    assert status == "completed"
    assert err is None


def test_run_status_from_terminal_task_failed():
    status, err = _run_status_from_terminal_task(
        SimpleNamespace(completed_items=0, last_error="timeout")
    )
    assert status == "failed"
    assert err == "timeout"


def test_run_status_from_terminal_task_failed_default_message():
    status, err = _run_status_from_terminal_task(
        SimpleNamespace(completed_items=0, last_error=None)
    )
    assert status == "failed"
    assert "未产生有效结果" in (err or "")
