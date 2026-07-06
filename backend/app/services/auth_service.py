from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.config import settings
from app.core.security import create_token, password_needs_rehash, hash_password, verify_password
from app.models.user import User
from app.models.user_identity import UserIdentity


def get_user_by_username(db: Session, username: str) -> User | None:
    return db.scalar(
        select(User)
        .options(joinedload(User.identities).joinedload(UserIdentity.tenant))
        .where(User.username == username, User.status.is_(True), User.deleted.is_(False))
    )


def active_identities(user: User) -> list[UserIdentity]:
    return [item for item in user.identities if item.status and not item.deleted and (item.tenant is None or item.tenant.status)]


def authenticate(db: Session, username: str, password: str) -> tuple[User, list[UserIdentity]] | None:
    user = get_user_by_username(db, username)
    if user is None or not verify_password(password, user.password_hash):
        return None
    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
        db.flush()
    identities = active_identities(user)
    if not identities:
        return None
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

