"""公告业务：CRUD、弹窗队列、确认、定时上线/失效。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentSession
from app.models.announcement import Announcement, AnnouncementAck
from app.schemas.announcement import AnnouncementUpsertRequest
from app.services.announcement_sanitize import sanitize_announcement_html
from app.services.menu_permission_service import require_platform_menu_permission

ANNOUNCEMENT_MENU = "platform.announcements"


def require_announcement_permission(db: Session, current: CurrentSession, action: str) -> None:
    require_platform_menu_permission(
        db,
        current,
        ANNOUNCEMENT_MENU,
        action,
        detail="当前账号无权管理公告",
    )


def _now() -> datetime:
    return datetime.now()


def _normalize_targets(targets: list[str], tenant_ids: list[int]) -> tuple[list[str], list[int]]:
    seen: list[str] = []
    for item in targets:
        if item not in seen:
            seen.append(item)
    if "customer_all" in seen and "customer_tenants" in seen:
        raise ValueError("「客户全员」与「指定企业」不能同时选择")
    ids = sorted({int(x) for x in tenant_ids if int(x) > 0})
    if "customer_tenants" in seen and not ids:
        raise ValueError("指定企业时请选择至少一个企业")
    if "customer_tenants" not in seen:
        ids = []
    return seen, ids


def _resolve_status(action: str, publish_at: datetime | None, now: datetime) -> tuple[str, datetime | None]:
    if action == "draft":
        return "draft", publish_at
    if action == "publish_now":
        return "published", now
    # schedule
    if publish_at is None:
        raise ValueError("定时发布请填写上线时间")
    if publish_at <= now:
        return "published", publish_at
    return "scheduled", publish_at


def serialize_announcement(row: Announcement) -> dict[str, Any]:
    return {
        "id": row.id,
        "title": row.title,
        "body_html": row.body_html,
        "targets": list(row.targets_json or []),
        "tenant_ids": list(row.tenant_ids_json or []),
        "status": row.status,
        "publish_at": row.publish_at.isoformat() if row.publish_at else None,
        "expire_at": row.expire_at.isoformat() if row.expire_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def list_announcements_admin(db: Session, current: CurrentSession) -> list[dict[str, Any]]:
    require_announcement_permission(db, current, "can_export")
    rows = db.scalars(
        select(Announcement)
        .where(Announcement.deleted.is_(False))
        .order_by(Announcement.id.desc())
        .limit(200)
    ).all()
    return [serialize_announcement(row) for row in rows]


def get_announcement_admin(db: Session, current: CurrentSession, announcement_id: int) -> dict[str, Any]:
    require_announcement_permission(db, current, "can_export")
    row = db.scalar(
        select(Announcement).where(Announcement.id == announcement_id, Announcement.deleted.is_(False))
    )
    if row is None:
        raise ValueError("公告不存在")
    return serialize_announcement(row)


def create_announcement(
    db: Session, current: CurrentSession, payload: AnnouncementUpsertRequest
) -> dict[str, Any]:
    require_announcement_permission(db, current, "can_create")
    targets, tenant_ids = _normalize_targets(list(payload.targets), list(payload.tenant_ids))
    body = sanitize_announcement_html(payload.body_html)
    now = _now()
    status, publish_at = _resolve_status(payload.action, payload.publish_at, now)
    row = Announcement(
        title=payload.title.strip(),
        body_html=body,
        targets_json=targets,
        tenant_ids_json=tenant_ids or None,
        status=status,
        publish_at=publish_at,
        expire_at=payload.expire_at,
        created_by_user_id=current.user.id,
        updated_by_user_id=current.user.id,
        deleted=False,
    )
    db.add(row)
    db.flush()
    return serialize_announcement(row)


def update_announcement(
    db: Session,
    current: CurrentSession,
    announcement_id: int,
    payload: AnnouncementUpsertRequest,
) -> dict[str, Any]:
    require_announcement_permission(db, current, "can_update")
    row = db.scalar(
        select(Announcement).where(Announcement.id == announcement_id, Announcement.deleted.is_(False))
    )
    if row is None:
        raise ValueError("公告不存在")
    targets, tenant_ids = _normalize_targets(list(payload.targets), list(payload.tenant_ids))
    body = sanitize_announcement_html(payload.body_html)
    now = _now()
    status, publish_at = _resolve_status(payload.action, payload.publish_at, now)
    row.title = payload.title.strip()
    row.body_html = body
    row.targets_json = targets
    row.tenant_ids_json = tenant_ids or None
    row.status = status
    row.publish_at = publish_at
    row.expire_at = payload.expire_at
    row.updated_by_user_id = current.user.id
    db.flush()
    return serialize_announcement(row)


def take_offline_announcement(db: Session, current: CurrentSession, announcement_id: int) -> dict[str, Any]:
    require_announcement_permission(db, current, "can_update")
    row = db.scalar(
        select(Announcement).where(Announcement.id == announcement_id, Announcement.deleted.is_(False))
    )
    if row is None:
        raise ValueError("公告不存在")
    row.status = "off"
    row.updated_by_user_id = current.user.id
    db.flush()
    return serialize_announcement(row)


def delete_announcement(db: Session, current: CurrentSession, announcement_id: int) -> None:
    require_announcement_permission(db, current, "can_delete")
    row = db.scalar(
        select(Announcement).where(Announcement.id == announcement_id, Announcement.deleted.is_(False))
    )
    if row is None:
        raise ValueError("公告不存在")
    row.deleted = True
    row.updated_by_user_id = current.user.id
    db.flush()


def _audience_match(row: Announcement, current: CurrentSession) -> bool:
    targets = set(row.targets_json or [])
    identity = current.identity
    if identity.identity_type == "PLATFORM":
        return "platform_all" in targets
    if identity.identity_type != "CUSTOMER" or not identity.tenant_id:
        return False
    if "customer_all" in targets:
        return True
    if "customer_tenants" in targets:
        ids = {int(x) for x in (row.tenant_ids_json or [])}
        return int(identity.tenant_id) in ids
    return False


def _is_active_published(row: Announcement, now: datetime) -> bool:
    if row.status != "published":
        return False
    if row.publish_at and row.publish_at > now:
        return False
    if row.expire_at and row.expire_at <= now:
        return False
    return True


def next_pending_announcement(db: Session, current: CurrentSession) -> dict[str, Any] | None:
    """登录弹窗：返回下一条未确认且有效的公告（按上线时间升序串行）。"""
    now = _now()
    user_created = current.user.created_at or now
    acked_ids = set(
        db.scalars(
            select(AnnouncementAck.announcement_id).where(AnnouncementAck.user_id == current.user.id)
        ).all()
    )
    rows = db.scalars(
        select(Announcement)
        .where(
            Announcement.deleted.is_(False),
            Announcement.status == "published",
        )
        .order_by(Announcement.publish_at.asc(), Announcement.id.asc())
        .limit(200)
    ).all()
    for row in rows:
        if row.id in acked_ids:
            continue
        if not _is_active_published(row, now):
            continue
        # 新人不补：账号创建前已发布的不弹
        pub = row.publish_at or row.created_at
        if pub and user_created and pub < user_created:
            continue
        if not _audience_match(row, current):
            continue
        return {
            "id": row.id,
            "title": row.title,
            "body_html": row.body_html,
            "publish_at": row.publish_at.isoformat() if row.publish_at else None,
        }
    return None


def ack_announcement(db: Session, current: CurrentSession, announcement_id: int) -> dict[str, Any]:
    row = db.scalar(
        select(Announcement).where(Announcement.id == announcement_id, Announcement.deleted.is_(False))
    )
    if row is None:
        raise ValueError("公告不存在")
    if not _audience_match(row, current):
        raise PermissionError("无权确认该公告")
    existing = db.scalar(
        select(AnnouncementAck).where(
            AnnouncementAck.user_id == current.user.id,
            AnnouncementAck.announcement_id == announcement_id,
        )
    )
    if existing is None:
        db.add(
            AnnouncementAck(
                user_id=current.user.id,
                announcement_id=announcement_id,
            )
        )
        db.flush()
    nxt = next_pending_announcement(db, current)
    return {"acked_id": announcement_id, "next": nxt}


def promote_scheduled_announcements(db: Session) -> int:
    now = _now()
    rows = db.scalars(
        select(Announcement).where(
            Announcement.deleted.is_(False),
            Announcement.status == "scheduled",
            Announcement.publish_at.is_not(None),
            Announcement.publish_at <= now,
        )
    ).all()
    for row in rows:
        row.status = "published"
    if rows:
        db.flush()
    return len(rows)


def expire_published_announcements(db: Session) -> int:
    now = _now()
    rows = db.scalars(
        select(Announcement).where(
            Announcement.deleted.is_(False),
            Announcement.status == "published",
            Announcement.expire_at.is_not(None),
            Announcement.expire_at <= now,
        )
    ).all()
    for row in rows:
        row.status = "off"
    if rows:
        db.flush()
    return len(rows)
