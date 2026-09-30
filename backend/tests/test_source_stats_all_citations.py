"""信源口径：露出词是品牌相关榜门槛；全量榜不过滤露出词。"""


def test_aggregate_source_stats_requires_exposure_hit():
    from datetime import date
    from types import SimpleNamespace

    from app.services.monitor_service import _aggregate_source_stats

    item = SimpleNamespace(
        id=1,
        platform="kimi",
        prompt="电梯广告公司推荐",
        reference_list_json=[
            {
                "title": "行业报告：户外广告趋势",
                "url": "https://example.com/ads-report",
                "site": "example",
            },
            {
                "title": "艾迪亚传媒案例",
                "url": "https://brand.example.com/case",
                "site": "brand",
            },
        ],
    )
    stats, daily, daily_by_platform = _aggregate_source_stats(
        [item],  # type: ignore[arg-type]
        business_day_by_id={1: date(2026, 7, 12)},
        subtask_tenant_map={1: 6},
        purchased_platforms_by_tenant={6: {"kimi"}},
        exposure_terms_by_tenant={6: ["艾迪亚"]},
    )
    assert len(stats) == 1
    assert stats[0]["url"] == "https://brand.example.com/case"
    assert "艾迪亚" in stats[0]["exposure_terms"]
    assert stats[0]["has_exposure"] is True
    assert daily["2026-07-12"] == 1
    assert daily_by_platform["kimi"]["2026-07-12"] == 1


def test_aggregate_source_stats_pair_includes_all_citations():
    from datetime import date
    from types import SimpleNamespace

    from app.services.monitor_service import _aggregate_source_stats_pair

    item = SimpleNamespace(
        id=1,
        platform="kimi",
        prompt="电梯广告公司推荐",
        reference_list_json=[
            {
                "title": "行业报告：户外广告趋势",
                "url": "https://example.com/ads-report",
                "site": "example",
            },
            {
                "title": "艾迪亚传媒案例",
                "url": "https://brand.example.com/case",
                "site": "brand",
            },
        ],
    )
    branded, all_stats, daily, _ = _aggregate_source_stats_pair(
        [item],  # type: ignore[arg-type]
        business_day_by_id={1: date(2026, 7, 12)},
        subtask_tenant_map={1: 6},
        purchased_platforms_by_tenant={6: {"kimi"}},
        exposure_terms_by_tenant={6: ["艾迪亚"]},
    )
    assert len(branded) == 1
    assert len(all_stats) == 2
    assert daily["2026-07-12"] == 1
    by_url = {row["url"]: row for row in all_stats}
    assert by_url["https://example.com/ads-report"]["has_exposure"] is False
    assert by_url["https://brand.example.com/case"]["has_exposure"] is True
    assert by_url["https://example.com/ads-report"]["count"] == 1
    assert by_url["https://brand.example.com/case"]["count"] == 1


def test_aggregate_source_stats_keeps_earliest_publish_date():
    from datetime import date
    from types import SimpleNamespace

    from app.services.monitor_service import _aggregate_source_stats_pair

    first = SimpleNamespace(
        id=1,
        platform="kimi",
        prompt="机场广告公司哪家好",
        reference_list_json=[
            {
                "title": "2026机场广告公司选择指南",
                "url": "https://baijiahao.baidu.com/s?id=1",
                "site": "百家号",
                "publishTime": "2026-08-21",
            },
            {
                "title": "无日期稿",
                "url": "https://example.com/no-date",
                "site": "example",
                "publishTime": None,
            },
        ],
    )
    second = SimpleNamespace(
        id=2,
        platform="doubao",
        prompt="高铁广告公司哪家好",
        reference_list_json=[
            {
                "title": "2026机场广告公司选择指南",
                "url": "https://baijiahao.baidu.com/s?id=1&from=2",
                "site": "百家号",
                "publishTime": "2026-06-01 16:40:37",
            },
            {
                "title": "坏日期",
                "url": "https://example.com/bad",
                "site": "example",
                "publishTime": "null",
            },
        ],
    )
    _branded, all_stats, _daily, _by_platform = _aggregate_source_stats_pair(
        [first, second],  # type: ignore[arg-type]
        business_day_by_id={1: date(2026, 9, 1), 2: date(2026, 9, 2)},
        subtask_tenant_map={1: 6, 2: 6},
        purchased_platforms_by_tenant={6: {"kimi", "doubao"}},
        exposure_terms_by_tenant={6: []},
    )
    by_url = {row["url"].split("?")[0]: row for row in all_stats}
    assert by_url["https://baijiahao.baidu.com/s"]["publish_time"] == "2026-06-01"
    assert by_url["https://baijiahao.baidu.com/s"]["count"] == 2
    assert by_url["https://example.com/no-date"]["publish_time"] is None
    assert by_url["https://example.com/bad"]["publish_time"] is None
