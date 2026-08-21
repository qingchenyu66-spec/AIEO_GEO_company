"""诊断驾驶舱问法打标与 1:1 壳注入自检。"""

from __future__ import annotations

from app.services.report_diagnosis_cockpit_service import build_diagnosis_cockpit_context, render_diagnosis_cockpit_html
from app.services.report_diagnosis_cockpit_taxonomy import (
    classify_prompt,
    prompt_contains_brand,
    resolve_filter_mode,
)


def test_scene_first_then_intent():
    row = classify_prompt("电梯广告公司推荐", brand="艾迪亚")
    assert row["lane"] == "acquisition"
    assert row["scene_code"] == "elevator"
    assert row["filter_dim"] == "scene"
    assert row["intent_code"] == "recommend"


def test_brand_defense_lane():
    row = classify_prompt("SAB伟星拉链靠谱吗", brand="SAB", aliases=["伟星"])
    assert row["lane"] == "brand_defense"
    assert row["is_brand_word"] is True
    assert row["scene_code"] is None
    assert row["filter_dim"] == "intent"
    assert row["intent_code"] == "reputation"


def test_intent_without_scene():
    # 2026-08-21 - 怎么选并入推荐名单，不再有 criteria/选型意图
    row = classify_prompt("服饰辅料供应商怎么选", brand="载望")
    assert row["lane"] == "acquisition"
    assert row["filter_dim"] == "intent"
    assert row["intent_code"] == "recommend"
    assert row["intent_label"] == "推荐名单"


def test_resolve_filter_mode_scene_wins():
    tagged = [
        classify_prompt("电梯广告公司推荐", brand="艾迪亚"),
        classify_prompt("户外广告怎么选", brand="艾迪亚"),
    ]
    assert resolve_filter_mode(tagged) == "scene"


def test_company_suffix_alias_for_brand_word():
    assert prompt_contains_brand("sab 拉链怎么样", "SAB") is True
    assert prompt_contains_brand("拉链推荐", "SAB") is False
    assert prompt_contains_brand("艾迪亚怎么样", "艾迪亚控股集团有限公司") is True


def test_cockpit_shell_matches_reference_controls():
    html = render_diagnosis_cockpit_html(
        {
            "brand_name": "艾迪亚",
            "kpis": {"mention_rate": 37.8, "avg_rank": 2.5, "top3_rate": 27.3, "positive_rate": 99.8},
            "prompt_analytics": [
                {"prompt": "电梯广告公司推荐", "brand_mention_rate": 8.0, "brand_avg_rank": 5.0, "sample_count": 10},
                {"prompt": "机场广告公司哪家好", "brand_mention_rate": 40.0, "brand_avg_rank": 2.0, "sample_count": 10},
                {"prompt": "艾迪亚怎么样", "brand_mention_rate": 90.0, "brand_avg_rank": 1.0, "sample_count": 4},
            ],
            "platform_stats": [
                {"platform": "doubao", "mention_rate": 60, "avg_rank": 2.6},
                {"platform": "deepseek", "mention_rate": 17.4, "avg_rank": 2.9},
            ],
            "source_analysis": {
                "total_references": 100,
                "brand_related_references": 37,
                "domain_stats": [{"domain": "quark.cn", "count": 10}],
            },
            "competitors": ["德高中国", "华铁传媒"],
            "diagnosis": {"recommendation": "补电梯案例"},
            "sentiment_counts": {"positive": 90, "neutral": 9, "negative": 1},
        }
    )
    assert 'data-stage="recognition"' in html
    assert 'data-stage="selection"' in html
    assert 'data-stage="procurement"' in html
    assert 'data-stage="risk"' in html
    assert "非品牌词获客提及率" in html
    assert "非品牌词平均推荐位" in html
    assert "负面关联率" in html
    assert "非品牌词 Top3 率" in html
    assert "品牌词防守提及率" in html
    assert "品牌信源引用率" in html
    assert "监测版本说明" in html
    assert "P0 · 场景攻坚" in html
    assert "P1 · 平台覆盖" in html
    assert "P2 · 优势放大" in html
    assert "场景矩阵" in html
    assert 'data-lane="acquisition"' not in html
    assert 'data-stage="recognition"' in html
    assert "const __COCKPIT__" in html
    assert "platformFilter.addEventListener" in html
    assert "productFilter.addEventListener" in html
    assert html.count('data-stage=') == 5


def test_cockpit_competitor_rows_use_cooccurrence_rate_not_fake_score():
    ctx = build_diagnosis_cockpit_context(
        {
            "brand_name": "SAB伟星拉链",
            "kpis": {"mention_rate": 20.0, "avg_rank": 3.0, "top3_rate": 10.0, "positive_rate": 80.0},
            "prompt_analytics": [
                {"prompt": "拉链品牌推荐哪家好", "brand_mention_rate": 20.0, "brand_avg_rank": 3.0, "sample_count": 6},
            ],
            "platform_stats": [{"platform": "doubao", "mention_rate": 20.0, "avg_rank": 3.0, "total": 6}],
            "competitors": ["YKK", "SBS"],
            "competitor_stats": [
                {"name": "YKK", "hit_count": 3, "sample_total": 6, "rate": 50.0},
                {"name": "SBS", "hit_count": 2, "sample_total": 6, "rate": 33.3},
            ],
        }
    )
    rows = ctx["competitor_rows"]
    assert rows[0] == {"name": "YKK", "width": 50.0, "score": 50.0}
    assert rows[1]["score"] == 33.3
    # 假分路径已删：不得再出现 90 / 83 示意分
    assert all(row["score"] not in {90, 83, 76} for row in rows)
    html = render_diagnosis_cockpit_html(
        {
            "brand_name": "SAB伟星拉链",
            "kpis": {"mention_rate": 20.0, "avg_rank": 3.0, "top3_rate": 10.0, "positive_rate": 80.0},
            "prompt_analytics": [
                {"prompt": "拉链品牌推荐哪家好", "brand_mention_rate": 20.0, "brand_avg_rank": 3.0, "sample_count": 6},
            ],
            "platform_stats": [{"platform": "doubao", "mention_rate": 20.0, "avg_rank": 3.0}],
            "competitors": ["YKK"],
            "competitor_stats": [{"name": "YKK", "hit_count": 3, "sample_total": 6, "rate": 50.0}],
        }
    )
    assert "非品牌词问法共现" in html
    assert "示意排序" not in html


def test_competitor_portfolio_card_uses_submitted_competitors_without_compare_prompts():
    context = build_diagnosis_cockpit_context(
        {
            "brand_name": "测试品牌",
            "kpis": {"mention_rate": 20.0, "avg_rank": 3.0, "top3_rate": 10.0, "positive_rate": 80.0},
            "prompt_analytics": [
                {"prompt": "广告公司推荐", "brand_mention_rate": 20.0, "brand_avg_rank": 3.0, "sample_count": 6},
            ],
            "platform_stats": [{"platform": "doubao", "mention_rate": 20.0, "avg_rank": 3.0, "total": 6}],
            "competitors": ["竞品甲", "竞品乙"],
            "competitor_stats": [
                {"name": "竞品甲", "hit_count": 2, "sample_total": 6, "rate": 33.3},
                {"name": "竞品乙", "hit_count": 0, "sample_total": 6, "rate": 0.0},
            ],
        }
    )
    compare = next(card for card in context["product_cards"] if card["code"] == "compare")
    assert compare["label"] == "竞品对标"
    assert compare["metric"] == "2 家"
    assert "竞品甲" in compare["desc"]
    assert "未配置直接对比问法" not in compare["desc"]
    assert compare["metric_sub"] != "暂无对口样本"


def test_cockpit_source_chart_uses_chinese_site_label_instead_of_domain():
    context = build_diagnosis_cockpit_context(
        {
            "brand_name": "测试品牌",
            "kpis": {"mention_rate": 20.0, "avg_rank": 3.0, "top3_rate": 10.0, "positive_rate": 80.0},
            "prompt_analytics": [
                {"prompt": "广告公司推荐", "brand_mention_rate": 20.0, "brand_avg_rank": 3.0, "sample_count": 6},
            ],
            "platform_stats": [{"platform": "doubao", "mention_rate": 20.0, "avg_rank": 3.0, "total": 6}],
            "source_analysis": {"domain_stats": [{"domain": "cnblogs.com", "count": 4}]},
        }
    )
    import json

    cockpit = json.loads(context["cockpit_json"])
    assert cockpit["sources"][0]["name"] == "博客园"


def test_scene_mode_coverage_uses_neutral_scope_label():
    context = build_diagnosis_cockpit_context(
        {
            "brand_name": "测试品牌",
            "kpis": {"mention_rate": 20.0, "avg_rank": 3.0, "top3_rate": 10.0, "positive_rate": 80.0},
            "prompt_analytics": [
                {"prompt": "公交地铁广告公司推荐", "brand_mention_rate": 20.0, "brand_avg_rank": 3.0, "sample_count": 6},
            ],
            "platform_stats": [{"platform": "doubao", "mention_rate": 20.0, "avg_rank": 3.0, "total": 6}],
        }
    )
    assert context["filter_mode"] == "scene"
    assert context["coverage_label"] == "场景化监测问法"
    import json

    assert all("公交地铁" not in chip for chip in context["evidence_chips"])


def test_export_payload_forwards_competitor_stats():
    from app.services.report_export_service import _normalize_export_payload

    payload = _normalize_export_payload(
        {
            "report_type": "diagnosis",
            "report_title": "测试",
            "report_content": {
                "brand_name": "SAB",
                "competitors": ["YKK"],
                "competitor_stats": [
                    {"name": "YKK", "hit_count": 3, "sample_total": 6, "rate": 50.0}
                ],
                "competitors_mined": [
                    {"name": "YKK", "hit_count": 3, "sample_total": 6, "rate": 50.0}
                ],
                "kpis": {},
            },
        }
    )
    assert payload["competitor_stats"][0]["rate"] == 50.0
    assert payload["competitors"] == ["YKK"]


def test_cockpit_intent_mode_uses_generic_six_cards():
    ctx = build_diagnosis_cockpit_context(
        {
            "brand_name": "SAB",
            "prompt_analytics": [
                {"prompt": "拉链品牌推荐", "brand_mention_rate": 40.0, "brand_avg_rank": 2.0, "sample_count": 4},
                {"prompt": "SAB拉链靠谱吗", "brand_mention_rate": 90.0, "brand_avg_rank": 1.0, "sample_count": 4},
            ],
            "platform_stats": [{"platform": "deepseek", "mention_rate": 50, "avg_rank": 2.5}],
            "diagnosis": {},
        }
    )
    assert ctx["priority_items"][0]["level"].startswith("P0")
    assert ctx["filter_mode"] == "intent"
    labels = [c["label"] for c in ctx["product_cards"]]
    assert len(labels) == 6
    assert "机场广告" not in labels
    assert "高铁广告" not in labels
    assert "LED广告" not in labels
    assert "电梯" not in "".join(labels)
    assert any("推荐" in x for x in labels)
    assert ctx["nav_portfolio_label"] == "问法意图矩阵"


def test_cockpit_scene_mode_only_hit_scenes_no_empty_airport():
    ctx = build_diagnosis_cockpit_context(
        {
            "brand_name": "艾迪亚",
            "prompt_analytics": [
                {"prompt": "电梯广告公司推荐", "brand_mention_rate": 8.0, "brand_avg_rank": 5.0, "sample_count": 10},
                {"prompt": "地铁广告投放服务商哪家靠谱", "brand_mention_rate": 40.0, "brand_avg_rank": 2.0, "sample_count": 10},
            ],
            "platform_stats": [{"platform": "doubao", "mention_rate": 60, "avg_rank": 2.6, "total": 10}],
            "diagnosis": {},
            "lead_context": {
                "website_url": "https://www.imtcmkj.com/",
                "industry": "户外广告",
                "product_focus": "地铁广告",
                "source": "lead_diagnosis_create",
            },
        }
    )
    assert ctx["filter_mode"] == "scene"
    labels = [c["label"] for c in ctx["product_cards"]]
    assert len(labels) == 6
    assert "电梯广告" in labels
    assert "公交/地铁广告" in labels or any("地铁" in x for x in labels)
    assert "机场广告" not in labels
    assert "高铁广告" not in labels
    assert "LED广告" not in labels
    # 禁止空场景暂无数据占位
    assert not any(c.get("metric") == "暂无数据" and "机场" in c.get("label", "") for c in ctx["product_cards"])


def test_cockpit_platform_chart_and_heat_use_matrix():
    ctx = build_diagnosis_cockpit_context(
        {
            "brand_name": "SAB伟星拉链",
            "kpis": {"mention_rate": 20.0, "avg_rank": 2.0, "top3_rate": 15.0},
            "prompt_analytics": [
                {"prompt": "服饰辅料供应商怎么选？", "brand_mention_rate": 10.0, "brand_avg_rank": 4.0, "sample_count": 9},
                {"prompt": "SAB伟星拉链品牌靠谱吗？", "brand_mention_rate": 50.0, "brand_avg_rank": 2.0, "sample_count": 9},
            ],
            "platform_stats": [
                {"platform": "chatgpt", "mention_rate": 11.1, "avg_rank": 1.4, "total": 45, "completed": 45},
            ],
            "matrix_rows": [
                {
                    "prompt": "服饰辅料供应商怎么选？",
                    "platform": "chatgpt",
                    "mention_rate": 0.0,
                    "avg_rank": None,
                    "sample_count": 9,
                },
                {
                    "prompt": "SAB伟星拉链品牌靠谱吗？",
                    "platform": "chatgpt",
                    "mention_rate": 22.2,
                    "avg_rank": 1.5,
                    "sample_count": 9,
                },
            ],
            "diagnosis": {},
        }
    )
    import json

    import json
    cockpit = json.loads(ctx["cockpit_json"])
    assert [r["key"] for r in cockpit["platformRows"]] == ["chatgpt"]
    # A+：平台行吃格级；非品牌 1 格未露出 → 0%；不再吃 platform_stats 11.1
    assert cockpit["platformRows"][0]["positive"] == 0.0
    assert cockpit["platformData"]["all"]["visibility"] == 0.0
    assert cockpit["platformData"]["all"]["brand_defense"] == 100.0
    assert cockpit["schema_version"] == "scope-v8"
    assert "productAdjust" not in cockpit
    assert cockpit["kpi_basis"]["basis_type"] == "question_platform_cell"
    assert cockpit["kpi_basis"]["nonbrand"]["total_cells"] == 1
    assert set(cockpit["kpi_basis"]["nonbrand"].keys()) == {
        "total_cells",
        "mention_cells",
        "top3_cells",
        "rank_sum",
    }
    assert cockpit["kpi_basis"]["brand"]["mention_cells"] == 1
    assert cockpit["sample_basis"]["basis_type"] == "run_sample"
    assert cockpit["sample_basis"]["enabled"] is True
    assert "不参与主 KPI" in str(cockpit["sample_basis"].get("note") or "")
    assert "sliceLabels" in cockpit
    assert cockpit["scenarios"][0]["values"] == [0]
    assert cockpit["scenarios"][1]["values"] == [2]
    assert "机场" not in ctx["heat_detail_default"]
    assert ctx["heat_model_names"] == ["ChatGPT"]
    sc0 = json.loads(ctx["cockpit_json"])["scenarios"][0]
    assert "is_brand_query" in sc0
    assert "query_intent" in sc0
    assert "scene" in sc0
    assert "is_primary_kpi_included" in sc0
    assert any(a.get("bullets") and "复测" in "".join(a["bullets"]) for a in ctx["actions"])
    assert all("案例、边界说明与权威信源" != r.get("evidence") for r in ctx["risk_rows"])


def test_single_platform_rule_summary_and_shell_copy():
    ctx = build_diagnosis_cockpit_context(
        {
            "brand_name": "SAB伟星拉链",
            "kpis": {"mention_rate": 37.0, "avg_rank": 1.9, "top3_rate": 20.0},
            "prompt_analytics": [
                {"prompt": "拉链品牌推荐", "brand_mention_rate": 67.0, "brand_avg_rank": 2.0, "sample_count": 9},
                {"prompt": "SAB伟星拉链靠谱吗", "brand_mention_rate": 44.0, "brand_avg_rank": 1.5, "sample_count": 9},
            ],
            "platform_stats": [
                {"platform": "chatgpt", "mention_rate": 11.1, "avg_rank": 1.4, "total": 45, "completed": 45},
            ],
            "matrix_rows": [
                {
                    "prompt": "拉链品牌推荐",
                    "platform": "chatgpt",
                    "avg_rank": 2.0,
                    "sample_count": 9,
                    "mention_rate": 67.0,
                }
            ],
            "diagnosis": {},
            "cockpit_narrative": {
                "stage_copy": {
                    "all": {
                        "label": "管理层摘要",
                        "title": "坏摘要<span>x</span>",
                        "summary": "且豆包、DeepSeek、千问、元宝、百度AI+等平台提及率均为0，存在明显覆盖缺口。",
                    },
                    "recognition": {"label": "品牌认知阶段", "title": "t", "summary": "s"},
                    "selection": {"label": "技术选型阶段", "title": "t", "summary": "s"},
                    "procurement": {"label": "项目采购阶段", "title": "t", "summary": "s"},
                    "risk": {"label": "风险质疑阶段", "title": "t", "summary": "s"},
                },
                "priority_items": [
                    {
                        "level_class": "p0",
                        "level": "P0 · 场景攻坚",
                        "tone": "status-risk",
                        "tone_label": "缺口明显",
                        "title": "a",
                        "body": "b",
                    },
                    {
                        "level_class": "p1",
                        "level": "P1 · 平台覆盖",
                        "tone": "status-gap",
                        "tone_label": "需结构化",
                        "title": "a",
                        "body": "b",
                    },
                    {
                        "level_class": "p2",
                        "level": "P2 · 优势放大",
                        "tone": "status-ok",
                        "tone_label": "基础较强",
                        "title": "a",
                        "body": "b",
                    },
                ],
            },
        }
    )
    import json

    import json
    cockpit = json.loads(ctx["cockpit_json"])
    hero = cockpit["stageCopy"]["all"]["summary"]
    assert "ChatGPT" in hero
    assert "豆包" not in hero
    assert "均为0" not in hero
    assert "不能把未监测平台记为 0" not in hero
    assert "同类品牌里排名怎么样" not in hero
    assert "靠谱吗" not in hero
    assert "未监测" not in hero or "仅适用" in hero
    assert "非品牌词" in hero or "短板" in hero or "提及率约" in hero
    assert "非品牌词" in cockpit["stageCopy"]["all"]["title"]
    assert ctx["platform_panel_title"] == "ChatGPT 表现"
    assert "户外广告" not in ctx["sources_subtitle"]
    assert "意图" in ctx["methodology_slice"]
    assert ctx["priority_items"][1]["level"] == "P1 · 问法补强"
    assert "不能把未监测平台记为 0" not in ctx["methodology_scope"]


def test_facts_include_kpi_lanes_split():
    ctx = build_diagnosis_cockpit_context(
        {
            "brand_name": "SAB",
            "prompt_analytics": [
                {"prompt": "拉链品牌推荐", "brand_mention_rate": 40.0, "brand_avg_rank": 2.0, "sample_count": 4},
                {"prompt": "SAB靠谱吗", "brand_mention_rate": 90.0, "brand_avg_rank": 1.0, "sample_count": 4},
            ],
            "platform_stats": [{"platform": "chatgpt", "mention_rate": 11.1, "avg_rank": 1.4, "total": 8}],
            "matrix_rows": [
                {"prompt": "拉链品牌推荐", "platform": "chatgpt", "avg_rank": 2.0, "sample_count": 4},
                {"prompt": "SAB靠谱吗", "platform": "chatgpt", "avg_rank": 1.0, "sample_count": 4},
            ],
            "diagnosis": {},
        }
    )
    facts = ctx["_facts_for_narrative"]
    assert facts["kpi_basis"]["nonbrand"]["total_cells"] == 1
    assert facts["kpi_basis"]["nonbrand"]["mention_rate"] == 100.0
    assert facts["kpi_basis"]["brand"]["mention_rate"] == 100.0
    # 样本级稳定性仍保留 PA 跨日率
    assert facts["sample_basis"]["nonbrand_mention_rate"] == 40.0
    assert facts["sample_basis"]["brand_mention_rate"] == 90.0
    assert any(x.get("lane") == "acquisition" for x in facts["prompt_taxonomy"])
    # 2026-08-13 - lane 必须带问法数，避免叙事「防守问法数=0」与品牌问法列表冲突
    assert facts["kpi_lanes"]["acquisition"]["prompt_count"] == 1
    assert facts["kpi_lanes"]["brand_defense"]["prompt_count"] == 1


def test_all_brand_prompts_primary_kpi_na():
    """来也式全品牌词：主 KPI 暂无数据，禁止回填全量 90%。"""
    import json

    from app.services.report_diagnosis_cockpit_service import (
        diagnosis_export_title,
        platform_version_tag,
    )

    prompts = [
        "来也科技有哪些产品值得推荐？",
        "来也科技在同类品牌里排名怎么样？",
        "来也科技和主要竞品哪家更好？",
        "选择来也科技需要重点关注什么？",
        "来也科技品牌靠谱吗？",
    ]
    ctx = build_diagnosis_cockpit_context(
        {
            "brand_name": "来也科技",
            "kpis": {"mention_rate": 90.0, "avg_rank": 1.4, "top3_rate": 90.0, "positive_rate": 100},
            "prompt_analytics": [
                {"prompt": p, "brand_mention_rate": 90.0, "brand_avg_rank": 1.4, "sample_count": 4}
                for p in prompts
            ],
            "platform_stats": [{"platform": "doubao", "mention_rate": 90.0, "avg_rank": 1.4, "total": 20}],
            "diagnosis": {},
            "sentiment_counts": {"positive": 20, "neutral": 0, "negative": 0},
        }
    )
    import json
    cockpit = json.loads(ctx["cockpit_json"])
    assert ctx["_facts_for_narrative"]["has_acquisition_kpi"] is False
    assert cockpit["platformData"]["all"]["visibility"] is None
    assert cockpit["platformData"]["all"]["rank"] is None
    assert cockpit["platformData"]["all"]["decision"] is None
    assert cockpit["platformData"]["all"]["primary_kpi_available"] is False
    assert ctx["portfolio_visibility"] == "暂无数据"
    assert ctx["portfolio_rank"] == "暂无数据"
    hero = cockpit["stageCopy"]["all"]["summary"]
    assert "暂无数据" in hero
    assert "只能评估品牌防守" in hero
    assert "90.0%" not in hero or "防守" in hero
    assert "正面可见度" not in ctx["platform_chart_aria"]
    assert "非品牌词获客提及率" in ctx["platform_chart_aria"]
    # 2026-08-13 - 无非品牌分母时诊断分/对标不得写 0
    for i in ctx["insights"]:
        if i["title"] in ("自然获客候选池", "意图选型说服力", "场景选型说服力", "项目采购信任"):
            assert i.get("score") is None
            assert i.get("score_display") == "暂无评估"
    assert "暂无对标" in ctx["gap_note"]
    assert "nonbrand_rank_sum" in cockpit["platformData"]["all"]
    assert len(cockpit["risks"]) >= 1
    assert len(cockpit["actions"]) == 3
    html = render_diagnosis_cockpit_html(
        {
            "brand_name": "来也科技",
            "prompt_analytics": [
                {"prompt": p, "brand_mention_rate": 90.0, "brand_avg_rank": 1.4, "sample_count": 4}
                for p in prompts
            ],
            "platform_stats": [{"platform": "doubao", "mention_rate": 90.0, "avg_rank": 1.4}],
            "diagnosis": {},
        }
    )
    assert 'id="riskBody"' in html
    assert 'id="actionGrid"' in html
    assert "renderRisks" in html
    assert "__COCKPIT__.risks" in html or "riskRows" in html
    assert platform_version_tag(["ChatGPT"]) == "ChatGPT单平台"
    assert platform_version_tag(["豆包", "ChatGPT"]) == "豆包+ChatGPT综合"
    assert diagnosis_export_title("SAB伟星拉链", ["豆包", "ChatGPT"]) == (
        "SAB伟星拉链_豆包+ChatGPT综合_售前品牌诊断报告"
    )
def test_acquisition_top3_from_prompt_ranks():
    """有非品牌词均排时 Top3 必须可算，不得再写暂无。"""
    import json

    ctx = build_diagnosis_cockpit_context(
        {
            "brand_name": "SAB伟星拉链",
            "prompt_analytics": [
                {
                    "prompt": "做高端服装品牌，靠谱的服饰辅料供应商推荐？",
                    "brand_mention_rate": 50.0,
                    "brand_avg_rank": 2.0,
                    "sample_count": 4,
                },
                {
                    "prompt": "工厂批量生产服装，性价比高的服饰辅料供应商求推荐？",
                    "brand_mention_rate": 0.0,
                    "brand_avg_rank": 0.0,
                    "sample_count": 4,
                },
                {
                    "prompt": "服饰辅料供应商怎么选？有没有选择标准？",
                    "brand_mention_rate": 0.0,
                    "brand_avg_rank": 0.0,
                    "sample_count": 4,
                },
                {
                    "prompt": "SAB伟星拉链靠谱吗？",
                    "brand_mention_rate": 90.0,
                    "brand_avg_rank": 1.0,
                    "sample_count": 4,
                },
            ],
            "platform_stats": [{"platform": "chatgpt", "mention_rate": 40.0, "avg_rank": 2.0, "total": 16}],
            "matrix_rows": [
                {
                    "prompt": "做高端服装品牌，靠谱的服饰辅料供应商推荐？",
                    "platform": "chatgpt",
                    "avg_rank": 2.0,
                    "sample_count": 4,
                },
                {
                    "prompt": "工厂批量生产服装，性价比高的服饰辅料供应商求推荐？",
                    "platform": "chatgpt",
                    "avg_rank": None,
                    "sample_count": 4,
                },
                {
                    "prompt": "服饰辅料供应商怎么选？有没有选择标准？",
                    "platform": "chatgpt",
                    "avg_rank": None,
                    "sample_count": 4,
                },
            ],
            "diagnosis": {},
        }
    )
    import json
    cockpit = json.loads(ctx["cockpit_json"])
    # 3 条非品牌词，1 条进前三 → 33.3%
    assert cockpit["platformData"]["all"]["decision"] == 33.3
    assert cockpit["platformData"]["chatgpt"]["decision"] == 33.3
    assert ctx["_facts_for_narrative"]["kpi_lanes"]["acquisition"]["top3_rate"] == 33.3


def test_null0_mention_zero_vs_no_denominator():
    """分母>0 命中0 → 0%/均排暂无；分母0 → 全 null；旧叙事不得覆盖。"""
    import json

    from app.services.report_diagnosis_cockpit_service import validate_cockpit_null0

    # 豆包式：3 格无露出
    ctx0 = build_diagnosis_cockpit_context(
        {
            "brand_name": "SAB",
            "prompt_analytics": [
                {"prompt": "服饰辅料供应商怎么选？", "brand_mention_rate": 0.0, "brand_avg_rank": 0.0, "sample_count": 3},
                {"prompt": "拉链品牌推荐", "brand_mention_rate": 0.0, "brand_avg_rank": 0.0, "sample_count": 3},
                {"prompt": "SAB靠谱吗", "brand_mention_rate": 100.0, "brand_avg_rank": 1.0, "sample_count": 3},
            ],
            "platform_stats": [{"platform": "doubao", "mention_rate": 10.0, "avg_rank": 1.0, "total": 9}],
            "matrix_rows": [
                {"prompt": "服饰辅料供应商怎么选？", "platform": "doubao", "avg_rank": None},
                {"prompt": "拉链品牌推荐", "platform": "doubao", "avg_rank": None},
                {"prompt": "SAB靠谱吗", "platform": "doubao", "avg_rank": 1.0},
            ],
            "diagnosis": {},
            "cockpit_narrative": {
                "stage_copy": {
                    "all": {
                        "label": "管理层摘要",
                        "title": "获客问法为 0",
                        "summary": "非品牌词获客问法条数为 0，获客提及率均为暂无数据。",
                    },
                    "recognition": {"label": "品牌认知阶段", "title": "t", "summary": "s"},
                    "selection": {"label": "技术选型阶段", "title": "t", "summary": "s"},
                    "procurement": {"label": "项目采购阶段", "title": "t", "summary": "s"},
                    "risk": {"label": "风险质疑阶段", "title": "t", "summary": "s"},
                },
                "risk_rows": [
                    {
                        "topic": "假风险",
                        "impact": "主 KPI 暂无",
                        "models": "豆包",
                        "evidence": "非品牌词获客问法条数为 0",
                        "priority": "P0",
                        "pill": "risk-high",
                    }
                ],
                "priority_items": [
                    {"level_class": "p0", "level": "P0", "tone": "status-risk", "tone_label": "x", "title": "t", "body": "获客问法条数为 0"},
                    {"level_class": "p1", "level": "P1", "tone": "status-gap", "tone_label": "x", "title": "t", "body": "b"},
                    {"level_class": "p2", "level": "P2", "tone": "status-ok", "tone_label": "x", "title": "t", "body": "b"},
                ],
                "actions": [
                    {"level_class": "p0", "level": "P0", "impact": "x", "title": "a", "body": "获客问法条数为 0", "bullets": ["a", "b", "c"]},
                    {"level_class": "p1", "level": "P1", "impact": "x", "title": "a", "body": "b", "bullets": ["a", "b", "c"]},
                    {"level_class": "p2", "level": "P2", "impact": "x", "title": "a", "body": "b", "bullets": ["a", "b", "c"]},
                ],
            },
        }
    )
    ck0 = json.loads(ctx0["cockpit_json"])
    assert ck0["kpi_basis"]["nonbrand"]["total_cells"] == 2
    assert ck0["platformData"]["all"]["visibility"] == 0.0
    assert ck0["platformData"]["all"]["decision"] == 0.0
    assert ck0["platformData"]["all"]["rank"] is None
    assert ck0["platformData"]["all"]["primary_kpi_available"] is True
    assert "0.0%" in ck0["stageCopy"]["all"]["summary"]
    assert "获客问法条数为 0" not in ck0["stageCopy"]["all"]["summary"]
    assert "获客问法条数为 0" not in json.dumps(ck0["risks"], ensure_ascii=False)
    assert validate_cockpit_null0(ck0) == []

    # 来也式：无非品牌格
    ctx_na = build_diagnosis_cockpit_context(
        {
            "brand_name": "来也",
            "prompt_analytics": [
                {"prompt": "来也科技靠谱吗？", "brand_mention_rate": 90.0, "brand_avg_rank": 1.0, "sample_count": 4},
            ],
            "platform_stats": [{"platform": "doubao", "mention_rate": 90.0, "avg_rank": 1.0, "total": 4}],
            "matrix_rows": [
                {"prompt": "来也科技靠谱吗？", "platform": "doubao", "avg_rank": 1.0},
            ],
            "diagnosis": {},
        }
    )
    ck_na = json.loads(ctx_na["cockpit_json"])
    assert ck_na["platformData"]["all"]["visibility"] is None
    assert ck_na["platformData"]["all"]["rank"] is None
    assert ck_na["platformData"]["all"]["decision"] is None
    assert ck_na["platformData"]["all"]["brand_defense"] == 100.0
    assert ck_na["platformData"]["all"]["primary_kpi_available"] is False
    assert "暂无数据" in ck_na["stageCopy"]["all"]["summary"]
    assert validate_cockpit_null0(ck_na) == []


def test_which_vendor_reliable_is_recommend_not_compare():
    # 2026-08-13 - 「哪家比较靠谱」勿被「比较」抢成竞品对比
    row = classify_prompt("地铁广告投放服务商哪家比较靠谱？", brand="艾迪亚")
    assert row["intent_code"] == "recommend"
    assert row["scene_code"] == "transit"


def test_generic_cards_brand_defense_labels_and_platform_rank():
    """品牌排名/口碑用防守口径；平台行带均排；无对口意图勿回退全量获客%。"""
    ctx = build_diagnosis_cockpit_context(
        {
            "brand_name": "艾迪亚控股集团有限公司",
            "prompt_analytics": [
                {
                    "prompt": "户外广告服务商怎么选？",
                    "brand_mention_rate": 66.7,
                    "brand_avg_rank": 2.0,
                    "sample_count": 6,
                },
                {
                    "prompt": "地铁广告投放服务商哪家比较靠谱？",
                    "brand_mention_rate": 100.0,
                    "brand_avg_rank": 2.0,
                    "sample_count": 6,
                },
                {
                    "prompt": "艾迪亚在户外广告和地铁广告服务商里排名怎么样？",
                    "brand_mention_rate": 100.0,
                    "brand_avg_rank": 2.0,
                    "sample_count": 6,
                },
                {
                    "prompt": "艾迪亚控股集团靠谱吗？客户评价怎么样？",
                    "brand_mention_rate": 100.0,
                    "brand_avg_rank": 2.0,
                    "sample_count": 6,
                },
            ],
            "platform_stats": [{"platform": "doubao", "mention_rate": 66.7, "avg_rank": 2.5, "total": 6}],
            "matrix_rows": [
                {"prompt": "户外广告服务商怎么选？", "platform": "doubao", "avg_rank": 2.0},
                {"prompt": "地铁广告投放服务商哪家比较靠谱？", "platform": "doubao", "avg_rank": 3.0},
                {
                    "prompt": "艾迪亚在户外广告和地铁广告服务商里排名怎么样？",
                    "platform": "doubao",
                    "avg_rank": 2.0,
                },
                {
                    "prompt": "艾迪亚控股集团靠谱吗？客户评价怎么样？",
                    "platform": "doubao",
                    "avg_rank": 2.0,
                },
            ],
            "diagnosis": {},
        }
    )
    by_code = {c["code"]: c for c in ctx["product_cards"]}
    brand_card = by_code["brand_rank"]
    assert "品牌防守" in brand_card["metric_sub"]
    assert "格级获客提及率" not in brand_card["metric_sub"]
    assert "均排" in brand_card["metric"]

    rep = by_code["reputation"]
    assert rep["metric_sub"] == "品牌防守提及率"
    assert "格级获客提及率" not in rep["metric_sub"]

    # 无「竞品对比」对口问法时不得伪装成全量获客%
    compare = by_code.get("compare")
    if compare:
        assert compare["metric_sub"] != "格级获客提及率" or "暂无" in compare.get("metric_sub", "")
        if compare.get("tag") == "待补问法":
            assert compare["metric"] == "—"

    plat = next(r for r in ctx["_facts_for_narrative"]["platform_rows"] if r["key"] == "doubao")
    assert plat.get("rank") == 2.5
    assert "intent_basis" in ctx["_facts_for_narrative"]
    assert ctx["_facts_for_narrative"]["kpi_lanes"]["brand_defense"]["prompt_count"] == 2

def test_full_sample_negative_rate_aidiya_like_not_eighty():
    """2026-08-14 - 方案 B：24/270≈8.9%，禁止再用已标注 24/30≈80%。"""
    from app.services.report_diagnosis_cockpit_service import (
        _full_sample_negative_rate,
        _reputation_high_risk,
        build_diagnosis_cockpit_context,
    )

    rate, neg_n, n = _full_sample_negative_rate(
        {"positive": 5, "neutral": 1, "negative": 24, "unknown": 240},
        completed_count=270,
    )
    assert neg_n == 24
    assert n == 270
    assert rate == 8.9
    assert not _reputation_high_risk(sample_n=n, negative_rate=rate, positive_rate=2.2)

    ctx = build_diagnosis_cockpit_context(
        {
            "brand_name": "艾迪亚控股集团有限公司",
            "kpis": {
                "mention_rate": 58.9,
                "avg_rank": 2.0,
                "top3_rate": 40.0,
                "positive_rate": 2.2,
                "completed_count": 270,
            },
            "prompt_analytics": [
                {
                    "prompt": "户外广告公司推荐",
                    "brand_mention_rate": 50.0,
                    "brand_avg_rank": 2.0,
                    "sample_count": 30,
                },
            ],
            "platform_stats": [
                {"platform": "doubao", "mention_rate": 50.0, "avg_rank": 2.0, "total": 45},
            ],
            "sentiment_counts": {"positive": 5, "neutral": 1, "negative": 24, "unknown": 240},
        }
    )
    import json

    cockpit = json.loads(ctx["cockpit_json"])
    plat_all = (cockpit.get("platformData") or {}).get("all") or {}
    assert plat_all.get("negative") == 8.9


def test_reputation_gate_blocks_positive_copy_when_full_sample_negative_high():
    """2026-08-14 - 全样本负面≥40% 才门禁「口碑正面」。"""
    from app.services.report_diagnosis_cockpit_service import (
        _full_sample_negative_rate,
        _reputation_high_risk,
        build_diagnosis_cockpit_context,
    )

    rate, neg_n, n = _full_sample_negative_rate(
        {"positive": 5, "neutral": 1, "negative": 120, "unknown": 144},
        completed_count=270,
    )
    assert neg_n == 120
    assert n == 270
    assert rate == 44.4
    assert _reputation_high_risk(sample_n=n, negative_rate=rate, positive_rate=2.2)

    ctx = build_diagnosis_cockpit_context(
        {
            "brand_name": "艾迪亚控股集团有限公司",
            "kpis": {
                "mention_rate": 58.9,
                "avg_rank": 2.0,
                "top3_rate": 40.0,
                "positive_rate": 2.2,
                "completed_count": 270,
            },
            "prompt_analytics": [
                {
                    "prompt": "户外广告公司推荐",
                    "brand_mention_rate": 50.0,
                    "brand_avg_rank": 2.0,
                    "sample_count": 30,
                },
            ],
            "platform_stats": [
                {"platform": "doubao", "mention_rate": 50.0, "avg_rank": 2.0, "total": 45},
            ],
            "sentiment_counts": {"positive": 5, "neutral": 1, "negative": 120, "unknown": 144},
            "cockpit_narrative": {
                "stage_copy": {
                    "all": {"label": "管理层摘要", "title": "摘要", "summary": "获客尚可。"},
                    "recognition": {"label": "品牌认知阶段", "title": "认知", "summary": "认知一般。"},
                    "selection": {"label": "技术选型阶段", "title": "选型", "summary": "选型一般。"},
                    "procurement": {"label": "项目采购阶段", "title": "采购", "summary": "采购一般。"},
                    "risk": {
                        "label": "风险质疑阶段",
                        "title": "口碑正面，但负面关联需关注",
                        "summary": "口碑正面，舆情风险极低，仅需关注个别负面。",
                    },
                },
                "priority_items": [
                    {"level": "P0 · 场景攻坚", "title": "a", "desc": "d"},
                    {"level": "P1 · 平台覆盖", "title": "b", "desc": "d"},
                    {"level": "P2 · 优势放大", "title": "c", "desc": "d"},
                ],
                "risk_rows": [{"title": "r", "desc": "d"}],
                "actions": [{"title": "a1"}, {"title": "a2"}, {"title": "a3"}],
            },
        }
    )
    import json

    cockpit = json.loads(ctx["cockpit_json"])
    risk = (cockpit.get("stageCopy") or {}).get("risk") or {}
    blob = f"{risk.get('title') or ''} {risk.get('summary') or ''}"
    assert "口碑正面，但" not in blob
    assert "舆情风险极低" not in blob
    assert "口碑风险偏高" in blob
    plat_all = (cockpit.get("platformData") or {}).get("all") or {}
    assert plat_all.get("negative") == 44.4
    insights = ctx.get("insights") or []
    titles = " ".join(str(i.get("title") or "") for i in insights if isinstance(i, dict))
    assert "口碑与风险可控" not in titles
