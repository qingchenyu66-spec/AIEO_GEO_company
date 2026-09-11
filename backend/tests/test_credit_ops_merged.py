"""算力运营页合并后：credit_ops_board 权限可访问 blocks/tenants 列表。"""
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.tenant import Tenant
from app.services.credit_service import credits_from_yuan, dedupe_credit_tenant_list_items

client = TestClient(app)


def test_credit_adjust_allows_amount_with_yuan_audit():
    from app.api.v1.endpoints.credit_management import CreditAdjustRequest

    req = CreditAdjustRequest(amount=Decimal("42"), yuan_amount=Decimal("10"), reason="audit")
    assert req.amount == Decimal("42")
    assert req.yuan_amount == Decimal("10")


def test_credits_from_yuan_default_rate():
    tenant = Tenant(name="t", code="T1", billing_mode="credit", credit_policy_json={})
    assert credits_from_yuan(tenant, Decimal("100")) == Decimal("420.0")


def test_credits_from_yuan_tenant_override():
    tenant = Tenant(
        name="t",
        code="T2",
        billing_mode="credit",
        credit_policy_json={"credits_per_yuan": 4.5},
    )
    assert credits_from_yuan(tenant, Decimal("100")) == Decimal("450.0")


def test_credit_adjust_request_optional_recharge_reason():
    from app.api.v1.endpoints.credit_management import CreditAdjustRequest

    req = CreditAdjustRequest(yuan_amount=Decimal("100"), reason="")
    assert req.reason == ""


def test_credit_adjust_request_deduct_requires_reason():
    import pytest
    from pydantic import ValidationError

    from app.api.v1.endpoints.credit_management import CreditAdjustRequest

    with pytest.raises(ValidationError):
        CreditAdjustRequest(amount=Decimal("-10"), reason="")


def test_dedupe_credit_tenant_list_items_by_name():
    rows = dedupe_credit_tenant_list_items([
        {"tenant_id": 1, "name": "艾迪亚控股集团有限公司", "credit_balance": 10},
        {"tenant_id": 3, "name": "艾迪亚控股集团有限公司", "credit_balance": 10},
        {"tenant_id": 2, "name": "其他企业", "credit_balance": 5},
    ])
    assert len(rows) == 2
    aidiya = next(row for row in rows if row["name"] == "艾迪亚控股集团有限公司")
    assert aidiya["tenant_id"] == 3


def _demo_platform_headers() -> dict[str, str]:
    login = client.post("/api/v1/auth/login", json={"username": "demo", "password": "Geo@2026"})
    assert login.status_code == 200, login.text
    body = login.json()["data"]
    if body.get("requires_identity_selection"):
        platform = next(i for i in body["identities"] if i["identity_type"] == "PLATFORM")
        picked = client.post(
            "/api/v1/auth/select-identity",
            json={"identity_id": platform["id"], "ticket": body["ticket"]},
        )
        token = picked.json()["data"]["access_token"]
    else:
        token = body["session"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_credit_ops_board_can_list_blocks_and_tenants():
    headers = _demo_platform_headers()
    blocks = client.get("/api/v1/management/credit/blocks", headers=headers)
    assert blocks.status_code == 200, blocks.text
    tenants = client.get("/api/v1/management/credit/tenants", headers=headers)
    assert tenants.status_code == 200, tenants.text


def test_credit_platform_ledger_accepts_tenant_name():
    headers = _demo_platform_headers()
    resp = client.get(
        "/api/v1/management/credit/ledger",
        headers=headers,
        params={"page": 1, "page_size": 20, "tenant_name": "demo"},
    )
    assert resp.status_code == 200, resp.text
    assert "items" in resp.json()["data"]


def test_tenant_credit_ledger_exclude_internal_param():
    headers = _demo_platform_headers()
    resp = client.get(
        "/api/v1/management/credit/tenants/1/ledger",
        headers=headers,
        params={"page": 1, "page_size": 20, "exclude_internal": True},
    )
    assert resp.status_code in (200, 403, 404), resp.text


def _patch_credit_ops_only_permission(monkeypatch, *, can_update: bool) -> None:
    from app.services import menu_permission_service as mps

    def fake(_db, _identity_id, menu_code, action="can_export"):
        if menu_code == "platform.credit_ops_board" and action == "can_export":
            return True
        if can_update and menu_code == "platform.credit_ops_board" and action == "can_update":
            return True
        return False

    monkeypatch.setattr(mps, "has_identity_menu_permission", fake)


def test_credit_ops_board_only_can_read_tenant_ops_endpoints(monkeypatch):
    _patch_credit_ops_only_permission(monkeypatch, can_update=False)
    headers = _demo_platform_headers()
    tenants = client.get("/api/v1/management/credit/tenants", headers=headers)
    assert tenants.status_code == 200, tenants.text
    items = tenants.json()["data"]
    if not items:
        pytest.skip("no credit tenants")
    tenant_id = items[0]["tenant_id"]
    detail = client.get(f"/api/v1/management/credit/tenants/{tenant_id}", headers=headers)
    assert detail.status_code == 200, detail.text
    ledger = client.get(
        f"/api/v1/management/credit/tenants/{tenant_id}/ledger",
        headers=headers,
        params={"page": 1, "page_size": 5},
    )
    assert ledger.status_code == 200, ledger.text


def test_credit_ops_board_only_can_adjust_without_tenant_credit_menu(monkeypatch):
    _patch_credit_ops_only_permission(monkeypatch, can_update=True)
    headers = _demo_platform_headers()
    tenants = client.get("/api/v1/management/credit/tenants", headers=headers)
    assert tenants.status_code == 200, tenants.text
    items = tenants.json()["data"]
    if not items:
        pytest.skip("no credit tenants")
    tenant_id = items[0]["tenant_id"]
    resp = client.post(
        f"/api/v1/management/credit/tenants/{tenant_id}/adjust",
        headers=headers,
        json={"yuan_amount": 1, "reason": ""},
    )
    assert resp.status_code != 403, resp.text


def test_credit_ops_board_only_can_update_policy_rate(monkeypatch):
    _patch_credit_ops_only_permission(monkeypatch, can_update=True)
    headers = _demo_platform_headers()
    tenants = client.get("/api/v1/management/credit/tenants", headers=headers)
    assert tenants.status_code == 200, tenants.text
    items = tenants.json()["data"]
    if not items:
        pytest.skip("no credit tenants")
    tenant_id = items[0]["tenant_id"]
    resp = client.put(
        f"/api/v1/management/credit/tenants/{tenant_id}/policy",
        headers=headers,
        json={"credit_policy": {"credits_per_yuan": 5.0}},
    )
    assert resp.status_code != 403, resp.text
    if resp.status_code == 200:
        assert resp.json()["data"]["credit_policy"]["credits_per_yuan"] == 5.0


def test_credit_ops_board_only_can_preview_and_history_billing_mode(monkeypatch):
    # 2026-09-09 - 合并菜单后切模式/历史不得再死盯旧 tenant_credit
    _patch_credit_ops_only_permission(monkeypatch, can_update=True)
    headers = _demo_platform_headers()
    tenants = client.get("/api/v1/management/credit/tenants", headers=headers)
    assert tenants.status_code == 200, tenants.text
    items = tenants.json()["data"]
    if not items:
        pytest.skip("no credit tenants")
    tenant_id = items[0]["tenant_id"]
    preview = client.get(
        f"/api/v1/management/credit/tenants/{tenant_id}/billing-mode/preview",
        headers=headers,
        params={"target": "hosted"},
    )
    assert preview.status_code != 403, preview.text
    history = client.get(
        f"/api/v1/management/credit/tenants/{tenant_id}/billing-mode/history",
        headers=headers,
    )
    assert history.status_code != 403, history.text
    reserves = client.get(
        f"/api/v1/management/credit/tenants/{tenant_id}/reserves",
        headers=headers,
    )
    assert reserves.status_code != 403, reserves.text
