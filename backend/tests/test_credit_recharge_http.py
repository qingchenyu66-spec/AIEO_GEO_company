"""算力在线充值 HTTP：托管拒单、无 create 拒单。"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.main import app
from app.models.permission import Menu, UserIdentityMenu
from app.models.tenant import Tenant
from app.models.user import User
from app.models.user_identity import UserIdentity
from app.services.auth_service import create_access_token
from app.services.credit_service import BILLING_MODE_CREDIT, BILLING_MODE_HOSTED
from app.services.tenant_purge_service import purge_tenant_thoroughly

client = TestClient(app)


def _make_customer(
    *,
    billing_mode: str,
    as_admin: bool,
) -> dict[str, object]:
    suffix = uuid4().hex[:8]
    password = "GeoTest@2026"
    db = SessionLocal()
    tenant = Tenant(
        name=f"充值HTTP_{suffix}",
        code=f"RH{suffix}",
        billing_mode=billing_mode,
        status=True,
        credit_balance=Decimal("0"),
        credit_reserved=Decimal("0"),
        credit_policy_json={"credits_per_yuan": 4.2},
    )
    db.add(tenant)
    db.flush()
    user = User(
        username=f"recharge_http_{suffix}",
        password_hash=hash_password(password),
        display_name="充值HTTP",
        status=True,
    )
    db.add(user)
    db.flush()
    identity = UserIdentity(
        identity_code=f"recharge_http_{suffix}",
        user_id=user.id,
        tenant_id=tenant.id,
        identity_type="CUSTOMER",
        identity_name="充值客户",
        # customer_admin → enterprise_admin（含 can_create）；其它 → viewer
        role_code="customer_admin" if as_admin else "customer_viewer",
        status=True,
    )
    db.add(identity)
    db.flush()
    menu = db.scalar(select(Menu).where(Menu.menu_code == "customer.enterprise_credit", Menu.deleted.is_(False)))
    assert menu is not None
    db.add(
        UserIdentityMenu(
            identity_id=identity.id,
            menu_id=menu.id,
            can_create=as_admin,
            can_update=True,
            can_delete=False,
            can_export=True,
        )
    )
    db.commit()
    token = create_access_token(user, identity)
    return {"token": token, "tenant_id": tenant.id, "db": db}


def _cleanup(ctx: dict[str, object]) -> None:
    db = ctx["db"]
    tenant_id = int(ctx["tenant_id"])
    tenant = db.get(Tenant, tenant_id)
    if tenant is not None and not tenant.deleted:
        purge_tenant_thoroughly(db, tenant, operator_user_id=1)
        db.commit()
    db.close()


def test_recharge_http_rejects_hosted() -> None:
    ctx = _make_customer(billing_mode=BILLING_MODE_HOSTED, as_admin=True)
    try:
        resp = client.post(
            "/api/v1/customer/enterprise/credit/recharge/orders",
            headers={"Authorization": f"Bearer {ctx['token']}"},
            json={"yuan_amount": 10, "pay_channel": "wechat"},
        )
        assert resp.status_code == 403
    finally:
        _cleanup(ctx)


def test_recharge_http_rejects_without_create(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.core.config.settings.wechat_pay_dev_mode", True)
    ctx = _make_customer(billing_mode=BILLING_MODE_CREDIT, as_admin=False)
    try:
        resp = client.post(
            "/api/v1/customer/enterprise/credit/recharge/orders",
            headers={"Authorization": f"Bearer {ctx['token']}"},
            json={"yuan_amount": 10, "pay_channel": "wechat"},
        )
        assert resp.status_code == 403
    finally:
        _cleanup(ctx)


def test_recharge_http_dev_paid_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.core.config.settings.wechat_pay_dev_mode", True)
    ctx = _make_customer(billing_mode=BILLING_MODE_CREDIT, as_admin=True)
    try:
        create_resp = client.post(
            "/api/v1/customer/enterprise/credit/recharge/orders",
            headers={"Authorization": f"Bearer {ctx['token']}"},
            json={"yuan_amount": 100, "pay_channel": "wechat"},
        )
        assert create_resp.status_code == 200, create_resp.text
        body = create_resp.json()["data"]
        assert body["credits_amount"] == 420.0
        assert body["dev_auto_paid"] is True
        paid_resp = client.post(
            f"/api/v1/customer/enterprise/credit/recharge/orders/{body['out_trade_no']}/dev-paid",
            headers={"Authorization": f"Bearer {ctx['token']}"},
        )
        assert paid_resp.status_code == 200, paid_resp.text
        assert paid_resp.json()["data"]["status"] == "paid"
        summary = client.get(
            "/api/v1/customer/enterprise/credit/summary",
            headers={"Authorization": f"Bearer {ctx['token']}"},
        )
        assert summary.status_code == 200
        assert summary.json()["data"]["available"] == 420.0
        assert summary.json()["data"]["credits_per_yuan"] == 4.2
    finally:
        _cleanup(ctx)


def test_recharge_http_status_pending_then_paid(monkeypatch: pytest.MonkeyPatch) -> None:
    """轮询依赖的状态接口：pending → paid。"""
    monkeypatch.setattr("app.core.config.settings.wechat_pay_dev_mode", True)
    ctx = _make_customer(billing_mode=BILLING_MODE_CREDIT, as_admin=True)
    try:
        headers = {"Authorization": f"Bearer {ctx['token']}"}
        create_resp = client.post(
            "/api/v1/customer/enterprise/credit/recharge/orders",
            headers=headers,
            json={"yuan_amount": 50, "pay_channel": "wechat"},
        )
        assert create_resp.status_code == 200, create_resp.text
        out_trade_no = create_resp.json()["data"]["out_trade_no"]

        pending = client.get(
            f"/api/v1/customer/enterprise/credit/recharge/orders/{out_trade_no}",
            headers=headers,
        )
        assert pending.status_code == 200, pending.text
        assert pending.json()["data"]["status"] == "pending"

        paid = client.post(
            f"/api/v1/customer/enterprise/credit/recharge/orders/{out_trade_no}/dev-paid",
            headers=headers,
        )
        assert paid.status_code == 200, paid.text

        done = client.get(
            f"/api/v1/customer/enterprise/credit/recharge/orders/{out_trade_no}",
            headers=headers,
        )
        assert done.status_code == 200, done.text
        assert done.json()["data"]["status"] == "paid"
        assert done.json()["data"]["credits_amount"] == 210.0
    finally:
        _cleanup(ctx)


def test_recharge_http_cross_tenant_status_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.core.config.settings.wechat_pay_dev_mode", True)
    owner = _make_customer(billing_mode=BILLING_MODE_CREDIT, as_admin=True)
    other = _make_customer(billing_mode=BILLING_MODE_CREDIT, as_admin=True)
    try:
        create_resp = client.post(
            "/api/v1/customer/enterprise/credit/recharge/orders",
            headers={"Authorization": f"Bearer {owner['token']}"},
            json={"yuan_amount": 20, "pay_channel": "wechat"},
        )
        assert create_resp.status_code == 200, create_resp.text
        out_trade_no = create_resp.json()["data"]["out_trade_no"]

        resp = client.get(
            f"/api/v1/customer/enterprise/credit/recharge/orders/{out_trade_no}",
            headers={"Authorization": f"Bearer {other['token']}"},
        )
        assert resp.status_code == 400
        assert "订单不存在" in str(resp.json().get("detail") or "")
    finally:
        _cleanup(other)
        _cleanup(owner)


def test_recharge_http_prod_mode_code_url_and_blocks_dev_paid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.core.config.settings.wechat_pay_dev_mode", False)
    monkeypatch.setattr("app.core.config.settings.alipay_dev_mode", False)
    monkeypatch.setattr(
        "app.services.credit_recharge_service.create_native_code_url",
        lambda **kwargs: "weixin://wxpay/bizpayurl?pr=PRODTEST",
    )
    ctx = _make_customer(billing_mode=BILLING_MODE_CREDIT, as_admin=True)
    try:
        headers = {"Authorization": f"Bearer {ctx['token']}"}
        create_resp = client.post(
            "/api/v1/customer/enterprise/credit/recharge/orders",
            headers=headers,
            json={"yuan_amount": 30, "pay_channel": "wechat"},
        )
        assert create_resp.status_code == 200, create_resp.text
        body = create_resp.json()["data"]
        assert body["code_url"] == "weixin://wxpay/bizpayurl?pr=PRODTEST"
        assert body.get("dev_auto_paid") is False
        assert body["status"] == "pending"

        blocked = client.post(
            f"/api/v1/customer/enterprise/credit/recharge/orders/{body['out_trade_no']}/dev-paid",
            headers=headers,
        )
        assert blocked.status_code == 400
        assert "开发模式" in str(blocked.json().get("detail") or "")
    finally:
        _cleanup(ctx)


def test_wechat_notify_fulfills_credit_recharge(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.core.config.settings.wechat_pay_dev_mode", True)
    ctx = _make_customer(billing_mode=BILLING_MODE_CREDIT, as_admin=True)
    try:
        headers = {"Authorization": f"Bearer {ctx['token']}"}
        create_resp = client.post(
            "/api/v1/customer/enterprise/credit/recharge/orders",
            headers=headers,
            json={"yuan_amount": 40, "pay_channel": "wechat"},
        )
        assert create_resp.status_code == 200, create_resp.text
        out_trade_no = create_resp.json()["data"]["out_trade_no"]

        monkeypatch.setattr(
            "app.api.v1.endpoints.h5_diagnosis.decrypt_notify_resource",
            lambda resource: {
                "trade_state": "SUCCESS",
                "out_trade_no": out_trade_no,
                "transaction_id": "WX-NOTIFY-1",
            },
        )
        notify = client.post("/api/v1/wechat-pay/notify", json={"resource": {"ciphertext": "x"}})
        assert notify.status_code == 200, notify.text
        assert notify.json()["code"] == "SUCCESS"

        status = client.get(
            f"/api/v1/customer/enterprise/credit/recharge/orders/{out_trade_no}",
            headers=headers,
        )
        assert status.status_code == 200
        assert status.json()["data"]["status"] == "paid"
        summary = client.get("/api/v1/customer/enterprise/credit/summary", headers=headers)
        assert summary.json()["data"]["available"] == 168.0
    finally:
        _cleanup(ctx)


def test_alipay_notify_fulfills_credit_recharge(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.core.config.settings.alipay_dev_mode", True)
    monkeypatch.setattr("app.core.config.settings.wechat_pay_dev_mode", False)
    monkeypatch.setattr(
        "app.api.v1.endpoints.h5_diagnosis.verify_notify_signature",
        lambda params: True,
    )
    ctx = _make_customer(billing_mode=BILLING_MODE_CREDIT, as_admin=True)
    try:
        headers = {"Authorization": f"Bearer {ctx['token']}"}
        create_resp = client.post(
            "/api/v1/customer/enterprise/credit/recharge/orders",
            headers=headers,
            json={"yuan_amount": 25, "pay_channel": "alipay"},
        )
        assert create_resp.status_code == 200, create_resp.text
        out_trade_no = create_resp.json()["data"]["out_trade_no"]
        assert create_resp.json()["data"]["dev_auto_paid"] is True

        notify = client.post(
            "/api/v1/alipay/notify",
            data={
                "trade_status": "TRADE_SUCCESS",
                "out_trade_no": out_trade_no,
                "trade_no": "ALI-NOTIFY-1",
            },
        )
        assert notify.status_code == 200, notify.text
        assert notify.text == "success"

        status = client.get(
            f"/api/v1/customer/enterprise/credit/recharge/orders/{out_trade_no}",
            headers=headers,
        )
        assert status.status_code == 200
        assert status.json()["data"]["status"] == "paid"
        summary = client.get("/api/v1/customer/enterprise/credit/summary", headers=headers)
        assert summary.json()["data"]["available"] == 105.0
    finally:
        _cleanup(ctx)
