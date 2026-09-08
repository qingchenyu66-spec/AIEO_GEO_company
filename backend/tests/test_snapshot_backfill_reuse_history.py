"""历史成功场次复用补录。"""

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.lead_diagnosis import LeadDiagnosisRun
from app.models.monitor import GeoMonitorSubtask, GeoMonitorTask
from app.models.ops import OperationLog
from app.services.monitor_service import serialize_subtask
from app.services.snapshot_backfill_service import (
    apply_snapshot_backfill,
    list_snapshot_backfill_history_candidates,
)


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(
        bind=engine,
        tables=[
            GeoMonitorTask.__table__,
            GeoMonitorSubtask.__table__,
            OperationLog.__table__,
            LeadDiagnosisRun.__table__,
        ],
    )
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def _platform_current():
    return SimpleNamespace(
        identity=SimpleNamespace(
            identity_type="PLATFORM",
            tenant_id=None,
            id=1,
            identity_name="运营测试",
            position_id=None,
        ),
        user=SimpleNamespace(id=1, display_name="运营测试", username="ops_test"),
    )


def _patch_getters(monkeypatch, db):
    monkeypatch.setattr(
        "app.services.snapshot_backfill_service.get_monitor_subtask",
        lambda _db, sid, _c: _db.scalar(select(GeoMonitorSubtask).where(GeoMonitorSubtask.subtask_id == sid)),
    )
    monkeypatch.setattr(
        "app.services.snapshot_backfill_service.get_monitor_task",
        lambda _db, tid, _c: _db.scalar(select(GeoMonitorTask).where(GeoMonitorTask.task_id == tid)),
    )
    monkeypatch.setattr(
        "app.services.snapshot_backfill_service.write_operation_log",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "app.services.snapshot_backfill_service.resolve_subtask_backfill_notification",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "app.services.snapshot_backfill_service._bust_snapshot_backfill_matrix_cache",
        lambda: None,
    )
    monkeypatch.setattr(
        "app.services.snapshot_backfill_service.build_backfill_notification_context",
        lambda *_a, **_k: {"schedule_label": "8月20日 09:00", "schedule_window_key": "20260820-0900"},
    )
    monkeypatch.setattr(
        "app.services.lead_diagnosis_service.refresh_lead_diagnosis_after_backfill",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "app.services.monitor_stats_service.refresh_stats_after_subtask_backfill",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "app.services.monitor_service.invalidate_monitor_summary_cache",
        lambda *_a, **_k: None,
    )


def test_list_history_candidates_same_prompt_platform(db_session, monkeypatch) -> None:
    _patch_getters(monkeypatch, db_session)
    src_task = GeoMonitorTask(
        task_id="task-src",
        tenant_id=91,
        monitor_keywords="品牌A",
        status="completed",
        total_items=1,
        completed_items=1,
        failed_items=0,
        prompts_json=["同词问题"],
        platforms_json=[{"platform": "doubao", "mode": "standard"}],
        raw_request_json={},
        raw_response_json={},
    )
    dst_task = GeoMonitorTask(
        task_id="task-dst",
        tenant_id=91,
        monitor_keywords="品牌A",
        status="failed",
        total_items=1,
        completed_items=0,
        failed_items=1,
        prompts_json=["同词问题"],
        platforms_json=[{"platform": "doubao", "mode": "standard"}],
        raw_request_json={},
        raw_response_json={},
    )
    src = GeoMonitorSubtask(
        subtask_id="st-src",
        task_id="task-src",
        platform="doubao",
        mode="standard",
        prompt="同词问题",
        status="completed",
        answer_content="历史成功正文一二三",
        mention_position=2,
        page_screenshot="/data/shot.png",
        raw_result_json={"source": "remote"},
    )
    mobile = GeoMonitorSubtask(
        subtask_id="st-mobile",
        task_id="task-src",
        platform="doubao_mobile",
        mode="standard",
        prompt="同词问题",
        status="completed",
        answer_content="手机端成功不该出现在PC候选",
        mention_position=1,
        raw_result_json={"source": "remote"},
    )
    chained = GeoMonitorSubtask(
        subtask_id="st-chain",
        task_id="task-src",
        platform="doubao",
        mode="standard",
        prompt="同词问题",
        status="completed",
        answer_content="也是复用出来的",
        mention_position=1,
        raw_result_json={"_ops_reuse_from": {"source_subtask_id": "x"}},
    )
    dst = GeoMonitorSubtask(
        subtask_id="st-dst",
        task_id="task-dst",
        platform="doubao",
        mode="standard",
        prompt="同词问题",
        status="failed",
        answer_content=None,
        raw_result_json={},
    )
    src_task.subtasks = [src, mobile, chained]
    dst_task.subtasks = [dst]
    db_session.add_all([src_task, dst_task])
    db_session.commit()

    items = list_snapshot_backfill_history_candidates(
        db_session, subtask_id="st-dst", current=_platform_current()
    )
    ids = [row["subtask_id"] for row in items]
    assert ids == ["st-src"]
    assert "st-mobile" not in ids


def test_reuse_history_copies_content_and_keeps_ops_meta(db_session, monkeypatch) -> None:
    _patch_getters(monkeypatch, db_session)
    src_task = GeoMonitorTask(
        task_id="task-src2",
        tenant_id=None,
        monitor_keywords="品牌B",
        status="completed",
        total_items=1,
        completed_items=1,
        failed_items=0,
        prompts_json=["问题复用"],
        platforms_json=[{"platform": "kimi", "mode": "standard"}],
        raw_request_json={},
        raw_response_json={},
    )
    dst_task = GeoMonitorTask(
        task_id="task-dst2",
        tenant_id=None,
        monitor_keywords="品牌B",
        status="failed",
        total_items=1,
        completed_items=0,
        failed_items=1,
        prompts_json=["问题复用"],
        platforms_json=[{"platform": "kimi", "mode": "standard"}],
        raw_request_json={},
        raw_response_json={},
    )
    src_refs = [{"url": "https://example.com/a", "title": "信源A"}]
    src_cites = [{"url": "https://example.com/b", "title": "引用B"}]
    src_all = [{"name": "品牌B", "rank": 3}, {"name": "竞品X", "rank": 1}]
    src_comp = [{"name": "竞品X", "rank": 1}, {"name": "竞品Y", "rank": 2}]
    src_qs = [{"text": "还想了解什么？"}]
    src = GeoMonitorSubtask(
        subtask_id="st-src2",
        task_id="task-src2",
        platform="kimi",
        mode="standard",
        prompt="问题复用",
        status="completed",
        answer_content="源正文内容，品牌B排第三",
        mention_position=3,
        mention_context="品牌B 排在第三",
        page_screenshot="/shot/src.png",
        sentiment="positive",
        reference_list_json=src_refs,
        citation_list_json=src_cites,
        all_rankings_json=src_all,
        competitor_rankings_json=src_comp,
        recommended_questions_json=src_qs,
        raw_result_json={"source": "remote"},
    )
    dst = GeoMonitorSubtask(
        subtask_id="st-dst2",
        task_id="task-dst2",
        platform="kimi",
        mode="standard",
        prompt="问题复用",
        status="failed",
        answer_content=None,
        page_screenshot=None,
        mention_position=None,
        reference_list_json=None,
        citation_list_json=None,
        all_rankings_json=None,
        competitor_rankings_json=None,
        recommended_questions_json=None,
        raw_result_json={},
    )
    src_task.subtasks = [src]
    dst_task.subtasks = [dst]
    db_session.add_all([src_task, dst_task])
    db_session.commit()

    result = apply_snapshot_backfill(
        db_session,
        subtask_id="st-dst2",
        reuse_from_subtask_id="st-src2",
        current=_platform_current(),
    )
    assert result.get("reuse_history") is True
    assert dst.answer_content == "源正文内容，品牌B排第三"
    assert dst.page_screenshot == "/shot/src.png"
    assert dst.mention_position == 3
    assert dst.mention_context == "品牌B 排在第三"
    assert dst.sentiment == "positive"
    assert dst.status == "completed"
    assert dst.reference_list_json == src_refs
    assert dst.citation_list_json == src_cites
    assert dst.competitor_rankings_json == src_comp
    assert dst.recommended_questions_json == src_qs
    # all_rankings 至少保留源结构（normalize 可能微调形态，但品牌位次仍在）
    assert isinstance(dst.all_rankings_json, list)
    assert any(str(item.get("name") or "") == "品牌B" for item in dst.all_rankings_json)
    raw = dst.raw_result_json or {}
    assert raw.get("source") == "manual_snapshot"
    assert raw["_ops_reuse_from"]["source_subtask_id"] == "st-src2"
    assert raw.get("manual_rank_locked") is True

    display = serialize_subtask(dst)
    assert "_ops_reuse_from" not in (display.get("raw_result") or {})
    assert display.get("mention_position") == 3
    assert display.get("reference_list")
    assert display.get("competitor_rankings") == src_comp


def test_reuse_rejects_chained_source(db_session, monkeypatch) -> None:
    _patch_getters(monkeypatch, db_session)
    task = GeoMonitorTask(
        task_id="task-chain",
        tenant_id=None,
        monitor_keywords="品牌C",
        status="failed",
        total_items=2,
        completed_items=1,
        failed_items=1,
        prompts_json=["链"],
        platforms_json=[{"platform": "doubao", "mode": "standard"}],
        raw_request_json={},
        raw_response_json={},
    )
    src = GeoMonitorSubtask(
        subtask_id="st-chained-src",
        task_id="task-chain",
        platform="doubao",
        mode="standard",
        prompt="链",
        status="completed",
        answer_content="复用过的",
        raw_result_json={"_ops_reuse_from": {"source_subtask_id": "old"}},
    )
    dst = GeoMonitorSubtask(
        subtask_id="st-chained-dst",
        task_id="task-chain",
        platform="doubao",
        mode="standard",
        prompt="链",
        status="failed",
        answer_content=None,
        raw_result_json={},
    )
    task.subtasks = [src, dst]
    db_session.add(task)
    db_session.commit()

    with pytest.raises(ValueError, match="不能再选用"):
        apply_snapshot_backfill(
            db_session,
            subtask_id="st-chained-dst",
            reuse_from_subtask_id="st-chained-src",
            current=_platform_current(),
        )
