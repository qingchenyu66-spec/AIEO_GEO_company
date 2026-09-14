from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.api.dependencies import CurrentSession, get_current_session
from app.core.database import get_db
from app.core.auth_cookie import (
    clear_auth_cookie,
    clear_csrf_cookie,
    generate_csrf_token,
    set_auth_cookie,
    set_csrf_cookie,
)
from app.core.config import settings
from app.core.http_rate_limit import enforce_identity_select_rate_limit, enforce_login_rate_limit
from app.core.security import decode_token
from app.models.user import User
from app.models.user_identity import UserIdentity
from app.models.permission import Position
from app.schemas.auth import (
    ChangePasswordRequest,
    IdentityInfo,
    IdentitySelectRequest,
    IdentitySwitchRequest,
    LoginRequest,
)
from app.schemas.common import ApiResponse
from app.services.auth_service import (
    LoginRejected,
    authenticate,
    authenticate_observer_demo,
    change_own_password,
    create_access_token,
    create_identity_ticket,
)
from app.services.menu_permission_service import ensure_identity_menus_from_position
from app.services.permission_service import get_identity_menus

router = APIRouter(prefix="/auth")


def _user_public(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "must_change_password": bool(getattr(user, "must_change_password", False)),
    }


def identity_info(identity: UserIdentity, db: Session) -> dict:
    position_name = None
    position_code = None
    if identity.position_id:
        position = db.scalar(
            select(Position).where(Position.id == identity.position_id, Position.deleted.is_(False))
        )
        if position is not None:
            position_name = position.position_name
            position_code = position.position_code
    return IdentityInfo(
        id=identity.id,
        identity_type=identity.identity_type,
        identity_name=identity.identity_name,
        role_code=identity.role_code,
        position_id=identity.position_id,
        position_name=position_name,
        position_code=position_code,
        tenant_id=identity.tenant_id,
        tenant_name=identity.tenant.name if identity.tenant else None,
        tenant_has_logo=bool(identity.tenant and identity.tenant.logo_path),
        tenant_logo_updated_at=(
            identity.tenant.logo_updated_at.isoformat(sep=" ", timespec="seconds")
            if identity.tenant and identity.tenant.logo_updated_at
            else None
        ),
        is_default=identity.is_default,
    ).model_dump()


def session_payload(
    db: Session,
    user: User,
    identity: UserIdentity,
    identities: list[UserIdentity],
    *,
    auth_time: datetime | None = None,
) -> dict:
    # 菜单权限随会话返回，前端只渲染数据库授权菜单，不再写死平台/客户菜单。
    if ensure_identity_menus_from_position(db, identity):
        db.commit()
    from app.services.menu_permission_service import identity_allowed_monitor_platforms

    menus = [item.model_dump() for item in get_identity_menus(db, identity)]
    customer_includes_today = False
    if identity.identity_type == "CUSTOMER" and identity.tenant_id:
        # 2026-09-02 - credit 助手未随 auth 上线时 ImportError → /me 500 踢登录
        try:
            from app.services.monitor_service import credit_customer_includes_today

            customer_includes_today = bool(credit_customer_includes_today(db, identity.tenant_id))
        except Exception:
            customer_includes_today = False
    return {
        "access_token": create_access_token(user, identity, auth_time=auth_time),
        "token_type": "bearer",
        "user": _user_public(user),
        "identity": identity_info(identity, db),
        "identities": [identity_info(item, db) for item in identities],
        "menus": menus,
        "allowed_monitor_platforms": identity_allowed_monitor_platforms(db, identity),
        "customer_includes_today": customer_includes_today,
    }


def public_session(session: dict) -> dict:
    """浏览器 Cookie 模式下不在 JSON 中回传 token。"""
    if not settings.auth_cookie_enabled or settings.auth_expose_token_in_body:
        return session
    return {key: value for key, value in session.items() if key not in {"access_token", "token_type"}}


def _attach_session_cookie(response: Response, session: dict | None) -> None:
    if not settings.auth_cookie_enabled or not session:
        return
    token = session.get("access_token")
    if token:
        set_auth_cookie(response, token)
        if settings.auth_csrf_enabled:
            set_csrf_cookie(response, generate_csrf_token())


def _clear_session_cookies(response: Response) -> None:
    clear_auth_cookie(response)
    clear_csrf_cookie(response)


@router.post("/login", response_model=ApiResponse[dict])
def login(payload: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)) -> ApiResponse[dict]:
    enforce_login_rate_limit(request)
    try:
        result = authenticate(db, payload.username, payload.password)
    except LoginRejected as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=exc.detail) from exc
    if result is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="账号或密码错误")
    user, identities = result
    db.commit()
    if len(identities) == 1:
        session = session_payload(db, user, identities[0], identities)
        _attach_session_cookie(response, session)
        return ApiResponse(data={"requires_identity_selection": False, "session": public_session(session)})
    return ApiResponse(data={
        "requires_identity_selection": True,
        "ticket": create_identity_ticket(user),
        "user": _user_public(user),
        "identities": [identity_info(item, db) for item in identities],
    })


@router.post("/demo/observer", response_model=ApiResponse[dict])
def demo_observer_login(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """H5 落地页一键体验：免密进入艾迪亚观察号客户门户。"""
    # 2026-09-01 - 与 login 同限流，避免被刷成会话洪泛
    enforce_login_rate_limit(request)
    try:
        user, identities = authenticate_observer_demo(db)
    except LoginRejected as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=exc.detail) from exc
    identity = identities[0]
    session = session_payload(db, user, identity, identities)
    _attach_session_cookie(response, session)
    return ApiResponse(
        data={
            "requires_identity_selection": False,
            "session": public_session(session),
        }
    )


@router.post("/select-identity", response_model=ApiResponse[dict])
def select_identity(payload: IdentitySelectRequest, request: Request, response: Response, db: Session = Depends(get_db)) -> ApiResponse[dict]:
    enforce_identity_select_rate_limit(request)
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
    session = session_payload(db, user, identity, identities)
    _attach_session_cookie(response, session)
    return ApiResponse(data=public_session(session))


@router.post("/logout", response_model=ApiResponse[dict])
def logout(response: Response) -> ApiResponse[dict]:
    """退出登录：幂等清理 Cookie；无有效会话也返回成功。"""
    _clear_session_cookies(response)
    return ApiResponse(data={"ok": True})


@router.post("/refresh", response_model=ApiResponse[dict])
def refresh_session(
    response: Response,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """Sliding renew: extend idle TTL from last real activity; keep original auth_time."""
    identities = list(
        db.scalars(
            select(UserIdentity)
            .options(joinedload(UserIdentity.tenant))
            .where(
                UserIdentity.user_id == current.user.id,
                UserIdentity.status.is_(True),
                UserIdentity.deleted.is_(False),
            )
        )
    )
    session = session_payload(
        db,
        current.user,
        current.identity,
        identities,
        auth_time=current.auth_time,
    )
    _attach_session_cookie(response, session)
    return ApiResponse(data={"ok": True})


@router.get("/me", response_model=ApiResponse[dict])
def me(current: CurrentSession = Depends(get_current_session), db: Session = Depends(get_db)) -> ApiResponse[dict]:
    identities = list(db.scalars(select(UserIdentity).options(joinedload(UserIdentity.tenant)).where(UserIdentity.user_id == current.user.id, UserIdentity.status.is_(True), UserIdentity.deleted.is_(False))))
    if ensure_identity_menus_from_position(db, current.identity):
        db.commit()
    # 2026-07-30 - /me 刷新会话冲掉平台白名单 - 与 login/switch 同口径带回 allowed_monitor_platforms
    from app.services.menu_permission_service import identity_allowed_monitor_platforms

    customer_includes_today = False
    if current.identity.identity_type == "CUSTOMER" and current.identity.tenant_id:
        # 2026-09-02 - credit 助手未随 auth 上线时 ImportError → /me 500 踢登录
        try:
            from app.services.monitor_service import credit_customer_includes_today

            customer_includes_today = bool(credit_customer_includes_today(db, current.identity.tenant_id))
        except Exception:
            customer_includes_today = False

    return ApiResponse(data={
        "user": _user_public(current.user),
        "identity": identity_info(current.identity, db),
        "identities": [identity_info(item, db) for item in identities],
        "menus": [item.model_dump() for item in get_identity_menus(db, current.identity)],
        "allowed_monitor_platforms": identity_allowed_monitor_platforms(db, current.identity),
        "customer_includes_today": customer_includes_today,
    })


@router.post("/change-password", response_model=ApiResponse[dict])
def change_password(
    payload: ChangePasswordRequest,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """登录用户修改密码；新建/重置账号后的强制改密也走此接口。"""
    try:
        change_own_password(
            db,
            current.user,
            old_password=payload.old_password,
            new_password=payload.new_password,
        )
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ApiResponse(data={"ok": True, "must_change_password": False})


@router.post("/switch-identity", response_model=ApiResponse[dict])
def switch_identity(
    payload: IdentitySwitchRequest,
    response: Response,
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
    session = session_payload(
        db,
        current.user,
        identity,
        identities,
        auth_time=current.auth_time,
    )
    _attach_session_cookie(response, session)
    return ApiResponse(data=public_session(session))
