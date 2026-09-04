"""商品卡 HTTP 集成：菜单、summary、开关拦截（TestClient 绕过登录限流）。"""
from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.database import SessionLocal
from app.main import app
from app.models.tenant import Tenant
from app.models.user import User
from app.models.user_identity import UserIdentity
from app.services.auth_service import create_access_token
from app.services.menu_permission_service import (
    ensure_identity_menus_from_position,
    get_tenant_customer_preview_menus,
    sync_goods_card_menu_for_tenant,
)

client = TestClient(app)


def _token(username: str, *, identity_type: str) -> str:
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.username == username, User.deleted.is_(False)))
        assert user is not None, username
        identity = db.scalar(
            select(UserIdentity).where(
                UserIdentity.user_id == user.id,
                UserIdentity.identity_type == identity_type,
                UserIdentity.deleted.is_(False),
            )
        )
        assert identity is not None, f"{username}/{identity_type}"
        return create_access_token(user, identity)
    finally:
        db.close()


def test_aidiya_preview_menus_include_goods_cards():
    db = SessionLocal()
    try:
        tenant = db.scalar(select(Tenant).where(Tenant.id == 6, Tenant.deleted.is_(False)))
        assert tenant is not None
        assert bool(tenant.goods_card_enabled) is True
        menus = get_tenant_customer_preview_menus(db, tenant.id)
        codes = {item.menu_code for item in menus}
        assert "customer.goods_cards" in codes
    finally:
        db.close()


def test_aidiya_customer_me_has_goods_cards_menu():
    token = _token("Xin", identity_type="CUSTOMER")
    resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    menus = resp.json()["data"]["menus"]
    codes = {m["menu_code"] for m in menus}
    assert "customer.goods_cards" in codes


def test_aidiya_customer_goods_cards_summary_200():
    token = _token("Xin", identity_type="CUSTOMER")
    resp = client.get(
        "/api/v1/analytics/goods-cards/summary",
        params={"days": 7},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert "kpi" in data
    assert "hits" in data
    assert "diagnosis" in data
    assert data["sample_total"] >= 0


def test_disabled_tenant_customer_no_goods_cards_menu():
    token = _token("jinoutuliao", identity_type="CUSTOMER")
    resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    codes = {m["menu_code"] for m in resp.json()["data"]["menus"]}
    assert "customer.goods_cards" not in codes


def test_disabled_tenant_goods_cards_summary_403():
    token = _token("jinoutuliao", identity_type="CUSTOMER")
    resp = client.get(
        "/api/v1/analytics/goods-cards/summary",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403, resp.text


def test_goods_card_grant_survives_auth_me_heal():
    db = SessionLocal()
    try:
        tenant = db.scalar(select(Tenant).where(Tenant.id == 6, Tenant.deleted.is_(False)))
        user = db.scalar(select(User).where(User.username == "Xin", User.deleted.is_(False)))
        identity = db.scalar(
            select(UserIdentity).where(
                UserIdentity.user_id == user.id,
                UserIdentity.identity_type == "CUSTOMER",
                UserIdentity.deleted.is_(False),
            )
        )
        assert tenant and identity
        tenant.goods_card_enabled = True
        sync_goods_card_menu_for_tenant(db, tenant.id, enabled=True)
        db.commit()
        ensure_identity_menus_from_position(db, identity)
        db.commit()
        token = create_access_token(user, identity)
        me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me.status_code == 200, me.text
        codes = {m["menu_code"] for m in me.json()["data"]["menus"]}
        assert "customer.goods_cards" in codes
        summary = client.get(
            "/api/v1/analytics/goods-cards/summary",
            params={"days": 7},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert summary.status_code == 200, summary.text
    finally:
        db.close()


def test_platform_brand_asset_get_returns_goods_card_enabled():
    # 2026-09-04 - 保存后重载依赖 GET 回传，缺字段会被前端当成关闭
    token = _token("demo", identity_type="PLATFORM")
    resp = client.get(
        "/api/v1/brand/asset",
        params={"tenant_id": 6},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert "goods_card_enabled" in data
    assert data["goods_card_enabled"] is True


def test_platform_preview_aidiya_goods_cards_summary():
    token = _token("demo", identity_type="PLATFORM")
    resp = client.get(
        "/api/v1/analytics/goods-cards/summary",
        params={"tenant_id": 6, "days": 7},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["sample_total"] >= 0
