# -*- coding: utf-8 -*-
"""口碑阶段：品牌词有样本时不得把非品牌口碑0格写成主风险。"""
from __future__ import annotations

import json

from app.services.report_diagnosis_cockpit_service import build_diagnosis_cockpit_context


def test_risk_stage_not_headline_nonbrand_reputation_gap_when_brand_has_cells():
    ctx = build_diagnosis_cockpit_context(
        {
            "brand_name": "SAB伟星拉链",
            "kpis": {"mention_rate": 50.0, "avg_rank": 2.0, "top3_rate": 40.0, "positive_rate": 90},
            "prompt_analytics": [
                {
                    "prompt": "服饰辅料供应商推荐",
                    "brand_mention_rate": 50.0,
                    "brand_avg_rank": 2.0,
                    "sample_count": 9,
                },
                {
                    "prompt": "SAB伟星拉链品牌靠谱吗？用户评价怎么样？",
                    "brand_mention_rate": 94.4,
                    "brand_avg_rank": 1.8,
                    "sample_count": 18,
                },
            ],
            "platform_stats": [{"platform": "doubao", "mention_rate": 50.0, "avg_rank": 2.0}],
            "source_analysis": {"total_references": 10, "brand_related_references": 4, "domain_stats": []},
            "competitors": [],
            "diagnosis": {},
            "sentiment_counts": {"positive": 20, "neutral": 2, "negative": 0},
            "cockpit_narrative": {
                "stage_copy": {
                    "all": {"label": "管理层摘要", "title": "t", "summary": "s"},
                    "recognition": {"label": "品牌认知", "title": "t", "summary": "s"},
                    "selection": {"label": "竞品对标", "title": "t", "summary": "s"},
                    "procurement": {"label": "推荐名单", "title": "t", "summary": "s"},
                    "risk": {
                        "label": "口碑评价",
                        "title": "品牌口碑正面，但非品牌口碑无样本",
                        "summary": (
                            "品牌词口碑问法提及率94.4%，均排1.8，情绪正面。"
                            "非品牌词口碑问法样本为0，暂无数据，无法评估自然口碑。"
                        ),
                    },
                }
            },
        }
    )
    cockpit = json.loads(ctx["cockpit_json"])
    risk = (cockpit.get("stageCopy") or {}).get("risk") or {}
    blob = f"{risk.get('title') or ''}{risk.get('summary') or ''}"
    assert "非品牌口碑无样本" not in blob
    assert "无法评估自然口碑" not in blob
    assert "品牌词" in blob or "品牌防守" in blob or "可引用" in blob
