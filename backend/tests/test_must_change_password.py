"""强制改密：创建置位、业务 API 闸门、改密后放行。"""
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


def test_must_change_password_blocks_then_clears() -> None:
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
        assert session["user"]["must_change_password"] is True
        token = session.get("access_token")
        headers = {"Authorization": f"Bearer {token}"} if token else {}

        blocked = client.get("/api/v1/management/overview", headers=headers)
        assert blocked.status_code == 403
        assert "必须先修改登录密码" in str(blocked.json().get("detail"))

        me = client.get("/api/v1/auth/me", headers=headers)
        assert me.status_code == 200

        bad = client.post(
            "/api/v1/auth/change-password",
            headers=headers,
            json={"old_password": password, "new_password": password},
        )
        assert bad.status_code == 400

        ok = client.post(
            "/api/v1/auth/change-password",
            headers=headers,
            json={"old_password": password, "new_password": new_password},
        )
        assert ok.status_code == 200, ok.text

        allowed = client.get("/api/v1/auth/me", headers=headers)
        assert allowed.status_code == 200
        assert allowed.json()["data"]["user"]["must_change_password"] is False

        # 改密后业务接口应放行（权限不足也可能 403，但不能再是强制改密文案）
        after = client.get("/api/v1/management/overview", headers=headers)
        assert "必须先修改登录密码" not in str(after.json().get("detail", ""))
        assert after.status_code in (200, 403)
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
