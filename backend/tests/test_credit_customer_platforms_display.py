"""算力自助：平台白名单会话口径 + 当天数据 cutoff。"""
from datetime import datetime, time, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.tenant import Tenant
from app.models.user_identity import UserIdentity
from app.services.credit_service import BILLING_MODE_CREDIT, BILLING_MODE_HOSTED
from app.services.menu_permission_service import identity_allowed_monitor_platforms
from app.services.monitor_service import (
    credit_customer_includes_today,
    customer_display_cutoff_for_tenant,
)




def test_credit_tenant_allowed_monitor_platforms_ignores_whitelist(db: Session):
    # 2026-09-07 - 方案 A：有历史白名单也返回目录全量
    from app.services.menu_permission_service import catalog_listed_platform_codes

    suffix = uuid4().hex[:8]
    tenant = Tenant(name="t", code=f"CREDIT_PLAT_{suffix}", billing_mode=BILLING_MODE_CREDIT)
    tenant.platform_whitelist_json = ["kimi"]
    db.add(tenant)
    db.flush()
    identity = UserIdentity(
        identity_code=f"CREDIT_PLAT_{suffix}",
        user_id=1,
        tenant_id=tenant.id,
        identity_type="CUSTOMER",
        identity_name="admin",
        role_code="TENANT_ADMIN",
        customer_position_id=1,
        position_id=None,
    )
    db.add(identity)
    db.flush()
    assert identity_allowed_monitor_platforms(db, identity) == catalog_listed_platform_codes(db)


def test_credit_empty_whitelist_means_all_catalog_listed(db: Session):
    # 2026-09-04 - 空白名单不设限：会话平台 = 目录上架全部
    from app.models.platform import GeoPlatform
    from app.services.menu_permission_service import catalog_listed_platform_codes

    suffix = uuid4().hex[:8]
    tenant = Tenant(name="t", code=f"CREDIT_ALL_{suffix}", billing_mode=BILLING_MODE_CREDIT)
    tenant.platform_whitelist_json = []
    db.add(tenant)
    db.flush()
    identity = UserIdentity(
        identity_code=f"CREDIT_ALL_{suffix}",
        user_id=1,
        tenant_id=tenant.id,
        identity_type="CUSTOMER",
        identity_name="admin",
        role_code="TENANT_ADMIN",
        customer_position_id=1,
        position_id=None,
    )
    db.add(identity)
    db.flush()
    allowed = identity_allowed_monitor_platforms(db, identity)
    catalog = catalog_listed_platform_codes(db)
    assert allowed == catalog
    assert len(allowed) >= 1
    # 目录若有上架行，空白名单不得退化成空列表
    listed = db.scalars(
        select(GeoPlatform).where(GeoPlatform.deleted.is_(False), GeoPlatform.catalog_listed.is_(True))
    ).first()
    if listed is not None:
        assert listed.platform_code in allowed


def test_hosted_customer_without_position_gets_empty_platforms(db: Session):
    suffix = uuid4().hex[:8]
    tenant = Tenant(name="h", code=f"HOSTED_PLAT_{suffix}", billing_mode=BILLING_MODE_HOSTED)
    db.add(tenant)
    db.flush()
    identity = UserIdentity(
        identity_code=f"HOSTED_PLAT_{suffix}",
        user_id=2,
        tenant_id=tenant.id,
        identity_type="CUSTOMER",
        identity_name="viewer",
        role_code="TENANT_USER",
        position_id=None,
    )
    db.add(identity)
    db.flush()
    assert identity_allowed_monitor_platforms(db, identity) == []


def test_credit_customer_display_cutoff_includes_today(db: Session):
    suffix = uuid4().hex[:8]
    tenant = Tenant(name="c", code=f"CREDIT_CUTOFF_{suffix}", billing_mode=BILLING_MODE_CREDIT)
    db.add(tenant)
    db.flush()
    now = datetime(2026, 8, 27, 15, 0, 0)
    assert credit_customer_includes_today(db, tenant.id) is True
    cutoff = customer_display_cutoff_for_tenant(db, tenant.id, now)
    assert cutoff == datetime.combine(now.date(), time.max)


def test_hosted_customer_display_cutoff_stops_at_yesterday(db: Session):
    suffix = uuid4().hex[:8]
    tenant = Tenant(name="h", code=f"HOSTED_CUTOFF_{suffix}", billing_mode=BILLING_MODE_HOSTED)
    db.add(tenant)
    db.flush()
    now = datetime(2026, 8, 27, 15, 0, 0)
    assert credit_customer_includes_today(db, tenant.id) is False
    cutoff = customer_display_cutoff_for_tenant(db, tenant.id, now)
    assert cutoff.date().isoformat() == "2026-08-26"


def test_resolve_monitor_date_range_credit_keeps_today(db: Session):
    """前端传今日时，算力客户后端不得再截到昨日。"""
    from types import SimpleNamespace

    from app.services.monitor_service import resolve_monitor_date_range

    suffix = uuid4().hex[:8]
    tenant = Tenant(name="c", code=f"CREDIT_RANGE_{suffix}", billing_mode=BILLING_MODE_CREDIT)
    db.add(tenant)
    db.flush()
    current = SimpleNamespace(
        identity=SimpleNamespace(identity_type="CUSTOMER", tenant_id=tenant.id),
    )
    today = datetime.now().date()
    start = datetime.combine(today - timedelta(days=6), time.min)
    end = datetime.combine(today, time.max)
    _start, range_end = resolve_monitor_date_range(
        current, start, end, customer_like=True, db=db, tenant_id=tenant.id
    )
    assert range_end.date() == today


def test_tenant_today_credit_deduct(db: Session):
    from app.models.credit import TenantCreditLedger
    from app.services.credit_service import tenant_today_credit_deduct

    suffix = uuid4().hex[:8]
    tenant = Tenant(name="t", code=f"CR_TD_{suffix}", billing_mode=BILLING_MODE_CREDIT, credit_balance=100)
    db.add(tenant)
    db.flush()
    db.add(
        TenantCreditLedger(
            tenant_id=tenant.id,
            amount=Decimal("-5"),
            balance_after=Decimal("95"),
            entry_type="settle",
            reason="test",
        )
    )
    db.flush()
    assert tenant_today_credit_deduct(db, tenant.id) == Decimal("5")


def test_tenant_purchased_platforms_no_whitelist_fallback(db: Session):
    # 2026-09-07 - 配置空不再回落白名单
    from app.models.brand import BrandAsset
    from app.services.brand_service import tenant_purchased_platforms

    suffix = uuid4().hex[:8]
    tenant = Tenant(name="t", code=f"CRWL_{suffix}", billing_mode=BILLING_MODE_CREDIT)
    tenant.platform_whitelist_json = ["kimi", "doubao"]
    db.add(tenant)
    db.flush()
    asset = BrandAsset(
        tenant_id=tenant.id,
        company_full_name="测试企业有限公司",
        brand_name="测试",
        monitor_keywords_json=[],
        aliases_json=[],
        product_keywords_json=[],
        monitored_platforms_json=[],
        schedule_times_json=["09:30"],
        schedule_weekdays_json=[],
        schedule_month_days_json=[],
    )
    db.add(asset)
    db.flush()
    assert tenant_purchased_platforms(db, tenant.id, asset) == []
