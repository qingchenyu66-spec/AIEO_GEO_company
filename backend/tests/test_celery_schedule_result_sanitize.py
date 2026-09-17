"""Celery 调度提交返回值不得含 URL / token / 敏感查询参数。"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services.celery_result_sanitize import (
    celery_result_contains_secrets,
    redact_url_query_secrets,
    summarize_schedule_submit_for_celery,
)
from app.services.monitor_service import serialize_task


def test_serialize_task_still_exposes_callback_url_for_api(monkeypatch: pytest.MonkeyPatch) -> None:
    """公共 API 序列化契约保留 callback_url；止血不在此处删除。"""
    monkeypatch.setattr("app.services.monitor_service._reconcile_task_progress", lambda _task: None)
    monkeypatch.setattr(
        "app.services.monitor_service.resolve_task_schedule_context",
        lambda *_a, **_k: {},
    )
    task = SimpleNamespace(
        task_id="task-api-1",
        tenant_id=1,
        monitor_keywords="品牌",
        status="pending",
        total_items=2,
        completed_items=0,
        failed_items=0,
        prompts_json=["q1"],
        platforms_json=[{"platform": "deepseek"}],
        callback_url="https://example.com/cb?token=secret-token-value",
        poll_url="https://example.com/poll",
        last_error=None,
        created_at=SimpleNamespace(isoformat=lambda: "2026-09-17T00:00:00"),
        updated_at=SimpleNamespace(isoformat=lambda: "2026-09-17T00:00:00"),
        subtasks=[],
    )
    payload = serialize_task(task)
    assert payload["callback_url"] == "https://example.com/cb?token=secret-token-value"


def test_summarize_schedule_submit_drops_nested_callback_url() -> None:
    raw = {
        "tenant_id": 9,
        "schedule_key": "20260917-0900-kw0",
        "status": "submitted",
        "keyword": "监测词",
        "task": {
            "task_id": "mz-1",
            "status": "pending",
            "total_items": 4,
            "completed_items": 0,
            "failed_items": 0,
            "callback_url": "https://www.aieokj.com/api/v1/monitor/molizhishu/callback?token=LEAKED",
            "poll_url": "https://business-api.example/poll?token=also-leak",
            "prompts": ["不应出现"],
            "platforms": [{"platform": "kimi"}],
        },
    }
    summary = summarize_schedule_submit_for_celery(raw)
    assert summary == {
        "tenant_id": 9,
        "schedule_key": "20260917-0900-kw0",
        "status": "submitted",
        "keyword": "监测词",
        "task_id": "mz-1",
        "task_status": "pending",
        "total_items": 4,
        "completed_items": 0,
        "failed_items": 0,
    }
    assert celery_result_contains_secrets(summary) is False
    assert "callback_url" not in summary
    assert "task" not in summary


def test_summarize_strips_url_from_message() -> None:
    summary = summarize_schedule_submit_for_celery(
        {
            "status": "failed",
            "message": "upstream https://cb.example/hook?token=abc123 failed",
        }
    )
    assert "http" not in summary["message"].lower()
    assert "token=" not in summary["message"].lower()
    assert "[redacted-url]" in summary["message"]
    assert celery_result_contains_secrets(summary) is False


def test_summarize_masks_bare_sensitive_assignment_in_message() -> None:
    summary = summarize_schedule_submit_for_celery(
        {
            "status": "failed",
            "message": "callback rejected: token=bare-secret; retry access_token=another-secret",
        }
    )
    assert "bare-secret" not in summary["message"]
    assert "another-secret" not in summary["message"]
    assert "token=***" in summary["message"]
    assert "access_token=***" in summary["message"]
    assert celery_result_contains_secrets(summary) is False


def test_redact_url_query_secrets_masks_token() -> None:
    redacted = redact_url_query_secrets(
        "https://www.aieokj.com/api/v1/monitor/molizhishu/callback?token=secret&x=1"
    )
    assert "secret" not in redacted
    from urllib.parse import parse_qs, urlsplit

    query = parse_qs(urlsplit(redacted).query)
    assert query.get("token") == ["***"]
    assert query.get("x") == ["1"]


def test_celery_result_contains_secrets_detects_token_query() -> None:
    assert celery_result_contains_secrets({"msg": "see ?token=abc"}) is True
    assert celery_result_contains_secrets({"callback_url": "https://x/?token=y"}) is True
    assert celery_result_contains_secrets({"task_id": "a", "status": "ok", "total_items": 1}) is False


def test_submit_schedule_group_task_return_is_sanitized(monkeypatch: pytest.MonkeyPatch) -> None:
    """Celery 边界：即使 service 返回完整 serialize_task，任务返回值也必须安全。"""
    from app.tasks import monitor as monitor_tasks

    monkeypatch.setattr(monitor_tasks.settings, "celery_enabled", True)
    monkeypatch.setattr(monitor_tasks, "SessionLocal", lambda: MagicMock())
    monkeypatch.setattr(
        monitor_tasks,
        "load_platform_session",
        lambda _db: SimpleNamespace(user=SimpleNamespace(id=1)),
    )
    monkeypatch.setattr(
        monitor_tasks,
        "due_item_from_group_key",
        lambda **_kwargs: SimpleNamespace(
            tenant_id=1,
            schedule_key="20260917-0900-kw0",
            group_key="20260917-0900-kw0",
            max_prompts=50,
            keyword="词",
            region_code=None,
        ),
    )
    monkeypatch.setattr(
        monitor_tasks,
        "execute_schedule_group",
        lambda *_a, **_k: {
            "tenant_id": 1,
            "schedule_key": "20260917-0900-kw0",
            "status": "submitted",
            "keyword": "词",
            "task": {
                "task_id": "t-1",
                "status": "pending",
                "total_items": 3,
                "completed_items": 0,
                "failed_items": 0,
                "callback_url": "https://example.com/cb?token=MUST-NOT-RETURN",
            },
        },
    )

    result = monitor_tasks.submit_schedule_group_task.run(
        tenant_id=1,
        group_key="20260917-0900-kw0",
        max_prompts=50,
        keyword="词",
    )
    assert result["task_id"] == "t-1"
    assert result["task_status"] == "pending"
    assert result["total_items"] == 3
    assert "callback_url" not in result
    assert "task" not in result
    assert celery_result_contains_secrets(result) is False


def test_submit_schedule_group_task_redacts_runtime_error_log(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """异常文本可能携带回调 URL；写 Worker 日志前必须脱敏。"""
    from app.tasks import monitor as monitor_tasks

    monkeypatch.setattr(monitor_tasks.settings, "celery_enabled", True)
    monkeypatch.setattr(monitor_tasks, "SessionLocal", lambda: MagicMock())
    monkeypatch.setattr(
        monitor_tasks,
        "load_platform_session",
        lambda _db: SimpleNamespace(user=SimpleNamespace(id=1)),
    )
    monkeypatch.setattr(
        monitor_tasks,
        "due_item_from_group_key",
        lambda **_kwargs: SimpleNamespace(
            tenant_id=1,
            schedule_key="20260917-0900-kw0",
            group_key="20260917-0900-kw0",
            max_prompts=50,
            keyword="词",
            region_code=None,
        ),
    )

    leaked_token = "MUST-NOT-LOG"

    def _raise_runtime_error(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError(f"callback https://example.com/cb?token={leaked_token} rejected")

    monkeypatch.setattr(monitor_tasks, "execute_schedule_group", _raise_runtime_error)

    with caplog.at_level(logging.WARNING):
        result = monitor_tasks.submit_schedule_group_task.run(
            tenant_id=1,
            group_key="20260917-0900-kw0",
            max_prompts=50,
            keyword="词",
        )

    assert leaked_token not in caplog.text
    assert "https://" not in caplog.text
    assert "[redacted-url]" in caplog.text
    assert result["message"] == "callback [redacted-url] rejected"
    assert celery_result_contains_secrets(result) is False
