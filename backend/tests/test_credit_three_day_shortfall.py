"""方案甲：三日预估不足通知；客户侧不展示预扣。"""
from decimal import Decimal
from uuid import uuid4
from unittest.mock import patch

import pytest
from sqlalchemy import select

from app.celery_app import celery_app
from app.models.brand import BrandAsset
from app.models.notification import SystemNotification
from app.models.tenant import Tenant
from app.services.credit_service import (
    BILLING_MODE_CREDIT,
    notify_tenant_three_day_shortfall_if_needed,
)




def _asset(tenant_id: int) -> BrandAsset:
    return BrandAsset(
        tenant_id=tenant_id,
        company_full_name="测试企业有限公司",
        brand_name="测",
        monitor_keywords_json=["词A"],
        aliases_json=["测"],
        product_keywords_json=[],
        monitored_platforms_json=["doubao"],
        schedule_times_json=["09:30"],
        schedule_weekdays_json=[],
        schedule_month_days_json=[],
        region_codes_json=["110000"],
    )


def test_scan_credit_three_day_shortfall_notifies(db):
    # 2026-09-08 - 单测只断言本租户，避免本地库其它 credit 企业污染 sent 计数
    suffix = uuid4().hex[:8]
    tenant = Tenant(
        name="t",
        code=f"R3{suffix}",
        billing_mode=BILLING_MODE_CREDIT,
        credit_balance=Decimal("10"),
        credit_reserved=Decimal("0"),
        status=True,
    )
    db.add(tenant)
    db.flush()
    db.add(_asset(tenant.id))
    db.flush()

    with patch(
        "app.services.credit_service.estimate_daily_credits",
        return_value={"credits_per_day": 20.0},
    ):
        wrote = notify_tenant_three_day_shortfall_if_needed(
            db, tenant, {"credits_per_day": 20.0}
        )
    assert wrote is True
    row = db.scalar(
        select(SystemNotification).where(
            SystemNotification.tenant_id == tenant.id,
            SystemNotification.category == "credit_runway",
        )
    )
    assert row is not None
    assert "不足 3 天" in row.message
    assert row.title == "算力余量提醒"


def test_scan_credit_three_day_shortfall_skips_when_enough(db):
    suffix = uuid4().hex[:8]
    tenant = Tenant(
        name="t",
        code=f"R3ok{suffix}",
        billing_mode=BILLING_MODE_CREDIT,
        credit_balance=Decimal("100"),
        credit_reserved=Decimal("0"),
        status=True,
    )
    db.add(tenant)
    db.flush()
    db.add(_asset(tenant.id))
    db.flush()
    with patch(
        "app.services.credit_service.estimate_daily_credits",
        return_value={"credits_per_day": 10.0},
    ):
        wrote = notify_tenant_three_day_shortfall_if_needed(
            db, tenant, {"credits_per_day": 10.0}
        )
    assert wrote is False


def test_credit_three_day_beat_registered():
    beat = celery_app.conf.beat_schedule or {}
    assert beat["scan-credit-three-day-shortfall"]["task"] == (
        "app.tasks.monitor.scan_credit_three_day_shortfall"
    )
