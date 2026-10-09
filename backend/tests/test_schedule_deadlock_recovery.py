"""方案 C：死锁重试类型、陈旧 running 复用、回收扫描。"""

from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError as SQLOperationalError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.celery_app import celery_app
from app.core.database import Base
from app.models.monitor import GeoMonitorScheduleRun
from app.services.schedule_service import (
    SCHEDULE_RUN_STALE_RUNNING_MINUTES,
    _SCHEDULE_TRANSIENT_ERRORS,
    DueScheduleGroup,
    due_item_from_group_key,
    list_recoverable_schedule_runs,
    mark_schedule_group_skipped,
    parse_schedule_group_key,
    register_schedule_group_plan,
    schedule_run_blocks_due,
)


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine, tables=[GeoMonitorScheduleRun.__table__])
    return sessionmaker(bind=engine)()


def test_transient_errors_include_sqlalchemy_operational():
    # 2026-09-07 - 死锁必须可重试；只抓 kombu 会留尸
    assert SQLOperationalError in _SCHEDULE_TRANSIENT_ERRORS


def test_parse_schedule_group_key_with_region():
    schedule_key, region = parse_schedule_group_key("20260905-1518-kw62-rg110000")
    assert schedule_key == "20260905-1518"
    assert region == "110000"
    item = due_item_from_group_key(tenant_id=1, group_key="20260905-1518-kw62-rg110000")
    assert item.region_code == "110000"
    assert item.schedule_key == "20260905-1518"


def test_stale_running_recoverable_and_old_cleanup() -> None:
    db_session = _session()
    try:
        now = datetime.now()
        stale = now - timedelta(minutes=SCHEDULE_RUN_STALE_RUNNING_MINUTES + 5)
        recent = GeoMonitorScheduleRun(
            tenant_id=1,
            schedule_key="20260906-0804-kw38",
            status="running",
            prompt_count=5,
            platform_count=1,
        )
        pending = GeoMonitorScheduleRun(
            tenant_id=1,
            schedule_key="bw20260906-0900-kw39",
            status="pending",
            prompt_count=0,
            platform_count=0,
        )
        old = GeoMonitorScheduleRun(
            tenant_id=1,
            schedule_key="20260729-0040-kw38-rg110000",
            status="running",
            prompt_count=6,
            platform_count=1,
        )
        permanent_fail = GeoMonitorScheduleRun(
            tenant_id=2,
            schedule_key="20260906-0900-kw1",
            status="failed",
            prompt_count=1,
            platform_count=1,
            error_message="算力不足，请联系销售充值",
        )
        deadlock_fail = GeoMonitorScheduleRun(
            tenant_id=2,
            schedule_key="20260906-0900-kw2",
            status="failed",
            prompt_count=1,
            platform_count=1,
            error_message="(pymysql.err.OperationalError) (1213, 'Deadlock found when trying to get lock')",
        )
        busy_fail = GeoMonitorScheduleRun(
            tenant_id=3,
            schedule_key="20260906-0900-kw3",
            status="failed",
            prompt_count=1,
            platform_count=1,
            error_message="企业 119 正在提交其他监测词组",
        )
        db_session.add_all([recent, pending, old, permanent_fail, deadlock_fail, busy_fail])
        db_session.flush()
        recent.created_at = now - timedelta(days=1)
        recent.updated_at = stale
        pending.created_at = now - timedelta(days=1)
        pending.updated_at = stale
        old.created_at = now - timedelta(days=40)
        old.updated_at = stale
        permanent_fail.created_at = now - timedelta(days=1)
        permanent_fail.updated_at = stale
        deadlock_fail.created_at = now - timedelta(days=1)
        deadlock_fail.updated_at = stale
        busy_fail.created_at = now - timedelta(days=1)
        busy_fail.updated_at = stale
        db_session.commit()

        resubmit, cleanup = list_recoverable_schedule_runs(db_session, now=now)
        resubmit_keys = {row.schedule_key for row in resubmit}
        cleanup_keys = {row.schedule_key for row in cleanup}
        assert "20260906-0804-kw38" in resubmit_keys
        assert "bw20260906-0900-kw39" in resubmit_keys
        assert "20260906-0900-kw2" in resubmit_keys
        assert "20260906-0900-kw3" in resubmit_keys
        assert "20260906-0900-kw1" not in resubmit_keys
        assert "20260729-0040-kw38-rg110000" in cleanup_keys
        assert schedule_run_blocks_due(recent, now=now) is False
    finally:
        db_session.close()


def test_stale_schedule_beat_registered():
    beat = celery_app.conf.beat_schedule or {}
    assert beat["scan-stale-schedule-submits"]["task"] == "app.tasks.monitor.scan_stale_schedule_submits"


def test_register_schedule_group_plan_records_whole_batch() -> None:
    db_session = _session()
    try:
        items = [
            DueScheduleGroup(
                tenant_id=7,
                schedule_key="bw20261005-0900",
                group_key=f"bw20261005-0900-kw{index}",
                max_prompts=10,
            )
            for index in (1, 2)
        ]
        assert register_schedule_group_plan(db_session, items) == 2
        rows = list(db_session.query(GeoMonitorScheduleRun).all())
        assert {row.status for row in rows} == {"pending"}
        assert {row.schedule_key for row in rows} == {
            "bw20261005-0900-kw1",
            "bw20261005-0900-kw2",
        }
        assert register_schedule_group_plan(db_session, items) == 0
    finally:
        db_session.close()


def test_skipped_planned_group_is_not_recovered_forever() -> None:
    db_session = _session()
    try:
        item = DueScheduleGroup(
            tenant_id=8,
            schedule_key="bw20261005-0900",
            group_key="bw20261005-0900-kw1",
            max_prompts=10,
        )
        register_schedule_group_plan(db_session, [item])
        mark_schedule_group_skipped(
            db_session,
            tenant_id=item.tenant_id,
            group_key=item.group_key,
            message="监测未配置完整",
        )
        row = db_session.query(GeoMonitorScheduleRun).one()
        row.updated_at = datetime.now() - timedelta(days=1)
        db_session.commit()

        resubmit, cleanup = list_recoverable_schedule_runs(db_session)
        assert row.status == "skipped"
        assert row not in resubmit
        assert row not in cleanup
    finally:
        db_session.close()
