"""MolizhishuApiError 继承 RuntimeError，捕获顺序必须让接口错误走重试。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from celery.exceptions import Retry

from app.services.molizhishu_client import MolizhishuApiError


def _force_retry(*args: object, **kwargs: object) -> None:
    """单元测试里把 Celery retry 固定成抛 Retry，避免同步 run 直接抛出业务异常。"""
    raise Retry("retrying", kwargs.get("exc"))


def test_submit_schedule_group_retries_on_molizhishu_api_error(monkeypatch: pytest.MonkeyPatch) -> None:
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
        lambda *_a, **_k: (_ for _ in ()).throw(MolizhishuApiError("upstream 503", code=503)),
    )
    monkeypatch.setattr(monitor_tasks.submit_schedule_group_task, "retry", _force_retry)

    with pytest.raises(Retry):
        monitor_tasks.submit_schedule_group_task.run(
            tenant_id=1,
            group_key="20260917-0900-kw0",
            max_prompts=50,
            keyword="词",
        )


def test_submit_schedule_group_skips_plain_runtime_error(monkeypatch: pytest.MonkeyPatch) -> None:
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
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("no platform session")),
    )

    result = monitor_tasks.submit_schedule_group_task.run(
        tenant_id=1,
        group_key="20260917-0900-kw0",
        max_prompts=50,
        keyword="词",
    )
    assert result["status"] == "skipped"
    assert "no platform session" in result["message"]


def test_sync_one_monitor_task_retries_on_molizhishu_api_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.tasks import monitor as monitor_tasks

    monkeypatch.setattr(monitor_tasks.settings, "celery_enabled", True)
    monkeypatch.setattr(monitor_tasks, "SessionLocal", lambda: MagicMock())
    monkeypatch.setattr(
        monitor_tasks,
        "load_platform_session",
        lambda _db: SimpleNamespace(user=SimpleNamespace(id=1)),
    )
    monkeypatch.setattr(monitor_tasks, "summarize_monitor_tasks_for_ops", lambda *_a, **_k: [])
    monkeypatch.setattr(monitor_tasks, "set_sync_live", lambda *_a, **_k: None)
    monkeypatch.setattr(monitor_tasks, "clear_sync_live", lambda *_a, **_k: None)
    monkeypatch.setattr(monitor_tasks, "_clear_enqueued_mark", lambda *_a, **_k: None)
    monkeypatch.setattr(
        monitor_tasks,
        "redis_lock",
        lambda *_a, **_k: MagicMock(__enter__=lambda _s: True, __exit__=lambda *_x: False),
    )
    monkeypatch.setattr(
        monitor_tasks,
        "sync_monitor_task",
        lambda *_a, **_k: (_ for _ in ()).throw(MolizhishuApiError("sync timeout", code=504)),
    )
    monkeypatch.setattr(monitor_tasks.sync_one_monitor_task, "retry", _force_retry)

    with pytest.raises(Retry):
        monitor_tasks.sync_one_monitor_task.run("task-sync-retry-1")
