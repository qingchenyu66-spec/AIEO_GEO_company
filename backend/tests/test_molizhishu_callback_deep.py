"""模力 Callback 深链路：排名补算 / 自动重试 / 快照通知 / 统计 / 锁 / CSRF / 5xx。"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core import config as config_mod
from app.core.database import Base, get_db
from app.core.config import settings
from app.main import app
from app.models.brand import BrandAsset
from app.models.lead_diagnosis import LeadDiagnosisRun
from app.models.monitor import (
    GeoMonitorCallbackEvent,
    GeoMonitorDailyStat,
    GeoMonitorScheduleRun,
    GeoMonitorSubtask,
    GeoMonitorTask,
)
from app.models.notification import SystemNotification
from app.services.molizhishu_callback_service import (
    _post_commit_side_effects,
    ingest_molizhishu_callback,
)

CALLBACK_PATH = "/api/v1/monitor/molizhishu/callback"
TEST_TOKEN = "pytest-callback-deep-secret"


@contextmanager
def _patch_heavy_only():
    """保留排名/重试/通知入口，只挡提交后统计里的外部依赖。"""
    with patch("app.services.brand_analysis_service.parse_sentiments_after_brand_word_sync"):
        yield


@pytest.fixture()
def deep_db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(
        bind=engine,
        tables=[
            GeoMonitorTask.__table__,
            GeoMonitorSubtask.__table__,
            GeoMonitorCallbackEvent.__table__,
            GeoMonitorDailyStat.__table__,
            GeoMonitorScheduleRun.__table__,
            LeadDiagnosisRun.__table__,
            BrandAsset.__table__,
            SystemNotification.__table__,
        ],
    )
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def deep_client(monkeypatch):
    monkeypatch.setattr(config_mod.settings, "molizhishu_callback_token", TEST_TOKEN)
    monkeypatch.setattr(config_mod.settings, "molizhishu_callback_url", "")
    return TestClient(app, raise_server_exceptions=False)


def _task(**kwargs) -> GeoMonitorTask:
    defaults = dict(
        task_id="deep-task-1",
        tenant_id=None,
        monitor_keywords="BrandCo",
        status="pending",
        total_items=1,
        completed_items=0,
        failed_items=0,
        prompts_json=["best vendor ranking"],
        platforms_json=[{"platform": "deepseek", "mode": "search", "screenshot": 1}],
        raw_request_json={"monitorKeywords": "BrandCo"},
        raw_response_json={},
    )
    defaults.update(kwargs)
    return GeoMonitorTask(**defaults)


# --- 1. 排名补算真实跑通 ---


def test_ingest_fills_missing_rank_from_answer(deep_db) -> None:
    deep_db.add(_task(task_id="rank-task"))
    deep_db.commit()
    payload = {
        "taskId": "rank-task",
        "status": "completed",
        "totalItems": 1,
        "completedItems": 1,
        "failedItems": 0,
        "subTaskList": [
            {
                "subTaskId": "rank-sub-1",
                "platform": "deepseek",
                "mode": "search",
                "prompt": "best vendor ranking",
                "status": "completed",
                "answerContent": "1. CompetitorCo\n2. BrandCo\n3. OtherCo",
            }
        ],
    }
    with (
        patch("app.services.monitor_auto_retry_service.apply_auto_retry_results"),
        patch("app.services.monitor_auto_retry_service.launch_auto_retries_for_task", return_value=[]),
        patch("app.services.snapshot_backfill_service.notify_failed_subtasks_for_task", return_value=0),
        patch("app.services.molizhishu_callback_service._post_commit_side_effects"),
    ):
        result = ingest_molizhishu_callback(deep_db, payload)
    assert result["status"] == "processed"
    sub = deep_db.scalar(select(GeoMonitorSubtask).where(GeoMonitorSubtask.subtask_id == "rank-sub-1"))
    assert sub is not None
    assert sub.mention_position == 2


# --- 2. 自动重试真实提交路径（mock 模力）---


def test_ingest_launches_auto_retry_for_failed_subtask(deep_db) -> None:
    deep_db.add(_task(task_id="retry-origin", tenant_id=1, monitor_keywords="品牌A"))
    deep_db.commit()
    payload = {
        "taskId": "retry-origin",
        "status": "partial_completed",
        "totalItems": 1,
        "completedItems": 0,
        "failedItems": 1,
        "subTaskList": [
            {
                "subTaskId": "fail-sub-1",
                "platform": "deepseek",
                "mode": "search",
                "prompt": "电梯广告公司推荐",
                "status": "failed",
                "errorMessage": "timeout",
                "answerContent": "",
            }
        ],
    }
    fake_submit = {
        "code": 0,
        "data": {
            "taskId": "retry-child-1",
            "status": "pending",
            "totalItems": 1,
            "completedItems": 0,
            "failedItems": 0,
            "subTaskList": [
                {
                    "subTaskId": "retry-child-sub-1",
                    "platform": "deepseek",
                    "mode": "search",
                    "prompt": "电梯广告公司推荐",
                    "status": "pending",
                }
            ],
        },
    }
    with (
        patch("app.services.molizhishu_callback_service.fill_missing_subtask_ranks_for_task", return_value=0),
        patch("app.services.molizhishu_callback_service._post_commit_side_effects"),
        patch("app.services.monitor_auto_retry_service.MolizhishuClient") as client_cls,
        patch("app.services.monitor_auto_retry_service._enqueue_sync"),
        patch("app.services.monitor_auto_retry_service.filter_submittable_platforms", return_value=["deepseek"]),
        patch("app.services.snapshot_backfill_service.notify_failed_subtasks_for_task", return_value=0),
    ):
        client_cls.return_value.submit_task.return_value = fake_submit
        result = ingest_molizhishu_callback(deep_db, payload)

    assert result["status"] == "processed"
    origin = deep_db.scalar(select(GeoMonitorSubtask).where(GeoMonitorSubtask.subtask_id == "fail-sub-1"))
    assert origin is not None
    assert origin.auto_retry_count == 1
    assert origin.auto_retry_task_id == "retry-child-1"
    assert origin.auto_retry_status == "pending"
    child = deep_db.scalar(select(GeoMonitorTask).where(GeoMonitorTask.task_id == "retry-child-1"))
    assert child is not None


# --- 3. 快照补录通知真实写入 ---


def test_ingest_writes_snapshot_backfill_notification(deep_db) -> None:
    deep_db.add(_task(task_id="notify-task", tenant_id=None, monitor_keywords="品牌A"))
    deep_db.commit()
    # 失败且无正文 → needs_backfill；auto_retry 记 exhausted 避免再提交
    payload = {
        "taskId": "notify-task",
        "status": "failed",
        "totalItems": 1,
        "completedItems": 0,
        "failedItems": 1,
        "subTaskList": [
            {
                "subTaskId": "notify-sub-1",
                "platform": "deepseek",
                "mode": "search",
                "prompt": "电梯广告公司推荐",
                "status": "failed",
                "errorMessage": "captcha",
                "answerContent": "",
            }
        ],
    }
    with (
        patch("app.services.molizhishu_callback_service.fill_missing_subtask_ranks_for_task", return_value=0),
        patch("app.services.molizhishu_callback_service._post_commit_side_effects"),
        # 提交失败路径：标记 exhausted，仍走 notify
        patch(
            "app.services.monitor_auto_retry_service.MolizhishuClient"
        ) as client_cls,
        patch("app.services.monitor_auto_retry_service.filter_submittable_platforms", return_value=["deepseek"]),
    ):
        from app.services.molizhishu_client import MolizhishuApiError

        client_cls.return_value.submit_task.side_effect = MolizhishuApiError("boom")
        result = ingest_molizhishu_callback(deep_db, payload)

    assert result["status"] == "processed"
    note = deep_db.scalar(select(SystemNotification))
    assert note is not None
    assert "补录" in note.title or "补录" in note.message


# --- 4. post_commit 统计 + 缓存失效 ---


def test_post_commit_refreshes_stats_and_busts_cache(deep_db) -> None:
    deep_db.add(
        _task(
            task_id="stats-task",
            tenant_id=9,
            status="completed",
            total_items=1,
            completed_items=1,
        )
    )
    deep_db.add(
        GeoMonitorSubtask(
            subtask_id="stats-sub-1",
            task_id="stats-task",
            platform="deepseek",
            mode="search",
            prompt="q",
            status="completed",
            mention_position=1,
            answer_content="ok",
            raw_result_json={},
        )
    )
    deep_db.commit()
    task = deep_db.scalar(select(GeoMonitorTask).where(GeoMonitorTask.task_id == "stats-task"))
    assert task is not None

    with (
        patch("app.services.monitor_service.invalidate_monitor_summary_cache") as bust,
        patch("app.services.brand_analysis_service.parse_sentiments_after_brand_word_sync"),
    ):
        _post_commit_side_effects(deep_db, task)

    bust.assert_called_once_with(9)
    row = deep_db.scalar(
        select(GeoMonitorDailyStat).where(
            GeoMonitorDailyStat.tenant_id == 9,
            GeoMonitorDailyStat.platform == "deepseek",
        )
    )
    assert row is not None
    assert row.completed_count >= 1


def test_ingest_calls_post_commit_after_success(deep_db) -> None:
    deep_db.add(_task(task_id="pc-task"))
    deep_db.commit()
    payload = {
        "taskId": "pc-task",
        "status": "completed",
        "totalItems": 1,
        "completedItems": 1,
        "failedItems": 0,
        "subTaskList": [
            {
                "subTaskId": "pc-sub",
                "platform": "deepseek",
                "mode": "search",
                "prompt": "q",
                "status": "completed",
                "answerContent": "hello",
            }
        ],
    }
    with (
        patch("app.services.molizhishu_callback_service.fill_missing_subtask_ranks_for_task", return_value=0),
        patch("app.services.monitor_auto_retry_service.apply_auto_retry_results"),
        patch("app.services.monitor_auto_retry_service.launch_auto_retries_for_task", return_value=[]),
        patch("app.services.snapshot_backfill_service.notify_failed_subtasks_for_task", return_value=0),
        patch("app.services.molizhishu_callback_service._post_commit_side_effects") as post,
    ):
        ingest_molizhishu_callback(deep_db, payload)
    post.assert_called_once()


# --- 5. Redis 锁冲突 → 409 ---


def test_http_409_when_sync_lock_not_acquired(deep_client, deep_db) -> None:
    app.dependency_overrides[get_db] = lambda: deep_db
    try:
        @contextmanager
        def _busy_lock(*_a, **_k):
            yield False

        with patch("app.core.redis_client.redis_lock", _busy_lock):
            resp = deep_client.post(
                f"{CALLBACK_PATH}?token={TEST_TOKEN}",
                json={"taskId": "locked-task", "status": "completed", "subTaskList": []},
            )
        assert resp.status_code == 409
    finally:
        app.dependency_overrides.pop(get_db, None)


# --- 6. 落库异常 → 5xx + event=failed ---


def test_http_500_marks_event_failed(deep_client, deep_db) -> None:
    deep_db.add(_task(task_id="boom-task"))
    deep_db.commit()
    app.dependency_overrides[get_db] = lambda: deep_db
    try:
        with patch(
            "app.services.molizhishu_callback_service._apply_callback_payload",
            side_effect=RuntimeError("simulated ingest boom"),
        ):
            resp = deep_client.post(
                f"{CALLBACK_PATH}?token={TEST_TOKEN}",
                json={
                    "taskId": "boom-task",
                    "status": "completed",
                    "totalItems": 1,
                    "completedItems": 1,
                    "failedItems": 0,
                    "subTaskList": [],
                },
            )
        assert resp.status_code == 500
        event = deep_db.scalar(select(GeoMonitorCallbackEvent))
        assert event is not None
        assert event.process_status == "failed"
        assert "simulated ingest boom" in (event.error_message or "")
    finally:
        app.dependency_overrides.pop(get_db, None)


# --- 7. CSRF 豁免 ---


def test_csrf_exempt_allows_callback_without_csrf_header(deep_client, deep_db) -> None:
    deep_db.add(_task(task_id="csrf-task"))
    deep_db.commit()
    app.dependency_overrides[get_db] = lambda: deep_db
    settings.auth_csrf_enabled = True
    settings.auth_cookie_enabled = True
    try:
        deep_client.cookies.set("geo_access_token", "fake-session")
        deep_client.cookies.set("geo_csrf_token", "token-a")
        with (
            patch("app.services.molizhishu_callback_service.fill_missing_subtask_ranks_for_task", return_value=0),
            patch("app.services.monitor_auto_retry_service.apply_auto_retry_results"),
            patch("app.services.monitor_auto_retry_service.launch_auto_retries_for_task", return_value=[]),
            patch("app.services.snapshot_backfill_service.notify_failed_subtasks_for_task", return_value=0),
            patch("app.services.molizhishu_callback_service._post_commit_side_effects"),
        ):
            # 故意不带 / 错 CSRF header；豁免路径应放行（非 403）
            resp = deep_client.post(
                f"{CALLBACK_PATH}?token={TEST_TOKEN}",
                json={
                    "taskId": "csrf-task",
                    "status": "completed",
                    "totalItems": 1,
                    "completedItems": 1,
                    "failedItems": 0,
                    "subTaskList": [
                        {
                            "subTaskId": "csrf-sub",
                            "platform": "deepseek",
                            "mode": "search",
                            "prompt": "q",
                            "status": "completed",
                            "answerContent": "x",
                        }
                    ],
                },
                headers={"X-CSRF-Token": "token-b"},
            )
        assert resp.status_code != 403
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "processed"
    finally:
        settings.auth_csrf_enabled = False
        deep_client.cookies.clear()
        app.dependency_overrides.pop(get_db, None)
