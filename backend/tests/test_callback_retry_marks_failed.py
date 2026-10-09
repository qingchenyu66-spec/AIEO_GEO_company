"""回调 Celery 重试耗尽时必须把 event 从 queued 收到 failed。"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from celery.exceptions import MaxRetriesExceededError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.monitor import GeoMonitorCallbackEvent
from app.tasks import monitor as monitor_tasks


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine, tables=[GeoMonitorCallbackEvent.__table__])
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def _queued_event(db_session, *, suffix: str) -> GeoMonitorCallbackEvent:
    event = GeoMonitorCallbackEvent(
        task_id=f"cb-retry-task-{suffix}",
        payload_hash=f"cb-retry-hash-{suffix}",
        process_status="queued",
        payload_json={"taskId": f"cb-retry-task-{suffix}", "status": "completed"},
        received_at=datetime.now(),
    )
    db_session.add(event)
    db_session.commit()
    db_session.refresh(event)
    return event


def test_mark_helper_sets_failed(db_session) -> None:
    event = _queued_event(db_session, suffix="helper")
    monitor_tasks._mark_callback_event_terminal_failed(db_session, event.id, "give up")
    db_session.refresh(event)
    assert event.process_status == "failed"
    assert event.processed_at is not None
    assert "give up" in (event.error_message or "")


def test_max_retries_marks_callback_event_failed(db_session, monkeypatch) -> None:
    event = _queued_event(db_session, suffix="lock")
    monkeypatch.setattr(monitor_tasks.settings, "celery_enabled", True)
    monkeypatch.setattr(db_session, "close", lambda: None)
    monkeypatch.setattr(monitor_tasks, "SessionLocal", lambda: db_session)

    class _Lock:
        def __enter__(self):
            return False

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(monitor_tasks, "redis_lock", lambda *a, **k: _Lock())

    task = monitor_tasks.process_molizhishu_callback_task
    monkeypatch.setattr(task, "max_retries", 8)
    monkeypatch.setattr(task.request, "retries", 8, raising=False)

    def _retry(*_a, **_k):
        raise MaxRetriesExceededError("Can't retry")

    monkeypatch.setattr(task, "retry", _retry)

    result = task.run(event.id)

    assert result["status"] == "failed"
    db_session.refresh(event)
    assert event.process_status == "failed"
    assert event.processed_at is not None
    assert "Can't retry" in (event.error_message or "")


def test_exception_exhaustion_marks_callback_event_failed(db_session, monkeypatch) -> None:
    event = _queued_event(db_session, suffix="boom")
    monkeypatch.setattr(monitor_tasks.settings, "celery_enabled", True)
    monkeypatch.setattr(db_session, "close", lambda: None)
    monkeypatch.setattr(monitor_tasks, "SessionLocal", lambda: db_session)

    class _Lock:
        def __enter__(self):
            return True

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(monitor_tasks, "redis_lock", lambda *a, **k: _Lock())
    monkeypatch.setattr(
        "app.services.molizhishu_callback_service.process_molizhishu_callback_event",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    task = monitor_tasks.process_molizhishu_callback_task
    monkeypatch.setattr(task, "max_retries", 8)
    monkeypatch.setattr(task.request, "retries", 8, raising=False)

    result = task.run(event.id)

    assert result["status"] == "failed"
    db_session.refresh(event)
    assert event.process_status == "failed"
    assert "boom" in (event.error_message or "")


def test_scan_stale_callback_events_requeues_only_old_pending(db_session, monkeypatch) -> None:
    old = _queued_event(db_session, suffix="old")
    old.received_at = datetime.now() - timedelta(minutes=30)
    fresh = _queued_event(db_session, suffix="fresh")
    fresh.received_at = datetime.now()
    db_session.commit()

    monkeypatch.setattr(monitor_tasks.settings, "celery_enabled", True)
    monkeypatch.setattr(db_session, "close", lambda: None)
    monkeypatch.setattr(monitor_tasks, "SessionLocal", lambda: db_session)
    submitted: list[dict] = []
    monkeypatch.setattr(
        monitor_tasks.process_molizhishu_callback_task,
        "apply_async",
        lambda **kwargs: submitted.append(kwargs),
    )

    result = monitor_tasks.scan_stale_callback_events.run(
        older_than_minutes=10,
        limit=10,
    )

    assert result["enqueued"] == 1
    assert result["event_ids"] == [old.id]
    assert submitted[0]["kwargs"] == {"event_id": old.id}
    assert str(old.id) in submitted[0]["task_id"]
    assert fresh.id not in result["event_ids"]


def test_stale_callback_recovery_beat_registered() -> None:
    beat = monitor_tasks.celery_app.conf.beat_schedule or {}
    assert (
        beat["scan-stale-callback-events"]["task"]
        == "app.tasks.monitor.scan_stale_callback_events"
    )
