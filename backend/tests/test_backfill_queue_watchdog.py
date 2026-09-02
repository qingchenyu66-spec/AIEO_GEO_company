"""补录：watchdog 扫 pending + G 严格截图。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import pytest

from app.core.database import Base
from app.models.lead_diagnosis import LeadDiagnosis, LeadDiagnosisRun
from app.models.monitor import GeoMonitorScheduleRun, GeoMonitorSubtask, GeoMonitorTask, GeoSnapshotBackfillGapDismiss
from app.models.ops import OperationLog
from app.models.tenant import Tenant
from app.services.share_page_fetch_service import SharePageFetchResult
from app.services.snapshot_backfill_service import fail_stale_backfill_parses


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(
        bind=engine,
        tables=[
            Tenant.__table__,
            GeoMonitorTask.__table__,
            GeoMonitorSubtask.__table__,
            OperationLog.__table__,
            LeadDiagnosis.__table__,
            LeadDiagnosisRun.__table__,
            GeoMonitorScheduleRun.__table__,
            GeoSnapshotBackfillGapDismiss.__table__,
        ],
    )
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def test_fail_stale_backfill_parses_marks_orphan_and_timeout(db_session) -> None:
    orphan = GeoMonitorSubtask(
        subtask_id="st-wd-orphan",
        task_id="task-wd",
        platform="doubao",
        mode="standard",
        prompt="问题",
        status="failed",
        raw_result_json={
            "backfill_parse_status": "pending",
            "snapshot_url": "https://www.doubao.com/thread/a",
            "_pending_parse_job_id": "job-orphan",
        },
    )
    stale = GeoMonitorSubtask(
        subtask_id="st-wd-stale",
        task_id="task-wd",
        platform="doubao",
        mode="standard",
        prompt="问题2",
        status="failed",
        raw_result_json={
            "backfill_parse_status": "pending",
            "snapshot_url": "https://www.doubao.com/thread/b",
            "_pending_parse_job_id": "job-stale",
            "backfill_parse_enqueue": "queued",
            "_pending_parse_started_at": (datetime.now(UTC) - timedelta(seconds=400)).isoformat(),
        },
    )
    fresh = GeoMonitorSubtask(
        subtask_id="st-wd-fresh",
        task_id="task-wd",
        platform="doubao",
        mode="standard",
        prompt="问题3",
        status="failed",
        raw_result_json={
            "backfill_parse_status": "pending",
            "snapshot_url": "https://www.doubao.com/thread/c",
            "_pending_parse_job_id": "job-fresh",
            "backfill_parse_enqueue": "queued",
            "_pending_parse_started_at": datetime.now(UTC).isoformat(),
        },
    )
    task = GeoMonitorTask(
        task_id="task-wd",
        tenant_id=None,
        monitor_keywords="品牌A",
        status="completed",
        prompts_json=["问题"],
        platforms_json=[{"platform": "doubao", "mode": "standard", "screenshot": 1}],
        raw_request_json={},
        raw_response_json={},
    )
    task.subtasks = [orphan, stale, fresh]
    db_session.add(task)
    db_session.commit()

    out = fail_stale_backfill_parses(db_session, timeout_seconds=300, limit=50)
    assert out["failed"] == 2
    db_session.refresh(orphan)
    db_session.refresh(stale)
    db_session.refresh(fresh)
    assert orphan.raw_result_json.get("backfill_parse_status") == "failed"
    assert stale.raw_result_json.get("backfill_parse_status") == "failed"
    assert fresh.raw_result_json.get("backfill_parse_status") == "pending"


def test_bulk_gap_dismiss_insert_ignores_duplicates_on_sqlite(db_session) -> None:
    from app.services.snapshot_backfill_service import _bulk_insert_gap_dismissals

    now = datetime.now(UTC).replace(tzinfo=None)
    row = {
        "tenant_id": 1,
        "platform": "doubao",
        "prompt": "测试问题",
        "schedule_window_key": "20260902-1000",
        "dismissed_at": now,
        "dismissed_by": 1,
    }

    assert _bulk_insert_gap_dismissals(db_session, rows=[row, dict(row)]) == 1
    assert _bulk_insert_gap_dismissals(db_session, rows=[dict(row)]) == 0


def test_watchdog_default_timeout_above_soft_limit() -> None:
    from app.services.snapshot_backfill_service import (
        _BACKFILL_PARSE_RETRY_STALE_SECONDS,
        _BACKFILL_PARSE_WATCHDOG_SECONDS,
    )

    assert _BACKFILL_PARSE_WATCHDOG_SECONDS >= 240
    assert _BACKFILL_PARSE_WATCHDOG_SECONDS > _BACKFILL_PARSE_RETRY_STALE_SECONDS


def test_mark_failed_skips_when_already_ok(db_session) -> None:
    """成功写回后 watchdog/失败路径不得盖掉 ok。"""
    from app.services.snapshot_backfill_service import _mark_backfill_parse_failed

    task = GeoMonitorTask(
        task_id="task-ok-lock",
        tenant_id=None,
        monitor_keywords="品牌A",
        status="completed",
        prompts_json=["问题"],
        platforms_json=[{"platform": "doubao", "mode": "standard", "screenshot": 1}],
        raw_request_json={},
        raw_response_json={},
    )
    subtask = GeoMonitorSubtask(
        subtask_id="st-ok-lock",
        task_id="task-ok-lock",
        platform="doubao",
        mode="standard",
        prompt="问题",
        status="completed",
        answer_content="1. 品牌A",
        raw_result_json={
            "backfill_parse_status": "ok",
            "source": "manual_snapshot",
            "parse_job_id": "job-done",
        },
    )
    task.subtasks = [subtask]
    db_session.add(task)
    db_session.commit()

    assert _mark_backfill_parse_failed(db_session, subtask, "超时", parse_job_id="job-done") is False
    db_session.refresh(subtask)
    assert subtask.raw_result_json.get("backfill_parse_status") == "ok"
    assert subtask.raw_result_json.get("source") == "manual_snapshot"


def test_watchdog_failed_count_only_when_marked(db_session, monkeypatch) -> None:
    """mark 跳过时 failed 计数不得虚高。"""
    stale = GeoMonitorSubtask(
        subtask_id="st-wd-skip",
        task_id="task-wd-skip",
        platform="doubao",
        mode="standard",
        prompt="问题",
        status="failed",
        raw_result_json={
            "backfill_parse_status": "pending",
            "snapshot_url": "https://www.doubao.com/thread/x",
            "_pending_parse_job_id": "job-stale",
            "backfill_parse_enqueue": "queued",
            "_pending_parse_started_at": (datetime.now(UTC) - timedelta(seconds=400)).isoformat(),
        },
    )
    task = GeoMonitorTask(
        task_id="task-wd-skip",
        tenant_id=None,
        monitor_keywords="品牌A",
        status="completed",
        prompts_json=["问题"],
        platforms_json=[{"platform": "doubao", "mode": "standard", "screenshot": 1}],
        raw_request_json={},
        raw_response_json={},
    )
    task.subtasks = [stale]
    db_session.add(task)
    db_session.commit()

    monkeypatch.setattr(
        "app.services.snapshot_backfill_service._mark_backfill_parse_failed",
        lambda *args, **kwargs: False,
    )
    out = fail_stale_backfill_parses(db_session, timeout_seconds=300, limit=50)
    assert out["checked"] >= 1
    assert out["failed"] == 0


def test_combined_does_not_skip_browser_when_qianwen_api_hits(monkeypatch) -> None:
    """严格 G：千问 API 命中也必须进浏览器截图。"""
    from app.services import share_page_fetch_service as svc

    api_hit = SharePageFetchResult(
        answer_content="x" * 100,
        references=[{"title": "a", "url": "https://example.com/a"}],
        title="t",
        source_host="www.qianwen.com",
    )
    monkeypatch.setattr(svc, "_is_qianwen_share_host", lambda host: True)
    monkeypatch.setattr(svc, "_try_qianwen_share_api", lambda url: api_hit)
    monkeypatch.setattr(svc, "_refs_quality_ok", lambda refs, page_host="": True)

    launched = {"browser": False}

    class _FakePage:
        def goto(self, *a, **k):
            return None

        def inner_text(self, *a, **k):
            return "浏览器正文" + ("y" * 80)

        def wait_for_timeout(self, *a, **k):
            return None

        def title(self):
            return "page"

        def content(self):
            return "<html><body>浏览器正文</body></html>"

    class _FakeContext:
        def new_page(self):
            return _FakePage()

        def close(self):
            return None

    class _FakeBrowser:
        def new_context(self, **kwargs):
            launched["browser"] = True
            return _FakeContext()

        def close(self):
            return None

    class _FakeChromium:
        @staticmethod
        def launch(headless=True):
            return _FakeBrowser()

    class _FakePw:
        chromium = _FakeChromium()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    import playwright.sync_api as pw

    monkeypatch.setattr(pw, "sync_playwright", lambda: _FakePw())
    monkeypatch.setattr(
        "app.services.share_page_screenshot_service.capture_share_page_screenshot_from_page",
        lambda page, url, subtask_id=None: "/api/v1/media/backfill-shot/x.png",
    )
    monkeypatch.setattr(svc, "_expand_citation_panels", lambda page: None)
    monkeypatch.setattr(
        svc,
        "_result_from_html",
        lambda *a, **k: SharePageFetchResult(
            answer_content="浏览器正文" + ("y" * 80),
            references=[],
            title="page",
            source_host="www.qianwen.com",
        ),
    )

    result, shot = svc.fetch_share_page_browser_combined(
        "https://www.qianwen.com/share/chat/abc",
        subtask_id="st-g",
    )
    assert launched["browser"] is True
    assert shot == "/api/v1/media/backfill-shot/x.png"
    assert len(result.answer_content) >= 80


def test_celery_routes_backfill_queue() -> None:
    from app.celery_app import celery_app

    routes = celery_app.conf.task_routes or {}
    assert routes["app.tasks.snapshot_backfill.parse_and_apply_backfill_task"]["queue"] == "backfill"
    assert routes["app.tasks.snapshot_backfill.capture_backfill_screenshot_task"]["queue"] == "backfill"
    assert "fail-stale-backfill-parses" in (celery_app.conf.beat_schedule or {})
