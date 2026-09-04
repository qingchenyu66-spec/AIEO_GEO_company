# -*- coding: utf-8 -*-
"""商品卡：客户写口忽略开关；平台可写。"""
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.schemas.brand import BrandAssetSaveRequest


def _run_save(monkeypatch, *, identity_type: str):
    from app.services import brand_service

    calls: list[tuple] = []
    tenant = SimpleNamespace(goods_card_enabled=False)

    class FakeAsset:
        company_full_name = "x"
        brand_name = "x"
        brand_short_name = None
        official_url = None
        description = None
        monitor_keywords_json = ["a"]
        aliases_json = []
        product_keywords_json = []
        monitored_platforms_json = ["doubao"]
        schedule_times_json = ["09:30"]
        schedule_weekdays_json = []
        schedule_month_days_json = []
        region_codes_json = []
        schedule_type = "daily_times"
        schedule_frequency = 1
        id = 1
        tenant_id = 99
        status = True
        deleted = False

    db = MagicMock()
    db.scalar.side_effect = lambda *_a, **_k: tenant
    asset = FakeAsset()

    monkeypatch.setattr(brand_service, "resolve_tenant_id", lambda *_a, **_k: 99)
    monkeypatch.setattr(brand_service, "_guard_tenant_write", lambda *_a, **_k: None)
    monkeypatch.setattr(brand_service, "get_brand_asset", lambda *_a, **_k: asset)
    monkeypatch.setattr(brand_service, "_log_brand_asset_config_changes", lambda *_a, **_k: None)
    monkeypatch.setattr(
        "app.services.menu_permission_service.has_identity_menu_permission",
        lambda *_a, **_k: True,
    )
    monkeypatch.setattr(
        "app.services.menu_permission_service.identity_allowed_monitor_platforms",
        lambda *_a, **_k: ["doubao"],
    )
    monkeypatch.setattr(
        "app.services.menu_permission_service.sync_goods_card_menu_for_tenant",
        lambda db, tenant_id, *, enabled: calls.append((tenant_id, enabled)) or 1,
    )
    monkeypatch.setattr(
        "app.services.monitor_service.invalidate_monitor_summary_cache",
        lambda *_a, **_k: None,
    )

    payload = BrandAssetSaveRequest(
        company_full_name="测试企业有限公司",
        brand_name="测试品牌",
        goods_card_enabled=True,
    )
    current = SimpleNamespace(
        identity=SimpleNamespace(
            identity_type=identity_type,
            id=1,
            tenant_id=99 if identity_type == "CUSTOMER" else None,
        ),
        user=SimpleNamespace(id=1),
    )
    brand_service.save_brand_asset(db, payload, current)  # type: ignore[arg-type]
    return tenant, calls


def test_customer_save_ignores_goods_card_enabled(monkeypatch) -> None:
    tenant, calls = _run_save(monkeypatch, identity_type="CUSTOMER")
    assert calls == []
    assert tenant.goods_card_enabled is False


def test_platform_save_writes_goods_card_enabled(monkeypatch) -> None:
    tenant, calls = _run_save(monkeypatch, identity_type="PLATFORM")
    assert tenant.goods_card_enabled is True
    assert calls == [(99, True)]
