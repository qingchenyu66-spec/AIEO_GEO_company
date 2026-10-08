from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.config import settings
from app.core.security import create_token, password_needs_rehash, hash_password, verify_password
from app.models.user import User
from app.models.user_identity import UserIdentity
class LoginRejected(Exception):
    """密码正确但账号/企业不可登录。"""

    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(detail)


def get_user_by_username(db: Session, username: str) -> User | None:
    return db.scalar(
        select(User)
        .options(joinedload(User.identities).joinedload(UserIdentity.tenant))
        .where(User.username == username, User.status.is_(True), User.deleted.is_(False))
    )


def get_user_for_login(db: Session, username: str) -> User | None:
    return db.scalar(
        select(User)
        .options(joinedload(User.identities).joinedload(UserIdentity.tenant))
        .where(User.username == username, User.deleted.is_(False))
    )


def active_identities(user: User) -> list[UserIdentity]:
    # 2026-08-03 - 服务未开始/到期/停服仍可登录用非模力；仅企业软删挡客户身份
    result: list[UserIdentity] = []
    for item in user.identities:
        if not item.status or item.deleted:
            continue
        if item.identity_type == "CUSTOMER":
            tenant = item.tenant
            if tenant is None or bool(getattr(tenant, "deleted", False)):
                continue
        result.append(item)
    return result


def mark_password_changed(user: User) -> None:
    """真的更换密码时调用. 登录时重算哈希不算改密."""
    user.password_changed_at = datetime.now(UTC).replace(tzinfo=None)


def login_block_reason(user: User) -> str:
    for item in user.identities:
        if item.identity_type != "CUSTOMER" or item.tenant_id is None:
            continue
        tenant = item.tenant
        if tenant is not None and bool(getattr(tenant, "deleted", False)):
            return "企业已删除，请联系运营人员"
    return "账号已停用，请联系运营人员"


def authenticate(db: Session, username: str, password: str) -> tuple[User, list[UserIdentity]] | None:
    user = get_user_for_login(db, username)
    if user is None or not verify_password(password, user.password_hash):
        return None
    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
        db.flush()
    # 2026-10-08 - 不再强制改密. 历史标记在本次登录清掉, 避免旧会话还被前端拉去改密页
    if user.must_change_password:
        user.must_change_password = False
        db.flush()
    if not user.status:
        raise LoginRejected(login_block_reason(user))
    identities = active_identities(user)
    if not identities:
        raise LoginRejected(login_block_reason(user))
    return user, identities


def authenticate_observer_demo(db: Session) -> tuple[User, list[UserIdentity]]:
    """H5 一键体验：免密登录写死的艾迪亚观察号（仅该账号）。"""
    # 2026-09-01 - 落地页样例体验不暴露密码；开关关闭或账号缺失则拒绝
    if not settings.h5_observer_demo_login_enabled:
        raise LoginRejected("样例体验暂未开放")
    from app.services.observer_account import OBSERVER_USERNAME

    user = get_user_for_login(db, OBSERVER_USERNAME)
    if user is None or not user.status:
        raise LoginRejected("样例账号未就绪，请联系顾问")
    identities = active_identities(user)
    # 优先客户身份，避免观察号误带平台身份时进错门户
    customer = [item for item in identities if item.identity_type == "CUSTOMER"]
    chosen = customer or identities
    if not chosen:
        raise LoginRejected("样例账号未就绪，请联系顾问")
    return user, chosen


def create_identity_ticket(user: User) -> str:
    return create_token(user.id, "identity_selection", settings.identity_ticket_expire_minutes)


def create_access_token(
    user: User,
    identity: UserIdentity,
    *,
    auth_time: datetime | None = None,
) -> str:
    """Issue access JWT. auth_time is original login instant; omit to start a new session."""
    at = auth_time or datetime.now(UTC)
    if at.tzinfo is None:
        at = at.replace(tzinfo=UTC)
    return create_token(
        user.id,
        "access",
        settings.access_token_expire_minutes,
        identity_id=identity.id,
        identity_type=identity.identity_type,
        tenant_id=identity.tenant_id,
        role_code=identity.role_code,
        auth_time=int(at.timestamp()),
    )

