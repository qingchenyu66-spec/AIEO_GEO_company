"""pytest 全局 fixture：测试环境放宽 Cookie/CSRF 策略。"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models.user import User
from app.models.user_identity import UserIdentity


@pytest.fixture
def db() -> Session:
    """算力等单测默认会话：服务层 commit 降级为 flush，结束 rollback，避免污染本地库。

    HTTP 写测若必须真实落库，请自建 SessionLocal 并在 teardown 主动 purge。
    """
    session = SessionLocal()

    def _flush_only() -> None:
        session.flush()

    # 2026-09-09 - 禁止单测路径把写测企业 commit 进共用库
    session.commit = _flush_only  # type: ignore[method-assign]
    try:
        yield session
        session.rollback()
    finally:
        session.close()


@pytest.fixture(autouse=True)
def _relax_auth_for_tests() -> None:
    """保留 JSON access_token 供 TestClient 使用 Bearer；关闭 CSRF 避免每个用例重复带头。"""
    settings.auth_expose_token_in_body = True
    settings.auth_csrf_enabled = False


@pytest.fixture(autouse=True, scope="session")
def _ensure_demo_platform_login() -> None:
    """测试环境固定账号夹具，避免本地库里的 demo 账号被业务用例停用后影响回归。"""
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == "demo"))
        if user is None:
            user = User(
                username="demo",
                password_hash=hash_password("Geo@2026"),
                display_name="平台测试账号",
                status=True,
                deleted=False,
            )
            db.add(user)
            db.flush()
        else:
            user.password_hash = hash_password("Geo@2026")
            user.status = True
            user.deleted = False

        identity = db.scalar(
            select(UserIdentity).where(
                UserIdentity.user_id == user.id,
                UserIdentity.identity_type == "PLATFORM",
            )
        )
        if identity is None:
            identity = UserIdentity(
                identity_code=f"pytest_platform_{user.id}",
                user_id=user.id,
                tenant_id=None,
                position_id=None,
                identity_type="PLATFORM",
                identity_name="平台管理员",
                role_code="PLATFORM_ADMIN",
                is_default=True,
                status=True,
                deleted=False,
            )
            db.add(identity)
        else:
            identity.identity_name = identity.identity_name or "平台管理员"
            identity.role_code = identity.role_code or "PLATFORM_ADMIN"
            identity.status = True
            identity.deleted = False
            identity.is_default = True
        db.commit()


@pytest.fixture(autouse=True, scope="session")
def _sweep_credit_test_junk_tenants() -> None:
    """会话起止清掉算力写测垃圾企业，兜底 HTTP 夹具/历史残留。"""
    try:
        from scripts.cleanup_credit_test_junk import purge_junk_tenants
    except ImportError:
        # 生产机未必带本地清理脚本；缺模块时跳过，勿堵掉整仓 pytest
        yield
        return

    def _purge() -> None:
        with SessionLocal() as db:
            purged, orphans = purge_junk_tenants(db)
            if purged or orphans:
                db.commit()
                print(f"[pytest] credit junk sweep: tenants={purged} orphans={orphans}")

    _purge()
    yield
    _purge()
