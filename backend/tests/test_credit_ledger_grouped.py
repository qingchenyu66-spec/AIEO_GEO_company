"""客户算力流水按窗口/按日聚合。"""

from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from app.models.credit import TenantCreditLedger
from app.models.tenant import Tenant
from app.services.credit_service import (
    list_credit_ledger,
    list_credit_ledger_group_lines,
    list_credit_ledger_grouped,
    settle_credits,
)


def _seed_credit_tenant(db, *, balance: Decimal = Decimal("100")) -> Tenant:
    suffix = uuid4().hex[:8]
    tenant = Tenant(
        name=f"LG-{suffix}",
        code=f"LG{suffix}",
        status=True,
        billing_mode="credit",
        credit_balance=balance,
        credit_reserved=Decimal("0"),
        platform_whitelist_json=["doubao"],
    )
    db.add(tenant)
    db.flush()
    return tenant


def test_list_credit_ledger_grouped_by_window(db):
    tenant = _seed_credit_tenant(db, balance=Decimal("100"))
    window = "bw20260914-0900"
    for platform, keyword in (("doubao", "艾迪亚"), ("kimi", "艾迪亚"), ("yuanbao", "载望")):
        settle_credits(
            db,
            tenant_id=tenant.id,
            ref_id=f"sub-{platform}",
            credits=Decimal("1"),
            platform_code=platform,
            keyword=keyword,
            window_key=window,
        )
    db.add(
        TenantCreditLedger(
            tenant_id=tenant.id,
            amount=Decimal("50"),
            balance_after=Decimal("150"),
            entry_type="recharge",
            reason="测试充值",
        )
    )
    db.flush()
    db.refresh(tenant)

    grouped = list_credit_ledger_grouped(db, tenant_id=tenant.id, group_by="window", page=1, page_size=20)
    assert grouped["view"] == "window"
    assert grouped["total"] >= 2
    window_rows = [row for row in grouped["items"] if row["group_key"] == f"w:{window}"]
    assert len(window_rows) == 1
    batch = window_rows[0]
    assert batch["entry_count"] == 3
    assert batch["amount_sum"] == -3.0
    assert batch["settle_sum"] == -3.0
    assert batch["platform_count"] == 3
    assert batch["keyword_count"] == 2

    lines = list_credit_ledger_group_lines(
        db,
        tenant_id=tenant.id,
        group_key=f"w:{window}",
        group_by="window",
        page=1,
        page_size=50,
    )
    assert lines["total"] == 3
    assert {row["platform_code"] for row in lines["items"]} == {"doubao", "kimi", "yuanbao"}


def test_list_credit_ledger_grouped_by_day(db):
    tenant = _seed_credit_tenant(db, balance=Decimal("80"))
    settle_credits(
        db,
        tenant_id=tenant.id,
        ref_id="day-a",
        credits=Decimal("2"),
        platform_code="doubao",
        keyword="甲",
        window_key="bw20260914-0800",
    )
    settle_credits(
        db,
        tenant_id=tenant.id,
        ref_id="day-b",
        credits=Decimal("3"),
        platform_code="kimi",
        keyword="乙",
        window_key="bw20260914-0900",
    )
    db.flush()

    grouped = list_credit_ledger_grouped(db, tenant_id=tenant.id, group_by="day", page=1, page_size=20)
    assert grouped["view"] == "day"
    assert grouped["total"] >= 1
    today = datetime.now().strftime("%Y-%m-%d")
    day_rows = [row for row in grouped["items"] if row["group_key"] == f"d:{today}"]
    assert len(day_rows) == 1
    assert day_rows[0]["settle_sum"] == -5.0
    assert day_rows[0]["entry_count"] == 2


def test_list_credit_ledger_detail_view_unchanged(db):
    tenant = _seed_credit_tenant(db, balance=Decimal("20"))
    settle_credits(
        db,
        tenant_id=tenant.id,
        ref_id="detail-1",
        credits=Decimal("1"),
        platform_code="doubao",
        window_key="bw20260914-1000",
    )
    db.flush()
    detail = list_credit_ledger(db, tenant_id=tenant.id, page=1, page_size=20, exclude_internal=True)
    assert detail["view"] == "detail"
    assert any(row["entry_type"] == "settle" for row in detail["items"])
