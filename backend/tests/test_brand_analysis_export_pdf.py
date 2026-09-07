# -*- coding: utf-8 -*-
from app.services.brand_analysis_export_service import (
    _build_pdf,
    _fallback_advice,
    _is_registry_noise,
    content_disposition_attachment,
)


def test_registry_noise_filter():
    assert _is_registry_noise("公司成立于2008年，法定代表人张三")
    assert not _is_registry_noise("户外媒体覆盖公交地铁机场")


def test_build_pdf_bytes_with_fallback_advice():
    facts = {
        "brand": "测试品牌",
        "period_label": "2026-08-08 ~ 2026-09-07",
        "compare_window": "月",
        "sample_count": 12,
        "share_pct": {"正面": 49.6, "中性": 44.9, "负面": 5.6},
        "delta_pt": {"正面": -1.1, "中性": 2.2, "负面": -1.0},
        "platforms": [
            {
                "name": "元宝",
                "positive_pct": 14.0,
                "neutral_pct": 61.0,
                "negative_pct": 25.0,
                "sample_count": 20,
            }
        ],
        "top_descriptions": [
            {"sentiment": "正面", "description": "户外媒体覆盖公交地铁", "sample_count": 8},
        ],
        "metric_note": "占比按 AI 描述归并组数；样本数为监测回答条数",
    }
    advice = _fallback_advice(facts)
    assert len(advice["actions"]) == 3
    pdf = _build_pdf(facts, advice)
    assert pdf[:4] == b"%PDF"
    assert len(pdf) > 1000


def test_content_disposition_has_utf8_filename():
    header = content_disposition_attachment("艾迪亚_品牌口碑_月.pdf")
    assert "attachment;" in header
    assert "filename*=" in header
