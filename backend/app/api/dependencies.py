from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.core.security import decode_token
from app.models.user import User
from app.models.user_identity import UserIdentity

bearer = HTTPBearer(auto_error=False)


@dataclass
class CurrentSession:
    user: User
    identity: UserIdentity


def get_current_session(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> CurrentSession:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请先登录")
    try:
        payload = decode_token(credentials.credentials)
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

