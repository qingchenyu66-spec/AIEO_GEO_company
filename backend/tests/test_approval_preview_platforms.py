"""Approval preview must tolerate object-shaped platform selections."""

from app.services.approval_preview_service import _brand_changes, _platform_labels


def test_platform_labels_mixed_shapes():
    assert _platform_labels(["doubao", {"code": "kimi", "mode": "search"}]) == [
        "doubao(极速)",
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
