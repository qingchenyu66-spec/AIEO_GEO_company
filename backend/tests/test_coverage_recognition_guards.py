# -*- coding: utf-8 -*-
"""覆盖标签含 0% 意图；认知页不得把无防守写成无法评估口碑。"""
from __future__ import annotations

import json

from app.services.report_diagnosis_cockpit_service import (
    _intent_coverage_label,
    _sanitize_recognition_defense_scope,
    build_diagnosis_cockpit_context,
)


def test_coverage_label_includes_zero_mention_intents() -> None:
    label = _intent_coverage_label(
        {
            "intents": {
                "awareness": {
                    "nonbrand": {"total_cells": 4, "mention_rate": 25.0},
                    "brand": {"total_cells": 0},
                },
                "recommend": {
                    "nonbrand": {"total_cells": 1, "mention_rate": 0.0},
                    "brand": {"total_cells": 0},
                },
                "compare": {"nonbrand": {"total_cells": 0}, "brand": {"total_cells": 0}},
                "reputation": {"nonbrand": {"total_cells": 0}, "brand": {"total_cells": 0}},
            }
        }
    )
    assert "品牌认知" in label
    assert "推荐名单" in label
    assert label.index("品牌认知") < label.index("推荐名单")


def test_recognition_stage_cannot_claim_cannot_eval_reputation() -> None:
    out = _sanitize_recognition_defense_scope(
        {
            "recognition": {
                "label": "品牌认知",
                "title": "品牌认知类问法提及率 25%，但品牌词防守样本缺失",
                "summary": (
                    "监测事实：非品牌词品牌认知类问法共 4 格，提及率 25.0%。"
                    "品牌词防守问法数为 0。分析判断：但品牌词防守数据缺失，"
                    "无法评估品牌口碑和品牌词排名。建议后续补充品牌词监测。"
                ),
            }
        }
    )
    blob = f"{out['recognition']['title']}{out['recognition']['summary']}"
    assert "无法评估品牌口碑" not in blob
    assert "无法评估品牌词防守" in blob or "防守提及与点名排名" in blob


def test_recognition_cross_scrubbed_in_cockpit_context() -> None:
    ctx = build_diagnosis_cockpit_context(
        {
            "brand_name": "沛安达",
            "kpis": {"mention_rate": 20.0, "avg_rank": 2.0, "top3_rate": 20.0, "positive_rate": 80},
            "prompt_analytics": [
                {
                    "prompt": "减重术后选哪款品牌蛋白粉更好",
                    "brand_mention_rate": 100.0,
                    "brand_avg_rank": 2.0,
                    "sample_count": 12,
                },
                {
                    "prompt": "有没有不腥的乳清蛋白粉品牌推荐",
                    "brand_mention_rate": 0.0,
                    "brand_avg_rank": None,
                    "sample_count": 12,
                },
            ],
            "platform_stats": [{"platform": "doubao", "mention_rate": 20.0, "avg_rank": 2.0}],
            "source_analysis": {"total_references": 10, "brand_related_references": 2, "domain_stats": []},
            "competitors": [],
            "diagnosis": {},
            "sentiment_counts": {"positive": 8, "neutral": 2, "negative": 0},
            "cockpit_narrative": {
                "stage_copy": {
                    "all": {"label": "管理层摘要", "title": "t", "summary": "s"},
                    "recognition": {
                        "label": "品牌认知",
                        "title": "品牌认知 25%，但品牌词防守样本缺失",
                        "summary": "防守问法数为 0，无法评估品牌口碑和品牌词排名。",
                    },
                    "selection": {"label": "竞品对标", "title": "t", "summary": "s"},
                    "procurement": {"label": "推荐名单", "title": "t", "summary": "s"},
                    "risk": {"label": "口碑评价", "title": "t", "summary": "s"},
                },
                "priority_items": [
                    {"level": "P0", "level_class": "p0", "tone": "status-risk", "tone_label": "a", "title": "t", "body": "b"},
                    {"level": "P1", "level_class": "p1", "tone": "status-gap", "tone_label": "a", "title": "t", "body": "b"},
                    {"level": "P2", "level_class": "p2", "tone": "status-ok", "tone_label": "a", "title": "t", "body": "b"},
                ],
                "actions": [
                    {"day": "30", "title": "a", "desc": "d"},
                    {"day": "60", "title": "a", "desc": "d"},
                    {"day": "90", "title": "a", "desc": "d"},
                ],
                "risk_rows": [
                    {"issue": "i", "coverage": "c", "impact": "m", "evidence": "e", "priority": "P0"},
                    {"issue": "i", "coverage": "c", "impact": "m", "evidence": "e", "priority": "P1"},
                    {"issue": "i", "coverage": "c", "impact": "m", "evidence": "e", "priority": "P2"},
                    {"issue": "i", "coverage": "c", "impact": "m", "evidence": "e", "priority": "P2"},
                ],
                "schema": "cockpit-narrative-v1",
                "source": "test",
            },
        }
    )
    assert "推荐名单" in str(ctx.get("coverage_label") or "")
    raw = ctx.get("cockpit_json")
    cockpit = json.loads(raw) if isinstance(raw, str) else (raw or {})
    recog = ((cockpit.get("stageCopy") or {}).get("recognition") or {})
    blob = f"{recog.get('title') or ''}{recog.get('summary') or ''}"
    assert "无法评估品牌口碑" not in blob
    assert "无法评估品牌词防守" in blob or "防守提及与点名排名" in blob
