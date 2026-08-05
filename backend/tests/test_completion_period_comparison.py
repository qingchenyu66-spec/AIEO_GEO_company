# -*- coding: utf-8 -*-
"""结项首末窗口对比。"""

from datetime import date
from types import SimpleNamespace

from app.services.report_completion_context_service import build_early_late_comparison


def _row(day: str, platform: str, completed: int, mentioned: int, top3: int = 0, rank_sum: int = 0, rank_count: int = 0):
    return SimpleNamespace(
        stat_date=date.fromisoformat(day),
        platform=platform,
        completed_count=completed,
        mentioned_count=mentioned,
        top3_count=top3,
        rank_sum=rank_sum,
        rank_count=rank_count,
    )


def test_early_late_comparison_overall_and_platform() -> None:
    rows = []
    # early days
    for i, day in enumerate(["2026-06-30", "2026-07-01", "2026-07-02", "2026-07-03", "2026-07-04", "2026-07-05", "2026-07-06"]):
        rows.append(_row(day, "kimi", 100, 30, 20, 60, 30))
        rows.append(_row(day, "doubao", 100, 50, 40, 80, 50))
    # late days
    for day in ["2026-07-25", "2026-07-26", "2026-07-27", "2026-07-28", "2026-07-29", "2026-07-30", "2026-07-31"]:
        rows.append(_row(day, "kimi", 100, 80, 60, 80, 80))  # mention up
        rows.append(_row(day, "doubao", 100, 30, 20, 90, 30))  # mention down

    cmp = build_early_late_comparison(rows, window_days=7, min_platform_samples=30)
    assert cmp["available"] is True
    assert cmp["early_label"] == "06-30~07-06"
    assert cmp["late_label"] == "07-25~07-31"
    assert cmp["overall"]["early"]["mention_rate"] == 40.0
    assert cmp["overall"]["late"]["mention_rate"] == 55.0
    assert cmp["overall"]["delta_mention_rate"] == 15.0

    by_code = {r["platform"]: r for r in cmp["platforms"]}
    assert by_code["kimi"]["reliable"] is True
    assert by_code["kimi"]["delta_mention_rate"] == 50.0
    assert by_code["doubao"]["delta_mention_rate"] == -20.0
    assert any("kimi" in h for h in cmp["highlights"])


def test_platform_unreliable_when_sparse() -> None:
    rows = [
        _row("2026-07-01", "quark", 10, 5, 2, 5, 5),
        _row("2026-07-02", "quark", 10, 5, 2, 5, 5),
        _row("2026-07-30", "quark", 10, 1, 0, 1, 1),
        _row("2026-07-31", "quark", 10, 1, 0, 1, 1),
        _row("2026-07-01", "kimi", 50, 10, 5, 20, 10),
        _row("2026-07-31", "kimi", 50, 40, 30, 40, 40),
    ]
    cmp = build_early_late_comparison(rows, window_days=2, min_platform_samples=30)
    by_code = {r["platform"]: r for r in cmp["platforms"]}
    assert by_code["quark"]["reliable"] is False
    assert by_code["kimi"]["reliable"] is True
