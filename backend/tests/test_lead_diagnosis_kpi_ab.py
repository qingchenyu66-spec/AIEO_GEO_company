"""A+B：售前诊断非品牌条级 KPI、格级阈值、健康分负面惩罚。"""

from __future__ import annotations

import json

from app.services.lead_diagnosis_service import _rule_health_score, _sample_kpis_from_subtasks
from app.services.report_diagnosis_cockpit_service import (
    _build_heat_scenarios,
    _cell_passes_mention_threshold,
    _matrix_cell_map,
    _worst_acquisition_matrix_cell,
    build_kpi_basis,
    build_rule_all_summary,
    validate_cockpit_null0,
)


def test_cell_mention_threshold_requires_three_of_five() -> None:
    assert _cell_passes_mention_threshold({"sample_count": 5, "mentioned_count": 3, "answer_hit_rate": 60.0})
    assert not _cell_passes_mention_threshold({"sample_count": 5, "mentioned_count": 2, "answer_hit_rate": 40.0})
    assert not _cell_passes_mention_threshold({"sample_count": 5, "mentioned_count": 1, "answer_hit_rate": 20.0})
    # 旧矩阵无 mentioned_count：仍按 avg_rank 回退
    assert _cell_passes_mention_threshold({"sample_count": 4, "avg_rank": 2.0})


def test_matrix_cell_map_keeps_sparse_rank() -> None:
    rows = [
        {
            "prompt": "获客问法",
            "platform": "doubao",
            "sample_count": 5,
            "mentioned_count": 1,
            "answer_hit_rate": 20.0,
            "avg_rank": 1.0,
        }
    ]
    assert _matrix_cell_map(rows)[("获客问法", "doubao")] == 1


def test_heat_shows_sparse_rank_while_grade_rate_stays_strict() -> None:
    tagged = [
        {
            "prompt": "获客问法",
            "lane": "acquisition",
            "intent_code": "recommend",
            "scene_code": None,
        }
    ]
    matrix_rows = [
        {
            "prompt": "获客问法",
            "platform": "doubao",
            "sample_count": 9,
            "mentioned_count": 1,
            "answer_hit_rate": 11.1,
            "avg_rank": 1.0,
        }
    ]
    scenarios = _build_heat_scenarios(tagged, matrix_rows, ["doubao"])
    assert scenarios[0]["values"] == [1]
    basis = build_kpi_basis(tagged, matrix_rows, ["doubao"])
    assert basis["nonbrand"]["mention_cells"] == 1
    assert basis["nonbrand"]["top3_cells"] == 1
    assert basis["nonbrand"]["total_cells"] == 1
    assert basis["nonbrand"]["top3_rate"] == 100.0


def test_build_kpi_basis_counts_sparse_top3_cell() -> None:
    tagged = [
        {
            "prompt": "获客问法",
            "lane": "acquisition",
            "intent_code": "x",
            "scene_code": "none",
        }
    ]
    matrix_rows = [
        {
            "prompt": "获客问法",
            "platform": "doubao",
            "sample_count": 5,
            "mentioned_count": 1,
            "answer_hit_rate": 20.0,
            "avg_rank": 1.0,
        }
    ]
    basis = build_kpi_basis(tagged, matrix_rows, ["doubao"])
    assert basis["nonbrand"]["mention_cells"] == 1
    assert basis["nonbrand"]["top3_cells"] == 1
    assert basis["nonbrand"]["total_cells"] == 1


def test_worst_acquisition_cell_picks_lowest_hit() -> None:
    rows = [
        {"prompt": "好问法", "platform": "doubao", "sample_count": 5, "mentioned_count": 5, "answer_hit_rate": 100.0},
        {"prompt": "差问法", "platform": "deepseek", "sample_count": 5, "mentioned_count": 0, "answer_hit_rate": 0.0},
    ]
    worst = _worst_acquisition_matrix_cell(rows, {"好问法", "差问法"})
    assert worst is not None
    assert worst["prompt"] == "差问法"
    assert worst["hit_rate"] == 0.0


def test_build_rule_all_summary_includes_sample_and_worst_cell() -> None:
    text = build_rule_all_summary(
        brand="测试品牌",
        visibility=75.0,
        rank=2.0,
        decision=50.0,
        negative=20.0,
        platform_rows=[{"key": "doubao", "name": "豆包"}],
        has_acquisition_kpi=True,
        sample_mention_rate=55.0,
        sample_mentioned=11,
        sample_total=20,
        worst_cell={
            "prompt": "差问法",
            "platform_label": "DeepSeek",
            "mentioned_count": 0,
            "sample_count": 5,
            "hit_rate": 0.0,
        },
    )
    assert "11/20" in text or "20 条样本中 11 条" in text
    assert "差问法" in text
    assert "0/5" in text


def test_health_score_uses_acquisition_and_penalizes_negative() -> None:
    loose = _rule_health_score(
        {
            "mention_rate": 70.0,
            "top3_rate": 66.7,
            "positive_rate": 30.0,
            "negative_rate": 26.7,
            "avg_rank": 1.6,
        }
    )
    strict = _rule_health_score(
        {
            "acquisition_sample_total": 20,
            "acquisition_mention_rate": 55.0,
            "acquisition_top3_rate": 45.0,
            "acquisition_avg_rank": 2.0,
            "positive_rate": 30.0,
            "negative_rate": 26.7,
            "mention_rate": 55.0,
            "top3_rate": 45.0,
            "avg_rank": 2.0,
        }
    )
    assert strict < loose


def test_caiwanjia_does_not_match_caiduoduo_ranking_name() -> None:
    """2026-09-03 - 仅全称+配置别名整段匹配，勿误伤菜多多。"""
    from app.models.lead_diagnosis import LeadDiagnosis
    from app.services.lead_diagnosis_service import _lead_brand_terms
    from app.services.monitor_service import _name_matches_brand

    lead = LeadDiagnosis(brand_name="广东菜万家供应链有限公司", brand_aliases_json=["菜万家"])
    terms = _lead_brand_terms(lead)
    assert terms == ["广东菜万家供应链有限公司", "菜万家"]
    assert _name_matches_brand("广东菜万家供应链有限公司", terms)
    assert _name_matches_brand("菜万家", terms)
    assert not _name_matches_brand("菜多多 (广东菜多多食品配送)", terms)
    assert not _name_matches_brand("采多多 (广东采多多食品配送)", terms)


def test_advice_numbered_tip_does_not_override_company_table_row_five() -> None:
    """2026-09-03 - 表第5行+「3.合同条款」顺带提菜万家 → 位次5非3。"""
    from types import SimpleNamespace

    from app.services.monitor_service import _resolve_brand_rank_detail

    answer = """
| 公司名称 | 亮点 | 业绩 |
| --- | --- | --- |
| **广东广垦绿色农产品有限公司** | 国企 | 第一 |
| **东莞市新农膳食管理服务有限公司** | 学校 | 第一 |
| **东莞市鲜源食品配送有限公司** | 高校 | 第二 |
| **广东宏华饮食有限公司** | 政府 | 稳健 |
| **广东菜万家供应链有限公司** | 本土 | 次日达 |

### 💡 怎么选更适合你？
1. **看规模与需求**：大型企业…
3. **看具体合同条款**：像「菜万家」承诺早上8:30前完成配送[citation:7]。
"""
    item = SimpleNamespace(
        prompt="东莞做食材配送的哪家好?",
        answer_content=answer,
        mention_context=None,
        all_rankings_json=[
            {"name": "广东广垦绿色农产品有限公司", "rank": 1},
            {"name": "东莞市新农膳食管理服务有限公司", "rank": 2},
            {"name": "东莞市鲜源食品配送有限公司", "rank": 3},
            {"name": "广东宏华饮食有限公司", "rank": 4},
            {"name": "广东菜万家供应链有限公司", "rank": 5},
        ],
        mention_position=3,
        raw_result_json={},
    )
    terms = ["广东菜万家供应链有限公司", "菜万家"]
    detail = _resolve_brand_rank_detail(item, item.prompt, terms, None)
    assert detail.mentioned is True
    assert detail.rank == 5


def test_exact_configured_term_rejects_fragment_slice() -> None:
    from app.services.lead_brand_match import exact_configured_term_in_text

    assert exact_configured_term_in_text("广东菜万家供应链有限公司", "菜万家")
    assert not exact_configured_term_in_text("菜多多", "菜万家")
    assert not exact_configured_term_in_text("广东菜多多食品配送", "广东菜万家供应链有限公司")


def test_product_cards_sample_primary_not_duplicate_cell_seventy_five() -> None:
    """2026-09-03 - 推荐名单与兜底卡勿重复格级 75%，与顶栏条级 55% 同源。"""
    from app.services.report_diagnosis_cockpit_service import build_diagnosis_cockpit_context

    ctx = build_diagnosis_cockpit_context(
        {
            "brand_name": "菜万家",
            "kpis": {
                "mention_rate": 55.0,
                "acquisition_mention_rate": 55.0,
                "acquisition_sample_mentioned": 11,
                "acquisition_sample_total": 20,
                "avg_rank": 2.0,
                "top3_rate": 75.0,
            },
            "prompt_analytics": [
                {
                    "prompt": "大湾区做食堂食材配送的头部品牌推荐",
                    "brand_mention_rate": 50.0,
                    "brand_avg_rank": 2.0,
                    "sample_count": 10,
                },
                {
                    "prompt": "东莞做食材配送的哪家好?",
                    "brand_mention_rate": 60.0,
                    "brand_avg_rank": 2.0,
                    "sample_count": 10,
                },
                {
                    "prompt": "菜万家品牌怎么样",
                    "brand_mention_rate": 100.0,
                    "brand_avg_rank": 1.0,
                    "sample_count": 10,
                },
            ],
            "matrix_rows": [
                {
                    "prompt": "大湾区做食堂食材配送的头部品牌推荐",
                    "platform": "doubao",
                    "avg_rank": None,
                    "sample_count": 5,
                    "mentioned_count": 0,
                },
                {
                    "prompt": "大湾区做食堂食材配送的头部品牌推荐",
                    "platform": "deepseek",
                    "avg_rank": None,
                    "sample_count": 5,
                    "mentioned_count": 0,
                },
                {
                    "prompt": "东莞做食材配送的哪家好?",
                    "platform": "doubao",
                    "avg_rank": 2.0,
                    "sample_count": 5,
                    "mentioned_count": 5,
                },
                {
                    "prompt": "东莞做食材配送的哪家好?",
                    "platform": "deepseek",
                    "avg_rank": 2.0,
                    "sample_count": 5,
                    "mentioned_count": 5,
                },
                {"prompt": "菜万家品牌怎么样", "platform": "doubao", "avg_rank": 1.0, "sample_count": 5},
                {"prompt": "菜万家品牌怎么样", "platform": "deepseek", "avg_rank": 1.0, "sample_count": 5},
            ],
            "platform_stats": [
                {"platform": "doubao", "mention_rate": 50.0, "avg_rank": 2.0, "total": 15},
                {"platform": "deepseek", "mention_rate": 50.0, "avg_rank": 2.0, "total": 15},
            ],
            "diagnosis": {},
        }
    )
    by_code = {c["code"]: c for c in ctx["product_cards"]}
    rec = by_code["recommend"]
    assert rec["metric"] == "55.0%"
    assert rec["metric_sub"] == "条级获客提及率"
    assert "格级" in rec["desc"] and "4格" in rec["desc"]
    assert not any(str(c.get("code") or "").startswith("fill_") for c in ctx["product_cards"])
    labels = [c["label"] for c in ctx["product_cards"]]
    assert labels.count("全部问法意图") == 0


def test_sparse_rank_counts_as_top3_and_drops_zero_mention_copy() -> None:
    from app.services.report_diagnosis_cockpit_service import build_diagnosis_cockpit_context

    ctx = build_diagnosis_cockpit_context(
        {
            "brand_name": "上海霞旭船舶服务有限公司",
            "kpis": {
                "acquisition_mention_rate": 1.9,
                "acquisition_sample_mentioned": 1,
                "acquisition_sample_total": 54,
                "acquisition_avg_rank": 1.0,
            },
            "prompt_analytics": [
                {
                    "prompt": "哪个公司可以做压载水设备维修",
                    "brand_mention_rate": 5.6,
                    "brand_avg_rank": 1.0,
                    "sample_count": 18,
                },
                {
                    "prompt": "PFOS检测公司有哪些",
                    "brand_mention_rate": 0.0,
                    "brand_avg_rank": 0.0,
                    "sample_count": 18,
                },
                {
                    "prompt": "船舶有害物质检测公司推荐",
                    "brand_mention_rate": 0.0,
                    "brand_avg_rank": 0.0,
                    "sample_count": 18,
                },
            ],
            "matrix_rows": [
                {
                    "prompt": "哪个公司可以做压载水设备维修",
                    "platform": "doubao",
                    "avg_rank": 1.0,
                    "sample_count": 9,
                    "mentioned_count": 1,
                    "answer_hit_rate": 11.1,
                },
                {
                    "prompt": "哪个公司可以做压载水设备维修",
                    "platform": "deepseek",
                    "avg_rank": None,
                    "sample_count": 9,
                    "mentioned_count": 0,
                    "answer_hit_rate": 0.0,
                },
                {
                    "prompt": "PFOS检测公司有哪些",
                    "platform": "doubao",
                    "avg_rank": None,
                    "sample_count": 9,
                    "mentioned_count": 0,
                    "answer_hit_rate": 0.0,
                },
                {
                    "prompt": "PFOS检测公司有哪些",
                    "platform": "deepseek",
                    "avg_rank": None,
                    "sample_count": 9,
                    "mentioned_count": 0,
                    "answer_hit_rate": 0.0,
                },
                {
                    "prompt": "船舶有害物质检测公司推荐",
                    "platform": "doubao",
                    "avg_rank": None,
                    "sample_count": 9,
                    "mentioned_count": 0,
                    "answer_hit_rate": 0.0,
                },
                {
                    "prompt": "船舶有害物质检测公司推荐",
                    "platform": "deepseek",
                    "avg_rank": None,
                    "sample_count": 9,
                    "mentioned_count": 0,
                    "answer_hit_rate": 0.0,
                },
            ],
            "platform_stats": [
                {"platform": "doubao", "mention_rate": 11.1, "avg_rank": 1.0},
                {"platform": "deepseek", "mention_rate": 0.0, "avg_rank": None},
            ],
            "cockpit_narrative": {
                "stage_copy": {
                    "all": {"label": "总览", "title": "旧标题", "summary": "格级提及率 0.0%"},
                    "recognition": {"label": "品牌认知", "title": "t", "summary": "提及率 0.0%"},
                    "selection": {"label": "竞品对标", "title": "t", "summary": "s"},
                    "procurement": {"label": "推荐名单", "title": "t", "summary": "s"},
                    "risk": {"label": "口碑评价", "title": "t", "summary": "s"},
                },
                "priority_items": [
                    {"level": "P0", "title": "a", "body": "提及率 0.0%"},
                    {"level": "P1", "title": "b", "body": "b"},
                    {"level": "P2", "title": "c", "body": "c"},
                ],
                "risk_rows": [
                    {
                        "topic": "「哪个公司可以做压载水设备维修」提及率 0.0%",
                        "models": "豆包、DeepSeek",
                        "impact": "格级均排 1.0 但提及率 0.0%，个别信号不足以形成获客",
                        "evidence": "格级提及率 0.0%、均排 1.0、回答命中率 5.6%，样本 18",
                        "priority": "P0",
                    }
                ],
            },
            "diagnosis": {},
        }
    )
    assert ctx["_facts_for_narrative"]["kpis"]["decision"] == 1.9
    cockpit = json.loads(ctx["cockpit_json"])
    assert cockpit["platformData"]["all"]["slices"]["all"]["decision"] == 1.9
    doubao = cockpit["platformData"]["doubao"]
    deepseek = cockpit["platformData"]["deepseek"]
    assert doubao["visibility"] == 0.0
    assert doubao["slices"]["all"]["visibility"] == 0.0
    assert doubao["decision"] == 3.7
    assert doubao["slices"]["all"]["decision"] == 3.7
    assert deepseek["visibility"] == 0.0
    assert deepseek["decision"] == 0.0
    assert validate_cockpit_null0(cockpit) == []
    scenarios = json.loads(ctx["cockpit_json"])["scenarios"]
    heat = next(row for row in scenarios if "压载水" in row["question"])
    assert 1 in heat["values"]
    blob = " ".join(
        f"{row.get('topic') or ''} {row.get('impact') or ''} {row.get('evidence') or ''}"
        for row in ctx["risk_rows"]
    )
    assert "个别信号" not in blob
    assert "但提及率 0" not in blob
    by_code = {card["code"]: card for card in ctx["product_cards"]}
    assert [card["code"] for card in ctx["product_cards"]] == [
        "recommend",
        "compare",
        "brand_rank",
        "reputation",
        "geo_source",
        "awareness",
    ]
    assert by_code["recommend"]["metric"] == "1.9%"
    assert by_code["awareness"]["tag"] == "待补问法"
    assert by_code["awareness"]["metric"] == "—"
    assert by_code["reputation"]["tag"] == "待补问法"
