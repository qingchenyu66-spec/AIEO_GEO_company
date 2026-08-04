"""Approval preview must tolerate object-shaped platform selections."""

from app.services.approval_preview_service import _brand_changes, _platform_labels


def test_platform_labels_mixed_shapes():
    # 字符串平台归一为 FAST_MONITOR_MODE(=search)；预览口径为「快速」
    assert _platform_labels(["doubao", {"code": "kimi", "mode": "search"}]) == [
        "doubao(快速)",
        "kimi(快速)",
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


def test_lead_changes_include_platforms_days_and_prompts(monkeypatch):
    from app.services.approval_preview_service import _lead_changes

    monkeypatch.setattr(
        "app.services.molizhishu_catalog_service.get_supported_platform_catalog",
        lambda: [
            {"code": "doubao", "name": "豆包"},
            {"code": "kimi", "name": "Kimi"},
        ],
    )
    monkeypatch.setattr(
        "app.services.approval_preview_service.region_display_labels",
        lambda codes: "北京市" if codes else "（空）",
    )
    rows = _lead_changes(
        {
            "brand_name": "SAB伟星拉链",
            "competitors": ["竞品A", "竞品B"],
            "region_codes": ["110000"],
            "platforms": ["doubao", "kimi"],
            "schedule_days": 4,
            "prompts": ["问题一", "问题二", "问题三"],
            "contact_note": "备注",
        },
        is_create=True,
    )
    by_field = {row["field"]: row["after"] for row in rows}
    assert by_field["品牌名称"] == "SAB伟星拉链"
    assert "竞品A" in by_field["竞品"]
    assert by_field["监测地区"] == "北京市"
    assert by_field["诊断平台"] == "豆包、Kimi"
    assert by_field["诊断天数"] == "4 天"
    assert by_field["检测问题 1"] == "问题一"
    assert by_field["检测问题 2"] == "问题二"
    assert by_field["检测问题 3"] == "问题三"
    assert by_field["销售备注"] == "备注"
