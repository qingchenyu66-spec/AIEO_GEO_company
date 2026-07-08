"""Tests for unified tenant diagnosis report pipeline."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.services.report_service import _merge_rich_monitor_snapshot


def test_merge_rich_monitor_snapshot_copies_lead_analytics_fields() -> None:
    content = {"monitor_snapshot": {"platform_stats": [{"platform": "doubao"}]}}
    snapshot = {
        "prompt_analytics": [{"prompt": "测试问题", "brand_mention_rate": 50}],
        "rank_trend": [{"round": 1, "avg_rank": 2.0}],
        "brand_city_rankings": [{"city": "北京", "avg_rank": 1.5}],
        "matrix_rows": [{"prompt": "测试问题", "platform": "doubao"}],
    }
    merged = _merge_rich_monitor_snapshot(content, snapshot)
    monitor = merged["monitor_snapshot"]
    assert monitor["prompt_analytics"][0]["prompt"] == "测试问题"
    assert monitor["rank_trend"][0]["round"] == 1
    assert monitor["brand_city_rankings"][0]["city"] == "北京"
    assert monitor["matrix_rows"][0]["platform"] == "doubao"
    assert merged["diagnosis_pipeline"] == "lead_diagnosis"


def test_compose_tenant_diagnosis_report_bundle_uses_lead_aggregate() -> None:
    from app.services.report_service import compose_tenant_diagnosis_report_bundle

    fake_result = {
        "brand_name": "艾迪亚控股",
        "company_name": "艾迪亚控股集团有限公司",
        "period_label": "2026-01-01 至 2026-01-03 · 三天九次均值（9/9 次有效抓取）",
        "kpis": {"mention_rate": 66.7, "completed_count": 27, "health_score": 72},
        "diagnosis": {"health_score": 72, "sentiment_summary": "测试摘要"},
        "ai_insights": {"highlights": ["亮点A"]},
        "report_sections": {"overview": "概览"},
        "monitor_snapshot": {
            "highlights": ["亮点A"],
            "platform_stats": [{"platform": "doubao", "mention_rate": 80}],
            "sentiment_counts": {"positive": 10},
            "top_sources": [{"title": "官网", "count": 3}],
            "prompt_analytics": [{"prompt": "品牌推荐", "brand_mention_rate": 50}],
            "rank_trend": [{"round": 1}],
        },
    }
    db = MagicMock()
    with patch(
        "app.services.report_service.aggregate_tenant_diagnosis",
        return_value=fake_result,
    ):
        with patch("app.services.report_service.list_competitors", return_value=[]):
            bundle = compose_tenant_diagnosis_report_bundle(db, tenant_id=6)

    assert bundle["content"]["diagnosis_pipeline"] == "lead_diagnosis"
    assert bundle["content"]["monitor_snapshot"]["prompt_analytics"]
    assert bundle["content"]["report_modules"] is not None
    assert bundle["report_title"] == "GEO 企业诊断报告"
    assert "三天九次均值" in bundle["data_summary"]
