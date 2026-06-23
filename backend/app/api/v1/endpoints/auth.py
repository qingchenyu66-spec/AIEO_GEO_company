from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.api.dependencies import CurrentSession, get_current_session
from app.core.database import get_db
from app.core.security import decode_token
from app.models.user import User
from app.models.user_identity import UserIdentity
from app.schemas.auth import IdentityInfo, IdentitySelectRequest, IdentitySwitchRequest, LoginRequest
from app.schemas.common import ApiResponse
from app.services.auth_service import authenticate, create_access_token, create_identity_ticket
from app.services.permission_service import get_identity_menus

router = APIRouter(prefix="/auth")


def identity_info(identity: UserIdentity) -> dict:
    return IdentityInfo(
        id=identity.id,
        identity_type=identity.identity_type,
        identity_name=identity.identity_name,
        role_code=identity.role_code,
        tenant_id=identity.tenant_id,
        tenant_name=identity.tenant.name if identity.tenant else None,
        is_default=identity.is_default,
    ).model_dump()


def session_payload(db: Session, user: User, identity: UserIdentity, identities: list[UserIdentity]) -> dict:
    # 菜单权限随会话返回，前端只渲染数据库授权菜单，不再写死平台/客户菜单。
    menus = [item.model_dump() for item in get_identity_menus(db, identity)]
    return {
        "access_token": create_access_token(user, identity),
        "token_type": "bearer",
        "user": {"id": user.id, "username": user.username, "display_name": user.display_name},
        "identity": identity_info(identity),
        "identities": [identity_info(item) for item in identities],
        "menus": menus,
    }


@router.post("/login", response_model=ApiResponse[dict])
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> ApiResponse[dict]:
    result = authenticate(db, payload.username, payload.password)
    if result is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="账号或密码错误")
    user, identities = result
    if len(identities) == 1:
        return ApiResponse(data={"requires_identity_selection": False, "session": session_payload(db, user, identities[0], identities)})
    return ApiResponse(data={
        "requires_identity_selection": True,
        "ticket": create_identity_ticket(user),
        "user": {"id": user.id, "username": user.username, "display_name": user.display_name},
        "identities": [identity_info(item) for item in identities],
    })


@router.post("/select-identity", response_model=ApiResponse[dict])
def select_identity(payload: IdentitySelectRequest, db: Session = Depends(get_db)) -> ApiResponse[dict]:
    try:
        claims = decode_token(payload.ticket)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    if claims.get("scope") != "identity_selection":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="身份选择凭证无效")
    user = db.scalar(select(User).where(User.id == int(claims["sub"]), User.status.is_(True)))
    identity = db.scalar(
        select(UserIdentity)
        .options(joinedload(UserIdentity.tenant))
        .where(UserIdentity.id == payload.identity_id, UserIdentity.user_id == int(claims["sub"]), UserIdentity.status.is_(True))
    )
    if user is None or identity is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权使用该身份")
    identities = list(db.scalars(select(UserIdentity).options(joinedload(UserIdentity.tenant)).where(UserIdentity.user_id == user.id, UserIdentity.status.is_(True), UserIdentity.deleted.is_(False))))
    return ApiResponse(data=session_payload(db, user, identity, identities))


@router.get("/me", response_model=ApiResponse[dict])
def me(current: CurrentSession = Depends(get_current_session), db: Session = Depends(get_db)) -> ApiResponse[dict]:
    identities = list(db.scalars(select(UserIdentity).options(joinedload(UserIdentity.tenant)).where(UserIdentity.user_id == current.user.id, UserIdentity.status.is_(True), UserIdentity.deleted.is_(False))))
    return ApiResponse(data={
        "user": {"id": current.user.id, "username": current.user.username, "display_name": current.user.display_name},
        "identity": identity_info(current.identity),
        "identities": [identity_info(item) for item in identities],
        "menus": [item.model_dump() for item in get_identity_menus(db, current.identity)],
    })


@router.post("/switch-identity", response_model=ApiResponse[dict])
def switch_identity(
    payload: IdentitySwitchRequest,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    identity = db.scalar(
        select(UserIdentity)
        .options(joinedload(UserIdentity.tenant))
        .where(
            UserIdentity.id == payload.identity_id,
            UserIdentity.user_id == current.user.id,
            UserIdentity.status.is_(True),
            UserIdentity.deleted.is_(False),
        )
    )
    if identity is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权使用该身份")
    identities = list(db.scalars(select(UserIdentity).options(joinedload(UserIdentity.tenant)).where(UserIdentity.user_id == current.user.id, UserIdentity.status.is_(True), UserIdentity.deleted.is_(False))))
    return ApiResponse(data=session_payload(db, current.user, identity, identities))
