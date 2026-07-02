"""Resolve a platform operator session for scheduled jobs and workers."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.api.dependencies import CurrentSession
from app.models.user import User
from app.models.user_identity import UserIdentity


def load_platform_session(db) -> CurrentSession:
    identity = db.scalar(
        select(UserIdentity)
        .options(joinedload(UserIdentity.user), joinedload(UserIdentity.tenant))
        .join(User, User.id == UserIdentity.user_id)
        .where(
            UserIdentity.identity_type == "PLATFORM",
            UserIdentity.status.is_(True),
            UserIdentity.deleted.is_(False),
            User.status.is_(True),
            User.deleted.is_(False),
        )
        .order_by(UserIdentity.is_default.desc(), UserIdentity.id.asc())
    )
    if identity is None or identity.user is None or not identity.user.status:
        raise RuntimeError("没有可用的平台运营端身份，无法执行监测调度。")
    return CurrentSession(user=identity.user, identity=identity)
