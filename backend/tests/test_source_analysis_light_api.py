"""信源分析轻接口：不走整包 monitor_summary。"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services.monitor_service import build_source_analysis_summary


def test_build_source_analysis_summary_uses_source_bundle_only():
    db = MagicMock()
    current = SimpleNamespace(
        identity=SimpleNamespace(id=1, identity_type="CUSTOMER", tenant_id=6),
        user=SimpleNamespace(id=1),
    )
    bundle = {
        "source_stats": [{"url": "https://a.com", "count": 2}],
        "source_stats_all": [{"url": "https://b.com", "count": 3}],
        "source_citation_trend": {"points": [{"label": "07-29", "value": 1}]},
        "source_citation_trend_by_platform": {"doubao": {"points": []}},
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
            "app.services.monitor_service.get_customer_source_stats_bundle",
            return_value=bundle,
        ) as mock_bundle,
        patch(
            "app.services.monitor_stats_service.has_daily_stats",
            return_value=False,
        ),
    ):
        data = build_source_analysis_summary(db, current, tenant_id=None)

    mock_bundle.assert_called_once()
    assert data["tenant_id"] == 6
    assert data["source_stats"][0]["url"] == "https://a.com"
    assert data["source_stats_all"][0]["count"] == 3
    assert data["source_citation_trend"]["points"][0]["value"] == 1
    assert "platform_stats" in data
