"""Helpers for P2 platform-service notification position recipients."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.permission import Position
from app.models.user_identity import UserIdentity


def parse_notify_position_ids(raw: str | None = None, db: Session | None = None) -> list[int]:
    if raw is None:
        from app.services.system_config_service import get_runtime_config

        raw = str(get_runtime_config("platform_service_notify_position_ids", db=db) or "")
    text = str(raw or "").strip()
    if not text:
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = [part.strip() for part in text.split(",") if part.strip()]
    result: list[int] = []
    for item in data if isinstance(data, list) else []:
        try:
            result.append(int(item))
        except (TypeError, ValueError):
            continue
    return result


def default_platform_notify_position_ids(db: Session) -> list[int]:
    rows = db.scalars(
        select(Position.id).where(
            Position.deleted.is_(False),
            Position.position_code.in_(("PLATFORM_SALES", "PLATFORM_OPERATION", "PLATFORM_ADMIN")),
        )
    )
    return list(rows)


def identity_can_view_platform_service(db: Session, identity: UserIdentity) -> bool:
    if identity.identity_type != "PLATFORM":
        return False
    allowed = parse_notify_position_ids(db=db)
    if not allowed:
        allowed = default_platform_notify_position_ids(db)
    if identity.position_id is None:
        return False
    return int(identity.position_id) in set(allowed)


def list_platform_positions_for_notify_config(db: Session) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(Position).where(
            Position.deleted.is_(False),
            Position.identity_type == "PLATFORM",
        ).order_by(Position.id.asc())
    )
    selected = set(parse_notify_position_ids(db=db) or default_platform_notify_position_ids(db))
    return [
        {
            "id": row.id,
            "position_code": row.position_code,
            "position_name": row.position_name,
            "selected": row.id in selected,
        }
        for row in rows
    ]
