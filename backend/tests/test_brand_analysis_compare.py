"""品牌分析 B+：描述组比例与环比窗口。"""

from __future__ import annotations

from datetime import datetime

from app.services.brand_analysis_service import (
    _description_compare_block,
    _sentiment_share_pct,
    _tally_description_group_counts,
    brand_compare_windows,
    resolve_brand_compare_period,
)


def test_resolve_compare_period_defaults_month() -> None:
    assert resolve_brand_compare_period(None) == "month"
    assert resolve_brand_compare_period("WEEK") == "week"
    assert resolve_brand_compare_period("nope") == "month"


def test_brand_compare_windows_equal_length() -> None:
    anchor = datetime(2026, 9, 22, 9, 0, 0)
    win = brand_compare_windows(anchor, "week")
    assert win["days"] == 7
    assert win["range_end"] == anchor
    assert (win["current_start"] - win["previous_start"]).days == 7
    assert (win["range_end"] - win["current_start"]).days == 7
    assert win["current_label"] == "2026-09-15 ~ 2026-09-22"


def test_brand_compare_windows_stable_when_calendar_day_moves() -> None:
    """同一抓取锚点：隔天打开窗口不变（客户可解释口径）。"""
    crawl = datetime(2026, 9, 22, 9, 5, 0)
    mon = brand_compare_windows(crawl, "week")
    thu = brand_compare_windows(crawl, "week")
    assert mon["current_label"] == thu["current_label"]
    assert mon["previous_label"] == thu["previous_label"]
    # 若误用「今天」作锚点，周四会滚到 09-17~09-24
    drifted = brand_compare_windows(datetime(2026, 9, 24, 10, 0, 0), "week")
    assert drifted["current_label"] != mon["current_label"]


def test_description_share_matches_filter_style_counts() -> None:
    rows = (
        [{"sentiment": "正面"}] * 343
        + [{"sentiment": "中性"}] * 214
        + [{"sentiment": "负面"}] * 37
    )
    counts = _tally_description_group_counts(rows)
    assert counts["正面"] == 343
    assert counts["中性"] == 214
    assert counts["负面"] == 37
    share = _sentiment_share_pct(counts)
    assert share["正面"] == 57.7
    assert share["中性"] == 36.0
    assert share["负面"] == 6.2
    assert abs(share["正面"] + share["中性"] + share["负面"] - 100.0) < 0.2


def test_description_compare_delta_pt() -> None:
    cur = {"正面": 60, "中性": 30, "负面": 10, "未知": 0}
    prev = {"正面": 50, "中性": 40, "负面": 10, "未知": 0}
    block = _description_compare_block(
        current_counts=cur,
        previous_counts=prev,
        current_share=_sentiment_share_pct(cur),
        previous_share=_sentiment_share_pct(prev),
    )
    assert block["insufficient"] is False
    assert block["deltas"]["正面_pt"] == 10.0
    assert block["deltas"]["中性_pt"] == -10.0
    assert block["deltas"]["负面_pt"] == 0.0


def test_description_compare_empty_prev_never_shows_rise() -> None:
    cur = {"正面": 10, "中性": 5, "负面": 2, "未知": 0}
    prev = {"正面": 0, "中性": 0, "负面": 0, "未知": 0}
    block = _description_compare_block(
        current_counts=cur,
        previous_counts=prev,
        current_share=_sentiment_share_pct(cur),
        previous_share=_sentiment_share_pct(prev),
    )
    assert block["insufficient"] is True
    assert block["reason"] == "empty"
    assert all(v is None for v in block["deltas"].values())


def test_description_compare_small_prev_still_compares() -> None:
    """上期只有少量组也如实环比，不做满 N 才比的魔法门槛。"""
    cur = {"正面": 8, "中性": 1, "负面": 1, "未知": 0}
    prev = {"正面": 2, "中性": 2, "负面": 1, "未知": 0}
    block = _description_compare_block(
        current_counts=cur,
        previous_counts=prev,
        current_share=_sentiment_share_pct(cur),
        previous_share=_sentiment_share_pct(prev),
    )
    assert block["insufficient"] is False
    assert block["deltas"]["正面_pt"] is not None


def test_subtask_event_at_prefers_remote_time_over_updated_at() -> None:
    from types import SimpleNamespace

    from app.services.brand_analysis_service import _subtask_event_at

    item = SimpleNamespace(
        remote_time=1_725_000_000_000,  # ms
        updated_at=datetime(2026, 9, 7, 15, 0, 0),
        task=SimpleNamespace(created_at=datetime(2026, 8, 1, 0, 0, 0)),
    )
    assert _subtask_event_at(item) == datetime.fromtimestamp(1_725_000_000_000 / 1000.0)
