# -*- coding: utf-8 -*-
"""2026-08-13 - 售前聚合应对齐生产：mention_position 空时仍吃 all_rankings。"""

from types import SimpleNamespace

from app.services.lead_diagnosis_service import (
    _effective_lead_mention_position,
    _lead_brand_terms,
    aggregate_lead_diagnosis,
)


def test_effective_position_from_all_rankings_when_mention_null():
    item = SimpleNamespace(
        mention_position=None,
        prompt="地铁广告投放服务商哪家比较靠谱？",
        answer_content="推荐全国性整合代理：1.雅仕维 2.艾迪亚传媒 3.传播易",
        all_rankings_json=[
            {"name": "雅仕维", "rank": 1, "category": "全国性整合代理公司"},
            {"name": "艾迪亚传媒", "rank": 2, "category": "全国性整合代理公司"},
        ],
        raw_result_json={},
        mention_context=None,
    )
    brand = "艾迪亚控股集团有限公司"
    terms = [brand, "艾迪亚", "艾迪亚控股集团", "艾迪亚传媒"]
    assert _effective_lead_mention_position(item, brand, terms) == 2.0


def test_aggregate_matrix_uses_structured_rank_without_mention_position(monkeypatch):
    lead = SimpleNamespace(
        brand_name="艾迪亚控股集团有限公司",
        competitors_json=["分众传媒"],
        diagnosis_result_json={"brand_aliases": ["艾迪亚", "艾迪亚控股集团"]},
        prompts_json=["地铁广告投放服务商哪家比较靠谱？"],
        diagnosis_date=__import__("datetime").date(2026, 8, 13),
        schedule_days=1,
        schedule_times_json=["09:30"],
        runs=[],
        created_at=None,
        id=15,
        platforms_json=["doubao"],
        region_codes_json=[],
    )
    sub = SimpleNamespace(
        status="completed",
        answer_content="正文含艾迪亚传媒推荐：雅仕维第一，艾迪亚传媒第二",
        mention_position=None,
        platform="doubao",
        prompt="地铁广告投放服务商哪家比较靠谱？",
        sentiment="neutral",
        reference_list_json=[],
        task_id="t1",
        all_rankings_json=[
            {"name": "雅仕维", "rank": 1, "category": "全国性整合代理公司"},
            {"name": "艾迪亚传媒", "rank": 2, "category": "全国性整合代理公司"},
        ],
        raw_result_json={},
        mention_context=None,
    )
    monkeypatch.setattr(
        "app.services.lead_diagnosis_service.build_lead_diagnosis_analytics",
        lambda *a, **k: {
            "competitors": [],
            "prompt_analytics": [],
            "source_analysis": {},
        },
    )
    monkeypatch.setattr(
        "app.services.lead_diagnosis_service.build_rule_report_sections",
        lambda **k: {},
    )
    monkeypatch.setattr(
        "app.services.report_enrichment_service.build_report_enrichment",
        lambda **k: {"prompt_commentaries": [], "priority_actions": []},
    )
    class _Off:
        report_enabled = False
    monkeypatch.setattr("app.services.lead_diagnosis_service.DeepseekClient", lambda: _Off())
    result = aggregate_lead_diagnosis(lead, [sub], db=None)
    rows = result.get("matrix_rows") or []
    assert rows, rows
    hit = next(r for r in rows if r["platform"] == "doubao")
    assert hit["avg_rank"] == 2.0
    assert hit["mention_rate"] == 100.0


def test_lead_brand_terms_include_short_name():
    lead = SimpleNamespace(
        brand_name="艾迪亚控股集团有限公司",
        diagnosis_result_json={"brand_aliases": ["艾迪亚传媒"]},
    )
    terms = _lead_brand_terms(lead)
    assert "艾迪亚控股集团有限公司" in terms
    assert "艾迪亚传媒" in terms
    assert any(t.startswith("艾迪亚") for t in terms)
