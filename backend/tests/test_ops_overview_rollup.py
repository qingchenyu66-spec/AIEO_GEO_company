"""ops_overview_rollup scope helper smoke."""

from app.services.ops_overview_rollup_service import (
    COST_RANKING_WINDOW_DAYS,
    PLATFORM_STATS_WINDOW_DAYS,
    overview_rollup_scope,
)


def test_overview_rollup_scope_stable() -> None:
    assert overview_rollup_scope(None) == "platform"
    assert overview_rollup_scope([3, 1]) == overview_rollup_scope([1, 3])
    assert overview_rollup_scope([1, 2]) != overview_rollup_scope([1, 3])
    assert PLATFORM_STATS_WINDOW_DAYS == 7
    assert COST_RANKING_WINDOW_DAYS == 30
