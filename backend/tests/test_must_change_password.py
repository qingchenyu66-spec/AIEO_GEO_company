"""历史强制改密标记不再拦截登录, 自助改密仍可用."""
from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.main import app
from app.models.user import User
from app.models.user_identity import UserIdentity

client = TestClient(app)


def test_stale_must_change_password_does_not_block() -> None:
    suffix = uuid4().hex[:8]
    username = f"mcp_{suffix}"
    password = "Init@2026"
    new_password = "Changed@2026"

    db = SessionLocal()
    try:
        user = User(
            username=username,
            password_hash=hash_password(password),
            display_name="强制改密测试",
            must_change_password=True,
            status=True,
        )
        db.add(user)
        db.flush()
        identity = UserIdentity(
            identity_code=f"MCP_{suffix}",
            user_id=user.id,
            identity_type="PLATFORM",
            identity_name="平台测试",
            role_code="PLATFORM_ADMIN",
            is_default=True,
            status=True,
        )
        db.add(identity)
        db.commit()
        user_id = user.id
    finally:
        db.close()

    try:
        login = client.post("/api/v1/auth/login", json={"username": username, "password": password})
        assert login.status_code == 200, login.text
        session = login.json()["data"]["session"]
        assert session["user"]["must_change_password"] is False
        token = session.get("access_token")
        headers = {"Authorization": f"Bearer {token}"} if token else {}

        me = client.get("/api/v1/auth/me", headers=headers)
        assert me.status_code == 200
        assert me.json()["data"]["user"]["must_change_password"] is False

        overview = client.get("/api/v1/management/overview", headers=headers)
        assert "必须先修改登录密码" not in str(overview.json().get("detail", ""))

        ok = client.post(
            "/api/v1/auth/change-password",
            headers=headers,
            json={"old_password": password, "new_password": new_password},
        )
        assert ok.status_code == 200, ok.text
        assert ok.json()["data"]["must_change_password"] is False
    finally:
        db = SessionLocal()
        try:
            user = db.scalar(select(User).where(User.id == user_id))
            if user is not None:
                for ident in list(db.scalars(select(UserIdentity).where(UserIdentity.user_id == user.id))):
                    db.delete(ident)
                db.delete(user)
                db.commit()
        finally:
            db.close()
