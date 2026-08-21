# -*- coding: utf-8 -*-
from __future__ import annotations

import json

from app.services.report_diagnosis_cockpit_service import (
    build_diagnosis_cockpit_context,
    render_diagnosis_cockpit_html,
)


def test_platform_views_generated_without_sample_pollution():
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
                    "prompt": "高性价比服饰辅料供应商推荐",
                    "brand_mention_rate": 55.6,
                    "brand_avg_rank": 1.6,
                    "sample_count": 9,
                },
                {
                    "prompt": "SAB伟星拉链品牌靠谱吗？",
                    "brand_mention_rate": 100.0,
                    "brand_avg_rank": 1.0,
                    "sample_count": 9,
                },
            ],
            "platform_stats": [
                {"platform": "doubao", "mention_rate": 33.3, "avg_rank": 1.0},
                {"platform": "chatgpt", "mention_rate": 66.7, "avg_rank": 2.5},
            ],
            "source_analysis": {
                "total_references": 40,
                "brand_related_references": 10,
                "domain_stats": [{"domain": "douyin.com", "count": 5}],
            },
            "competitors": ["YKK"],
            "competitor_stats": [{"name": "YKK", "hit_count": 3, "sample_total": 6, "rate": 50.0}],
            "diagnosis": {"recommendation": "test"},
            "sentiment_counts": {"positive": 80, "neutral": 10, "negative": 10},
            "matrix_rows": [
                {
                    "prompt": "服饰辅料供应商怎么选？有没有选型标准？",
                    "platform": "doubao",
                    "avg_rank": 0,
                    "sample_count": 3,
                },
                {
                    "prompt": "服饰辅料供应商怎么选？有没有选型标准？",
                    "platform": "chatgpt",
                    "avg_rank": 5,
                    "sample_count": 3,
                },
                {
                    "prompt": "高性价比服饰辅料供应商推荐",
                    "platform": "doubao",
                    "avg_rank": 1,
                    "sample_count": 3,
                },
                {
                    "prompt": "高性价比服饰辅料供应商推荐",
                    "platform": "chatgpt",
                    "avg_rank": 2,
                    "sample_count": 3,
                },
                {
                    "prompt": "SAB伟星拉链品牌靠谱吗？",
                    "platform": "doubao",
                    "avg_rank": 1,
                    "sample_count": 3,
                },
                {
                    "prompt": "SAB伟星拉链品牌靠谱吗？",
                    "platform": "chatgpt",
                    "avg_rank": 1,
                    "sample_count": 3,
                },
            ],
            "snapshot_evidence": {
                "服饰辅料供应商怎么选？有没有选型标准？|doubao": {
                    "answer_summary": "本地暂无明确辅料供应商名单，建议先看区域替代方案。",
                    "mentioned": False,
                    "rank": None,
                },
                "高性价比服饰辅料供应商推荐|chatgpt": {
                    "answer_summary": "综合性价比可关注 SAB伟星拉链、YKK 等。",
                    "mentioned": True,
                    "rank": 2,
                },
            },
        }
    )
    cockpit = json.loads(ctx["cockpit_json"])
    views = cockpit["platformViews"]
    assert "all" in views and views["all"].get("restore") is True
    assert "doubao" in views and "chatgpt" in views
    assert views["doubao"]["col"] == 0
    assert views["chatgpt"]["col"] == 1
    assert isinstance(views["doubao"].get("quotes"), list)
    assert views["doubao"]["quotes"], "platform slice should carry quotes"
    assert views["doubao"]["stages"]["selection"]["title"].endswith("同框席位")
    assert "艾迪亚" not in json.dumps(views, ensure_ascii=False)
    assert cockpit.get("allPriorityHTML")
    assert cockpit.get("visibleStages") == [
        "all",
        "recognition",
        "selection",
        "procurement",
        "risk",
    ]
    assert isinstance(cockpit.get("priority"), list)
    assert isinstance(cockpit.get("priority_items"), list)
    # 本地答法含地域线索时应打出桌面同款标签
    doubao_tags = {q.get("tag") for q in views["doubao"]["quotes"]}
    assert "地域跑偏" in doubao_tags or "未进入推荐" in doubao_tags
    html = render_diagnosis_cockpit_html(
        {
            "brand_name": "SAB伟星拉链",
            "kpis": {"mention_rate": 50.0, "avg_rank": 2.0, "top3_rate": 33.3, "positive_rate": 90},
            "prompt_analytics": [
                {
                    "prompt": "拉链品牌推荐",
                    "brand_mention_rate": 40.0,
                    "brand_avg_rank": 2.0,
                    "sample_count": 6,
                }
            ],
            "platform_stats": [{"platform": "doubao", "mention_rate": 40.0, "avg_rank": 2.0}],
            "source_analysis": {
                "total_references": 10,
                "brand_related_references": 4,
                "domain_stats": [],
            },
            "competitors": [],
            "diagnosis": {},
            "sentiment_counts": {"positive": 8, "neutral": 1, "negative": 1},
        }
    )
    assert 'id="scheme-a-fullslice"' in html
    assert 'id="schemeAViewNote"' in html
    assert "platformViews" in html
    assert "艾迪亚" not in html
