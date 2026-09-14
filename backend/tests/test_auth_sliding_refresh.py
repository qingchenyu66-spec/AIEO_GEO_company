"""Sliding session renew: idle TTL extend via /auth/refresh; absolute cap from auth_time."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.security import ALGORITHM, hash_password
from app.main import app
from app.models.user import User
from app.models.user_identity import UserIdentity
from app.services.auth_service import create_access_token

client = TestClient(app)


@pytest.fixture()
def sliding_user() -> dict[str, str | int]:
    suffix = uuid4().hex[:10]
    username = f"pytest_slide_{suffix}"
    password = "GeoTest@2026"
    db = SessionLocal()
    try:
        user = User(
            username=username,
            password_hash=hash_password(password),
            display_name="滑动续期测试",
            status=True,
        )
        db.add(user)
        db.flush()
        identity = UserIdentity(
            identity_code=f"pytest_slide_plat_{suffix}",
            user_id=user.id,
            identity_type="PLATFORM",
            identity_name="平台测试身份",
            role_code="platform_admin",
            is_default=True,
            status=True,
        )
        db.add(identity)
        db.commit()
        return {"username": username, "password": password, "user_id": user.id, "identity_id": identity.id}
    finally:
        db.close()

    # unreachable; cleanup in teardown via yield would be nicer but keep simple
    return {}


def _login(username: str, password: str) -> None:
    r = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text


def test_refresh_extends_cookie(sliding_user: dict[str, str | int]) -> None:
    _login(str(sliding_user["username"]), str(sliding_user["password"]))
    before = client.cookies.get("geo_access_token")
    assert before
    payload_before = jwt.decode(before, settings.secret_key, algorithms=[ALGORITHM])
    assert "auth_time" in payload_before

    r = client.post("/api/v1/auth/refresh")
    assert r.status_code == 200, r.text
    assert r.json()["data"]["ok"] is True
    assert "geo_access_token" in r.headers.get("set-cookie", "").lower() or client.cookies.get("geo_access_token")
    after = client.cookies.get("geo_access_token")
    assert after
    payload_after = jwt.decode(after, settings.secret_key, algorithms=[ALGORITHM])
    assert payload_after["auth_time"] == payload_before["auth_time"]
    assert payload_after["sub"] == payload_before["sub"]
    assert payload_after["identity_id"] == payload_before["identity_id"]
    # Still usable
    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200, me.text


def test_absolute_cap_rejects_stale_auth_time(sliding_user: dict[str, str | int]) -> None:
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.id == int(sliding_user["user_id"])))
        identity = db.scalar(select(UserIdentity).where(UserIdentity.id == int(sliding_user["identity_id"])))
        assert user and identity
        stale = datetime.now(UTC) - timedelta(minutes=settings.access_token_absolute_expire_minutes + 5)
        token = create_access_token(user, identity, auth_time=stale)
    finally:
        db.close()

    r = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401
    assert "最长有效期" in (r.json().get("detail") or "")

    r2 = client.post("/api/v1/auth/refresh", headers={"Authorization": f"Bearer {token}"})
    assert r2.status_code == 401
