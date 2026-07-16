"""客户引用趋势不补零日。"""

from datetime import datetime


def test_build_source_citation_trend_only_with_data_skips_zeros():
    from app.services.monitor_service import _build_source_citation_trend

    trend = _build_source_citation_trend(
        {
            "2026-04-15": 0,
            "2026-06-30": 36,
            "2026-07-01": 15,
            "2026-07-13": 27,
        },
        range_start=datetime(2026, 4, 15),
        range_end=datetime(2026, 7, 13),
        only_with_data=True,
    )
    assert [p["day_key"] for p in trend["points"]] == [
        "2026-06-30",
        "2026-07-01",
        "2026-07-13",
    ]
    assert [p["value"] for p in trend["points"]] == [36, 15, 27]


def test_build_source_citation_trends_by_platform():
    from datetime import datetime

    from app.services.monitor_service import _build_source_citation_trends_by_platform

    trends = _build_source_citation_trends_by_platform(
        {
            "doubao": {"2026-07-13": 10, "2026-07-14": 7},
            "kimi": {"2026-07-14": 3},
        },
        range_start=datetime(2026, 7, 1),
        range_end=datetime(2026, 7, 15),
        only_with_data=True,
    )
    assert trends["doubao"]["points"] == [
        {"label": "07-13", "day_key": "2026-07-13", "value": 10},
        {"label": "07-14", "day_key": "2026-07-14", "value": 7},
    ]
    assert trends["kimi"]["points"] == [
        {"label": "07-14", "day_key": "2026-07-14", "value": 3},
    ]
