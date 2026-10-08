"""历史强制改密标记不再拦截登录, 自助改密仍可用."""
from __future__ import annotations

import time
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.security import hash_password
from app.main import app
from app.models.user import User
from app.models.user_identity import UserIdentity
from app.services.sms_login_service import apply_login_phone

client = TestClient(app)


def test_stale_must_change_password_does_not_block(monkeypatch) -> None:
    monkeypatch.setattr("app.services.sms_login_service.redis_enabled", lambda: False)
    monkeypatch.setattr(settings, "debug", True)
    monkeypatch.setattr(settings, "aliyun_sms_enabled", False)
    monkeypatch.setattr(settings, "http_login_rate_per_minute", 1000)
    from app.services import sms_login_service

    sms_login_service._MEMORY.clear()
    suffix = uuid4().hex[:8]
    username = f"mcp_{suffix}"
    password = "Init@2026"
    new_password = "Changed@2026"
    phone = f"131{uuid4().int % 100000000:08d}"

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
        apply_login_phone(db, user, phone)
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
        csrf = client.cookies.get("geo_csrf_token")
        if csrf:
            headers["X-CSRF-Token"] = csrf

        me = client.get("/api/v1/auth/me", headers=headers)
        assert me.status_code == 200
        assert me.json()["data"]["user"]["must_change_password"] is False

        overview = client.get("/api/v1/management/overview", headers=headers)
        assert "必须先修改登录密码" not in str(overview.json().get("detail", ""))

        time.sleep(1.1)
        sent = client.post("/api/v1/auth/phone/code", headers=headers, json={"purpose": "password"})
        assert sent.status_code == 200, sent.text
        code = sent.json()["data"]["dev_code"]
        ok = client.post(
            "/api/v1/auth/change-password",
            headers=headers,
            json={"code": code, "new_password": new_password},
        )
        assert ok.status_code == 200, ok.text
        assert ok.json()["data"]["must_change_password"] is False
        db_check = SessionLocal()
        try:
            changed_at = db_check.get(User, user_id).password_changed_at
        finally:
            db_check.close()
        assert changed_at is not None, "password_changed_at was not stored"
        old_token = client.cookies.get("geo_access_token") or token
        other = TestClient(app)
        stale = other.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {old_token}"})
        assert stale.status_code == 401
        assert stale.json()["detail"] == "密码已变更, 请重新登录"
        relogin = client.post("/api/v1/auth/login", json={"username": username, "password": new_password})
        assert relogin.status_code == 200, relogin.text
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
