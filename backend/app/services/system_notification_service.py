"""站内系统通知：创建、列表、已读。"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Integer, Select, and_, delete, func, or_, select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.notification import SystemNotification, SystemNotificationRead

logger = logging.getLogger(__name__)

NOTIFICATION_RETENTION_DAYS = 30

CUSTOMER_RESTRICTED_CATEGORIES = ("report_published",)
PLATFORM_RESTRICTED_CATEGORIES = (
    "operation_approval",
    "operation_approval_result",
    "celery_queue",
    "snapshot_backfill",
)


def can_view_notification_category(
    category: str,
    *,
    can_review_approvals: bool,
    can_view_ops_alerts: bool,
    can_view_snapshot_backfill: bool,
    can_view_customer_reports: bool = False,
) -> bool | None:
    """通知分类是否可见；None 表示需结合 payload 中的 requester_user_id 判断。"""
    if category == "operation_approval":
        return can_review_approvals
    if category == "operation_approval_result":
        return None
    if category == "celery_queue":
        return can_view_ops_alerts
    if category == "snapshot_backfill":
        return can_view_snapshot_backfill
    if category == "report_published":
        return can_view_customer_reports
    return False


def _delete_notification(db: Session, row: SystemNotification, *, auto_commit: bool = True) -> None:
    db.execute(
        delete(SystemNotificationRead).where(SystemNotificationRead.notification_id == row.id)
    )
    db.delete(row)
    if auto_commit:
        db.commit()


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


def _apply_notification_visibility_filter(
    stmt: Select[tuple[SystemNotification]],
    *,
    user_id: int,
    can_review_approvals: bool,
    can_view_ops_alerts: bool,
    can_view_snapshot_backfill: bool,
) -> Select[tuple[SystemNotification]]:
    """按角色过滤通知：审批、运维告警、补录待办分别鉴权。"""
    clauses = [SystemNotification.category.not_in(PLATFORM_RESTRICTED_CATEGORIES)]
    if can_review_approvals:
        clauses.append(SystemNotification.category == "operation_approval")
    requester_id_expr = func.cast(
        func.json_unquote(func.json_extract(SystemNotification.payload_json, "$.requester_user_id")),
        Integer,
    )
    clauses.append(
        and_(
            SystemNotification.category == "operation_approval_result",
            requester_id_expr == user_id,
        )
    )
    if can_view_ops_alerts:
        clauses.append(SystemNotification.category == "celery_queue")
    if can_view_snapshot_backfill:
        clauses.append(SystemNotification.category == "snapshot_backfill")
    return stmt.where(or_(*clauses))


def _apply_customer_notification_visibility_filter(
    stmt: Select[tuple[SystemNotification]],
    *,
    can_view_customer_reports: bool,
) -> Select[tuple[SystemNotification]]:
    clauses = [SystemNotification.category.not_in(CUSTOMER_RESTRICTED_CATEGORIES)]
    if can_view_customer_reports:
        clauses.append(SystemNotification.category == "report_published")
    return stmt.where(or_(*clauses))


def _notification_retention_cutoff() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None) - timedelta(days=NOTIFICATION_RETENTION_DAYS)


def _user_can_read_notification(
    row: SystemNotification,
    *,
    user_id: int,
    identity_type: str,
    tenant_id: int | None,
    can_review_approvals: bool,
    can_view_ops_alerts: bool,
    can_view_snapshot_backfill: bool,
    can_view_customer_reports: bool,
) -> bool:
    if row.created_at < _notification_retention_cutoff():
        return False
    if identity_type == "CUSTOMER":
        if row.audience_type != "CUSTOMER" or row.tenant_id != tenant_id:
            return False
        allowed = can_view_notification_category(
            row.category,
            can_review_approvals=False,
            can_view_ops_alerts=False,
            can_view_snapshot_backfill=False,
            can_view_customer_reports=can_view_customer_reports,
        )
        return allowed is True

    if row.audience_type != "PLATFORM" or row.tenant_id is not None:
        return False
    if row.category == "operation_approval_result":
        if not row.payload_json:
            return False
        try:
            payload = json.loads(row.payload_json)
        except json.JSONDecodeError:
            return False
        return int(payload.get("requester_user_id") or 0) == user_id
    allowed = can_view_notification_category(
        row.category,
        can_review_approvals=can_review_approvals,
        can_view_ops_alerts=can_view_ops_alerts,
        can_view_snapshot_backfill=can_view_snapshot_backfill,
    )
    return allowed is True


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


def resolve_stale_monitor_alert_notifications(db: Session, active_alerts: list[dict[str, Any]]) -> int:
    """告警恢复后移除不再触发的 celery_queue 站内通知。"""
    active_keys = {
        f"monitor:celery:{str(alert.get('queue') or 'unknown')}:{str(alert.get('level') or 'warning')}"
        for alert in active_alerts
    }
    rows = list(
        db.scalars(
            select(SystemNotification).where(
                SystemNotification.category == "celery_queue",
                SystemNotification.audience_type == "PLATFORM",
                SystemNotification.tenant_id.is_(None),
            )
        )
    )
    removed = 0
    for row in rows:
        if row.source_key in active_keys:
            continue
        _delete_notification(db, row, auto_commit=False)
        removed += 1
    if removed:
        db.commit()
    return removed


def upsert_report_published_notification(
    db: Session,
    *,
    tenant_id: int,
    report_id: int,
    report_title: str,
    report_type: str,
    type_label: str,
    auto_commit: bool = True,
) -> SystemNotification:
    """报告发布后通知客户企业端用户。"""
    title = f"新{type_label}已发布"
    message = f"「{report_title.strip() or type_label}」已发布，请在报告中心查看"
    source_key = f"report:published:{report_id}"
    payload = {
        "report_id": report_id,
        "report_title": report_title,
        "report_type": report_type,
        "menu_code": "customer.reports",
    }
    payload_text = json.dumps(payload, ensure_ascii=False)
    existing = db.scalar(
        select(SystemNotification).where(
            SystemNotification.source_key == source_key,
            SystemNotification.audience_type == "CUSTOMER",
            SystemNotification.tenant_id == tenant_id,
        )
    )
    if existing is not None:
        existing.title = title
        existing.message = message[:500]
        existing.level = "info"
        existing.payload_json = payload_text
        existing.updated_at = datetime.now(UTC).replace(tzinfo=None)
        row = existing
    else:
        row = SystemNotification(
            audience_type="CUSTOMER",
            tenant_id=tenant_id,
            category="report_published",
            level="info",
            title=title,
            message=message[:500],
            payload_json=payload_text,
            source_key=source_key,
        )
        db.add(row)
    if auto_commit:
        db.commit()
        db.refresh(row)
    else:
        db.flush()
    return row


def upsert_subtask_backfill_notification(
    db: Session,
    *,
    subtask_id: str,
    title: str,
    message: str,
    payload: dict[str, Any],
) -> SystemNotification:
    """单条失败子任务对应一条待补录通知（source_key 去重）。"""
    source_key = f"subtask:backfill:{subtask_id}"
    payload_text = json.dumps(payload, ensure_ascii=False)
    existing = db.scalar(
        select(SystemNotification).where(
            SystemNotification.source_key == source_key,
            SystemNotification.audience_type == "PLATFORM",
            SystemNotification.tenant_id.is_(None),
        )
    )
    if existing is not None:
        existing.title = title
        existing.message = message[:500]
        existing.level = "warning"
        existing.payload_json = payload_text
        existing.updated_at = datetime.now(UTC).replace(tzinfo=None)
        db.commit()
        db.refresh(existing)
        return existing

    row = SystemNotification(
        audience_type="PLATFORM",
        tenant_id=None,
        category="snapshot_backfill",
        level="warning",
        title=title,
        message=message[:500],
        payload_json=payload_text,
        source_key=source_key,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def upsert_approval_pending_notification(
    db: Session,
    *,
    approval_id: int,
    summary: str,
    requester_user_id: int,
    requester_name: str | None,
    module_label: str,
) -> SystemNotification:
    """销售提交审批后，通知运营/管理员处理。"""
    name = (requester_name or "").strip() or "销售"
    title = "待审批操作"
    message = f"{name} 提交了「{summary}」，请及时处理"
    source_key = f"approval:pending:{approval_id}"
    payload = {
        "approval_id": approval_id,
        "summary": summary,
        "module_label": module_label,
        "requester_user_id": requester_user_id,
        "requester_name": name,
        "menu_code": "platform.approvals",
    }
    payload_text = json.dumps(payload, ensure_ascii=False)
    existing = db.scalar(
        select(SystemNotification).where(
            SystemNotification.source_key == source_key,
            SystemNotification.audience_type == "PLATFORM",
            SystemNotification.tenant_id.is_(None),
        )
    )
    if existing is not None:
        existing.title = title
        existing.message = message[:500]
        existing.level = "warning"
        existing.payload_json = payload_text
        existing.updated_at = datetime.now(UTC).replace(tzinfo=None)
        db.commit()
        db.refresh(existing)
        return existing

    row = SystemNotification(
        audience_type="PLATFORM",
        tenant_id=None,
        category="operation_approval",
        level="warning",
        title=title,
        message=message[:500],
        payload_json=payload_text,
        source_key=source_key,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def resolve_approval_pending_notification(db: Session, approval_id: int) -> None:
    """审批处理完成后移除待办通知。"""
    source_key = f"approval:pending:{approval_id}"
    row = db.scalar(
        select(SystemNotification).where(
            SystemNotification.source_key == source_key,
            SystemNotification.audience_type == "PLATFORM",
        )
    )
    if row is None:
        return
    _delete_notification(db, row)


def upsert_approval_result_notification(
    db: Session,
    *,
    approval_id: int,
    status: str,
    summary: str,
    requester_user_id: int,
    reviewer_name: str | None = None,
    review_comment: str | None = None,
) -> SystemNotification:
    """审批通过/驳回后通知提交人。"""
    approved = status == "approved"
    status_label = "已通过" if approved else "已驳回"
    title = f"审批{status_label}"
    message = f"您提交的「{summary}」{status_label}"
    if not approved and review_comment:
        message += f"：{review_comment.strip()}"
    elif approved and reviewer_name:
        message += f"（审核人：{reviewer_name.strip()}）"
    source_key = f"approval:result:{approval_id}"
    payload = {
        "approval_id": approval_id,
        "status": status,
        "summary": summary,
        "requester_user_id": requester_user_id,
        "menu_code": "platform.approvals",
    }
    payload_text = json.dumps(payload, ensure_ascii=False)
    existing = db.scalar(
        select(SystemNotification).where(
            SystemNotification.source_key == source_key,
            SystemNotification.audience_type == "PLATFORM",
            SystemNotification.tenant_id.is_(None),
        )
    )
    level = "info" if approved else "warning"
    if existing is not None:
        existing.title = title
        existing.message = message[:500]
        existing.level = level
        existing.payload_json = payload_text
        existing.updated_at = datetime.now(UTC).replace(tzinfo=None)
        db.commit()
        db.refresh(existing)
        return existing

    row = SystemNotification(
        audience_type="PLATFORM",
        tenant_id=None,
        category="operation_approval_result",
        level=level,
        title=title,
        message=message[:500],
        payload_json=payload_text,
        source_key=source_key,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def resolve_subtask_backfill_notification(db: Session, subtask_id: str) -> None:
    """补录成功后移除待办通知。"""
    source_key = f"subtask:backfill:{subtask_id}"
    row = db.scalar(
        select(SystemNotification).where(
            SystemNotification.source_key == source_key,
            SystemNotification.audience_type == "PLATFORM",
        )
    )
    if row is None:
        return
    _delete_notification(db, row)


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
    can_review_approvals: bool = False,
    can_view_ops_alerts: bool = False,
    can_view_snapshot_backfill: bool = False,
    can_view_customer_reports: bool = False,
) -> list[dict[str, Any]]:
    stmt = _notification_query_for_user(
        user_id=user_id,
        identity_type=identity_type,
        tenant_id=tenant_id,
    )
    if identity_type == "PLATFORM":
        stmt = _apply_notification_visibility_filter(
            stmt,
            user_id=user_id,
            can_review_approvals=can_review_approvals,
            can_view_ops_alerts=can_view_ops_alerts,
            can_view_snapshot_backfill=can_view_snapshot_backfill,
        )
    else:
        stmt = _apply_customer_notification_visibility_filter(
            stmt,
            can_view_customer_reports=can_view_customer_reports,
        )
    stmt = stmt.order_by(SystemNotification.created_at.desc()).limit(max(1, min(limit, 100)))
    stmt = stmt.where(SystemNotification.created_at >= _notification_retention_cutoff())

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
    can_review_approvals: bool = False,
    can_view_ops_alerts: bool = False,
    can_view_snapshot_backfill: bool = False,
    can_view_customer_reports: bool = False,
) -> int:
    audience = "PLATFORM" if identity_type == "PLATFORM" else "CUSTOMER"
    visible_ids = select(SystemNotification.id).where(
        SystemNotification.audience_type == audience,
        SystemNotification.created_at >= _notification_retention_cutoff(),
    )
    if audience == "CUSTOMER":
        visible_ids = visible_ids.where(SystemNotification.tenant_id == tenant_id)
        visible_ids = _apply_customer_notification_visibility_filter(
            visible_ids,
            can_view_customer_reports=can_view_customer_reports,
        )
    else:
        visible_ids = visible_ids.where(SystemNotification.tenant_id.is_(None))
        visible_ids = _apply_notification_visibility_filter(
            visible_ids,
            user_id=user_id,
            can_review_approvals=can_review_approvals,
            can_view_ops_alerts=can_view_ops_alerts,
            can_view_snapshot_backfill=can_view_snapshot_backfill,
        )

    read_subq = (
        select(SystemNotificationRead.notification_id)
        .where(SystemNotificationRead.user_id == user_id)
        .scalar_subquery()
    )
    stmt = select(func.count()).select_from(SystemNotification).where(
        SystemNotification.id.in_(visible_ids),
        SystemNotification.id.not_in(read_subq),
    )
    return int(db.scalar(stmt) or 0)


def mark_notification_read(
    db: Session,
    *,
    user_id: int,
    notification_id: int,
    identity_type: str,
    tenant_id: int | None,
    can_review_approvals: bool = False,
    can_view_ops_alerts: bool = False,
    can_view_snapshot_backfill: bool = False,
    can_view_customer_reports: bool = False,
) -> bool:
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
    if not _user_can_read_notification(
        notification,
        user_id=user_id,
        identity_type=identity_type,
        tenant_id=tenant_id,
        can_review_approvals=can_review_approvals,
        can_view_ops_alerts=can_view_ops_alerts,
        can_view_snapshot_backfill=can_view_snapshot_backfill,
        can_view_customer_reports=can_view_customer_reports,
    ):
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
    can_review_approvals: bool = False,
    can_view_ops_alerts: bool = False,
    can_view_snapshot_backfill: bool = False,
    can_view_customer_reports: bool = False,
) -> int:
    unread = list_notifications_for_user(
        db,
        user_id=user_id,
        identity_type=identity_type,
        tenant_id=tenant_id,
        unread_only=True,
        limit=100,
        can_review_approvals=can_review_approvals,
        can_view_ops_alerts=can_view_ops_alerts,
        can_view_snapshot_backfill=can_view_snapshot_backfill,
        can_view_customer_reports=can_view_customer_reports,
    )
    count = 0
    for item in unread:
        if mark_notification_read(
            db,
            user_id=user_id,
            notification_id=int(item["id"]),
            identity_type=identity_type,
            tenant_id=tenant_id,
            can_review_approvals=can_review_approvals,
            can_view_ops_alerts=can_view_ops_alerts,
            can_view_snapshot_backfill=can_view_snapshot_backfill,
            can_view_customer_reports=can_view_customer_reports,
        ):
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
