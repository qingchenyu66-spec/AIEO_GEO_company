"""客户 summary 不暴露 reserved；流水详情对客户屏蔽内部账；配额脏数据可清。"""
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.credit import TenantCreditLedger
from app.models.tenant import Tenant
from app.services.credit_service import (
    BILLING_MODE_CREDIT,
    get_ledger_entry_detail,
    reserve_credits,
)




def test_customer_ledger_detail_hides_reserve(db: Session):
    suffix = uuid4().hex[:8]
    tenant = Tenant(
        name="t",
        code=f"HID{suffix}",
        billing_mode=BILLING_MODE_CREDIT,
        credit_balance=Decimal("100"),
        credit_reserved=Decimal("0"),
        status=True,
    )
    db.add(tenant)
    db.flush()
    assert reserve_credits(
        db,
        tenant,
        Decimal("10"),
        ref_id=f"ref-{suffix}",
        ref_type="reserve_batch",
        window_key="w1",
    )
    row = db.scalar(
        select(TenantCreditLedger)
        .where(
            TenantCreditLedger.tenant_id == tenant.id,
            TenantCreditLedger.entry_type == "reserve",
        )
        .order_by(TenantCreditLedger.id.desc())
    )
    assert row is not None
    assert get_ledger_entry_detail(db, tenant.id, row.id) is not None
    assert get_ledger_entry_detail(db, tenant.id, row.id, customer_visible_only=True) is None


def test_customer_summary_endpoint_omits_reserved_and_pending_terms():
    import inspect

    from app.api.v1.endpoints import customer_enterprise as mod

    src = inspect.getsource(mod.enterprise_credit_summary)
    assert '"reserved"' not in src
    assert '"pending_terms"' not in src
    assert '"available"' in src


def test_terms_ack_route_removed():
    from app.main import app

    paths = set(app.openapi()["paths"])
    assert "/api/v1/customer/enterprise/credit/terms/ack" not in paths
    assert "/api/v1/customer/enterprise/credit/terms/current" in paths


def test_cleanup_quota_dirt_scan_and_apply(db: Session):
    from scripts.cleanup_credit_quota_dirt import apply_cleanup, scan_dirt

    suffix = uuid4().hex[:8]
    tenant = Tenant(
        name="dirt",
        code=f"DIRT{suffix}",
        billing_mode=BILLING_MODE_CREDIT,
        platform_whitelist_json=["doubao", "kimi"],
        credit_policy_json={"keyword_limit": 30, "credits_per_yuan": 4.2},
        status=True,
    )
    db.add(tenant)
    db.flush()
    hits = [r for r in scan_dirt(db) if r["tenant_id"] == tenant.id]
    assert len(hits) == 1
    assert hits[0]["whitelist"] == ["doubao", "kimi"]
    assert "keyword_limit" in hits[0]["retired_policy_keys"]
    touched = apply_cleanup(db)
    assert touched >= 1
    db.flush()
    db.expire(tenant)
    db.refresh(tenant)
    assert list(tenant.platform_whitelist_json or []) == []
    assert "keyword_limit" not in (tenant.credit_policy_json or {})
