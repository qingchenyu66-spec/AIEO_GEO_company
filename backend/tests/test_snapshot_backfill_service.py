"""Tests for snapshot backfill service."""

from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.lead_diagnosis import LeadDiagnosis, LeadDiagnosisRun
from app.models.monitor import GeoMonitorScheduleRun, GeoMonitorSubtask, GeoMonitorTask
from app.models.notification import SystemNotification, SystemNotificationRead
from app.models.ops import OperationLog
from app.models.tenant import Tenant
from app.services.monitor_service import subtask_needs_snapshot_backfill
from app.services.snapshot_backfill_service import (
    list_snapshot_backfill_items,
    list_snapshot_backfill_page,
    notify_failed_subtasks_for_task,
    subtask_backfill_eligible,
    validate_snapshot_url,
)


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(
        bind=engine,
        tables=[
            Tenant.__table__,
            LeadDiagnosis.__table__,
            LeadDiagnosisRun.__table__,
            GeoMonitorTask.__table__,
            GeoMonitorSubtask.__table__,
            GeoMonitorScheduleRun.__table__,
            SystemNotification.__table__,
            SystemNotificationRead.__table__,
            OperationLog.__table__,
        ],
    )
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def test_validate_snapshot_url_accepts_doubao_thread() -> None:
    url = "https://www.doubao.com/thread/xd4f2cd8525a78a05b8033361a6cb58e0"
    assert validate_snapshot_url(url, platform="doubao_mobile") == url


def test_validate_snapshot_url_rejects_invalid_scheme() -> None:
    with pytest.raises(ValueError, match="http"):
        validate_snapshot_url("ftp://doubao.com/thread/abc")


def test_subtask_needs_snapshot_backfill_when_failed() -> None:
    subtask = GeoMonitorSubtask(
        subtask_id="st-1",
        task_id="task-1",
        platform="doubao_mobile",
        mode="standard",
        prompt="测试问题",
        status="failed",
        raw_result_json={},
        error_message="timeout",
    )
    assert subtask_needs_snapshot_backfill(subtask) is True


def test_subtask_needs_snapshot_backfill_when_answer_present() -> None:
    subtask = GeoMonitorSubtask(
        subtask_id="st-2",
        task_id="task-1",
        platform="doubao_mobile",
        mode="standard",
        prompt="测试问题",
        status="completed",
        answer_content="已有回答",
        raw_result_json={},
    )
    assert subtask_needs_snapshot_backfill(subtask) is False


def test_notify_failed_subtasks_for_task_creates_single_notification(db_session) -> None:
    task = GeoMonitorTask(
        task_id="task-1",
        monitor_keywords="艾迪亚",
        status="partial_completed",
        total_items=1,
        completed_items=0,
        failed_items=1,
        prompts_json=["测试问题"],
        platforms_json=[{"platform": "doubao_mobile", "mode": "standard", "screenshot": 1}],
        raw_request_json={},
        raw_response_json={},
    )
    subtask = GeoMonitorSubtask(
        subtask_id="st-fail-1",
        task_id="task-1",
        platform="doubao_mobile",
        mode="standard",
        prompt="测试问题",
        status="failed",
        raw_result_json={},
        error_message="抓取失败",
    )
    task.subtasks = [subtask]
    db_session.add(task)
    db_session.commit()

    count = notify_failed_subtasks_for_task(db_session, task)
    assert count == 1
    row = db_session.query(SystemNotification).one()
    assert row.category == "snapshot_backfill"
    assert row.source_key == "subtask:backfill:st-fail-1"
    assert "doubao_mobile" in row.message


def test_subtask_backfill_eligible_includes_completed_with_answer() -> None:
    subtask = GeoMonitorSubtask(
        subtask_id="st-done",
        task_id="task-1",
        platform="doubao_mobile",
        mode="standard",
        prompt="测试问题",
        status="completed",
        answer_content="已有回答",
        raw_result_json={},
    )
    assert subtask_needs_snapshot_backfill(subtask) is False
    assert subtask_backfill_eligible(subtask, pending_only=False) is True
    assert subtask_backfill_eligible(subtask, pending_only=True) is False


def test_apply_snapshot_backfill_overwrites_answer(db_session) -> None:
    from types import SimpleNamespace

    from sqlalchemy import select

    from app.models.ops import OperationLog
    from app.services.snapshot_backfill_service import apply_snapshot_backfill

    task = GeoMonitorTask(
        task_id="task-backfill",
        monitor_keywords="品牌A",
        status="completed",
        total_items=1,
        completed_items=1,
        failed_items=0,
        prompts_json=["问题A"],
        platforms_json=[{"platform": "doubao", "mode": "standard", "screenshot": 1}],
        raw_request_json={},
        raw_response_json={},
    )
    subtask = GeoMonitorSubtask(
        subtask_id="st-backfill",
        task_id="task-backfill",
        platform="doubao",
        mode="standard",
        prompt="问题A",
        status="completed",
        answer_content="旧回答",
        raw_result_json={"source": "remote"},
    )
    task.subtasks = [subtask]
    db_session.add(task)
    db_session.commit()

    current = SimpleNamespace(
        identity=SimpleNamespace(
            identity_type="PLATFORM",
            tenant_id=None,
            id=1,
            identity_name="运营测试",
            position_id=None,
        ),
        user=SimpleNamespace(id=1, display_name="运营测试", username="ops_test"),
    )
    result = apply_snapshot_backfill(
        db_session,
        subtask_id="st-backfill",
        snapshot_url="https://www.doubao.com/thread/abc1234567890",
        answer_content="1. 分众传媒\n2. 艾迪亚\n3. 新潮传媒",
        current=current,
    )
    assert result["subtask"]["subtask_id"] == "st-backfill"
    assert subtask.answer_content.startswith("1.")
    assert subtask.raw_result_json.get("source") == "manual_snapshot"

    log = db_session.scalar(
        select(OperationLog).where(OperationLog.action_type == "快照覆盖").order_by(OperationLog.id.desc())
    )
    assert log is not None
    assert log.target_module == "快照补录"
    assert "问题A" in log.description
    assert "st-backfill" not in log.description
    assert log.operator_name == "运营测试"


def test_list_snapshot_backfill_items_filters_by_tenant_and_date(db_session) -> None:
    tenant_a = Tenant(name="企业A", code="tenant-a", deleted=False)
    tenant_b = Tenant(name="企业B", code="tenant-b", deleted=False)
    db_session.add_all([tenant_a, tenant_b])
    db_session.flush()

    task_a = GeoMonitorTask(
        tenant_id=tenant_a.id,
        task_id="task-a",
        monitor_keywords="品牌A",
        status="completed",
        total_items=1,
        completed_items=1,
        failed_items=0,
        prompts_json=["问题A"],
        platforms_json=[{"platform": "doubao_mobile", "mode": "standard", "screenshot": 1}],
        raw_request_json={},
        raw_response_json={},
        created_at=datetime(2026, 7, 2, 8, 0, 0),
    )
    task_b = GeoMonitorTask(
        tenant_id=tenant_b.id,
        task_id="task-b",
        monitor_keywords="品牌B",
        status="failed",
        total_items=1,
        completed_items=0,
        failed_items=1,
        prompts_json=["问题B"],
        platforms_json=[{"platform": "doubao_mobile", "mode": "standard", "screenshot": 1}],
        raw_request_json={},
        raw_response_json={},
        created_at=datetime(2026, 7, 3, 8, 0, 0),
    )
    done = GeoMonitorSubtask(
        subtask_id="st-a",
        task_id="task-a",
        platform="doubao_mobile",
        mode="standard",
        prompt="问题A",
        status="completed",
        answer_content="回答A",
        raw_result_json={},
        updated_at=datetime(2026, 7, 2, 10, 0, 0),
    )
    failed = GeoMonitorSubtask(
        subtask_id="st-b",
        task_id="task-b",
        platform="doubao_mobile",
        mode="standard",
        prompt="问题B",
        status="failed",
        raw_result_json={},
        error_message="抓取失败",
        updated_at=datetime(2026, 7, 3, 10, 0, 0),
    )
    task_a.subtasks = [done]
    task_b.subtasks = [failed]
    db_session.add_all([task_a, task_b])
    db_session.commit()

    tenant_rows = list_snapshot_backfill_items(db_session, tenant_id=tenant_a.id, limit=10)
    assert [item["subtask_id"] for item in tenant_rows] == ["st-a"]
    assert tenant_rows[0]["has_answer"] is True

    pending_rows = list_snapshot_backfill_items(
        db_session,
        pending_only=True,
        detect_date=datetime(2026, 7, 3).date(),
        limit=10,
    )
    assert [item["subtask_id"] for item in pending_rows] == ["st-b"]
    assert pending_rows[0]["needs_backfill"] is True

    empty_rows = list_snapshot_backfill_items(
        db_session,
        tenant_id=tenant_a.id,
        detect_date=datetime(2026, 7, 1).date(),
        limit=10,
    )
    assert empty_rows == []

    platform_rows = list_snapshot_backfill_items(
        db_session,
        tenant_id=tenant_a.id,
        platform="doubao_mobile",
        limit=10,
    )
    assert [item["subtask_id"] for item in platform_rows] == ["st-a"]
    assert platform_rows[0]["source"] == "tenant_monitor"

    all_page = list_snapshot_backfill_page(db_session, limit=10)
    assert all_page["summary"]["total"] == 2
    assert all_page["summary"]["pending"] == 1
    assert all_page["summary"]["overwrite"] == 1

    tenant_page = list_snapshot_backfill_page(db_session, tenant_id=tenant_a.id, limit=10)
    assert tenant_page["summary"]["total"] == 1
    assert tenant_page["summary"]["overwrite"] == 1
    assert tenant_page["summary"]["pending"] == 0
    assert tenant_page["summary"]["has_more"] is False

    page_one = list_snapshot_backfill_page(db_session, limit=1, offset=0)
    page_two = list_snapshot_backfill_page(db_session, limit=1, offset=1)
    assert page_one["summary"]["total"] == 2
    assert page_one["summary"]["has_more"] is True
    assert len(page_one["items"]) == 1
    assert len(page_two["items"]) == 1
    assert page_one["items"][0]["subtask_id"] != page_two["items"][0]["subtask_id"]


def test_list_snapshot_backfill_items_uses_schedule_run_label(db_session) -> None:
    """签约企业任务批次应来自 GeoMonitorScheduleRun（与实时监测一致）。"""
    tenant = Tenant(name="企业C", code="tenant-c", deleted=False)
    db_session.add(tenant)
    db_session.flush()

    task = GeoMonitorTask(
        tenant_id=tenant.id,
        task_id="task-schedule",
        monitor_keywords="品牌C",
        status="completed",
        total_items=1,
        completed_items=1,
        failed_items=0,
        prompts_json=["问题C"],
        platforms_json=[{"platform": "kimi", "mode": "standard", "screenshot": 1}],
        raw_request_json={},
        raw_response_json={},
        created_at=datetime(2026, 7, 1, 9, 35, 0),
    )
    subtask = GeoMonitorSubtask(
        subtask_id="st-schedule",
        task_id="task-schedule",
        platform="kimi",
        mode="standard",
        prompt="问题C",
        status="completed",
        answer_content="回答C",
        raw_result_json={},
        updated_at=datetime(2026, 7, 1, 9, 40, 0),
    )
    db_session.add(
        GeoMonitorScheduleRun(
            tenant_id=tenant.id,
            task_id="task-schedule",
            schedule_key="20260701-0930-kw1",
            status="completed",
        )
    )
    task.subtasks = [subtask]
    db_session.add(task)
    db_session.commit()

    rows = list_snapshot_backfill_items(
        db_session,
        tenant_id=tenant.id,
        detect_date=datetime(2026, 7, 1).date(),
        platform="kimi",
        limit=10,
    )
    assert len(rows) == 1
    assert rows[0]["schedule_label"] == "2026-07-01 09:30"
    assert rows[0]["source"] == "tenant_monitor"


def test_list_snapshot_backfill_items_includes_region_from_schedule_key(db_session) -> None:
    tenant = Tenant(name="企业E", code="tenant-e", deleted=False)
    db_session.add(tenant)
    db_session.flush()

    task = GeoMonitorTask(
        tenant_id=tenant.id,
        task_id="task-region",
        monitor_keywords="品牌E",
        status="completed",
        total_items=1,
        completed_items=1,
        failed_items=0,
        prompts_json=["郑州板材门店推荐"],
        platforms_json=[{"platform": "doubao", "mode": "standard", "screenshot": 1}],
        raw_request_json={},
        raw_response_json={},
        created_at=datetime(2026, 7, 8, 9, 35, 0),
    )
    subtask = GeoMonitorSubtask(
        subtask_id="st-region",
        task_id="task-region",
        platform="doubao",
        mode="standard",
        prompt="郑州板材门店推荐",
        status="completed",
        answer_content="回答E",
        raw_result_json={},
        updated_at=datetime(2026, 7, 8, 9, 40, 0),
    )
    db_session.add(
        GeoMonitorScheduleRun(
            tenant_id=tenant.id,
            task_id="task-region",
            schedule_key="20260708-0930-kw24-rg330000",
            status="submitted",
        )
    )
    task.subtasks = [subtask]
    db_session.add(task)
    db_session.commit()

    rows = list_snapshot_backfill_items(
        db_session,
        tenant_id=tenant.id,
        detect_date=datetime(2026, 7, 8).date(),
        platform="doubao",
        limit=10,
    )
    assert len(rows) == 1
    assert rows[0]["region_code"] == "330000"
    assert rows[0]["region_label"] == "浙江"
    assert rows[0]["schedule_key"] == "20260708-0930-kw24-rg330000"
    assert rows[0]["schedule_window_key"] == "20260708-0930"


def test_list_snapshot_backfill_items_filters_by_keyword(db_session) -> None:
    tenant = Tenant(name="企业D", code="tenant-d", deleted=False)
    db_session.add(tenant)
    db_session.flush()

    task = GeoMonitorTask(
        tenant_id=tenant.id,
        task_id="task-keyword",
        monitor_keywords="地铁广告",
        status="completed",
        total_items=2,
        completed_items=2,
        failed_items=0,
        prompts_json=["地铁广告公司推荐", "电梯广告公司推荐"],
        platforms_json=[{"platform": "kimi", "mode": "standard", "screenshot": 1}],
        raw_request_json={},
        raw_response_json={},
        created_at=datetime(2026, 7, 2, 9, 0, 0),
    )
    sub_a = GeoMonitorSubtask(
        subtask_id="st-kw-a",
        task_id="task-keyword",
        platform="kimi",
        mode="standard",
        prompt="地铁广告公司推荐",
        status="completed",
        answer_content="回答A",
        raw_result_json={},
    )
    sub_b = GeoMonitorSubtask(
        subtask_id="st-kw-b",
        task_id="task-keyword",
        platform="kimi",
        mode="standard",
        prompt="电梯广告公司推荐",
        status="completed",
        answer_content="回答B",
        raw_result_json={},
    )
    task.subtasks = [sub_a, sub_b]
    db_session.add(task)
    db_session.commit()

    rows = list_snapshot_backfill_items(db_session, tenant_id=tenant.id, keyword="地铁", limit=10)
    assert [item["subtask_id"] for item in rows] == ["st-kw-a"]

    empty = list_snapshot_backfill_items(db_session, tenant_id=tenant.id, keyword="公交", limit=10)
    assert empty == []
