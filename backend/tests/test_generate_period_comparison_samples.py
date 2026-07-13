from __future__ import annotations

import json

from app.services.report_period_comparison_service import (
    enrich_competitor_analytics,
    render_competitor_html,
)


def _monthly_trend() -> dict:
    return {
        "points": [
            {"label": "第1周", "sub": "07-01~07-07"},
            {"label": "第2周", "sub": "07-08~07-14"},
        ]
    }


def test_sample_competitors_share_production_visual_and_analysis_rules() -> None:
    analytics = enrich_competitor_analytics(
        brand_name="艾迪亚控股集团有限公司",
        competitor_names=["分众传媒", "白马户外媒体", "华铁传媒"],
        report_type="monthly",
        trend=_monthly_trend(),
        brand_mention_rate=8.8,
    )

    styles = [series["style"] for series in analytics["rank_trend"]["series"]]
    assert [style["color"] for style in styles] == ["#F28E2B", "#009E73", "#C43C92", "#0057D9"]
    assert len({json.dumps(style["line_type"]) for style in styles}) == 4
    assert len({style["symbol"] for style in styles}) == 4
    assert analytics["analysis"]["management_summary"]
    assert analytics["analysis"]["actions"]


def test_sample_competitor_html_contains_summary_actions_and_risk_legend() -> None:
    analytics = enrich_competitor_analytics(
        brand_name="艾迪亚控股集团有限公司",
        competitor_names=["分众传媒", "白马户外媒体", "华铁传媒"],
        report_type="monthly",
        trend=_monthly_trend(),
        brand_mention_rate=8.8,
    )

    rendered = render_competitor_html(analytics, report_type="monthly")

    assert "竞争格局摘要" in rendered
    assert "运营建议动作" in rendered
    assert "排名风险说明" in rendered
    assert "#F28E2B" in rendered
    assert "#009E73" in rendered
    assert "#C43C92" in rendered
    assert "#0057D9" in rendered
    assert "AI 回答摘录" not in rendered
