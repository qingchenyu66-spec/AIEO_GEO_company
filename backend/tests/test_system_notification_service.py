import pytest
from datetime import datetime, timedelta

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.notification import SystemNotification, SystemNotificationRead
from app.services.system_notification_service import (
    can_view_notification_category,
    count_unread_notifications,
    list_notifications_for_user,
    mark_all_notifications_read,
    mark_notification_read,
    resolve_stale_monitor_alert_notifications,
    upsert_monitor_alert_notification,
    upsert_report_published_notification,
)


@pytest.fixture()
def db_session():
    from sqlalchemy import event

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    def _register_json_helpers(dbapi_conn, _connection_record):
        # MySQL 可见性过滤用了 json_unquote/json_extract；SQLite 单测补同名空壳
        dbapi_conn.create_function("json_unquote", 1, lambda value: value)
        dbapi_conn.create_function("json_extract", 2, lambda _doc, _path: None)

    event.listen(engine, "connect", _register_json_helpers)

    Base.metadata.create_all(
        bind=engine,
        tables=[SystemNotification.__table__, SystemNotificationRead.__table__],
    )
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def test_upsert_monitor_alert_notification(db_session):
    alert = {
        "queue": "submit",
        "level": "warning",
        "title": "提交队列积压预警",
        "message": "提交队列待处理 60 条，阈值 50",
        "queued": 60,
        "threshold": 50,
    }
    first = upsert_monitor_alert_notification(db_session, alert)
    assert first is not None
    assert first.source_key == "monitor:celery:submit:warning"

    alert["message"] = "提交队列待处理 80 条，阈值 50"
    second = upsert_monitor_alert_notification(db_session, alert)
    assert second is not None
    assert second.id == first.id
    assert "80" in second.message


def test_celery_notification_category_gated():
    flags = {
        "can_review_approvals": False,
        "can_view_ops_alerts": False,
        "can_view_snapshot_backfill": False,
    }
    assert can_view_notification_category("celery_queue", **flags) is False
    assert can_view_notification_category("celery_queue", **{**flags, "can_view_ops_alerts": True}) is True
    assert can_view_notification_category("snapshot_backfill", **flags) is False
    # 有菜单权限后仍需按 payload 归属判断
    assert can_view_notification_category("snapshot_backfill", **{**flags, "can_view_snapshot_backfill": True}) is None
    assert (
        can_view_notification_category(
            "snapshot_backfill",
            **{**flags, "can_view_snapshot_backfill": True, "snapshot_backfill_owner_only": True},
        )
        is None
    )
    assert can_view_notification_category("report_published", **flags) is False
    assert can_view_notification_category("report_published", **{**flags, "can_view_customer_reports": True}) is True
    # 2026-09-08 - 算力类须对客户可见，否则三日不足通知发了也看不到
    assert can_view_notification_category("credit_runway", **flags) is True
    assert can_view_notification_category("credit_submit_block", **flags) is True
    assert can_view_notification_category("credit_balance_capped", **flags) is True
    assert can_view_notification_category("unknown_category", **flags) is False


def test_credit_billing_mode_platform_owner_only(db_session):
    from app.services.system_notification_service import _user_can_read_notification

    row = SystemNotification(
        audience_type="PLATFORM",
        tenant_id=None,
        category="credit_billing_mode",
        level="info",
        title="客户已转回托管",
        message="测试",
        payload_json='{"owner_user_id": 42, "tenant_id": 1, "to_mode": "hosted"}',
        source_key="credit:billing_mode:sales:1:tenant:1",
    )
    db_session.add(row)
    db_session.commit()
    common = dict(
        identity_type="PLATFORM",
        tenant_id=None,
        can_review_approvals=False,
        can_view_ops_alerts=False,
        can_view_snapshot_backfill=False,
        can_view_customer_reports=False,
    )
    assert _user_can_read_notification(row, user_id=42, **common) is True
    assert _user_can_read_notification(row, user_id=99, **common) is False


def test_snapshot_backfill_owner_only_read_check(db_session):
    from app.services.system_notification_service import _user_can_read_notification

    row = SystemNotification(
        audience_type="PLATFORM",
        tenant_id=None,
        category="snapshot_backfill",
        level="warning",
        title="快照待补录",
        message="a · b · c",
        payload_json='{"owner_user_id": 42, "subtask_id": "st-1"}',
        source_key="subtask:backfill:st-1",
    )
    db_session.add(row)
    db_session.commit()

    assert (
        _user_can_read_notification(
            row,
            user_id=42,
            identity_type="PLATFORM",
            tenant_id=None,
            can_review_approvals=False,
            can_view_ops_alerts=False,
            can_view_snapshot_backfill=True,
            can_view_customer_reports=False,
            snapshot_backfill_owner_only=True,
        )
        is True
    )
    assert (
        _user_can_read_notification(
            row,
            user_id=99,
            identity_type="PLATFORM",
            tenant_id=None,
            can_review_approvals=False,
            can_view_ops_alerts=False,
            can_view_snapshot_backfill=True,
            can_view_customer_reports=False,
            snapshot_backfill_owner_only=True,
        )
        is False
    )
    assert (
        _user_can_read_notification(
            row,
            user_id=99,
            identity_type="PLATFORM",
            tenant_id=None,
            can_review_approvals=False,
            can_view_ops_alerts=False,
            can_view_snapshot_backfill=True,
            can_view_customer_reports=False,
            snapshot_backfill_owner_only=False,
        )
        is False
    )
    # 运营可见：无人认领
    unclaimed = SystemNotification(
        audience_type="PLATFORM",
        tenant_id=None,
        category="snapshot_backfill",
        level="warning",
        title="待补录 · 无人认领",
        message="测试 · 早 · 待补录1条",
        payload_json='{"subtask_id": "st-2"}',
        source_key="backfill:batch:lead:x:2026-07-28:早",
    )
    db_session.add(unclaimed)
    db_session.commit()
    assert (
        _user_can_read_notification(
            unclaimed,
            user_id=99,
            identity_type="PLATFORM",
            tenant_id=None,
            can_review_approvals=False,
            can_view_ops_alerts=False,
            can_view_snapshot_backfill=True,
            can_view_customer_reports=False,
            snapshot_backfill_owner_only=False,
        )
        is True
    )
    assert (
        _user_can_read_notification(
            unclaimed,
            user_id=99,
            identity_type="PLATFORM",
            tenant_id=None,
            can_review_approvals=False,
            can_view_ops_alerts=False,
            can_view_snapshot_backfill=True,
            can_view_customer_reports=False,
            snapshot_backfill_owner_only=True,
        )
        is False
    )
    assert (
        _user_can_read_notification(
            row,
            user_id=42,
            identity_type="CUSTOMER",
            tenant_id=10,
            can_review_approvals=False,
            can_view_ops_alerts=False,
            can_view_snapshot_backfill=True,
            can_view_customer_reports=True,
            snapshot_backfill_owner_only=False,
        )
        is False
    )


def test_report_published_notification_for_customer_tenant(db_session):
    upsert_report_published_notification(
        db_session,
        tenant_id=10,
        report_id=42,
        report_title="GEO 监测周报",
        report_type="weekly",
        type_label="监测周报",
    )
    visible = list_notifications_for_user(
        db_session,
        user_id=5,
        identity_type="CUSTOMER",
        tenant_id=10,
        can_view_customer_reports=True,
    )
    assert len(visible) == 1
    assert visible[0]["category"] == "report_published"
    assert visible[0]["payload"]["report_id"] == 42

    hidden = list_notifications_for_user(
        db_session,
        user_id=5,
        identity_type="CUSTOMER",
        tenant_id=10,
        can_view_customer_reports=False,
    )
    assert hidden == []


def test_mark_notification_read_rejects_invisible_notification(db_session):
    upsert_report_published_notification(
        db_session,
        tenant_id=10,
        report_id=7,
        report_title="GEO 监测月报",
        report_type="monthly",
        type_label="监测月报",
    )
    row = db_session.scalar(select(SystemNotification).where(SystemNotification.category == "report_published"))
    assert row is not None
    denied = mark_notification_read(
        db_session,
        user_id=99,
        notification_id=row.id,
        identity_type="CUSTOMER",
        tenant_id=10,
        can_view_customer_reports=False,
    )
    assert denied is False
    allowed = mark_notification_read(
        db_session,
        user_id=99,
        notification_id=row.id,
        identity_type="CUSTOMER",
        tenant_id=10,
        can_view_customer_reports=True,
    )
    assert allowed is True


def test_resolve_stale_monitor_alert_notifications(db_session):
    upsert_monitor_alert_notification(
        db_session,
        {
            "queue": "workers",
            "level": "critical",
            "title": "Celery Worker 离线",
            "message": "未检测到在线 Worker",
            "queued": 0,
            "threshold": 0,
        },
    )
    row = db_session.scalar(select(SystemNotification).where(SystemNotification.category == "celery_queue"))
    assert row is not None
    db_session.add(SystemNotificationRead(user_id=1, notification_id=row.id))
    db_session.commit()

    removed = resolve_stale_monitor_alert_notifications(db_session, [])
    assert removed == 1
    assert db_session.scalar(select(SystemNotification).where(SystemNotification.category == "celery_queue")) is None


def test_mark_all_read_covers_older_unread_beyond_recent_window(db_session):
    """全部已读必须覆盖「不在最近 N 条里」的更早未读，否则刷新角标会回来。"""
    now = datetime.utcnow().replace(tzinfo=None)
    for index in range(5):
        db_session.add(SystemNotification(
            audience_type="PLATFORM",
            tenant_id=None,
            category="celery_queue",
            level="warning",
            title=f"旧告警 {index}",
            message="older unread",
            payload_json="{}",
            source_key=f"test:old:{index}",
            created_at=now - timedelta(days=10 - index),
            updated_at=now - timedelta(days=10 - index),
        ))
    newer_read = []
    for index in range(3):
        row = SystemNotification(
            audience_type="PLATFORM",
            tenant_id=None,
            category="celery_queue",
            level="info",
            title=f"新已读 {index}",
            message="newer read",
            payload_json="{}",
            source_key=f"test:new:{index}",
            created_at=now - timedelta(hours=3 - index),
            updated_at=now - timedelta(hours=3 - index),
        )
        db_session.add(row)
        newer_read.append(row)
    db_session.commit()
    for row in newer_read:
        db_session.add(SystemNotificationRead(user_id=7, notification_id=row.id))
    db_session.commit()

    assert count_unread_notifications(
        db_session,
        user_id=7,
        identity_type="PLATFORM",
        tenant_id=None,
        can_view_ops_alerts=True,
    ) == 5

    marked = mark_all_notifications_read(
        db_session,
        user_id=7,
        identity_type="PLATFORM",
        tenant_id=None,
        can_view_ops_alerts=True,
    )
    assert marked == 5
    assert count_unread_notifications(
        db_session,
        user_id=7,
        identity_type="PLATFORM",
        tenant_id=None,
        can_view_ops_alerts=True,
    ) == 0
    assert int(db_session.scalar(select(func.count()).select_from(SystemNotificationRead).where(
        SystemNotificationRead.user_id == 7,
    )) or 0) == 8
