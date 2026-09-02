"""补录 D：慢路径异步入队 + Worker 合并解析。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.lead_diagnosis import LeadDiagnosis, LeadDiagnosisRun
from app.models.monitor import GeoMonitorScheduleRun, GeoMonitorSubtask, GeoMonitorTask
from app.models.ops import OperationLog
from app.models.tenant import Tenant
from app.services.share_page_fetch_service import SharePageFetchResult
from app.services.snapshot_backfill_service import apply_snapshot_backfill, run_async_backfill_parse


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
        ],
    )
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def test_slow_share_url_queues_async_parse(monkeypatch) -> None:
    task = GeoMonitorTask(
        task_id="task-async",
        tenant_id=1,
        monitor_keywords="品牌A",
        status="completed",
        platforms_json=[{"platform": "deepseek", "mode": "standard", "screenshot": 1}],
        raw_request_json={},
        raw_response_json={},
    )
    subtask = GeoMonitorSubtask(
        subtask_id="st-async",
        task_id="task-async",
        platform="deepseek",
        mode="standard",
        prompt="问题",
        status="failed",
        raw_result_json={},
    )
    task.subtasks = [subtask]

    db = MagicMock()

    monkeypatch.setattr(
        "app.services.snapshot_backfill_service.get_monitor_subtask",
        lambda db, sid, current: subtask,
    )
    monkeypatch.setattr(
        "app.services.snapshot_backfill_service.get_monitor_task",
        lambda db, tid, current: task,
    )
    monkeypatch.setattr(
        "app.services.snapshot_backfill_service.try_fast_fetch_share_page",
        lambda url: None,
    )
    monkeypatch.setattr(
        "app.services.snapshot_backfill_service.get_brand_asset",
        lambda db, tid: None,
    )
    monkeypatch.setattr(
        "app.services.snapshot_backfill_service.list_keyword_groups",
        lambda db, tid: [],
    )
    monkeypatch.setattr(
        "app.services.snapshot_backfill_service._pack_backfill_apply_response",
        lambda db, st, tk, **kwargs: {"parse_async": kwargs.get("parse_async", False), "subtask": {"subtask_id": st.subtask_id}},
    )
    enqueued: list[str] = []
    seen_enqueue_at_delay: list[str] = []

    def _enqueue(*, subtask_id, parse_job_id):
        seen_enqueue_at_delay.append(str(subtask.raw_result_json.get("backfill_parse_enqueue") or ""))
        enqueued.append((subtask_id, parse_job_id))
        return "queued"

    monkeypatch.setattr(
        "app.services.snapshot_backfill_service.enqueue_backfill_parse",
        _enqueue,
    )

    current = SimpleNamespace(
        identity=SimpleNamespace(identity_type="PLATFORM", tenant_id=None, id=1),
        user=SimpleNamespace(id=9),
    )
    out = apply_snapshot_backfill(
        db,
        subtask_id="st-async",
        snapshot_url="https://chat.deepseek.com/share/abc",
        current=current,
    )
    assert out.get("parse_async") is True
    assert subtask.raw_result_json.get("backfill_parse_status") == "pending"
    job_id = subtask.raw_result_json.get("_pending_parse_job_id")
    assert job_id
    assert enqueued == [("st-async", job_id)]
    assert seen_enqueue_at_delay == ["dispatching"]
    assert subtask.raw_result_json.get("backfill_parse_enqueue") == "queued"


def test_dispatching_pending_not_immediately_stale() -> None:
    from app.services.snapshot_backfill_service import _backfill_parse_pending_stale

    fresh = {
        "backfill_parse_status": "pending",
        "backfill_parse_enqueue": "dispatching",
        "_pending_parse_started_at": datetime.now(UTC).isoformat(),
    }
    assert _backfill_parse_pending_stale(fresh) is False
    orphan = {
        "backfill_parse_status": "pending",
        "_pending_parse_started_at": datetime.now(UTC).isoformat(),
    }
    assert _backfill_parse_pending_stale(orphan) is True


def test_orphan_pending_allows_retry(monkeypatch) -> None:
    """入队失败遗留的 pending（无 enqueue 标记）应允许重提。"""
    task = GeoMonitorTask(
        task_id="task-orphan",
        tenant_id=1,
        monitor_keywords="品牌A",
        status="completed",
        platforms_json=[{"platform": "doubao", "mode": "standard", "screenshot": 1}],
        raw_request_json={},
        raw_response_json={},
    )
    subtask = GeoMonitorSubtask(
        subtask_id="st-orphan",
        task_id="task-orphan",
        platform="doubao",
        mode="standard",
        prompt="问题",
        status="failed",
        raw_result_json={
            "backfill_parse_status": "pending",
            "snapshot_url": "https://www.doubao.com/thread/abc",
        },
    )
    task.subtasks = [subtask]
    db = MagicMock()
    monkeypatch.setattr(
        "app.services.snapshot_backfill_service.get_monitor_subtask",
        lambda db, sid, current: subtask,
    )
    monkeypatch.setattr(
        "app.services.snapshot_backfill_service.get_monitor_task",
        lambda db, tid, current: task,
    )
    monkeypatch.setattr(
        "app.services.snapshot_backfill_service.try_fast_fetch_share_page",
        lambda url: None,
    )
    monkeypatch.setattr(
        "app.services.snapshot_backfill_service.get_brand_asset",
        lambda db, tid: None,
    )
    monkeypatch.setattr(
        "app.services.snapshot_backfill_service.list_keyword_groups",
        lambda db, tid: [],
    )
    monkeypatch.setattr(
        "app.services.snapshot_backfill_service._pack_backfill_apply_response",
        lambda db, st, tk, **kwargs: {"parse_async": kwargs.get("parse_async", False), "subtask": {"subtask_id": st.subtask_id}},
    )
    enqueued: list[str] = []
    monkeypatch.setattr(
        "app.services.snapshot_backfill_service.enqueue_backfill_parse",
        lambda *, subtask_id, parse_job_id: enqueued.append((subtask_id, parse_job_id)) or "thread_fallback",
    )
    current = SimpleNamespace(
        identity=SimpleNamespace(identity_type="PLATFORM", tenant_id=None, id=1),
        user=SimpleNamespace(id=9),
    )
    out = apply_snapshot_backfill(
        db,
        subtask_id="st-orphan",
        snapshot_url="https://www.doubao.com/thread/abc",
        current=current,
    )
    assert out.get("parse_async") is True
    job_id = subtask.raw_result_json.get("_pending_parse_job_id")
    assert enqueued == [("st-orphan", job_id)]
    assert subtask.raw_result_json.get("backfill_parse_enqueue") == "thread_fallback"
    assert job_id


def test_celery_enqueue_failure_clears_pending(monkeypatch) -> None:
    """celery_enabled 时入队失败应清 pending，不得线程兜底。"""
    task = GeoMonitorTask(
        task_id="task-enq-fail",
        tenant_id=1,
        monitor_keywords="品牌A",
        status="completed",
        platforms_json=[{"platform": "doubao", "mode": "standard", "screenshot": 1}],
        raw_request_json={},
        raw_response_json={},
    )
    subtask = GeoMonitorSubtask(
        subtask_id="st-enq-fail",
        task_id="task-enq-fail",
        platform="doubao",
        mode="standard",
        prompt="问题",
        status="failed",
        raw_result_json={},
    )
    task.subtasks = [subtask]
    db = MagicMock()
    monkeypatch.setattr(
        "app.services.snapshot_backfill_service.get_monitor_subtask",
        lambda db, sid, current: subtask,
    )
    monkeypatch.setattr(
        "app.services.snapshot_backfill_service.get_monitor_task",
        lambda db, tid, current: task,
    )
    monkeypatch.setattr(
        "app.services.snapshot_backfill_service.try_fast_fetch_share_page",
        lambda url: None,
    )
    monkeypatch.setattr(
        "app.services.snapshot_backfill_service.get_brand_asset",
        lambda db, tid: None,
    )
    monkeypatch.setattr(
        "app.services.snapshot_backfill_service.list_keyword_groups",
        lambda db, tid: [],
    )
    monkeypatch.setattr(
        "app.services.snapshot_backfill_service.enqueue_backfill_parse",
        lambda *, subtask_id, parse_job_id: (_ for _ in ()).throw(RuntimeError("broker down")),
    )
    current = SimpleNamespace(
        identity=SimpleNamespace(identity_type="PLATFORM", tenant_id=None, id=1),
        user=SimpleNamespace(id=9),
    )
    with pytest.raises(ValueError, match="解析任务入队失败"):
        apply_snapshot_backfill(
            db,
            subtask_id="st-enq-fail",
            snapshot_url="https://www.doubao.com/thread/abc",
            current=current,
        )
    assert subtask.raw_result_json.get("backfill_parse_status") == "failed"
    assert "入队失败" in str(subtask.raw_result_json.get("backfill_parse_error") or "")
    assert not subtask.raw_result_json.get("_pending_parse_job_id")


def test_run_async_backfill_parse_applies_combined_result(db_session, monkeypatch) -> None:
    task = GeoMonitorTask(
        task_id="task-worker",
        tenant_id=None,
        monitor_keywords="品牌A",
        status="completed",
        prompts_json=["问题"],
        platforms_json=[{"platform": "deepseek", "mode": "standard", "screenshot": 1}],
        raw_request_json={},
        raw_response_json={},
    )
    subtask = GeoMonitorSubtask(
        subtask_id="st-worker",
        task_id="task-worker",
        platform="deepseek",
        mode="standard",
        prompt="问题",
        status="failed",
        raw_result_json={
            "backfill_parse_status": "pending",
            "snapshot_url": "https://chat.deepseek.com/share/abc",
            "_pending_operator_user_id": 1,
            "_pending_parse_job_id": "job-worker-1",
            "backfill_parse_enqueue": "queued",
        },
    )
    task.subtasks = [subtask]
    db_session.add(task)
    db_session.commit()

    def _combined(url: str, *, subtask_id: str | None = None, timeout_ms: int = 120000):
        return (
            SharePageFetchResult(
                answer_content="1. 品牌A\n2. 竞品B",
                references=[{"title": "x", "url": "https://example.com/x", "site": "example.com"}],
                title="t",
                source_host="deepseek.com",
            ),
            "/api/v1/media/backfill-shot/st-worker_abc.png",
        )

    monkeypatch.setattr(
        "app.services.share_page_fetch_service.fetch_share_page_browser_combined",
        _combined,
    )
    monkeypatch.setattr(
        "app.services.snapshot_backfill_service.enqueue_backfill_screenshot",
        lambda **kwargs: "queued",
    )
    monkeypatch.setattr(
        "app.services.monitor_stats_service.refresh_stats_after_subtask_backfill",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "app.services.monitor_service.invalidate_monitor_summary_cache",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "app.services.lead_diagnosis_service.refresh_lead_diagnosis_after_backfill",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "app.services.snapshot_backfill_service._bust_snapshot_backfill_matrix_cache",
        lambda: None,
    )
    monkeypatch.setattr(
        "app.services.snapshot_backfill_service.resolve_subtask_backfill_notification",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "app.services.snapshot_backfill_service._snapshot_backfill_log_description",
        lambda *a, **k: "补录",
    )
    monkeypatch.setattr(
        "app.services.snapshot_backfill_service.get_brand_asset",
        lambda db, tid: None,
    )
    monkeypatch.setattr(
        "app.services.snapshot_backfill_service.list_keyword_groups",
        lambda db, tid: [],
    )
    monkeypatch.setattr(
        "app.services.snapshot_backfill_service._operator_session_from_raw",
        lambda db, raw: SimpleNamespace(
            user=SimpleNamespace(id=1, display_name="ops", username="ops"),
            identity=SimpleNamespace(
                id=1,
                identity_type="PLATFORM",
                identity_name="ops",
                tenant_id=None,
                position_id=None,
            ),
        ),
    )

    result = run_async_backfill_parse(db_session, "st-worker", parse_job_id="job-worker-1")
    assert result.get("status") == "ok"
    db_session.refresh(subtask)
    assert (subtask.answer_content or "").strip()
    assert subtask.raw_result_json.get("backfill_parse_status") == "ok"
    assert subtask.raw_result_json.get("_pending_parse_job_id") is None
    db_session.refresh(subtask)
    assert subtask.answer_content.startswith("1.")
    assert subtask.page_screenshot == "/api/v1/media/backfill-shot/st-worker_abc.png"
    assert subtask.raw_result_json.get("backfill_parse_status") == "ok"
    assert subtask.raw_result_json.get("fetch_async") is True
    assert subtask.raw_result_json.get("_pending_parse_started_at") is None
    assert subtask.raw_result_json.get("_pending_parse_job_id") is None


def test_run_async_skips_when_parse_job_superseded(db_session, monkeypatch) -> None:
    """旧 Worker 写回前发现 job_id 已被新任务替换则跳过。"""
    task = GeoMonitorTask(
        task_id="task-super",
        tenant_id=None,
        monitor_keywords="品牌A",
        status="completed",
        prompts_json=["问题"],
        platforms_json=[{"platform": "deepseek", "mode": "standard", "screenshot": 1}],
        raw_request_json={},
        raw_response_json={},
    )
    subtask = GeoMonitorSubtask(
        subtask_id="st-super",
        task_id="task-super",
        platform="deepseek",
        mode="standard",
        prompt="问题",
        status="failed",
        raw_result_json={
            "backfill_parse_status": "pending",
            "snapshot_url": "https://chat.deepseek.com/share/abc",
            "_pending_operator_user_id": 1,
            "_pending_parse_job_id": "job-old",
            "backfill_parse_enqueue": "queued",
        },
    )
    task.subtasks = [subtask]
    db_session.add(task)
    db_session.commit()

    def _combined(url: str, *, subtask_id: str | None = None, timeout_ms: int = 120000):
        # 模拟解析期间用户重提换了 job
        db_session.refresh(subtask)
        raw = dict(subtask.raw_result_json or {})
        raw["_pending_parse_job_id"] = "job-new"
        subtask.raw_result_json = raw
        db_session.commit()
        return (
            SharePageFetchResult(
                answer_content="旧 Worker 正文不应入库",
                references=[],
                title="t",
                source_host="deepseek.com",
            ),
            None,
        )

    monkeypatch.setattr(
        "app.services.share_page_fetch_service.fetch_share_page_browser_combined",
        _combined,
    )
    monkeypatch.setattr(
        "app.services.snapshot_backfill_service._operator_session_from_raw",
        lambda db, raw: SimpleNamespace(
            user=SimpleNamespace(id=1, display_name="ops", username="ops"),
            identity=SimpleNamespace(
                id=1,
                identity_type="PLATFORM",
                identity_name="ops",
                tenant_id=None,
                position_id=None,
            ),
        ),
    )

    result = run_async_backfill_parse(db_session, "st-super", parse_job_id="job-old")
    assert result.get("status") == "skipped"
    assert result.get("reason") == "superseded"
    db_session.refresh(subtask)
    assert not (subtask.answer_content or "").strip()
    assert subtask.raw_result_json.get("_pending_parse_job_id") == "job-new"
    assert subtask.raw_result_json.get("backfill_parse_status") == "pending"


def test_run_async_skips_when_queued_job_mismatches_db(db_session) -> None:
    """排队旧任务带着旧 job_id 启动时，库已是新 job → 开头就 skip，不得冒用。"""
    task = GeoMonitorTask(
        task_id="task-mismatch",
        tenant_id=None,
        monitor_keywords="品牌A",
        status="completed",
        prompts_json=["问题"],
        platforms_json=[{"platform": "deepseek", "mode": "standard", "screenshot": 1}],
        raw_request_json={},
        raw_response_json={},
    )
    subtask = GeoMonitorSubtask(
        subtask_id="st-mismatch",
        task_id="task-mismatch",
        platform="deepseek",
        mode="standard",
        prompt="问题",
        status="failed",
        raw_result_json={
            "backfill_parse_status": "pending",
            "snapshot_url": "https://chat.deepseek.com/share/abc",
            "_pending_parse_job_id": "job-new",
            "backfill_parse_enqueue": "queued",
        },
    )
    task.subtasks = [subtask]
    db_session.add(task)
    db_session.commit()

    result = run_async_backfill_parse(db_session, "st-mismatch", parse_job_id="job-old")
    assert result.get("status") == "skipped"
    assert result.get("reason") == "superseded"
    db_session.refresh(subtask)
    assert not (subtask.answer_content or "").strip()
    assert subtask.raw_result_json.get("_pending_parse_job_id") == "job-new"


def test_run_async_rejects_missing_parse_job_id(db_session) -> None:
    """无入参 job_id 不得用库里当前身份（防排队旧任务冒用）。"""
    task = GeoMonitorTask(
        task_id="task-nojid",
        tenant_id=None,
        monitor_keywords="品牌A",
        status="completed",
        prompts_json=["问题"],
        platforms_json=[{"platform": "deepseek", "mode": "standard", "screenshot": 1}],
        raw_request_json={},
        raw_response_json={},
    )
    subtask = GeoMonitorSubtask(
        subtask_id="st-nojid",
        task_id="task-nojid",
        platform="deepseek",
        mode="standard",
        prompt="问题",
        status="failed",
        raw_result_json={
            "backfill_parse_status": "pending",
            "snapshot_url": "https://chat.deepseek.com/share/abc",
            "_pending_parse_job_id": "job-current",
            "backfill_parse_enqueue": "queued",
        },
    )
    task.subtasks = [subtask]
    db_session.add(task)
    db_session.commit()

    result = run_async_backfill_parse(db_session, "st-nojid")
    assert result.get("status") == "skipped"
    assert result.get("reason") == "missing_parse_job_id"
    db_session.refresh(subtask)
    assert subtask.raw_result_json.get("backfill_parse_status") == "pending"
    assert subtask.raw_result_json.get("_pending_parse_job_id") == "job-current"


def test_post_apply_new_pending_not_wiped_by_ok_commit(db_session, monkeypatch) -> None:
    """apply 提交后若用户已重提新 pending，旧路径不得再二次 commit 抹掉。"""
    import app.services.snapshot_backfill_service as svc

    task = GeoMonitorTask(
        task_id="task-wipe",
        tenant_id=None,
        monitor_keywords="品牌A",
        status="completed",
        prompts_json=["问题"],
        platforms_json=[{"platform": "deepseek", "mode": "standard", "screenshot": 1}],
        raw_request_json={},
        raw_response_json={},
    )
    subtask = GeoMonitorSubtask(
        subtask_id="st-wipe",
        task_id="task-wipe",
        platform="deepseek",
        mode="standard",
        prompt="问题",
        status="failed",
        raw_result_json={
            "backfill_parse_status": "pending",
            "snapshot_url": "https://chat.deepseek.com/share/abc",
            "_pending_operator_user_id": 1,
            "_pending_parse_job_id": "job-old",
            "backfill_parse_enqueue": "queued",
        },
    )
    task.subtasks = [subtask]
    db_session.add(task)
    db_session.commit()

    monkeypatch.setattr(
        "app.services.share_page_fetch_service.fetch_share_page_browser_combined",
        lambda url, *, subtask_id=None, timeout_ms=120000: (
            SharePageFetchResult(
                answer_content="1. 品牌A\n正文",
                references=[],
                title="t",
                source_host="deepseek.com",
            ),
            None,
        ),
    )
    monkeypatch.setattr(
        "app.services.snapshot_backfill_service.enqueue_backfill_screenshot",
        lambda **kwargs: "queued",
    )
    monkeypatch.setattr(
        "app.services.monitor_stats_service.refresh_stats_after_subtask_backfill",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "app.services.monitor_service.invalidate_monitor_summary_cache",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "app.services.lead_diagnosis_service.refresh_lead_diagnosis_after_backfill",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "app.services.snapshot_backfill_service._bust_snapshot_backfill_matrix_cache",
        lambda: None,
    )
    monkeypatch.setattr(
        "app.services.snapshot_backfill_service.resolve_subtask_backfill_notification",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "app.services.snapshot_backfill_service._snapshot_backfill_log_description",
        lambda *a, **k: "补录",
    )
    monkeypatch.setattr(
        "app.services.snapshot_backfill_service.get_brand_asset",
        lambda db, tid: None,
    )
    monkeypatch.setattr(
        "app.services.snapshot_backfill_service.list_keyword_groups",
        lambda db, tid: [],
    )
    monkeypatch.setattr(
        "app.services.snapshot_backfill_service._operator_session_from_raw",
        lambda db, raw: SimpleNamespace(
            user=SimpleNamespace(id=1, display_name="ops", username="ops"),
            identity=SimpleNamespace(
                id=1,
                identity_type="PLATFORM",
                identity_name="ops",
                tenant_id=None,
                position_id=None,
            ),
        ),
    )

    real_apply = svc._apply_share_fetched_backfill

    def _apply_then_requeue(*args, **kwargs):
        out = real_apply(*args, **kwargs)
        db_session.refresh(subtask)
        raw = dict(subtask.raw_result_json or {})
        raw["backfill_parse_status"] = "pending"
        raw["_pending_parse_job_id"] = "job-new"
        raw["backfill_parse_enqueue"] = "queued"
        raw["_pending_parse_started_at"] = datetime.now(UTC).isoformat()
        subtask.raw_result_json = raw
        db_session.commit()
        return out

    monkeypatch.setattr(svc, "_apply_share_fetched_backfill", _apply_then_requeue)

    result = run_async_backfill_parse(db_session, "st-wipe", parse_job_id="job-old")
    assert result.get("status") == "ok"
    db_session.refresh(subtask)
    assert subtask.raw_result_json.get("_pending_parse_job_id") == "job-new"
    assert subtask.raw_result_json.get("backfill_parse_status") == "pending"
    assert (subtask.answer_content or "").strip()


def test_display_stale_later_than_retry_stale() -> None:
    from app.services.snapshot_backfill_service import (
        _backfill_parse_display_stale,
        _backfill_parse_pending_stale,
    )

    mid = {
        "backfill_parse_status": "pending",
        "backfill_parse_enqueue": "queued",
        "_pending_parse_started_at": (datetime.now(UTC) - timedelta(seconds=200)).isoformat(),
    }
    assert _backfill_parse_pending_stale(mid) is True
    assert _backfill_parse_display_stale(mid) is False
