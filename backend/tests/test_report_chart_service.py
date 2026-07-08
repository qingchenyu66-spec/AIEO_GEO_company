"""Tests for report chart PNG generation."""

from app.services.report_chart_service import (
    build_entity_rank_trend_chart,
    build_mention_rate_bar_chart,
    build_platform_mention_chart,
    build_rank_trend_chart,
    build_sentiment_pie_chart,
)


def test_build_rank_trend_chart_returns_png() -> None:
    png = build_rank_trend_chart([
        {"schedule_label": "2026-06-30 09:30", "avg_rank": 4.2, "mention_rate": 35.0},
        {"schedule_label": "2026-07-01 14:30", "avg_rank": 3.1, "mention_rate": 42.0},
    ])
    assert png is not None
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_build_entity_rank_trend_chart_returns_png() -> None:
    png = build_entity_rank_trend_chart(
        [
            {
                "schedule_label": "2026-06-07",
                "entities": {"儒思HR": 4.0, "北森": 1.0},
                "avg_rank": 4.0,
            },
            {
                "schedule_label": "2026-06-08",
                "entities": {"儒思HR": 2.0, "北森": 3.0},
                "avg_rank": 2.0,
            },
        ],
        brand="儒思HR",
        tracked_entities=["儒思HR", "北森"],
    )
    assert png is not None
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_build_mention_rate_bar_chart_returns_png() -> None:
    png = build_mention_rate_bar_chart(
        [
            {"name": "儒思HR", "mention_rate": 83.7, "is_brand": True},
            {"name": "北森", "mention_rate": 27.9, "is_competitor": True},
        ],
        title="语义词测试",
        brand="儒思HR",
    )
    assert png is not None
    assert len(png) > 1000


def test_build_sentiment_pie_chart_skips_zero_unknown() -> None:
    png = build_sentiment_pie_chart({"正面": 100, "中性": 30, "负面": 10, "未知": 0})
    assert png is not None
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
