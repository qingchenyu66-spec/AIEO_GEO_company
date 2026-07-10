from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.main import app
from app.models.tenant import Tenant
from app.models.user import User
from app.models.user_identity import UserIdentity

client = TestClient(app)


@pytest.fixture()
def auth_seed() -> Iterator[dict[str, str]]:
    """创建独立登录测试数据，避免依赖演示账号或现网账号状态。"""
    suffix = uuid4().hex[:10]
    password = "GeoTest@2026"
    dual_username = f"pytest_dual_{suffix}"
    single_username = f"pytest_single_{suffix}"

    db = SessionLocal()
    created_user_ids: list[int] = []
    created_tenant_ids: list[int] = []
    try:
        tenant = Tenant(
            name=f"测试企业_{suffix}",
            code=f"PYTEST_{suffix}",
            status=True,
        )
        db.add(tenant)
        db.flush()
        created_tenant_ids.append(tenant.id)

        dual_user = User(
            username=dual_username,
            password_hash=hash_password(password),
            display_name="双身份测试用户",
            status=True,
        )
        single_user = User(
            username=single_username,
            password_hash=hash_password(password),
            display_name="单身份测试用户",
            status=True,
        )
        db.add_all([dual_user, single_user])
        db.flush()
        created_user_ids.extend([dual_user.id, single_user.id])

        db.add_all(
            [
                UserIdentity(
                    identity_code=f"pytest_platform_{suffix}",
                    user_id=dual_user.id,
                    identity_type="PLATFORM",
                    identity_name="平台测试身份",
                    role_code="platform_admin",
                    is_default=True,
                    status=True,
                ),
                UserIdentity(
                    identity_code=f"pytest_customer_dual_{suffix}",
                    user_id=dual_user.id,
                    tenant_id=tenant.id,
                    identity_type="CUSTOMER",
                    identity_name="客户测试身份",
                    role_code="customer_admin",
                    is_default=False,
                    status=True,
                ),
                UserIdentity(
                    identity_code=f"pytest_customer_single_{suffix}",
                    user_id=single_user.id,
                    tenant_id=tenant.id,
                    identity_type="CUSTOMER",
                    identity_name="客户单身份",
                    role_code="customer_admin",
                    is_default=True,
                    status=True,
                ),
            ]
        )
        db.commit()
        yield {
            "password": password,
            "dual_username": dual_username,
            "single_username": single_username,
        }
    finally:
        db.rollback()
        for identity in db.scalars(
            select(UserIdentity).where(UserIdentity.user_id.in_(created_user_ids))
        ):
            db.delete(identity)
        for user in db.scalars(select(User).where(User.id.in_(created_user_ids))):
            db.delete(user)
        for tenant in db.scalars(select(Tenant).where(Tenant.id.in_(created_tenant_ids))):
            db.delete(tenant)
        db.commit()
        db.close()


def test_dual_identity_login_and_select(auth_seed: dict[str, str]) -> None:
    login = client.post(
        "/api/v1/auth/login",
        json={"username": auth_seed["dual_username"], "password": auth_seed["password"]},
    )
    assert login.status_code == 200
    data = login.json()["data"]
    assert data["requires_identity_selection"] is True
    assert len(data["identities"]) == 2

    platform_identity = next(item for item in data["identities"] if item["identity_type"] == "PLATFORM")
    selected = client.post(
        "/api/v1/auth/select-identity",
        json={"ticket": data["ticket"], "identity_id": platform_identity["id"]},
    )
    assert selected.status_code == 200
    session = selected.json()["data"]
    assert session["identity"]["identity_type"] == "PLATFORM"

    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {session['access_token']}"})
    assert me.status_code == 200
    assert me.json()["data"]["identity"]["identity_type"] == "PLATFORM"

    customer_identity = next(item for item in session["identities"] if item["identity_type"] == "CUSTOMER")
    switched = client.post(
        "/api/v1/auth/switch-identity",
        json={"identity_id": customer_identity["id"]},
        headers={"Authorization": f"Bearer {session['access_token']}"},
    )
    assert switched.status_code == 200
    assert switched.json()["data"]["identity"]["identity_type"] == "CUSTOMER"


def test_stopped_tenant_login_shows_service_message(auth_seed: dict[str, str]) -> None:
    db = SessionLocal()
    try:
        user = db.scalar(
            select(User)
            .options(joinedload(User.identities).joinedload(UserIdentity.tenant))
            .where(User.username == auth_seed["single_username"])
        )
        assert user is not None
        tenant = next(item.tenant for item in user.identities if item.tenant_id is not None)
        tenant.status = False
        tenant.stop_reason = "manual"
        user.status = False
        for identity in user.identities:
            identity.status = False
            identity.deleted = True
        db.commit()
    finally:
        db.close()

    login = client.post(
        "/api/v1/auth/login",
        json={"username": auth_seed["single_username"], "password": auth_seed["password"]},
    )
    assert login.status_code == 401
    assert login.json()["detail"] == "企业服务已停止，请联系运营人员"


def test_single_identity_login(auth_seed: dict[str, str]) -> None:
    login = client.post(
        "/api/v1/auth/login",
        json={"username": auth_seed["single_username"], "password": auth_seed["password"]},
    )
    assert login.status_code == 200
    data = login.json()["data"]
    assert data["requires_identity_selection"] is False
    assert data["session"]["identity"]["identity_type"] == "CUSTOMER"
