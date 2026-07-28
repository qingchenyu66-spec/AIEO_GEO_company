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
    # 尚未自动重试：不进补录
    assert subtask_needs_snapshot_backfill(subtask) is False
    subtask.auto_retry_count = 1
    subtask.auto_retry_status = "pending"
    assert subtask_needs_snapshot_backfill(subtask) is False
    subtask.auto_retry_status = "failed"
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
        mention_position=2,
        raw_result_json={},
    )
    assert subtask_needs_snapshot_backfill(subtask) is False


def test_subtask_needs_snapshot_backfill_when_rank_after_top3() -> None:
    subtask = GeoMonitorSubtask(
        subtask_id="st-rank4",
        task_id="task-1",
        platform="doubao_mobile",
        mode="standard",
        prompt="测试问题",
        status="completed",
        answer_content="品牌出现在第四",
        mention_position=4,
        raw_result_json={},
    )
    assert subtask_needs_snapshot_backfill(subtask) is True
    assert subtask_backfill_eligible(subtask, pending_only=True) is True


def test_subtask_needs_snapshot_backfill_uses_effective_display_rank() -> None:
    """库内 raw 差，但展示位次已是 Top3 时不应标待补录。"""
    subtask = GeoMonitorSubtask(
        subtask_id="st-raw7",
        task_id="task-1",
        platform="doubao_mobile",
        mode="standard",
        prompt="测试问题",
        status="completed",
        answer_content="已有回答",
        mention_position=7,
        raw_result_json={},
    )
    assert subtask_needs_snapshot_backfill(subtask) is True
    assert subtask_needs_snapshot_backfill(subtask, effective_rank=2, use_effective_rank=True) is False
    assert subtask_needs_snapshot_backfill(subtask, effective_rank=3, use_effective_rank=True) is False
    assert subtask_needs_snapshot_backfill(subtask, effective_rank=4, use_effective_rank=True) is True
    # 无位次 / 未提及：一律待补录（仅前三放过）
    assert subtask_needs_snapshot_backfill(subtask, effective_rank=None, use_effective_rank=True) is True
    assert (
        subtask_needs_snapshot_backfill(
            subtask, effective_rank=None, use_effective_rank=True, brand_mentioned=False
        )
        is True
    )


def test_notify_failed_subtasks_for_task_creates_single_notification(db_session) -> None:
    tenant = Tenant(name="艾迪亚", code="aidya", owner_user_id=88)
    db_session.add(tenant)
    db_session.flush()
    task = GeoMonitorTask(
        task_id="task-1",
        tenant_id=tenant.id,
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
        auto_retry_count=1,
        auto_retry_status="failed",
    )
    task.subtasks = [subtask]
    db_session.add(task)
    db_session.commit()

    count = notify_failed_subtasks_for_task(db_session, task)
    assert count == 1
    row = db_session.query(SystemNotification).one()
    assert row.category == "snapshot_backfill"
    assert row.source_key.startswith("backfill:batch:")
    assert row.title.startswith("待补录 · ")
    assert "待补录1条" in row.message
    import json

    payload = json.loads(row.payload_json or "{}")
    assert payload.get("owner_user_id") == 88
    assert payload.get("period") not in {"早", "午", "晚"}
    assert "st-fail-1" in (payload.get("subtask_ids") or [])


def test_notify_weak_rank_uses_rank_title(db_session, monkeypatch) -> None:
    """不依赖解析器：直接锁展示位次路径，验证标题与 owner。"""
    from app.services import snapshot_backfill_service as svc

    tenant = Tenant(name="测试企业", code="t-weak", owner_user_id=9)
    db_session.add(tenant)
    db_session.flush()
    task = GeoMonitorTask(
        task_id="task-weak",
        tenant_id=tenant.id,
        monitor_keywords="测试品牌",
        status="completed",
        total_items=1,
        completed_items=1,
        failed_items=0,
        prompts_json=["弱排名"],
        platforms_json=[{"platform": "doubao", "mode": "standard", "screenshot": 1}],
        raw_request_json={},
        raw_response_json={},
    )
    subtask = GeoMonitorSubtask(
        subtask_id="st-weak",
        task_id="task-weak",
        platform="doubao",
        mode="standard",
        prompt="弱排名",
        status="completed",
        answer_content="测试品牌在列表第五",
        mention_position=5,
        raw_result_json={},
    )
    task.subtasks = [subtask]
    db_session.add(task)
    db_session.commit()

    def _fake_item(db, st, tk, **kwargs):
        return {
            "subtask_id": st.subtask_id,
            "tenant_id": tk.tenant_id,
            "tenant_name": "测试企业",
            "brand_name": None,
            "owner_user_id": 9,
            "mention_position": 5,
            "needs_backfill": True,
            "has_answer": True,
            "platform": st.platform,
            "prompt": st.prompt,
        }

    monkeypatch.setattr(svc, "build_snapshot_backfill_item", _fake_item)
    assert notify_failed_subtasks_for_task(db_session, task) == 1
    row = db_session.query(SystemNotification).one()
    assert row.title == "待补录 · 测试企业"
    assert "待补录1条" in row.message
    import json

    assert json.loads(row.payload_json or "{}").get("owner_user_id") == 9


def test_matrix_cell_has_todo_rules() -> None:
    from app.services.snapshot_backfill_service import matrix_cell_has_todo

    assert matrix_cell_has_todo(ranks=[], sample_count=0) is False
    assert matrix_cell_has_todo(ranks=[], sample_count=2) is True  # 算不出均值也标红
    assert matrix_cell_has_todo(ranks=[1.0, 2.0, 3.0], sample_count=3) is False
    assert matrix_cell_has_todo(ranks=[1.0, 5.0, 6.0], sample_count=3) is True
    assert matrix_cell_has_todo(ranks=[4.0], sample_count=1) is True


def test_schedule_period_bucket() -> None:
    from app.services.snapshot_backfill_service import parse_schedule_slot, schedule_period_bucket

    assert parse_schedule_slot("20260728-0430") == ("20260728-0430", "2026-07-28 04:30")
    assert parse_schedule_slot("20260728-0930") == ("20260728-0930", "2026-07-28 09:30")
    assert parse_schedule_slot("20260728-1430") == ("20260728-1430", "2026-07-28 14:30")
    assert parse_schedule_slot(None, "2026-07-28 09:30") == ("20260728-0930", "2026-07-28 09:30")
    # 兼容旧名：现返回具体时刻
    assert schedule_period_bucket("20260728-0430") == "2026-07-28 04:30"
    subtask = GeoMonitorSubtask(
        subtask_id="st-done",
        task_id="task-1",
        platform="doubao_mobile",
        mode="standard",
        prompt="测试问题",
        status="completed",
        answer_content="已有回答",
        mention_position=2,
        raw_result_json={},
    )
    assert subtask_needs_snapshot_backfill(subtask) is False
    assert subtask_backfill_eligible(subtask, pending_only=False) is True
    assert subtask_backfill_eligible(subtask, pending_only=True) is False


def test_subtask_needs_backfill_when_answer_without_rank() -> None:
    """有回答但无排名（库内位次空）应进待补录。"""
    subtask = GeoMonitorSubtask(
        subtask_id="st-norank",
        task_id="task-1",
        platform="doubao_mobile",
        mode="standard",
        prompt="测试问题",
        status="completed",
        answer_content="已有回答但未解析出位次",
        mention_position=None,
        raw_result_json={},
    )
    assert subtask_needs_snapshot_backfill(subtask) is True
    assert subtask_backfill_eligible(subtask, pending_only=True) is True


def test_apply_snapshot_backfill_overwrites_answer(db_session, monkeypatch) -> None:
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

    from app.services.share_page_fetch_service import SharePageFetchResult

    def _fake_fetch(url: str, **kwargs):
        return SharePageFetchResult(
            answer_content="1. 分众传媒\n2. 艾迪亚\n3. 新潮传媒",
            references=[
                {
                    "index": 1,
                    "url": "https://example.com/a",
                    "title": "示例信源",
                    "site": "example.com",
                }
            ],
            title="fake",
            source_host="doubao.com",
        )

    monkeypatch.setattr(
        "app.services.snapshot_backfill_service.fetch_share_page",
        _fake_fetch,
    )
    result = apply_snapshot_backfill(
        db_session,
        subtask_id="st-backfill",
        snapshot_url="https://www.doubao.com/thread/abc1234567890",
        current=current,
    )
    assert result["subtask"]["subtask_id"] == "st-backfill"
    assert subtask.answer_content.startswith("1.")
    assert subtask.reference_list_json and subtask.reference_list_json[0]["url"].startswith("https://example.com")
    assert subtask.raw_result_json.get("source") == "manual_snapshot"
    assert subtask.raw_result_json.get("manual_rank_locked") is False
    assert subtask.raw_result_json.get("fetch_reference_count") == 1

    log = db_session.scalar(
        select(OperationLog).where(OperationLog.action_type == "快照覆盖").order_by(OperationLog.id.desc())
    )
    assert log is not None
    assert log.target_module == "快照补录"
    assert "问题A" in log.description
    assert "st-backfill" not in log.description
    assert log.operator_name == "运营测试"


def test_apply_snapshot_backfill_rank_only_keeps_snapshot(db_session, monkeypatch) -> None:
    from types import SimpleNamespace

    from sqlalchemy import select

    from app.models.ops import OperationLog
    from app.services.snapshot_backfill_service import apply_snapshot_backfill

    task = GeoMonitorTask(
        task_id="task-rank-only",
        monitor_keywords="品牌A",
        status="completed",
        total_items=1,
        completed_items=1,
        failed_items=0,
        prompts_json=["问题B"],
        platforms_json=[{"platform": "doubao", "mode": "standard", "screenshot": 1}],
        raw_request_json={},
        raw_response_json={},
    )
    subtask = GeoMonitorSubtask(
        subtask_id="st-rank-only",
        task_id="task-rank-only",
        platform="doubao",
        mode="standard",
        prompt="问题B",
        status="completed",
        answer_content="旧回答保留",
        page_screenshot="https://www.doubao.com/thread/keep-me",
        mention_position=8,
        raw_result_json={"source": "remote", "snapshot_url": "https://www.doubao.com/thread/keep-me"},
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

    def _should_not_fetch(*_args, **_kwargs):
        raise AssertionError("rank-only path must not fetch share page")

    monkeypatch.setattr(
        "app.services.snapshot_backfill_service.fetch_share_page",
        _should_not_fetch,
    )
    result = apply_snapshot_backfill(
        db_session,
        subtask_id="st-rank-only",
        snapshot_url=None,
        mention_position=2,
        current=current,
    )
    assert result.get("rank_only") is True
    assert subtask.answer_content == "旧回答保留"
    assert subtask.page_screenshot == "https://www.doubao.com/thread/keep-me"
    assert subtask.mention_position == 2
    assert subtask.raw_result_json.get("rank_only") is True
    assert subtask.raw_result_json.get("manual_rank_locked") is True

    log = db_session.scalar(
        select(OperationLog).where(OperationLog.action_type == "排名补录").order_by(OperationLog.id.desc())
    )
    assert log is not None
    assert log.target_module == "快照补录"


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
        mention_position=2,
        # 无结构化榜时展示位次会被对账清空；锁住以模拟已确认 Top3
        raw_result_json={"source": "manual_snapshot", "manual_rank_locked": True},
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
        auto_retry_count=1,
        auto_retry_status="failed",
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


def test_dismissed_subtask_excluded_from_eligible_and_list(db_session) -> None:
    from datetime import datetime

    from app.services.snapshot_backfill_service import subtask_backfill_dismissed

    tenant = Tenant(name="忽略企业", code="tenant-dismiss", deleted=False)
    db_session.add(tenant)
    db_session.flush()
    task = GeoMonitorTask(
        tenant_id=tenant.id,
        task_id="task-dismiss",
        monitor_keywords="品牌D",
        status="completed",
        total_items=1,
        completed_items=1,
        failed_items=0,
        prompts_json=["弱排名问题"],
        platforms_json=[{"platform": "doubao", "mode": "standard", "screenshot": 1}],
        raw_request_json={},
        raw_response_json={},
    )
    subtask = GeoMonitorSubtask(
        subtask_id="st-dismiss",
        task_id="task-dismiss",
        platform="doubao",
        mode="standard",
        prompt="弱排名问题",
        status="completed",
        answer_content="品牌D 排在后面",
        mention_position=8,
        raw_result_json={},
        backfill_dismissed_at=datetime(2026, 7, 17, 12, 0, 0),
        backfill_dismissed_by=1,
    )
    task.subtasks = [subtask]
    db_session.add(task)
    db_session.commit()

    assert subtask_backfill_dismissed(subtask) is True
    assert subtask_needs_snapshot_backfill(subtask) is True
    assert subtask_backfill_eligible(subtask, pending_only=True) is False
    assert subtask_backfill_eligible(subtask, pending_only=False) is False

    page = list_snapshot_backfill_page(db_session, tenant_id=tenant.id, pending_only=True, limit=10)
    assert page["summary"]["pending"] == 0
    assert page["items"] == []
    assert notify_failed_subtasks_for_task(db_session, task) == 0


def test_dismiss_and_undismiss_snapshot_backfill(db_session, monkeypatch) -> None:
    from types import SimpleNamespace

    from sqlalchemy import select

    from app.services.snapshot_backfill_service import (
        dismiss_snapshot_backfill,
        undismiss_snapshot_backfill,
    )

    tenant = Tenant(name="取消忽略企业", code="tenant-undismiss", deleted=False, owner_user_id=3)
    db_session.add(tenant)
    db_session.flush()
    task = GeoMonitorTask(
        tenant_id=tenant.id,
        task_id="task-undismiss",
        monitor_keywords="品牌U",
        status="failed",
        total_items=1,
        completed_items=0,
        failed_items=1,
        prompts_json=["失败问题"],
        platforms_json=[{"platform": "doubao", "mode": "standard", "screenshot": 1}],
        raw_request_json={},
        raw_response_json={},
    )
    subtask = GeoMonitorSubtask(
        subtask_id="st-undismiss",
        task_id="task-undismiss",
        platform="doubao",
        mode="standard",
        prompt="失败问题",
        status="failed",
        error_message="timeout",
        raw_result_json={},
        auto_retry_count=1,
        auto_retry_status="failed",
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
            role_code="PLATFORM_ADMIN",
        ),
        user=SimpleNamespace(id=1, display_name="运营测试", username="ops_test"),
    )

    def _fake_get_subtask(db, subtask_id, _current):
        return db.scalar(select(GeoMonitorSubtask).where(GeoMonitorSubtask.subtask_id == subtask_id))

    def _fake_get_task(db, task_id, _current):
        return db.scalar(select(GeoMonitorTask).where(GeoMonitorTask.task_id == task_id))

    monkeypatch.setattr("app.services.snapshot_backfill_service.get_monitor_subtask", _fake_get_subtask)
    monkeypatch.setattr("app.services.snapshot_backfill_service.get_monitor_task", _fake_get_task)

    assert notify_failed_subtasks_for_task(db_session, task) == 1
    assert db_session.query(SystemNotification).count() == 1

    dismissed = dismiss_snapshot_backfill(db_session, subtask_id="st-undismiss", current=current)
    assert dismissed["backfill_dismissed"] is True
    assert subtask.backfill_dismissed_at is not None
    assert subtask.answer_content is None
    assert db_session.query(SystemNotification).count() == 0
    log = db_session.scalar(select(OperationLog).where(OperationLog.action_type == "忽略补录"))
    assert log is not None
    assert log.target_module == "快照补录"
    assert "st-undismiss" in log.description

    page = list_snapshot_backfill_page(db_session, tenant_id=tenant.id, pending_only=True, limit=10)
    assert page["summary"]["pending"] == 0

    restored = undismiss_snapshot_backfill(db_session, subtask_id="st-undismiss", current=current)
    assert restored["backfill_dismissed"] is False
    assert subtask.backfill_dismissed_at is None
    assert restored["item"]["needs_backfill"] is True
    assert db_session.query(SystemNotification).count() == 1
    undo_log = db_session.scalar(select(OperationLog).where(OperationLog.action_type == "取消忽略补录"))
    assert undo_log is not None

    page2 = list_snapshot_backfill_page(db_session, tenant_id=tenant.id, pending_only=True, limit=10)
    assert page2["summary"]["pending"] == 1
    assert page2["items"][0]["subtask_id"] == "st-undismiss"
