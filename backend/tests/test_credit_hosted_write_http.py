"""C6：托管企业写企业配置 API 一律 403（HTTP 回归）。"""
from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.services.auth_service import create_access_token
from app.main import app
from app.models.permission import Menu, UserIdentityMenu
from app.models.tenant import Tenant
from app.models.user import User
from app.models.user_identity import UserIdentity
from app.services.billing_mode_service import ENTERPRISE_MENU_CODES
from app.services.credit_service import BILLING_MODE_HOSTED

client = TestClient(app)

HOSTED_WRITE_CASES = [
    ("PUT", "/api/v1/customer/enterprise/monitor", {"tenant_id": 0, "company_full_name": "测试企业有限公司", "brand_name": "测试", "keyword_groups": []}),
    ("POST", "/api/v1/customer/enterprise/monitor/estimate", {}),
    ("POST", "/api/v1/customer/enterprise/monitor/brand-words/estimate", {"run_immediately": False}),
    ("PUT", "/api/v1/customer/enterprise/monitor/brand-words", {"run_immediately": False, "groups": []}),
    ("POST", "/api/v1/customer/enterprise/monitor/competitors", {"tenant_id": 0, "name": "竞品A", "short_name": "A", "category": "直接竞品"}),
    ("POST", "/api/v1/customer/enterprise/members", {"display_name": "成员", "username": "usr_test", "password": "Password1!", "customer_position_id": 1}),
]


@pytest.fixture(scope="module")
def hosted_customer_auth() -> dict[str, object]:
    suffix = uuid4().hex[:8]
    password = "GeoTest@2026"
    username = f"hosted_wr_{suffix}"
    db = SessionLocal()
    tenant_id: int | None = None
    try:
        tenant = Tenant(
            name=f"托管写测_{suffix}",
            code=f"HW{suffix}",
            billing_mode=BILLING_MODE_HOSTED,
            status=True,
        )
        db.add(tenant)
        db.flush()
        tenant_id = tenant.id
        user = User(
            username=username,
            password_hash=hash_password(password),
            display_name="托管写测",
            status=True,
        )
        db.add(user)
        db.flush()
        identity = UserIdentity(
            identity_code=f"hosted_wr_{suffix}",
            user_id=user.id,
            tenant_id=tenant.id,
            identity_type="CUSTOMER",
            identity_name="托管客户",
            role_code="customer_admin",
            status=True,
        )
        db.add(identity)
        db.flush()
        menu_ids = list(
            db.scalars(
                select(Menu.id).where(Menu.menu_code.in_(ENTERPRISE_MENU_CODES), Menu.deleted.is_(False))
            )
        )
        for menu_id in menu_ids:
            db.add(
                UserIdentityMenu(
                    identity_id=identity.id,
                    menu_id=menu_id,
                    can_create=True,
                    can_update=True,
                    can_delete=True,
                    can_export=True,
                )
            )
        db.commit()
        token = create_access_token(user, identity)
        yield {"token": token, "tenant_id": tenant.id}
    finally:
        # 2026-08-28 - 模块夹具 commit 后 rollback 无效 - 跑完用例主动 purge 写测企业
        if tenant_id is not None:
            from app.services.tenant_purge_service import purge_tenant_thoroughly

            tenant = db.get(Tenant, tenant_id)
            if tenant is not None and not tenant.deleted:
                purge_tenant_thoroughly(db, tenant, operator_user_id=1)
                db.commit()
        db.close()


@pytest.mark.parametrize("method,path,body", HOSTED_WRITE_CASES)
def test_hosted_customer_write_returns_403(method, path, body, hosted_customer_auth):
    payload = dict(body)
    if payload.get("tenant_id") == 0:
        payload["tenant_id"] = hosted_customer_auth["tenant_id"]
    headers = {"Authorization": f"Bearer {hosted_customer_auth['token']}"}
    response = client.request(method, path, json=payload, headers=headers)
    assert response.status_code == 403, response.text
    assert "托管" in response.json().get("detail", "") or "403" in str(response.status_code)


def test_hosted_customer_delete_competitor_403(hosted_customer_auth):
    headers = {"Authorization": f"Bearer {hosted_customer_auth['token']}"}
    response = client.delete("/api/v1/customer/enterprise/monitor/competitors/1", headers=headers)
    assert response.status_code == 403


def test_hosted_customer_update_member_403(hosted_customer_auth):
    headers = {"Authorization": f"Bearer {hosted_customer_auth['token']}"}
    response = client.put(
        "/api/v1/customer/enterprise/members/1",
        json={"display_name": "x", "customer_position_id": 1, "status": True},
        headers=headers,
    )
    assert response.status_code == 403


def test_hosted_customer_delete_member_403(hosted_customer_auth):
    headers = {"Authorization": f"Bearer {hosted_customer_auth['token']}"}
    response = client.delete("/api/v1/customer/enterprise/members/1", headers=headers)
    assert response.status_code == 403
