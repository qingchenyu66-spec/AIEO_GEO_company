"""客户即将到期通知：窗口扫描、销售名下过滤、无归属非销售可见。"""
from __future__ import annotations

import json
from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.notification import SystemNotification, SystemNotificationRead
from app.models.tenant import Tenant
from app.models.user import User
from app.services.system_notification_service import (
    _user_can_read_notification,
    can_view_notification_category,
    list_notifications_for_user,
)
from app.services.tenant_expiry_notify_service import sync_tenant_expiry_notifications


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    def _json_extract(doc, path):
        if doc is None:
            return None
        try:
            data = json.loads(doc) if isinstance(doc, str) else doc
        except (TypeError, json.JSONDecodeError):
            return None
        key = str(path or "").lstrip("$.").strip()
        return data.get(key) if isinstance(data, dict) else None

    def _register_json_helpers(dbapi_conn, _connection_record):
        dbapi_conn.create_function("json_unquote", 1, lambda value: value)
        dbapi_conn.create_function("json_extract", 2, _json_extract)

    event.listen(engine, "connect", _register_json_helpers)

    Base.metadata.create_all(
        bind=engine,
        tables=[
            User.__table__,
            Tenant.__table__,
            SystemNotification.__table__,
            SystemNotificationRead.__table__,
        ],
    )
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def test_tenant_expiry_category_gates():
    flags = {
        "can_review_approvals": False,
        "can_view_ops_alerts": False,
        "can_view_snapshot_backfill": False,
        "can_view_tenant_expiry": False,
    }
    assert can_view_notification_category("tenant_expiry", **flags) is False
    assert can_view_notification_category("tenant_expiry", **{**flags, "can_view_tenant_expiry": True}) is True
    assert (
        can_view_notification_category(
            "tenant_expiry",
            **{**flags, "can_view_tenant_expiry": True, "tenant_expiry_owner_only": True},
        )
        is None
    )


def test_sync_tenant_expiry_and_sales_visibility(db_session, monkeypatch):
    today = date(2026, 7, 31)
    owner = User(username="sales_a", password_hash="x", display_name="销售A", status=True)
    db_session.add(owner)
    db_session.flush()

    owned = Tenant(
        name="名下客户有限公司",
        code="owned_exp",
        status=True,
        deleted=False,
        owner_user_id=owner.id,
        service_end_date=today + timedelta(days=3),
    )
    orphan = Tenant(
        name="无人认领有限公司",
        code="orphan_exp",
        status=True,
        deleted=False,
        owner_user_id=None,
        service_end_date=today + timedelta(days=5),
    )
    far = Tenant(
        name="很远才到期",
        code="far_exp",
        status=True,
        deleted=False,
        owner_user_id=owner.id,
        service_end_date=today + timedelta(days=30),
    )
    db_session.add_all([owned, orphan, far])
    db_session.commit()

    monkeypatch.setattr(
        "app.services.tenant_expiry_notify_service.get_runtime_config",
        lambda key, db=None: 7 if key.endswith("days") else "[]",
    )
    monkeypatch.setattr(
        "app.services.tenant_expiry_notify_service.parse_notify_position_ids",
        lambda raw=None, db=None, config_key=None: [1, 2],
    )

    result = sync_tenant_expiry_notifications(db_session, today=today)
    assert result["upserted"] == 2

    rows = list(
        db_session.scalars(
            select(SystemNotification).where(SystemNotification.category == "tenant_expiry")
        )
    )
    assert len(rows) == 2

    sales_seen = list_notifications_for_user(
        db_session,
        user_id=owner.id,
        identity_type="PLATFORM",
        tenant_id=None,
        can_view_tenant_expiry=True,
        tenant_expiry_owner_only=True,
    )
    assert len(sales_seen) == 1
    assert sales_seen[0]["payload"]["owner_user_id"] == owner.id

    ops_seen = list_notifications_for_user(
        db_session,
        user_id=99,
        identity_type="PLATFORM",
        tenant_id=None,
        can_view_tenant_expiry=True,
        tenant_expiry_owner_only=False,
    )
    assert len(ops_seen) == 2

    other_sales = list_notifications_for_user(
        db_session,
        user_id=77,
        identity_type="PLATFORM",
        tenant_id=None,
        can_view_tenant_expiry=True,
        tenant_expiry_owner_only=True,
    )
    assert other_sales == []

    orphan_row = next(r for r in rows if "无人认领" in r.title)
    assert (
        _user_can_read_notification(
            orphan_row,
            user_id=owner.id,
            identity_type="PLATFORM",
            tenant_id=None,
            can_review_approvals=False,
            can_view_ops_alerts=False,
            can_view_snapshot_backfill=False,
            can_view_customer_reports=False,
            can_view_tenant_expiry=True,
            tenant_expiry_owner_only=True,
        )
        is False
    )
    assert (
        _user_can_read_notification(
            orphan_row,
            user_id=99,
            identity_type="PLATFORM",
            tenant_id=None,
            can_review_approvals=False,
            can_view_ops_alerts=False,
            can_view_snapshot_backfill=False,
            can_view_customer_reports=False,
            can_view_tenant_expiry=True,
            tenant_expiry_owner_only=False,
        )
        is True
    )


def test_sync_skips_when_no_positions(db_session, monkeypatch):
    today = date(2026, 7, 31)
    db_session.add(
        Tenant(
            name="窗口内",
            code="win_exp",
            status=True,
            deleted=False,
            service_end_date=today + timedelta(days=2),
        )
    )
    db_session.commit()
    monkeypatch.setattr(
        "app.services.tenant_expiry_notify_service.get_runtime_config",
        lambda key, db=None: 7,
    )
    monkeypatch.setattr(
        "app.services.tenant_expiry_notify_service.parse_notify_position_ids",
        lambda raw=None, db=None, config_key=None: [],
    )
    result = sync_tenant_expiry_notifications(db_session, today=today)
    assert result["skipped"] == "disabled"
    assert result["upserted"] == 0
