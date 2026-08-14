# -*- coding: utf-8 -*-
"""ponytail: 区间合并日物化 count 只含区间内；脏 CDN 读路径剔除。"""
from datetime import date, datetime, time
from types import SimpleNamespace

from app.services.monitor_source_rollup_service import _bundle_from_day_rows


def test_bundle_from_day_rows_respects_range_and_filters_cdn():
    day_a = SimpleNamespace(
        stat_date=date(2026, 8, 10),
        branded_json={
            "https://www.smzdm.com/p/1": {
                "title": "smzdm",
                "url": "https://www.smzdm.com/p/1",
                "count": 2,
                "platforms": ["doubao"],
                "exposure_terms": ["宝得聪"],
                "questions": [],
                "latest_time": "2026-08-10T12:00:00",
            },
            "https://g.alicdn.com": {
                "title": "cdn",
                "url": "https://g.alicdn.com",
                "count": 9,
                "platforms": ["doubao"],
                "exposure_terms": [],
                "questions": [],
                "latest_time": "2026-08-10T12:00:00",
            },
        },
        all_json={},
        daily_branded_count=11,
        daily_by_platform_json={"doubao": 11},
    )
    day_b = SimpleNamespace(
        stat_date=date(2026, 8, 1),
        branded_json={
            "https://www.zhihu.com/q/1": {
                "title": "zhihu",
                "url": "https://www.zhihu.com/q/1",
                "count": 5,
                "platforms": ["doubao"],
                "exposure_terms": [],
                "questions": [],
                "latest_time": "2026-08-01T12:00:00",
            },
        },
        all_json={},
        daily_branded_count=5,
        daily_by_platform_json={"doubao": 5},
    )
    bundle = _bundle_from_day_rows(
        [day_a, day_b],
        cutoff_day=date(2026, 8, 13),
        range_start_day=date(2026, 8, 7),
    )
    urls = {row["url"] for row in bundle["source_stats"]}
    assert "https://www.smzdm.com/p/1" in urls
    assert "https://g.alicdn.com" not in urls
    assert "https://www.zhihu.com/q/1" not in urls
    assert bundle["source_stats"][0]["count"] == 2
    points = bundle["source_citation_trend"]["points"]
    assert points
    assert all(pt["value"] != 5 for pt in points)
