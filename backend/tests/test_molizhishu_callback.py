"""模力 Callback：鉴权、提交、落库、HTTP 路由自检。"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core import config as config_mod
from app.core.database import Base
from app.main import app
from app.models.monitor import GeoMonitorCallbackEvent, GeoMonitorSubtask, GeoMonitorTask
from app.schemas.monitor import FAST_MONITOR_MODE, MonitorTaskCreateRequest, PlatformConfig
from app.services.molizhishu_callback_service import (
    expected_callback_token,
    ingest_molizhishu_callback,
    verify_callback_token,
)
from app.services.monitor_service import _build_submit_payload

CALLBACK_PATH = "/api/v1/monitor/molizhishu/callback"
TEST_TOKEN = "pytest-callback-secret"


@contextmanager
def _patch_callback_side_effects():
    """回调单测只验落库/幂等，跳过排名/重试/快照/统计等重依赖。"""
    with (
        patch("app.services.molizhishu_callback_service._post_commit_side_effects"),
        patch("app.services.molizhishu_callback_service.fill_missing_subtask_ranks_for_task", return_value=0),
        patch("app.services.monitor_auto_retry_service.apply_auto_retry_results"),
        patch("app.services.monitor_auto_retry_service.launch_auto_retries_for_task"),
        patch("app.services.snapshot_backfill_service.notify_failed_subtasks_for_task"),
    ):
        yield


def _sample_callback(task_id: str = "cb-task-1", subtask_id: str = "sub_cb_1") -> dict:
    return {
        "taskId": task_id,
        "userId": 1,
        "timestamp": 1700000000000,
        "status": "completed",
        "totalItems": 1,
        "completedItems": 1,
        "failedItems": 0,
        "subTaskList": [
            {
                "subTaskId": subtask_id,
                "platform": "deepseek",
                "mode": "search",
                "prompt": "测试问题",
                "status": "completed",
                "answerContent": "回答含品牌A",
                "referenceList": [{"title": "来源1", "url": "https://example.com/1"}],
            }
        ],
    }


def _monitor_task(task_id: str = "cb-task-1") -> GeoMonitorTask:
    return GeoMonitorTask(
        task_id=task_id,
        tenant_id=1,
        status="pending",
        total_items=1,
        completed_items=0,
        failed_items=0,
        prompts_json=["测试问题"],
        platforms_json=[{"platform": "deepseek", "mode": "search", "screenshot": 1}],
        raw_request_json={},
        raw_response_json={},
    )


@pytest.fixture()
def cb_db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(
        bind=engine,
        tables=[
            GeoMonitorTask.__table__,
            GeoMonitorSubtask.__table__,
            GeoMonitorCallbackEvent.__table__,
        ],
    )
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def callback_client(monkeypatch):
    monkeypatch.setattr(config_mod.settings, "molizhishu_callback_token", TEST_TOKEN)
    monkeypatch.setattr(config_mod.settings, "molizhishu_callback_url", "")
    return TestClient(app, raise_server_exceptions=False)


# --- 鉴权 / 提交 ---


def test_expected_token_prefers_dedicated_setting(monkeypatch) -> None:
    monkeypatch.setattr(config_mod.settings, "molizhishu_callback_token", "from-token-field")
    monkeypatch.setattr(
        config_mod.settings,
        "molizhishu_callback_url",
        "https://example.com/api/v1/monitor/molizhishu/callback?token=from-url",
    )
    assert expected_callback_token() == "from-token-field"
    assert verify_callback_token("from-token-field") is True
    assert verify_callback_token("from-url") is False


def test_expected_token_falls_back_to_callback_url_query(monkeypatch) -> None:
    monkeypatch.setattr(config_mod.settings, "molizhishu_callback_token", "")
    monkeypatch.setattr(
        config_mod.settings,
        "molizhishu_callback_url",
        "https://example.com/api/v1/monitor/molizhishu/callback?token=url-secret",
    )
    assert expected_callback_token() == "url-secret"
    assert verify_callback_token("url-secret") is True
    assert verify_callback_token("") is False
    assert verify_callback_token(None) is False


def test_verify_rejects_when_token_unconfigured(monkeypatch) -> None:
    monkeypatch.setattr(config_mod.settings, "molizhishu_callback_token", "")
    monkeypatch.setattr(config_mod.settings, "molizhishu_callback_url", "")
    assert expected_callback_token() == ""
    assert verify_callback_token("anything") is False


def test_submit_payload_includes_callback_url(monkeypatch) -> None:
    monkeypatch.setattr(
        config_mod.settings,
        "molizhishu_callback_url",
        "https://example.com/api/v1/monitor/molizhishu/callback?token=cb",
    )
    payload = MonitorTaskCreateRequest(
        prompts=["问题A"],
        platforms=[PlatformConfig(platform="doubao", mode=FAST_MONITOR_MODE)],
    )
    body = _build_submit_payload(payload, monitor_keywords="品牌A")
    assert body["callbackUrl"] == "https://example.com/api/v1/monitor/molizhishu/callback?token=cb"


# --- ingest 落库 ---


def test_ingest_unknown_task_is_ignored(cb_db) -> None:
    payload = _sample_callback(task_id="missing-task")
    with _patch_callback_side_effects():
        result = ingest_molizhishu_callback(cb_db, payload)
    assert result["status"] == "ignored"
    event = cb_db.scalar(select(GeoMonitorCallbackEvent))
    assert event is not None
    assert event.process_status == "ignored"


def test_ingest_processes_subtasks(cb_db) -> None:
    cb_db.add(_monitor_task())
    cb_db.commit()
    payload = _sample_callback()
    with _patch_callback_side_effects():
        result = ingest_molizhishu_callback(cb_db, payload)
    assert result["status"] == "processed"
    task = cb_db.scalar(select(GeoMonitorTask).where(GeoMonitorTask.task_id == "cb-task-1"))
    assert task is not None
    assert task.status == "completed"
    assert task.completed_items == 1
    sub = cb_db.scalar(select(GeoMonitorSubtask).where(GeoMonitorSubtask.subtask_id == "sub_cb_1"))
    assert sub is not None
    assert sub.answer_content == "回答含品牌A"
    assert isinstance(sub.reference_list_json, list) and len(sub.reference_list_json) == 1


def test_ingest_duplicate_payload_is_idempotent(cb_db) -> None:
    cb_db.add(_monitor_task())
    cb_db.commit()
    payload = _sample_callback()
    with _patch_callback_side_effects():
        first = ingest_molizhishu_callback(cb_db, payload)
        second = ingest_molizhishu_callback(cb_db, payload)
    assert first["status"] == "processed"
    assert second["status"] == "duplicate"
    assert cb_db.scalar(select(GeoMonitorCallbackEvent)).id == second["event_id"]
    assert cb_db.query(GeoMonitorCallbackEvent).count() == 1


def test_ingest_rejects_missing_task_id(cb_db) -> None:
    with pytest.raises(ValueError, match="taskId"):
        ingest_molizhishu_callback(cb_db, {"status": "completed"})


# --- HTTP 路由 ---


def test_http_callback_rejects_bad_token(callback_client) -> None:
    resp = callback_client.post(f"{CALLBACK_PATH}?token=wrong", json=_sample_callback())
    assert resp.status_code == 401


def test_http_callback_rejects_invalid_json(callback_client) -> None:
    resp = callback_client.post(
        f"{CALLBACK_PATH}?token={TEST_TOKEN}",
        content=b"not-json",
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 400


def test_http_callback_unknown_task_returns_200(callback_client, cb_db, monkeypatch) -> None:
    monkeypatch.setattr(config_mod.settings, "celery_enabled", False)
    monkeypatch.setattr("app.api.v1.endpoints.monitor.get_db", lambda: cb_db)
    # FastAPI Depends 需 override
    from app.core.database import get_db

    app.dependency_overrides[get_db] = lambda: cb_db
    try:
        with _patch_callback_side_effects():
            resp = callback_client.post(
                f"{CALLBACK_PATH}?token={TEST_TOKEN}",
                json=_sample_callback(task_id="http-missing"),
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"]["status"] == "ignored"
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_http_callback_processes_known_task(callback_client, cb_db, monkeypatch) -> None:
    monkeypatch.setattr(config_mod.settings, "celery_enabled", False)
    cb_db.add(_monitor_task(task_id="http-known"))
    cb_db.commit()
    from app.core.database import get_db

    app.dependency_overrides[get_db] = lambda: cb_db
    try:
        with _patch_callback_side_effects():
            resp = callback_client.post(
                f"{CALLBACK_PATH}?token={TEST_TOKEN}",
                json=_sample_callback(task_id="http-known", subtask_id="sub_http_1"),
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"]["status"] == "processed"
        sub = cb_db.scalar(select(GeoMonitorSubtask).where(GeoMonitorSubtask.subtask_id == "sub_http_1"))
        assert sub is not None
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_http_callback_accepts_when_celery_enqueues(callback_client, cb_db, monkeypatch) -> None:
    monkeypatch.setattr(config_mod.settings, "celery_enabled", True)
    cb_db.add(_monitor_task(task_id="http-queued"))
    cb_db.commit()
    from app.core.database import get_db

    app.dependency_overrides[get_db] = lambda: cb_db
    try:
        with patch(
            "app.services.molizhishu_callback_service._enqueue_callback_event",
            return_value=True,
        ):
            resp = callback_client.post(
                f"{CALLBACK_PATH}?token={TEST_TOKEN}",
                json=_sample_callback(task_id="http-queued", subtask_id="sub_queued_1"),
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"]["status"] == "accepted"
        assert body["data"]["process_status"] == "queued"
        event = cb_db.scalar(select(GeoMonitorCallbackEvent))
        assert event is not None
        assert event.process_status == "queued"
        # 尚未被 worker 处理，子任务不应已写入
        sub = cb_db.scalar(select(GeoMonitorSubtask).where(GeoMonitorSubtask.subtask_id == "sub_queued_1"))
        assert sub is None
    finally:
        app.dependency_overrides.pop(get_db, None)
