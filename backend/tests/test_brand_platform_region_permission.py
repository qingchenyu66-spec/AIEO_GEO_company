"""地区/平台拆权：无编辑权时保留库内配置（ponytail 自检）。"""

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.schemas.brand import BrandAssetSaveRequest, BrandKeywordGroupSaveRequest


def test_save_keyword_groups_preserves_platforms_without_edit_permission(monkeypatch):
    existing = SimpleNamespace(
        id=11,
        tenant_id=1,
        brand_asset_id=2,
        name="词组1",
        monitor_keyword="防火涂料品牌",
        monitor_keywords_json=["防火涂料品牌"],
        exposure_terms_json=["防火涂料品牌"],
        platforms_json=[{"code": "doubao", "mode": "standard", "screenshot": 1}],
        sort_order=0,
        status=True,
        deleted=False,
    )
    asset = SimpleNamespace(
        id=2,
        tenant_id=1,
        monitored_platforms_json=["doubao"],
    )
    db = MagicMock()
    db.scalars.return_value = [existing]

    import app.services.brand_service as mod

    monkeypatch.setattr(mod, "list_keyword_groups", lambda *_a, **_k: [existing])
    monkeypatch.setattr(mod, "flag_modified", lambda *_a, **_k: None)
    monkeypatch.setattr(mod, "keyword_group_platforms", lambda *_a, **_k: ["doubao"])

    payload = BrandAssetSaveRequest(
        tenant_id=1,
        company_full_name="金隅涂料",
        brand_name="金隅涂料",
        brand_short_name=None,
        monitor_keywords=["防火涂料品牌"],
        aliases=[],
        product_keywords=[],
        monitored_platforms=["qianwen"],
        keyword_groups=[
            BrandKeywordGroupSaveRequest(
                id=11,
                name="词组1",
                monitor_keyword="防火涂料品牌",
                monitor_keywords=["防火涂料品牌"],
                exposure_terms=["防火涂料品牌"],
                platforms=[{"code": "qianwen", "mode": "standard", "screenshot": 1}],
                sort_order=0,
                status=True,
            )
        ],
        region_codes=[],
        official_url=None,
        description=None,
        schedule_type="daily_times",
        schedule_times=["09:00"],
        schedule_frequency=1,
        schedule_weekdays=[],
        schedule_month_days=[],
    )
    mod.save_keyword_groups(db, asset, payload, allow_platform_edit=False)
    assert existing.platforms_json == [{"code": "doubao", "mode": "standard", "screenshot": 1}]
