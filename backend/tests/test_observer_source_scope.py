"""观察号信源：读路径按平台过滤，不改日物化 purchased。"""

from app.services.monitor_service import scope_source_analysis_bundle


def test_scope_source_analysis_bundle_filters_platforms_and_trend():
    bundle = {
        "source_stats": [
            {"url": "https://a.example/1", "count": 3, "platforms": ["doubao", "kimi"], "exposure_terms": ["艾迪亚"]},
            {"url": "https://b.example/2", "count": 2, "platforms": ["yuanbao"], "exposure_terms": ["艾迪亚"]},
            {"url": "https://c.example/3", "count": 1, "platforms": ["doubao"], "exposure_terms": ["艾迪亚"]},
        ],
        "source_stats_all": [
            {"url": "https://a.example/1", "count": 5, "platforms": ["kimi"], "exposure_terms": []},
            {"url": "https://d.example/4", "count": 1, "platforms": ["wenxin"], "exposure_terms": []},
        ],
        "source_citation_trend": {"points": [{"day_key": "2026-08-08", "value": 9}]},
        "source_citation_trend_by_platform": {
            "doubao": {"points": [{"day_key": "2026-08-08", "label": "08-08", "value": 4}]},
            "kimi": {"points": [{"day_key": "2026-08-08", "label": "08-08", "value": 3}]},
            "yuanbao": {"points": [{"day_key": "2026-08-08", "label": "08-08", "value": 2}]},
        },
    }
    scoped = scope_source_analysis_bundle(bundle, frozenset({"kimi", "yuanbao"}))
    urls = {row["url"] for row in scoped["source_stats"]}
    assert urls == {"https://a.example/1", "https://b.example/2"}
    a_row = next(r for r in scoped["source_stats"] if r["url"].endswith("/1"))
    assert a_row["platforms"] == ["kimi"]  # doubao 被裁掉
    assert {row["url"] for row in scoped["source_stats_all"]} == {"https://a.example/1"}
    assert set(scoped["source_citation_trend_by_platform"]) == {"kimi", "yuanbao"}
    points = scoped["source_citation_trend"]["points"]
    assert len(points) == 1
    assert points[0]["value"] == 5  # 3+2，不含 doubao


def test_scope_source_analysis_bundle_none_allow_passthrough():
    bundle = {"source_stats": [{"url": "u", "platforms": ["doubao"], "count": 1}]}
    assert scope_source_analysis_bundle(bundle, None) is bundle
