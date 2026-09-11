"""算力自助：空白名单下保存须能删掉监测平台（勿回填）。"""
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentSession
from app.models.brand import BrandAsset, BrandKeywordGroup
from app.models.tenant import Tenant
from app.schemas.brand import BrandAssetSaveRequest, BrandKeywordGroupSaveRequest
from app.services.brand_service import keyword_group_platforms, save_brand_asset
from app.services.credit_service import BILLING_MODE_CREDIT
from app.services.menu_permission_service import catalog_listed_platform_codes
from app.services.platform_selection import normalize_platform_selections




def test_credit_empty_whitelist_save_removes_platform(db: Session, monkeypatch):
    # 2026-09-04 - 空白名单保存忽略平台变更 - 保存后勾选应能减少
    catalog = catalog_listed_platform_codes(db)
    assert len(catalog) >= 2
    keep, drop = catalog[0], catalog[1]

    suffix = uuid4().hex[:8]
    tenant = Tenant(
        name=f"空白名单保存_{suffix}",
        code=f"WLSAVE{suffix}",
        billing_mode=BILLING_MODE_CREDIT,
        platform_whitelist_json=[],
        status=True,
    )
    db.add(tenant)
    db.flush()
    asset = BrandAsset(
        tenant_id=tenant.id,
        company_full_name=f"测企{suffix}",
        brand_name="测牌",
        brand_short_name="测",
        monitor_keywords_json=["词1"],
        aliases_json=[],
        product_keywords_json=[],
        monitored_platforms_json=[keep, drop],
        schedule_times_json=["09:30"],
        schedule_weekdays_json=[],
        schedule_month_days_json=[],
        status=True,
    )
    db.add(asset)
    db.flush()
    group = BrandKeywordGroup(
        tenant_id=tenant.id,
        brand_asset_id=asset.id,
        name="综合",
        monitor_keyword="词1",
        monitor_keywords_json=["词1"],
        exposure_terms_json=["测"],
        platforms_json=normalize_platform_selections([keep, drop]),
        sort_order=0,
        status=True,
    )
    db.add(group)
    db.flush()

    monkeypatch.setattr(
        "app.services.menu_permission_service.has_identity_menu_permission",
        lambda *_a, **_k: True,
    )
    monkeypatch.setattr(
        "app.services.brand_service._log_brand_asset_config_changes",
        lambda *_a, **_k: None,
    )

    identity = SimpleNamespace(
        id=1,
        identity_type="CUSTOMER",
        tenant_id=tenant.id,
        user_id=1,
        position_id=None,
    )
    current = CurrentSession(user=SimpleNamespace(id=1), identity=identity)
    payload = BrandAssetSaveRequest(
        tenant_id=tenant.id,
        company_full_name=asset.company_full_name,
        brand_name=asset.brand_name,
        brand_short_name=asset.brand_short_name,
        keyword_groups=[
            BrandKeywordGroupSaveRequest(
                id=group.id,
                name=group.name,
                monitor_keywords=["词1"],
                exposure_terms=["测"],
                platforms=[keep],
                status=True,
            )
        ],
        schedule_times=["09:30"],
    )
    save_brand_asset(db, payload, current)
    db.flush()
    db.refresh(group)
    codes = set(keyword_group_platforms(group))
    assert keep in codes
    assert drop not in codes
