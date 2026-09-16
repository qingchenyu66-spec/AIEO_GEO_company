"""信源分析轻接口：不走整包 monitor_summary。"""

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services.monitor_service import build_source_analysis_summary


def test_build_source_analysis_summary_uses_source_bundle_only():
    db = MagicMock()
    current = SimpleNamespace(
        identity=SimpleNamespace(id=1, identity_type="CUSTOMER", tenant_id=6),
        user=SimpleNamespace(id=1, username="demo"),
    )
    ranged = {
        "source_stats": [{"url": "https://a.com", "count": 1, "platforms": ["doubao"]}],
        "source_stats_all": [{"url": "https://b.com", "count": 1, "platforms": ["doubao"]}],
        "source_citation_trend": {"points": [{"label": "08-10", "value": 1}]},
        "source_citation_trend_by_platform": {"doubao": {"points": [{"label": "08-10", "value": 1}]}},
    }

    with (
        patch(
            "app.services.tenant_scope.resolve_and_guard_analytics_tenant",
            return_value=6,
        ),
        patch(
            "app.services.brand_service.get_brand_asset",
            return_value=SimpleNamespace(),
        ),
        patch(
            "app.services.brand_service.active_keyword_groups",
            return_value=[],
        ),
        patch(
            "app.services.brand_service.brand_exposure_terms",
            return_value=["品牌"],
        ),
        patch(
            "app.services.brand_service.tenant_purchased_platforms",
            return_value=["doubao"],
        ),
        patch(
            "app.services.monitor_source_rollup_service.ensure_source_daily_range",
            return_value=[],
        ) as mock_ensure,
        patch(
            "app.services.monitor_service.customer_display_cutoff",
            return_value=SimpleNamespace(date=lambda: date(2026, 8, 13)),
        ),
        patch(
            "app.services.monitor_source_rollup_service._bundle_from_day_rows",
            return_value=ranged,
        ) as mock_range,
        patch(
            "app.services.monitor_stats_service.has_daily_stats",
            return_value=False,
        ),
    ):
        db.scalars.return_value = []
        data = build_source_analysis_summary(
            db,
            current,
            tenant_id=None,
            start_date=date(2026, 8, 7),
            end_date=date(2026, 8, 13),
        )

    mock_range.assert_called_once()
    mock_ensure.assert_called_once()
    assert mock_ensure.call_args.kwargs["start_day"] == date(2026, 8, 7)
    assert mock_ensure.call_args.kwargs["end_day"] == date(2026, 8, 13)
    assert data["tenant_id"] == 6
    assert data["source_stats"][0]["count"] == 1
    assert data["end_date"] == "2026-08-13"
    assert data["source_citation_trend"]["points"][0]["value"] == 1
    assert "platform_stats" in data


def test_build_source_analysis_summary_filters_platform():
    db = MagicMock()
    current = SimpleNamespace(
        identity=SimpleNamespace(id=1, identity_type="CUSTOMER", tenant_id=6),
        user=SimpleNamespace(id=1, username="demo"),
    )
    ranged = {
        "source_stats": [
            {"url": "https://a.com", "count": 2, "platforms": ["doubao", "deepseek"]},
            {"url": "https://b.com", "count": 1, "platforms": ["deepseek"]},
        ],
        "source_stats_all": [
            {"url": "https://a.com", "count": 2, "platforms": ["doubao", "deepseek"]},
        ],
        "source_citation_trend": {"points": [{"label": "08-10", "value": 3}]},
        "source_citation_trend_by_platform": {
            "doubao": {"points": [{"label": "08-10", "value": 2}]},
            "deepseek": {"points": [{"label": "08-10", "value": 1}]},
        },
    }
    with (
        patch("app.services.tenant_scope.resolve_and_guard_analytics_tenant", return_value=6),
        patch("app.services.brand_service.get_brand_asset", return_value=SimpleNamespace()),
        patch("app.services.brand_service.active_keyword_groups", return_value=[]),
        patch("app.services.brand_service.brand_exposure_terms", return_value=["品牌"]),
        patch("app.services.brand_service.tenant_purchased_platforms", return_value=["doubao", "deepseek"]),
        patch("app.services.monitor_source_rollup_service.ensure_source_daily_range", return_value=[]),
        patch(
            "app.services.monitor_service.customer_display_cutoff",
            return_value=SimpleNamespace(date=lambda: date(2026, 8, 13)),
        ),
        patch("app.services.monitor_source_rollup_service._bundle_from_day_rows", return_value=ranged),
        patch("app.services.monitor_stats_service.has_daily_stats", return_value=False),
        patch("app.services.observer_account.observer_platforms_for_session", return_value=None),
    ):
        db.scalars.return_value = []
        data = build_source_analysis_summary(
            db,
            current,
            platform="doubao",
            start_date=date(2026, 8, 7),
            end_date=date(2026, 8, 13),
        )
    assert len(data["source_stats"]) == 1
    assert data["source_stats"][0]["url"] == "https://a.com"
    assert data["source_citation_trend"]["points"][0]["value"] == 2
