from dataclasses import dataclass, field
from datetime import UTC, datetime

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.auth_cookie import AUTH_COOKIE_NAME
from app.core.config import settings
from app.core.database import get_db
from app.core.security import decode_token
from app.models.user import User
from app.models.user_identity import UserIdentity

bearer = HTTPBearer(auto_error=False)


@dataclass
class CurrentSession:
    user: User
    identity: UserIdentity
    # Default for internal/service actors; HTTP auth always sets real auth_time from JWT
    auth_time: datetime = field(default_factory=lambda: datetime.now(UTC))


def _resolve_access_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None,
) -> str | None:
    if credentials and credentials.credentials:
        return credentials.credentials
    cookie_token = request.cookies.get(AUTH_COOKIE_NAME)
    if cookie_token:
        return cookie_token
    return None


def _auth_time_from_payload(payload: dict) -> datetime:
    raw = payload.get("auth_time", payload.get("iat"))
    if raw is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录状态无效或已过期")
    at = datetime.fromtimestamp(int(raw), UTC)
    age_minutes = (datetime.now(UTC) - at).total_seconds() / 60.0
    if age_minutes > float(settings.access_token_absolute_expire_minutes):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="登录已超过最长有效期，请重新登录",
        )
    return at


def get_current_session(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> CurrentSession:
    token = _resolve_access_token(request, credentials)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请先登录")
    try:
        payload = decode_token(token)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    if payload.get("scope") != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录凭证类型错误")
    auth_time = _auth_time_from_payload(payload)
    identity = db.scalar(
        select(UserIdentity)
        .options(joinedload(UserIdentity.user), joinedload(UserIdentity.tenant))
        .where(
            UserIdentity.id == int(payload["identity_id"]),
            UserIdentity.user_id == int(payload["sub"]),
            UserIdentity.status.is_(True),
            UserIdentity.deleted.is_(False),
        )
    )
    if identity is None or not identity.user.status:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="账号或身份已停用")
    # 2026-08-03 - 服务期只限模力提交；客户会话不因未开始/到期/停服被踢
    if identity.identity_type == "CUSTOMER" and (
        identity.tenant is None or bool(getattr(identity.tenant, "deleted", False))
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="企业不存在或已删除，请联系运营人员")
    return CurrentSession(user=identity.user, identity=identity, auth_time=auth_time)


def require_platform(
    current: CurrentSession,
    *,
    detail: str = "仅平台运营端可访问",
) -> None:
    if current.identity.identity_type != "PLATFORM":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)
