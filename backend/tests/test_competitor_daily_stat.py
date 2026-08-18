"""B3+ 竞品日表区间聚合自检。"""

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services.monitor_stats_service import (
    competitor_period_rows_from_daily_stats,
    has_competitor_daily_stats,
)


def test_has_competitor_daily_stats_empty_tenant_ids():
    assert has_competitor_daily_stats(MagicMock(), []) is False


def test_competitor_period_rows_weights_same_denominator():
    rows = [
        SimpleNamespace(
            competitor_id=1,
            competitor_name="竞品A",
            platform="kimi",
            completed_count=10,
            mentioned_count=4,
            rank_sum=8,
            rank_count=4,
        ),
        SimpleNamespace(
            competitor_id=1,
            competitor_name="竞品A",
            platform="doubao",
            completed_count=10,
            mentioned_count=6,
            rank_sum=6,
            rank_count=2,
        ),
    ]
    with patch(
        "app.services.monitor_stats_service.list_competitor_daily_stats_for_tenant",
        return_value=rows,
    ):
        out = competitor_period_rows_from_daily_stats(
            MagicMock(),
            1,
            range_start=date(2026, 8, 1),
            range_end=date(2026, 8, 7),
        )
    assert out is not None
    assert len(out) == 1
    assert out[0]["mention_count"] == 10
    assert out[0]["mention_rate"] == 50.0
    assert out[0]["avg_rank"] == round(14 / 6, 1)
    assert out[0]["sample_count"] == 20
