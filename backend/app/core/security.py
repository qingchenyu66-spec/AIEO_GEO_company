from datetime import UTC, datetime, timedelta
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

ALGORITHM = "HS256"
password_context = CryptContext(
    schemes=["argon2", "pbkdf2_sha256"],
    deprecated=["pbkdf2_sha256"],
)


def hash_password(password: str) -> str:
    return password_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return password_context.verify(password, password_hash)


def password_needs_rehash(password_hash: str) -> bool:
    return password_context.needs_update(password_hash)


def create_token(subject: int, scope: str, expires_minutes: int, **claims: Any) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(subject),
        "scope": scope,
        "iat": now,
        "exp": now + timedelta(minutes=expires_minutes),
        **claims,
    }
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def decode_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    except JWTError as exc:
        raise ValueError("登录状态无效或已过期") from exc
