import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.notification import SystemNotification, SystemNotificationRead
from app.services.system_notification_service import (
    can_view_notification_category,
    list_notifications_for_user,
    mark_notification_read,
    resolve_stale_monitor_alert_notifications,
    upsert_monitor_alert_notification,
    upsert_report_published_notification,
)


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
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
    assert can_view_notification_category("snapshot_backfill", **{**flags, "can_view_snapshot_backfill": True}) is True
    assert can_view_notification_category("report_published", **flags) is False
    assert can_view_notification_category("report_published", **{**flags, "can_view_customer_reports": True}) is True
    assert can_view_notification_category("unknown_category", **flags) is False


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
