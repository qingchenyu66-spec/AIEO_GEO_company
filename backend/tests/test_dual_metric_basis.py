# -*- coding: utf-8 -*-
"""2026-08-21 - 口径：弱别名门槛 + 格级举例 + 混写门禁。"""

from app.services.lead_brand_match import is_weak_brand_alias, matchable_brand_terms
from app.services.report_diagnosis_cockpit_service import (
    _kpi_prompt_examples,
    _sanitize_dual_metric_copy,
)


def test_weak_alias_filters_short_latin_and_short_cjk():
    assert is_weak_brand_alias("SAB") is True
    assert is_weak_brand_alias("AB") is True
    assert is_weak_brand_alias("伟") is True
    assert is_weak_brand_alias("艾迪亚") is False
    assert is_weak_brand_alias("SAB伟星拉链") is False


def test_matchable_brand_terms_keeps_full_brand_drops_sab():
    terms = matchable_brand_terms("SAB伟星拉链", ["SAB", "伟星拉链", "SAB伟星"])
    assert "SAB伟星拉链" in terms
    assert "SAB" not in terms
    assert "伟星拉链" in terms


def test_kpi_prompt_examples_prefer_cell_rates():
    tagged = [
        {
            "prompt": "服饰辅料供应商推荐？",
            "lane": "acquisition",
            "is_brand_word": False,
            "brand_mention_rate": 33.3,
            "brand_avg_rank": 1.7,
            "cell_mention_rate": 0.0,
            "cell_avg_rank": None,
        },
        {
            "prompt": "工厂辅料求推荐？",
            "lane": "acquisition",
            "is_brand_word": False,
            "brand_mention_rate": 44.4,
            "brand_avg_rank": 1.0,
            "cell_mention_rate": 100.0,
            "cell_avg_rank": 1.0,
        },
    ]
    weak, strong = _kpi_prompt_examples(tagged)
    assert weak[0]["prompt"] == "服饰辅料供应商推荐？"
    assert weak[0]["mention_rate"] == 0.0
    assert weak[0]["answer_hit_rate"] == 33.3
    assert strong[0]["mention_rate"] == 100.0
    assert strong[0]["basis"] == "question_platform_cell"


def test_sanitize_dual_metric_aligns_prompt_rate_and_renames_sample():
    stage = {
        "procurement": {
            "title": "非品牌词推荐名单提及率0.0%",
            "summary": (
                "监测事实：非品牌词推荐名单问法3条，提及率0.0%。"
                "具体问法如'做高端服装品牌，靠谱的服饰辅料供应商推荐？'提及率33.3%，"
                "但整体非品牌格提及率为0。跨日样本提及率：非品牌词 40%。"
            ),
        }
    }
    facts = {
        "weak_prompts": [
            {
                "prompt": "做高端服装品牌，靠谱的服饰辅料供应商推荐？",
                "mention_rate": 0.0,
            }
        ]
    }
    out = _sanitize_dual_metric_copy(stage, facts=facts)
    summary = out["procurement"]["summary"]
    assert "提及率0.0%" in summary
    assert "33.3%" not in summary
    assert "跨日回答命中率" in summary
    assert "但整体非品牌格提及率为0" not in summary


def test_heat_scenarios_carry_answer_hit_not_as_main_cell_value():
    from app.services.report_diagnosis_cockpit_service import _build_heat_scenarios

    tagged = [
        {
            "prompt": "品牌怎么样",
            "lane": "brand_defense",
            "is_brand_word": True,
            "intent_label": "口碑评价",
            "intent_code": "reputation",
            "scene_code": None,
            "scene_label": None,
            "brand_mention_rate": 33.3,
        }
    ]
    matrix = [
        {
            "prompt": "品牌怎么样",
            "platform": "doubao",
            "avg_rank": 2.0,
            "mention_rate": 33.3,
            "answer_hit_rate": 33.3,
        }
    ]
    scenarios = _build_heat_scenarios(tagged, matrix, ["doubao"])
    assert scenarios[0]["values"] == [2]
    assert scenarios[0]["answer_hit_rate"] == 33.3
    assert scenarios[0]["snapshots"][0]["exposed"] is True
    assert scenarios[0]["snapshots"][0]["answer_hit_rate"] == 33.3
