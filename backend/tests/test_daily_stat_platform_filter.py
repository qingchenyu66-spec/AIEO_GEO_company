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

    scoped = filter_daily_stat_rows_by_platforms(rows, {"kimi", "yuanbao"})
    scoped_metrics = workspace_metrics_from_stat_rows(scoped)
    # 10/20 = 50% mention; but different from naive all-platform if mix changes
    assert scoped_metrics["ranking_sample_count"] == 20
    assert scoped_metrics["brand_mention_rate"] == 50.0  # 10/20
    assert scoped_metrics["top3_rate"] == 30.0  # 6/20
    assert scoped_metrics["avg_brand_rank"] == 2.2  # 22/10
