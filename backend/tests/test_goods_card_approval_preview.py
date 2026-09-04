"""审批预览须展示商品卡开关（新建摊开 + 变更对照）。"""

from types import SimpleNamespace

from app.services.approval_preview_service import (
    _brand_bootstrap_changes,
    _brand_changes,
    brand_asset_has_changes,
)


def test_bootstrap_preview_shows_goods_card_on():
    rows = _brand_bootstrap_changes(
        {
            "official_url": "https://example.com",
            "description": "",
            "goods_card_enabled": True,
            "keyword_groups": [],
            "competitors": [],
        }
    )
    goods = next(row for row in rows if row.get("field") == "商品卡")
    assert goods["after"] == "开通"
    assert goods["kind"] == "add"


def test_bootstrap_preview_shows_goods_card_off_by_default():
    rows = _brand_bootstrap_changes(
        {
            "official_url": "",
            "description": "",
            "keyword_groups": [],
            "competitors": [],
        }
    )
    goods = next(row for row in rows if row.get("field") == "商品卡")
    assert goods["after"] == "关闭"


def test_brand_changes_goods_card_toggle_detected(monkeypatch):
    class FakeAsset:
        pass

    monkeypatch.setattr(
        "app.services.approval_preview_service.get_brand_asset",
        lambda db, tenant_id: FakeAsset(),
    )
    monkeypatch.setattr(
        "app.services.approval_preview_service.list_keyword_groups",
        lambda db, tenant_id: [],
    )
    monkeypatch.setattr(
        "app.services.approval_preview_service.asset_to_dict",
        lambda asset, groups: {
            "company_full_name": "测试企业",
            "brand_name": "测试企业",
            "brand_short_name": "",
            "official_url": "",
            "description": "",
            "region_codes": [],
            "schedule_type": "daily_times",
            "schedule_times": ["09:30"],
            "schedule_frequency": 1,
            "schedule_weekdays": [],
            "schedule_month_days": [],
            "aliases": [],
            "keyword_groups": [],
        },
    )
    db = SimpleNamespace(
        scalar=lambda stmt: SimpleNamespace(goods_card_enabled=False, deleted=False)
    )
    rows = _brand_changes(
        db=db,  # type: ignore[arg-type]
        tenant_id=1,
        body={
            "company_full_name": "测试企业",
            "brand_name": "测试企业",
            "schedule_times": ["09:30"],
            "region_codes": [],
            "keyword_groups": [],
            "goods_card_enabled": True,
        },
    )
    goods = next(row for row in rows if row.get("field") == "商品卡")
    assert goods["before"] == "关闭"
    assert goods["after"] == "开通"
    assert brand_asset_has_changes(
        db,  # type: ignore[arg-type]
        1,
        {
            "company_full_name": "测试企业",
            "brand_name": "测试企业",
            "schedule_times": ["09:30"],
            "region_codes": [],
            "keyword_groups": [],
            "goods_card_enabled": True,
        },
    )
