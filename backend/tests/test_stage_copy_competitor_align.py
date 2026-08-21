# -*- coding: utf-8 -*-
from __future__ import annotations

import json

from app.services.report_diagnosis_cockpit_service import build_diagnosis_cockpit_context


def test_stage_copy_selection_is_competitor_not_criteria():
    """顶栏竞品对标应对齐 stageCopy.selection，不得再写技术选型/选型标准。"""
    ctx = build_diagnosis_cockpit_context(
        {
            "brand_name": "SAB伟星拉链",
            "kpis": {"mention_rate": 50.0, "avg_rank": 2.0, "top3_rate": 33.3, "positive_rate": 90},
            "prompt_analytics": [
                {
                    "prompt": "服饰辅料供应商怎么选？有没有选型标准？",
                    "brand_mention_rate": 5.6,
                    "brand_avg_rank": 5.0,
                    "sample_count": 9,
                },
                {
                    "prompt": "拉链品牌推荐哪家好",
                    "brand_mention_rate": 55.6,
                    "brand_avg_rank": 2.0,
                    "sample_count": 9,
                },
            ],
            "platform_stats": [
                {"platform": "doubao", "mention_rate": 33.3, "avg_rank": 1.0},
                {"platform": "chatgpt", "mention_rate": 66.7, "avg_rank": 2.5},
            ],
            "source_analysis": {
                "total_references": 10,
                "brand_related_references": 4,
                "domain_stats": [],
            },
            "competitors": ["YKK"],
            "competitor_stats": [{"name": "YKK", "hit_count": 3, "sample_total": 6, "rate": 50.0}],
            "diagnosis": {},
            "sentiment_counts": {"positive": 8, "neutral": 1, "negative": 1},
            # 旧叙事包：selection 仍写选型标准
            "cockpit_narrative": {
                "stage_copy": {
                    "all": {"label": "管理层摘要", "title": "t", "summary": "s"},
                    "recognition": {"label": "品牌认知阶段", "title": "t", "summary": "s"},
                    "selection": {
                        "label": "技术选型阶段",
                        "title": "选型标准类问法覆盖薄弱",
                        "summary": "只有 1 条非品牌选型标准问法。",
                    },
                    "procurement": {"label": "项目采购阶段", "title": "t", "summary": "s"},
                    "risk": {"label": "风险质疑阶段", "title": "t", "summary": "s"},
                }
            },
        }
    )
    cockpit = json.loads(ctx["cockpit_json"])
    sc = cockpit["stageCopy"]
    assert sc["selection"]["label"] == "竞品对标"
    assert "选型标准" not in str(sc["selection"].get("title") or "")
    assert "选型标准" not in str(sc["selection"].get("summary") or "")
    assert "技术选型" not in str(sc["selection"])
    assert sc["recognition"]["label"] == "品牌认知"
    assert sc["procurement"]["label"] == "推荐名单"
    assert sc["risk"]["label"] == "口碑评价"
    # 2026-08-21 - 标题/阶段不得再写选型标准；引号内原问法可保留原词作证据
    for item in cockpit.get("priority_items") or []:
        assert "选型标准" not in str(item.get("title") or "")
    assert "选型标准" not in str(sc.get("selection") or "")


def test_priority_criteria_title_scrubbed_to_recommend():
    """落库叙事 P0 写「选型标准问法零提及」时，对外应 scrub 成推荐类，不再出现选型品类。"""
    ctx = build_diagnosis_cockpit_context(
        {
            "brand_name": "SAB伟星拉链",
            "kpis": {"mention_rate": 11.1, "avg_rank": 1.4, "top3_rate": 11.1, "positive_rate": 90},
            "prompt_analytics": [
                {
                    "prompt": "服饰辅料供应商怎么选？有没有选择标准？",
                    "brand_mention_rate": 0.0,
                    "brand_avg_rank": None,
                    "sample_count": 1,
                }
            ],
            "platform_stats": [{"platform": "doubao", "mention_rate": 0.0, "avg_rank": None}],
            "source_analysis": {"total_references": 1, "brand_related_references": 0, "domain_stats": []},
            "competitors": [],
            "diagnosis": {},
            "sentiment_counts": {"positive": 1, "neutral": 0, "negative": 0},
            "cockpit_narrative": {
                "stage_copy": {
                    "all": {"label": "管理层摘要", "title": "t", "summary": "s"},
                    "recognition": {"label": "品牌认知", "title": "t", "summary": "s"},
                    "selection": {"label": "竞品对标", "title": "t", "summary": "s"},
                    "procurement": {"label": "推荐名单", "title": "t", "summary": "s"},
                    "risk": {"label": "口碑评价", "title": "t", "summary": "s"},
                },
                "priority_items": [
                    {
                        "level_class": "p0",
                        "level": "P0 · 意图攻坚",
                        "tone": "status-risk",
                        "tone_label": "缺口明显",
                        "title": "选型标准问法零提及",
                        "body": "该意图是采购决策前置环节，零提及意味着品牌未进入选型标准讨论。",
                    },
                    {
                        "level_class": "p1",
                        "level": "P1 · 问法补强",
                        "tone": "status-gap",
                        "tone_label": "需结构化",
                        "title": "平台证据",
                        "body": "补证据",
                    },
                    {
                        "level_class": "p2",
                        "level": "P2 · 优势放大",
                        "tone": "status-ok",
                        "tone_label": "基础较强",
                        "title": "巩固优势",
                        "body": "放大",
                    },
                ],
            },
        }
    )
    cockpit = json.loads(ctx["cockpit_json"])
    p0 = (cockpit.get("priority_items") or [{}])[0]
    blob = json.dumps(cockpit.get("priority_items") or [], ensure_ascii=False)
    assert "选型标准" not in blob
    assert "选型路径" not in str(p0.get("title") or "")
    assert "选择标准" not in str(p0.get("title") or "")
    assert "推荐" in str(p0.get("title") or "")
