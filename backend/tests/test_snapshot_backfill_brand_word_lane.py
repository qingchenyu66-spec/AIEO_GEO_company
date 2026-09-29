"""快照补录：品牌词分轨（方案 B）。"""
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.api.dependencies import CurrentSession
from app.core.database import SessionLocal
from app.models.monitor import GeoMonitorSubtask, GeoMonitorTask
from app.models.tenant import Tenant
from app.services.snapshot_backfill_service import (
    list_snapshot_backfill_history_candidates,
    list_snapshot_backfill_page,
)


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
        session.rollback()
    finally:
        session.close()


def _mk_task_subtask(db, *, tenant_id: int, purpose: str, prompt: str, platform: str = "kimi"):
    suffix = uuid4().hex[:10]
    task = GeoMonitorTask(
        task_id=f"bwbf-{purpose}-{suffix}",
        tenant_id=tenant_id,
        purpose=purpose,
        status="completed",
        monitor_keywords=prompt,
        total_items=1,
        completed_items=0,
        failed_items=1,
        prompts_json=[prompt],
        platforms_json=[{"platform": platform, "mode": "standard", "screenshot": 1}],
        raw_request_json={},
        raw_response_json={},
        deleted=False,
    )
    db.add(task)
    db.flush()
    sub = GeoMonitorSubtask(
        subtask_id=f"bwbf-st-{purpose}-{suffix}",
        task_id=task.task_id,
        platform=platform,
        mode="standard",
        prompt=prompt,
        status="failed",
        answer_content=None,
        error_message="mock fail",
        raw_result_json={},
        auto_retry_count=1,
        auto_retry_status="failed",
    )
    db.add(sub)
    db.flush()
    return task, sub


def test_backfill_page_purpose_lanes_isolate(db):
    # 2026-09-08 - 日常轨不含品牌词；品牌词轨不含 geo
    suffix = uuid4().hex[:8]
    tenant = Tenant(name="bw-lane", code=f"BWL{suffix}", status=True)
    db.add(tenant)
    db.flush()
    _mk_task_subtask(db, tenant_id=tenant.id, purpose="geo", prompt="日常问法")
    _mk_task_subtask(db, tenant_id=tenant.id, purpose="brand_word", prompt="品牌词问法")
    db.flush()

    geo_page = list_snapshot_backfill_page(
        db, tenant_id=tenant.id, purpose="geo", pending_only=True, limit=50, include_summary=False
    )
    bw_page = list_snapshot_backfill_page(
        db, tenant_id=tenant.id, purpose="brand_word", pending_only=True, limit=50, include_summary=False
    )
    geo_prompts = {str(item.get("prompt") or "") for item in (geo_page.get("items") or [])}
    bw_prompts = {str(item.get("prompt") or "") for item in (bw_page.get("items") or [])}
    assert "日常问法" in geo_prompts
    assert "品牌词问法" not in geo_prompts
    assert "品牌词问法" in bw_prompts
    assert "日常问法" not in bw_prompts


def test_history_candidates_scoped_by_purpose(db, monkeypatch):
    from app.services import snapshot_backfill_service as mod

    suffix = uuid4().hex[:8]
    tenant = Tenant(name="bw-hist", code=f"BWH{suffix}", status=True)
    db.add(tenant)
    db.flush()
    prompt = f"同问法-{suffix}"
    platform = "kimi"
    _geo_task, geo_ok = _mk_task_subtask(db, tenant_id=tenant.id, purpose="geo", prompt=prompt, platform=platform)
    geo_ok.status = "completed"
    geo_ok.answer_content = "geo answer body"
    geo_ok.error_message = None
    bw_task, bw_target = _mk_task_subtask(db, tenant_id=tenant.id, purpose="brand_word", prompt=prompt, platform=platform)
    _bw_ok_task, bw_ok = _mk_task_subtask(db, tenant_id=tenant.id, purpose="brand_word", prompt=prompt, platform=platform)
    bw_ok.status = "completed"
    bw_ok.answer_content = "brand word answer"
    bw_ok.error_message = None
    db.flush()

    current = CurrentSession(
        user=SimpleNamespace(id=1, username="ops"),
        identity=SimpleNamespace(id=1, identity_type="PLATFORM", tenant_id=None, user_id=1),
    )
    monkeypatch.setattr(mod, "get_monitor_subtask", lambda *_a, **_k: bw_target)
    monkeypatch.setattr(mod, "get_monitor_task", lambda *_a, **_k: bw_task)

    rows = list_snapshot_backfill_history_candidates(db, subtask_id=bw_target.subtask_id, current=current)
    ids = {row["subtask_id"] for row in rows}
    assert bw_ok.subtask_id in ids
    assert geo_ok.subtask_id not in ids
