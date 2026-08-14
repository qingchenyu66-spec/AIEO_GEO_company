"""日统计按平台过滤后 KPI 口径自检。"""

from types import SimpleNamespace

from app.services.monitor_stats_service import (
    filter_daily_stat_rows_by_platforms,
    workspace_metrics_from_stat_rows,
)


def _row(platform: str, completed: int, mentioned: int, top3: int, rank_sum: float, rank_count: int):
    return SimpleNamespace(
        platform=platform,
        completed_count=completed,
        mentioned_count=mentioned,
        top3_count=top3,
        rank_sum=rank_sum,
        rank_count=rank_count,
    )


def test_filter_daily_stat_rows_and_kpi_recalc():
    rows = [
        _row("doubao", 100, 50, 20, 100.0, 50),
        _row("kimi", 10, 8, 5, 16.0, 8),
        _row("yuanbao", 10, 2, 1, 6.0, 2),
    ]
    all_metrics = workspace_metrics_from_stat_rows(rows)
    assert all_metrics["brand_mention_rate"] == 50.0  # 60/120
    assert all_metrics["mentioned_count"] == 60

    scoped = filter_daily_stat_rows_by_platforms(rows, {"kimi", "yuanbao"})
    scoped_metrics = workspace_metrics_from_stat_rows(scoped)
    # 10/20 = 50% mention; but different from naive all-platform if mix changes
    assert scoped_metrics["ranking_sample_count"] == 20
    assert scoped_metrics["brand_mention_rate"] == 50.0  # 10/20
    assert scoped_metrics["mentioned_count"] == 10
    assert scoped_metrics["top3_rate"] == 30.0  # 6/20
    assert scoped_metrics["avg_brand_rank"] == 2.2  # 22/10


def test_overlay_brand_kpi_from_daily_stats_replaces_brand_row():
    from app.services.competitor_analytics_service import _overlay_brand_kpi_from_daily_stats
    from unittest.mock import MagicMock, patch
    from datetime import datetime

    payload = {
        "rows": [
            {"name": "本品牌", "is_brand": True, "mention_rate": 99.0, "mention_count": 9, "avg_rank": 1.0},
            {"name": "竞品", "is_brand": False, "mention_rate": 10.0, "mention_count": 1, "avg_rank": 3.0},
        ],
        "mention_trends": {
            "labels": ["08-06", "08-07"],
            "series": [
                {"name": "本品牌", "is_brand": True, "values": [0.0, 0.0]},
                {"name": "竞品", "is_brand": False, "values": [10.0, 20.0]},
            ],
        },
        "platform_rows": [],
        "sample_total": 10,
    }
    metrics = {
        "ranking_sample_count": 54,
        "mentioned_count": 25,
        "brand_mention_rate": 46.3,
        "avg_brand_rank": 2.0,
        "top3_rate": 40.0,
        "top3_count": 20,
        "exposure_sample_count": 0,
        "negative_count": 0,
        "negative_rate": 0.0,
    }
    with patch(
        "app.services.competitor_analytics_service.get_brand_asset",
        return_value=None,
    ), patch(
        "app.services.brand_service.tenant_purchased_platforms",
        return_value=["doubao"],
    ), patch(
        "app.services.monitor_stats_service.brand_period_metrics_from_daily_stats",
        return_value=metrics,
    ), patch(
        "app.services.monitor_stats_service.workspace_kpi_trends_from_stats",
        return_value=[
            {"label": "08-06", "mention_rate": 33.3},
            {"label": "08-07", "mention_rate": 50.0},
        ],
    ):
        out = _overlay_brand_kpi_from_daily_stats(
            MagicMock(),
            1,
            payload,
            range_start=datetime(2026, 8, 6),
            range_end=datetime(2026, 8, 12),
            platform_filters=[],
            brand_display="本品牌",
            sorted_days=["2026-08-06", "2026-08-07"],
            trend_labels=["08-06", "08-07"],
        )
    brand = next(r for r in out["rows"] if r["is_brand"])
    assert brand["mention_rate"] == 46.3
    assert brand["mention_count"] == 25
    assert brand["sample_count"] == 54
    assert out["sample_total"] == 54
    assert out["brand_kpi_basis"] == "daily_stat"
    brand_series = next(s for s in out["mention_trends"]["series"] if s["is_brand"])
    assert brand_series["values"] == [33.3, 50.0]
    # 竞品行不被日表覆盖
    comp = next(r for r in out["rows"] if not r["is_brand"])
    assert comp["mention_rate"] == 10.0
