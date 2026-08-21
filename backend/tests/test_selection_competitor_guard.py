# -*- coding: utf-8 -*-
from app.services.report_diagnosis_cockpit_service import apply_narrative_scope_guards


def test_selection_guard_rewrites_false_no_competitor_claim():
    facts = {
        "platform_rows": [{"name": "豆包", "key": "doubao"}],
        "kpis": {"visibility": 90.0, "rank": 2.0, "decision": 80.0, "negative": 3.0},
        "has_acquisition_kpi": True,
        "weak_prompts": [],
        "strong_prompts": [],
        "filter_mode": "intent",
        "competitor_stats": [
            {"name": "广州地铁传媒", "rate": 40.0, "hit_count": 18, "sample_total": 45},
            {"name": "德高中国", "rate": 26.7, "hit_count": 12, "sample_total": 45},
        ],
    }
    narr = {
        "stage_copy": {
            "all": {"label": "管理层摘要", "title": "t", "summary": "s"},
            "selection": {
                "label": "竞品对标",
                "title": "非品牌词获客场景中未见竞品同框数据",
                "summary": "监测事实：未提供竞品共现或同框数据。分析判断：无法评估与分众传媒等竞品。",
            },
        },
        "priority_items": [],
        "risk_rows": [],
        "actions": [],
    }
    out = apply_narrative_scope_guards(narr, brand="艾迪亚控股集团有限公司", facts=facts)
    sel = out["stage_copy"]["selection"]
    assert "未见" not in sel["title"]
    assert "未见" not in sel["summary"]
    assert "广州地铁传媒" in sel["summary"]
    assert "40.0%" in sel["summary"]
    assert "不是「没有竞品」" not in sel["summary"]
    assert "不是没有竞品" not in sel["summary"]
    assert "分析判断" in sel["summary"]
    assert "优化建议" in sel["summary"]
    assert "差距" in sel["summary"] or "相对" in sel["summary"]


def test_selection_guard_fills_missing_top_rates_without_deny_phrase():
    """有共现命中但摘要含糊（未写未见、也未写名/率）时也必须回写。"""
    facts = {
        "platform_rows": [{"name": "豆包", "key": "doubao"}],
        "kpis": {"visibility": 90.0, "rank": 2.0, "decision": 80.0, "negative": 3.0},
        "has_acquisition_kpi": True,
        "weak_prompts": [],
        "strong_prompts": [],
        "filter_mode": "intent",
        "competitor_stats": [
            {"name": "YKK", "rate": 41.7, "hit_count": 10, "sample_total": 24},
            {"name": "SBS", "rate": 33.3, "hit_count": 8, "sample_total": 24},
        ],
    }
    narr = {
        "stage_copy": {
            "all": {"label": "管理层摘要", "title": "t", "summary": "s"},
            "selection": {
                "label": "竞品对标",
                "title": "短名单竞争需要对照",
                "summary": "竞品压力存在，建议补对比口径。",
            },
        },
        "priority_items": [],
        "risk_rows": [],
        "actions": [],
    }
    out = apply_narrative_scope_guards(narr, brand="SAB伟星拉链", facts=facts)
    sel = out["stage_copy"]["selection"]
    assert "YKK" in sel["summary"]
    assert "41.7%" in sel["summary"]
    assert "SBS" in sel["summary"]
    assert "不是「没有竞品」" not in sel["summary"]


def test_selection_guard_strips_empty_rhetoric_when_facts_already_ok():
    """名/率已齐但仍残留「不是没有竞品」套话时，必须改成差距判断。"""
    facts = {
        "platform_rows": [{"name": "豆包", "key": "doubao"}],
        "kpis": {"visibility": 50.0, "rank": 2.0, "decision": 40.0, "negative": 2.0},
        "has_acquisition_kpi": True,
        "weak_prompts": [],
        "strong_prompts": [],
        "filter_mode": "intent",
        "competitor_stats": [
            {"name": "YKK", "rate": 41.7, "hit_count": 20, "sample_total": 48},
            {"name": "SBS", "rate": 33.3, "hit_count": 16, "sample_total": 48},
        ],
    }
    narr = {
        "stage_copy": {
            "all": {"label": "管理层摘要", "title": "t", "summary": "s"},
            "selection": {
                "label": "竞品对标",
                "title": "竞品共现率领先，但需强化差异化",
                "summary": (
                    "监测事实：较高的有 YKK 41.7%（20/48）、SBS 33.3%（16/48）。"
                    "分析判断：不是「没有竞品」，而是要对照共现名单补可核验案例与对比口径。"
                    "优化建议：继续观察。"
                ),
            },
        },
        "priority_items": [],
        "risk_rows": [],
        "actions": [],
    }
    out = apply_narrative_scope_guards(narr, brand="SAB伟星拉链", facts=facts)
    sel = out["stage_copy"]["selection"]
    assert "不是「没有竞品」" not in sel["summary"]
    assert "YKK" in sel["summary"]
    assert "差距" in sel["summary"] or "相对" in sel["summary"]
