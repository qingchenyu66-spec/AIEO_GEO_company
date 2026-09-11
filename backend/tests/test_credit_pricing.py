"""算力定价：解析优先级、改价后扣费、price-rules HTTP。"""
from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.models.brand import BrandAsset
from app.models.tenant import Tenant
from app.services.credit_service import (
    BILLING_MODE_CREDIT,
    estimate_daily_credits,
    reserve_credits,
    resolve_credits_per_subtask,
    settle_credits,
    tenant_available_credits,
    upsert_price_rule,
)

client = TestClient(app)




def _demo_headers() -> dict[str, str]:
    # 2026-09-04 - 本地登录多为 Cookie；同时带 Bearer 兼容
    login = client.post("/api/v1/auth/login", json={"username": "demo", "password": "Geo@2026"})
    assert login.status_code == 200, login.text
    body = login.json()["data"]
    if body.get("requires_identity_selection"):
        platform = next(i for i in body["identities"] if i["identity_type"] == "PLATFORM")
        picked = client.post(
            "/api/v1/auth/select-identity",
            json={"identity_id": platform["id"], "ticket": body["ticket"]},
        )
        assert picked.status_code == 200, picked.text
        session = (picked.json().get("data") or {}).get("session") or picked.json().get("data") or {}
    else:
        session = body.get("session") or {}
    headers: dict[str, str] = {}
    token = session.get("access_token") or client.cookies.get("geo_access_token")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    csrf = client.cookies.get("geo_csrf_token")
    if csrf:
        headers["X-CSRF-Token"] = csrf
    return headers


def test_resolve_credits_priority_tenant_over_global(db: Session):
    suffix = uuid4().hex[:8]
    tenant = Tenant(
        name=f"price-{suffix}",
        code=f"PR{suffix}",
        billing_mode=BILLING_MODE_CREDIT,
        credit_balance=Decimal("100"),
        status=True,
    )
    db.add(tenant)
    db.flush()
    upsert_price_rule(db, scope="global", tenant_id=None, platform_code="kimi", credits_per_subtask=Decimal("2"))
    upsert_price_rule(db, scope="global", tenant_id=None, platform_code=None, credits_per_subtask=Decimal("1"))
    upsert_price_rule(
        db,
        scope="tenant",
        tenant_id=tenant.id,
        platform_code="kimi",
        credits_per_subtask=Decimal("3.5"),
    )
    db.flush()
    assert resolve_credits_per_subtask(db, tenant_id=tenant.id, platform_code="kimi") == Decimal("3.5")
    assert resolve_credits_per_subtask(db, tenant_id=tenant.id, platform_code="doubao") == Decimal("1")


def test_settle_uses_resolved_unit_price(db: Session):
    suffix = uuid4().hex[:8]
    tenant = Tenant(
        name=f"settle-price-{suffix}",
        code=f"SP{suffix}",
        billing_mode=BILLING_MODE_CREDIT,
        credit_balance=Decimal("50"),
        credit_reserved=Decimal("0"),
        status=True,
    )
    db.add(tenant)
    db.flush()
    upsert_price_rule(
        db,
        scope="tenant",
        tenant_id=tenant.id,
        platform_code="doubao",
        credits_per_subtask=Decimal("2"),
    )
    db.flush()
    unit = resolve_credits_per_subtask(db, tenant_id=tenant.id, platform_code="doubao")
    assert unit == Decimal("2")
    ref = f"price-sim-{suffix}"
    assert reserve_credits(db, tenant, unit, ref_id=ref, ref_type="reserve_batch", window_key="w1")
    settle_credits(
        db,
        tenant_id=tenant.id,
        ref_id=ref,
        credits=unit,
        platform_code="doubao",
        keyword="测价",
        window_key="w1",
    )
    db.refresh(tenant)
    assert tenant_available_credits(tenant) == Decimal("48")


def test_estimate_daily_credits_follows_platform_price(db: Session):
    suffix = uuid4().hex[:8]
    tenant = Tenant(
        name=f"est-{suffix}",
        code=f"ES{suffix}",
        billing_mode=BILLING_MODE_CREDIT,
        platform_whitelist_json=["doubao", "kimi"],
        status=True,
    )
    db.add(tenant)
    db.flush()
    asset = BrandAsset(
        tenant_id=tenant.id,
        company_full_name="测试企业有限公司",
        brand_name="测",
        monitor_keywords_json=["词A"],
        aliases_json=["测"],
        product_keywords_json=[],
        monitored_platforms_json=["doubao", "kimi"],
        schedule_times_json=["09:30"],
        schedule_weekdays_json=[],
        schedule_month_days_json=[],
        region_codes_json=["110000"],
    )
    db.add(asset)
    db.flush()
    upsert_price_rule(db, scope="global", tenant_id=None, platform_code=None, credits_per_subtask=Decimal("1"))
    upsert_price_rule(db, scope="global", tenant_id=None, platform_code="kimi", credits_per_subtask=Decimal("2"))
    db.flush()
    est = estimate_daily_credits(db, tenant, asset, keyword_count=1)
    # 1 词 × 1 场 × 1 区 × (doubao1 + kimi2) = 3
    assert float(est["credits_per_day"]) == 3.0
    assert int(est["platform_count"]) == 2


def test_price_rules_http_list_and_upsert_roundtrip():
    headers = _demo_headers()
    listed = client.get("/api/v1/management/credit/price-rules", headers=headers, params={"scope": "global"})
    assert listed.status_code == 200, listed.text
    before = listed.json()["data"] or []
    assert isinstance(before, list)

    platform = "quark"
    original = next((r for r in before if r.get("platform_code") == platform), None)
    original_credits = float(original["credits_per_subtask"]) if original else None

    put = client.put(
        "/api/v1/management/credit/price-rules",
        headers=headers,
        json={
            "scope": "global",
            "platform_code": platform,
            "credits_per_subtask": 1.25,
            "status": True,
        },
    )
    assert put.status_code == 200, put.text
    assert float(put.json()["data"]["credits_per_subtask"]) == 1.25

    again = client.get("/api/v1/management/credit/price-rules", headers=headers, params={"scope": "global"})
    assert again.status_code == 200
    hit = next(r for r in (again.json()["data"] or []) if r.get("platform_code") == platform)
    assert float(hit["credits_per_subtask"]) == 1.25

    if original_credits is not None:
        restore = client.put(
            "/api/v1/management/credit/price-rules",
            headers=headers,
            json={
                "scope": "global",
                "platform_code": platform,
                "credits_per_subtask": original_credits,
                "status": True,
            },
        )
        assert restore.status_code == 200, restore.text
    else:
        restore = client.put(
            "/api/v1/management/credit/price-rules",
            headers=headers,
            json={
                "scope": "global",
                "platform_code": platform,
                "credits_per_subtask": 1,
                "status": False,
            },
        )
        assert restore.status_code == 200, restore.text


def test_price_rules_unauth_is_401_or_403():
    # 独立 client，避免同模块其它用例登录 Cookie 污染
    bare = TestClient(app)
    resp = bare.get("/api/v1/management/credit/price-rules")
    assert resp.status_code in (401, 403)
