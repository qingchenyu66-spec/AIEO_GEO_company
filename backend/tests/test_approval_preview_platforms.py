"""Approval preview must tolerate object-shaped platform selections."""

from app.services.approval_preview_service import _brand_changes, _platform_labels


def test_platform_labels_mixed_shapes():
    assert _platform_labels(["doubao", {"code": "kimi", "mode": "search"}]) == [
        "doubao(快速)",
        "kimi(联网)",
    ]


def test_brand_changes_with_object_platforms(monkeypatch):
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
            "company_full_name": "旧企业",
            "official_url": "",
            "description": "",
            "region_codes": [],
            "schedule_times": ["09:30"],
            "keyword_groups": [
                {
                    "id": 1,
                    "name": "综合",
                    "monitor_keywords": ["品牌"],
                    "platforms": [{"code": "doubao", "mode": "standard", "screenshot": 1}],
                }
            ],
        },
    )
    rows = _brand_changes(
        db=None,
        tenant_id=1,
        body={
            "company_full_name": "旧企业",
            "schedule_times": ["09:30"],
            "region_codes": [],
            "keyword_groups": [
                {
                    "id": 1,
                    "name": "综合",
                    "monitor_keywords": ["品牌"],
                    "platforms": [
                        {"code": "doubao", "mode": "reasoning", "screenshot": 1},
                        {"code": "kimi", "mode": "search", "screenshot": 1},
                    ],
                }
            ],
        },
    )
    assert any("平台" in row.get("field", "") for row in rows)

def test_brand_asset_has_changes_false_when_identical(monkeypatch):
    from app.services.approval_preview_service import brand_asset_has_changes

    class FakeAsset:
        pass

    current = {
        "company_full_name": "戮望保研",
        "brand_name": "戮望保研",
        "brand_short_name": "",
        "official_url": "",
        "description": "",
        "region_codes": [],
        "schedule_type": "daily_times",
        "schedule_times": ["09:30"],
        "schedule_frequency": 1,
        "schedule_weekdays": [],
        "schedule_month_days": [],
        "aliases": ["品牌"],
        "keyword_groups": [
            {
                "id": 1,
                "name": "综合",
                "monitor_keywords": ["品牌"],
                "exposure_terms": ["品牌"],
                "platforms": [{"code": "doubao", "mode": "standard", "screenshot": 1}],
                "status": True,
            }
        ],
    }
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
        lambda asset, groups: current,
    )
    assert brand_asset_has_changes(None, 1, dict(current)) is False
    changed = dict(current)
    changed["description"] = "有改动"
    assert brand_asset_has_changes(None, 1, changed) is True
