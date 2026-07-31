from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.config import settings
from app.core.security import create_token, password_needs_rehash, hash_password, verify_password
from app.models.user import User
from app.models.user_identity import UserIdentity
from app.services.tenant_account_service import tenant_service_is_operational


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
    return [
        item
        for item in user.identities
        if item.status and not item.deleted and (item.tenant is None or tenant_service_is_operational(item.tenant))
    ]


def login_block_reason(user: User) -> str:
    for item in user.identities:
        if item.identity_type != "CUSTOMER" or item.tenant_id is None:
            continue
        tenant = item.tenant
        if tenant and not tenant_service_is_operational(tenant):
            if tenant.stop_reason in {"manual", "canceled"}:
                return "企业服务已停止，请联系运营人员"
            return "企业服务已停用或已到期，请联系运营人员"
    return "账号已停用，请联系运营人员"


def authenticate(db: Session, username: str, password: str) -> tuple[User, list[UserIdentity]] | None:
    user = get_user_for_login(db, username)
    if user is None or not verify_password(password, user.password_hash):
        return None
    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
        db.flush()
    if not user.status:
        raise LoginRejected(login_block_reason(user))
    identities = active_identities(user)
    if not identities:
        raise LoginRejected(login_block_reason(user))
    return user, identities


def create_identity_ticket(user: User) -> str:
    return create_token(user.id, "identity_selection", settings.identity_ticket_expire_minutes)


def create_access_token(user: User, identity: UserIdentity) -> str:
    return create_token(
        user.id,
        "access",
        settings.access_token_expire_minutes,
        identity_id=identity.id,
        identity_type=identity.identity_type,
        tenant_id=identity.tenant_id,
        role_code=identity.role_code,
    )


def change_own_password(db: Session, user: User, *, old_password: str, new_password: str) -> User:
    """用户自助改密；成功后清除 must_change_password。"""
    if not verify_password(old_password, user.password_hash):
        raise ValueError("当前密码不正确")
    if old_password == new_password:
        raise ValueError("新密码不能与当前密码相同")
    if len(new_password.strip()) < 6:
        raise ValueError("新密码至少 6 个字符")
    user.password_hash = hash_password(new_password)
    user.must_change_password = False
    db.flush()
    return user
