from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.auth_cookie import AUTH_COOKIE_NAME
from app.core.database import get_db
from app.core.security import decode_token
from app.models.user import User
from app.models.user_identity import UserIdentity

bearer = HTTPBearer(auto_error=False)


@dataclass
class CurrentSession:
    user: User
    identity: UserIdentity


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
    return CurrentSession(user=identity.user, identity=identity)
