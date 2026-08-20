"""工作台趋势点透出 sample_count，供前端空日断点。"""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace


def test_workspace_kpi_trends_empty_day_sample_count_zero():
    from app.services.monitor_stats_service import workspace_kpi_trends_from_stats

    calls: dict[str, object] = {}

    def fake_list(_db, _tenant_id, *, since, until):
        calls["since"] = since
        calls["until"] = until
        return []

    import app.services.monitor_stats_service as mod

    original = mod.list_daily_stats_for_tenant
    mod.list_daily_stats_for_tenant = fake_list  # type: ignore[assignment]
    try:
        start = datetime(2026, 8, 18)
        end = datetime(2026, 8, 19)
        points = workspace_kpi_trends_from_stats(SimpleNamespace(), 1, start, end)
    finally:
        mod.list_daily_stats_for_tenant = original  # type: ignore[assignment]

    assert len(points) == 2
    assert points[0]["sample_count"] == 0
    assert points[1]["sample_count"] == 0
    assert calls["since"] == date(2026, 8, 18)
    assert calls["until"] == date(2026, 8, 19)
    assert points[0]["label"] == "08-18"
