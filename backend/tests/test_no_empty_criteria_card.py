# -*- coding: utf-8 -*-
from app.services.report_diagnosis_cockpit_service import build_diagnosis_cockpit_context


def test_portfolio_has_no_empty_criteria_shell():
    """2026-08-20 - 无选型标准对口样本时，意图矩阵不得再塞「选型标准 / 暂无对口样本」空壳。"""
    ctx = build_diagnosis_cockpit_context(
        {
            "brand_name": "测试品牌",
            "kpis": {"mention_rate": 40.0, "avg_rank": 3.0, "top3_rate": 20.0, "positive_rate": 80},
            "prompt_analytics": [
                {
                    "prompt": "地铁广告公司推荐",
                    "brand_mention_rate": 50.0,
                    "brand_avg_rank": 2.0,
                    "sample_count": 6,
                }
            ],
            "platform_stats": [{"platform": "doubao", "mention_rate": 50.0, "avg_rank": 2.0}],
            "source_analysis": {
                "total_references": 10,
                "brand_related_references": 2,
                "domain_stats": [],
            },
            "competitors": [],
            "diagnosis": {},
            "sentiment_counts": {"positive": 8, "neutral": 1, "negative": 1},
        }
    )
    labels = [str(c.get("label") or "") for c in ctx["product_cards"]]
    assert "选型标准" not in labels
    assert "选型路径" not in labels
    assert not any(
        c.get("label") in {"选型标准", "选型路径"} and c.get("tag") == "待补问法" for c in ctx["product_cards"]
    )
