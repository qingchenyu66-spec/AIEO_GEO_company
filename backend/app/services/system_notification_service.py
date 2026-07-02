"""站内系统通知：创建、列表、已读。"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.notification import SystemNotification, SystemNotificationRead

logger = logging.getLogger(__name__)

NOTIFICATION_RETENTION_DAYS = 30


def _notification_query_for_user(
    *,
    user_id: int,
    identity_type: str,
    tenant_id: int | None,
) -> Select[tuple[SystemNotification]]:
    audience = "PLATFORM" if identity_type == "PLATFORM" else "CUSTOMER"
    stmt = select(SystemNotification).where(SystemNotification.audience_type == audience)
    if audience == "CUSTOMER":
        stmt = stmt.where(SystemNotification.tenant_id == tenant_id)
    else:
        stmt = stmt.where(SystemNotification.tenant_id.is_(None))
    read_exists = (
        select(SystemNotificationRead.id)
        .where(
            SystemNotificationRead.notification_id == SystemNotification.id,
            SystemNotificationRead.user_id == user_id,
        )
        .exists()
    )
    return stmt


def upsert_monitor_alert_notification(db: Session, alert: dict[str, Any]) -> SystemNotification | None:
    """将监控告警写入平台运营站内通知（可测试）。"""
    queue = str(alert.get("queue") or "unknown")
    level = str(alert.get("level") or "warning")
    source_key = f"monitor:celery:{queue}:{level}"
    title = str(alert.get("title") or "系统告警")
    message = str(alert.get("message") or "")
    payload = json.dumps(alert, ensure_ascii=False)

    existing = db.scalar(
        select(SystemNotification).where(
            SystemNotification.source_key == source_key,
            SystemNotification.audience_type == "PLATFORM",
            SystemNotification.tenant_id.is_(None),
        )
    )
    if existing is not None:
        existing.title = title
        existing.message = message
        existing.level = level
        existing.payload_json = payload
        existing.updated_at = datetime.now(UTC).replace(tzinfo=None)
        db.commit()
        db.refresh(existing)
        return existing

    row = SystemNotification(
        audience_type="PLATFORM",
        tenant_id=None,
        category="celery_queue",
        level=level,
        title=title,
        message=message,
        payload_json=payload,
        source_key=source_key,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def push_monitor_alert_notification(alert: dict[str, Any]) -> SystemNotification | None:
    """将监控告警写入平台运营站内通知。"""
    db = SessionLocal()
    try:
        return upsert_monitor_alert_notification(db, alert)
    except Exception:
        db.rollback()
        logger.exception("Failed to persist monitor alert notification")
        return None
    finally:
        db.close()


def list_notifications_for_user(
    db: Session,
    *,
    user_id: int,
    identity_type: str,
    tenant_id: int | None,
    unread_only: bool = False,
    limit: int = 20,
) -> list[dict[str, Any]]:
    stmt = _notification_query_for_user(
        user_id=user_id,
        identity_type=identity_type,
        tenant_id=tenant_id,
    ).order_by(SystemNotification.created_at.desc()).limit(max(1, min(limit, 100)))

    cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=NOTIFICATION_RETENTION_DAYS)
    stmt = stmt.where(SystemNotification.created_at >= cutoff)

    rows = list(db.scalars(stmt))
    if not rows:
        return []

    read_ids = set(
        db.scalars(
            select(SystemNotificationRead.notification_id).where(
                SystemNotificationRead.user_id == user_id,
                SystemNotificationRead.notification_id.in_([row.id for row in rows]),
            )
        )
    )

    items: list[dict[str, Any]] = []
    for row in rows:
        is_read = row.id in read_ids
        if unread_only and is_read:
            continue
        items.append(_serialize_notification(row, is_read=is_read))
    return items


def count_unread_notifications(
    db: Session,
    *,
    user_id: int,
    identity_type: str,
    tenant_id: int | None,
) -> int:
    audience = "PLATFORM" if identity_type == "PLATFORM" else "CUSTOMER"
    cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=NOTIFICATION_RETENTION_DAYS)
    stmt = select(func.count()).select_from(SystemNotification).where(
        SystemNotification.audience_type == audience,
        SystemNotification.created_at >= cutoff,
    )
    if audience == "CUSTOMER":
        stmt = stmt.where(SystemNotification.tenant_id == tenant_id)
    else:
        stmt = stmt.where(SystemNotification.tenant_id.is_(None))

    read_subq = (
        select(SystemNotificationRead.notification_id)
        .where(SystemNotificationRead.user_id == user_id)
        .scalar_subquery()
    )
    stmt = stmt.where(SystemNotification.id.not_in(read_subq))
    return int(db.scalar(stmt) or 0)


def mark_notification_read(db: Session, *, user_id: int, notification_id: int) -> bool:
    exists = db.scalar(
        select(SystemNotificationRead.id).where(
            SystemNotificationRead.user_id == user_id,
            SystemNotificationRead.notification_id == notification_id,
        )
    )
    if exists is not None:
        return True
    notification = db.get(SystemNotification, notification_id)
    if notification is None:
        return False
    db.add(SystemNotificationRead(user_id=user_id, notification_id=notification_id))
    db.commit()
    return True


def mark_all_notifications_read(
    db: Session,
    *,
    user_id: int,
    identity_type: str,
    tenant_id: int | None,
) -> int:
    unread = list_notifications_for_user(
        db,
        user_id=user_id,
        identity_type=identity_type,
        tenant_id=tenant_id,
        unread_only=True,
        limit=100,
    )
    count = 0
    for item in unread:
        if mark_notification_read(db, user_id=user_id, notification_id=int(item["id"])):
            count += 1
    return count


def _serialize_notification(row: SystemNotification, *, is_read: bool) -> dict[str, Any]:
    payload: dict[str, Any] | None = None
    if row.payload_json:
        try:
            payload = json.loads(row.payload_json)
        except json.JSONDecodeError:
            payload = None
    return {
        "id": row.id,
        "audience_type": row.audience_type,
        "tenant_id": row.tenant_id,
        "category": row.category,
        "level": row.level,
        "title": row.title,
        "message": row.message,
        "payload": payload,
        "source_key": row.source_key,
        "is_read": is_read,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }
