"""手机验证码登录: 4 位码, 建号手机号立即可用, 观察号不能绑."""
from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.security import hash_password
from app.main import app
from app.models.user import User
from app.models.user_identity import UserIdentity
from app.services.observer_account import OBSERVER_USERNAME
from app.services.sms_login_service import apply_login_phone, issue_code, set_phone_login_enabled

client = TestClient(app)


def _use_memory(monkeypatch) -> None:
    monkeypatch.setattr("app.services.sms_login_service.redis_enabled", lambda: False)
    monkeypatch.setattr(settings, "debug", True)
    monkeypatch.setattr(settings, "aliyun_sms_enabled", False)
    monkeypatch.setattr(settings, "http_login_rate_per_minute", 1000)
    from app.services import sms_login_service

    sms_login_service._MEMORY.clear()


def _cleanup(user_id: int) -> None:
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.id == user_id))
        if user is None:
            return
        for ident in list(db.scalars(select(UserIdentity).where(UserIdentity.user_id == user.id))):
            db.delete(ident)
        db.delete(user)
        db.commit()
    finally:
        db.close()


def test_issue_code_is_four_digits(monkeypatch) -> None:
    _use_memory(monkeypatch)
    code = issue_code("13800138000", "login")
    assert len(code) == 4 and code.isdigit()


def test_bind_cooldown_does_not_block_login(monkeypatch) -> None:
    _use_memory(monkeypatch)
    phone = "13800138111"
    issue_code(phone, "bind")
    login_code = issue_code(phone, "login")
    assert len(login_code) == 4 and login_code.isdigit()
    try:
        issue_code(phone, "login")
        raise AssertionError("same purpose should cool down")
    except ValueError as exc:
        assert "稍后再试" in str(exc)


def test_created_phone_can_login_immediately(monkeypatch) -> None:
    _use_memory(monkeypatch)
    suffix = uuid4().hex[:8]
    phone = f"137{uuid4().int % 100000000:08d}"
    username = f"sms_{suffix}"
    db = SessionLocal()
    try:
        user = User(
            username=username,
            password_hash=hash_password("Init@2026"),
            display_name="短信登录测试",
            status=True,
        )
        db.add(user)
        db.flush()
        apply_login_phone(db, user, phone)
        db.add(UserIdentity(
            identity_code=f"SMS_{suffix}",
            user_id=user.id,
            identity_type="PLATFORM",
            identity_name="平台测试",
            role_code="PLATFORM_ADMIN",
            is_default=True,
            status=True,
        ))
        db.commit()
        user_id = user.id
    finally:
        db.close()

    try:
        sent = client.post("/api/v1/auth/sms/login-code", json={"phone": phone})
        assert sent.status_code == 200, sent.text
        dev_code = sent.json()["data"].get("dev_code")
        assert isinstance(dev_code, str) and len(dev_code) == 4
        logged = client.post("/api/v1/auth/sms/login", json={"phone": phone, "code": dev_code})
        assert logged.status_code == 200, logged.text
        assert logged.json()["data"]["session"]["user"]["username"] == username
        again = client.post("/api/v1/auth/sms/login", json={"phone": phone, "code": dev_code})
        assert again.status_code == 401
    finally:
        _cleanup(user_id)


def test_unknown_phone_is_rejected(monkeypatch) -> None:
    _use_memory(monkeypatch)
    sent = client.post("/api/v1/auth/sms/login-code", json={"phone": "13900001111"})
    assert sent.status_code == 400, sent.text
    assert sent.json()["detail"] == "该手机号尚未绑定, 请用账号密码登录, 或联系管理员绑定"


def test_observer_cannot_bind_phone() -> None:
    ghost = User(username=OBSERVER_USERNAME, password_hash="x", display_name="观察号")
    db = SessionLocal()
    try:
        try:
            apply_login_phone(db, ghost, "13800138001")
            raise AssertionError("observer phone should be rejected")
        except ValueError as exc:
            assert "观察号" in str(exc)
    finally:
        db.close()


def test_duplicate_phone_rejected() -> None:
    suffix = uuid4().hex[:6]
    phone = f"136{uuid4().int % 100000000:08d}"
    db = SessionLocal()
    ids: list[int] = []
    try:
        first = User(username=f"ph1_{suffix}", password_hash=hash_password("Init@2026"), display_name="甲", status=True)
        second = User(username=f"ph2_{suffix}", password_hash=hash_password("Init@2026"), display_name="乙", status=True)
        db.add(first)
        db.add(second)
        db.flush()
        apply_login_phone(db, first, phone)
        try:
            apply_login_phone(db, second, phone)
            raise AssertionError("duplicate phone should be rejected")
        except ValueError as exc:
            assert "已绑定" in str(exc)
        db.rollback()
    finally:
        db.close()
        for user_id in ids:
            _cleanup(user_id)


def test_phone_login_requires_a_bound_phone() -> None:
    user = User(username=f"nophone_{uuid4().hex[:6]}", password_hash="x", display_name="无号")
    try:
        set_phone_login_enabled(user, True)
        raise AssertionError("switch should stay off without a phone")
    except ValueError as exc:
        assert "安全手机号" in str(exc)


def test_phone_login_switch_blocks_sms(monkeypatch) -> None:
    _use_memory(monkeypatch)
    suffix = uuid4().hex[:8]
    phone = f"135{uuid4().int % 100000000:08d}"
    username = f"sw_{suffix}"
    password = "Init@2026"
    db = SessionLocal()
    try:
        user = User(
            username=username,
            password_hash=hash_password(password),
            display_name="开关测试",
            status=True,
        )
        db.add(user)
        db.flush()
        apply_login_phone(db, user, phone)
        db.add(UserIdentity(
            identity_code=f"SW_{suffix}",
            user_id=user.id,
            identity_type="PLATFORM",
            identity_name="平台测试",
            role_code="PLATFORM_ADMIN",
            is_default=True,
            status=True,
        ))
        db.commit()
        user_id = user.id
        assert user.phone_login_enabled is True
    finally:
        db.close()

    own = TestClient(app)
    try:
        login = own.post("/api/v1/auth/login", json={"username": username, "password": password})
        assert login.status_code == 200, login.text
        csrf = own.cookies.get("geo_csrf_token")
        headers = {"X-CSRF-Token": csrf} if csrf else {}
        off = own.post("/api/v1/auth/phone/login-enabled", json={"enabled": False}, headers=headers)
        assert off.status_code == 200, off.text
        body = off.json()["data"]
        assert body["phone_login_enabled"] is False
        assert body["phone_masked"]
        blocked = own.post("/api/v1/auth/sms/login-code", json={"phone": phone}, headers=headers)
        assert blocked.status_code == 400, blocked.text
        assert blocked.json()["detail"] == "该手机号未开启验证码登录"
        on = own.post("/api/v1/auth/phone/login-enabled", json={"enabled": True}, headers=headers)
        assert on.status_code == 200, on.text
        assert on.json()["data"]["phone_login_enabled"] is True
        from app.services import sms_login_service

        sms_login_service._MEMORY.clear()
        sent = own.post("/api/v1/auth/sms/login-code", json={"phone": phone}, headers=headers)
        assert sent.status_code == 200, sent.text
        assert isinstance(sent.json()["data"].get("dev_code"), str)
    finally:
        _cleanup(user_id)


def test_failed_send_does_not_keep_cooldown_or_hourly_slot(monkeypatch) -> None:
    _use_memory(monkeypatch)
    monkeypatch.setattr(settings, "sms_hourly_send_limit", 1)
    phone = "13800139900"
    calls = {"n": 0}

    def flaky(target: str, code: str) -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            raise ValueError("短信发送失败, 请稍后再试")
        return code

    monkeypatch.setattr("app.services.sms_login_service.deliver_code", flaky)
    from app.services.sms_login_service import dispatch_code

    try:
        dispatch_code(phone, "login")
        raise AssertionError("first send should fail")
    except ValueError as exc:
        assert str(exc) == "短信发送失败, 请稍后再试"
    sent = dispatch_code(phone, "login")
    assert isinstance(sent, str) and len(sent) == 4
    try:
        dispatch_code(phone, "password")
        raise AssertionError("hourly cap should be shared")
    except ValueError as exc:
        assert str(exc) == "该手机号一小时内发送次数已达上限, 请稍后再试"


def test_forgot_password_uses_bound_phone(monkeypatch) -> None:
    _use_memory(monkeypatch)
    missing = client.post("/api/v1/auth/password/reset-code", json={"username": "no_such_user_xx"})
    assert missing.status_code == 400, missing.text
    assert missing.json()["detail"] == "该账号尚未绑定手机号, 请联系管理员重置密码"

    suffix = uuid4().hex[:8]
    phone = f"136{uuid4().int % 100000000:08d}"
    username = f"rst_{suffix}"
    db = SessionLocal()
    try:
        user = User(
            username=username,
            password_hash=hash_password("Init@2026"),
            display_name="找回密码测试",
            status=True,
        )
        db.add(user)
        db.flush()
        db.add(UserIdentity(
            identity_code=f"RST_{suffix}",
            user_id=user.id,
            identity_type="PLATFORM",
            identity_name="平台测试",
            role_code="PLATFORM_ADMIN",
            is_default=True,
            status=True,
        ))
        db.commit()
        user_id = user.id
        bare = client.post("/api/v1/auth/password/reset-check", json={"username": username})
        assert bare.status_code == 400, bare.text
        assert bare.json()["detail"] == "该账号尚未绑定手机号, 请联系管理员重置密码"
        apply_login_phone(db, user, phone)
        set_phone_login_enabled(user, False)
        db.commit()
    finally:
        db.close()

    try:
        from app.services import sms_login_service

        sms_login_service._MEMORY.clear()
        checked = client.post("/api/v1/auth/password/reset-check", json={"username": username})
        assert checked.status_code == 200, checked.text
        assert "****" in checked.json()["data"]["phone_masked"]
        sent = client.post("/api/v1/auth/password/reset-code", json={"username": username})
        assert sent.status_code == 200, sent.text
        body = sent.json()["data"]
        assert "****" in body["phone_masked"]
        code = body["dev_code"]
        assert isinstance(code, str) and len(code) == 4
        changed = client.post("/api/v1/auth/password/reset", json={
            "username": username,
            "code": code,
            "new_password": "Next@2026",
        })
        assert changed.status_code == 200, changed.text
        old = client.post("/api/v1/auth/login", json={"username": username, "password": "Init@2026"})
        assert old.status_code == 401
        new = client.post("/api/v1/auth/login", json={"username": username, "password": "Next@2026"})
        assert new.status_code == 200, new.text
    finally:
        _cleanup(user_id)
