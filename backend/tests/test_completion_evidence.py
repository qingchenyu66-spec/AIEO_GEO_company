# -*- coding: utf-8 -*-
"""结项成绩/挑战样本选样。"""

from app.services.report_completion_context_service import (
    brand_leads_answer,
    competitor_leads_answer,
    select_completion_evidence,
)


def test_brand_leads_requires_brand_before_competitor() -> None:
    brand = ["艾迪亚", "艾迪亚控股"]
    comps = ["分众传媒", "德高中国"]
    assert brand_leads_answer(
        "推荐首选艾迪亚控股，其次可关注区域代理。",
        brand_terms=brand,
        competitor_names=comps,
    )
    assert not brand_leads_answer(
        "1. 分众传媒为绝对龙头；也可关注艾迪亚。",
        brand_terms=brand,
        competitor_names=comps,
    )
    assert competitor_leads_answer(
        "分众、新潮是全国头部；艾迪亚适合整合投放。",
        brand_terms=brand,
        competitor_names=comps,
    )


def test_select_completion_evidence_splits_brand_and_challenge() -> None:
    rows = [
        {
            "platform": "kimi",
            "prompt": "机场广告公司推荐",
            "brand_rank": 1,
            "answer": "首选艾迪亚控股集团，覆盖枢纽机场资源。",
            "screenshot_url": "https://example.com/a.png",
            "sentiment": "positive",
            "reference_count": 5,
        },
        {
            "platform": "kimi",
            "prompt": "电梯广告公司推荐",
            "brand_rank": 1,
            "answer": "1. 分众传媒绝对龙头……也可看看艾迪亚。",
            "screenshot_url": "https://example.com/b.png",
            "sentiment": "positive",
            "reference_count": 5,
        },
        {
            "platform": "doubao",
            "prompt": "电梯广告公司哪家好",
            "brand_rank": None,
            "answer": "分众、新潮、城市纵横是全国三大头部。",
            "screenshot_url": None,
            "sentiment": "neutral",
            "reference_count": 2,
        },
    ]
    picked = select_completion_evidence(
        rows,
        brand_terms=["艾迪亚", "艾迪亚控股"],
        competitor_names=["分众传媒", "新潮"],
        brand_limit=3,
        challenge_limit=3,
    )
    assert len(picked["brand_evidence"]) == 1
    assert "艾迪亚" in picked["brand_evidence"][0]["answer_excerpt"]
    assert len(picked["challenge_evidence"]) == 2
    assert all(item["kind"] == "competitor_lead" for item in picked["challenge_evidence"])
