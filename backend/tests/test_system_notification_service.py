import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.notification import SystemNotification, SystemNotificationRead
from app.services.system_notification_service import upsert_monitor_alert_notification


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
