"""客户信源全历史走独立缓存；语义仍是露出词门槛 + 截止昨日。"""

from datetime import datetime
from unittest.mock import patch


def test_get_customer_source_stats_bundle_uses_cache_key_with_cutoff() -> None:
    from app.core.read_cache import SOURCE_STATS_CACHE_TTL, source_stats_cache_key
    from app.services.monitor_service import get_customer_source_stats_bundle

    captured: dict[str, object] = {}

    def fake_get_or_build(key, builder, *, ttl_seconds, **kwargs):
        captured["key"] = key
        captured["ttl"] = ttl_seconds
        return {"source_stats": [{"url": "https://x"}], "source_citation_trend": {"points": []}}

    with (
        patch(
            "app.services.monitor_service.customer_display_cutoff",
            return_value=datetime(2026, 7, 13, 23, 59, 59),
        ),
        patch("app.core.read_cache.get_or_build_json_cache", side_effect=fake_get_or_build),
    ):
        result = get_customer_source_stats_bundle(
            db=None,  # type: ignore[arg-type]
            tenant_id=6,
            purchased_platforms={"kimi"},
            exposure_terms=["艾迪亚"],
        )

    assert result["source_stats"][0]["url"] == "https://x"
    from app.core.read_cache import source_stats_config_fingerprint

    fp = source_stats_config_fingerprint(["艾迪亚"], ["kimi"])
    assert captured["key"] == source_stats_cache_key(6, "2026-07-13", fp)
    assert captured["ttl"] == SOURCE_STATS_CACHE_TTL


def test_source_stats_fingerprint_changes_with_exposure() -> None:
    from app.core.read_cache import source_stats_config_fingerprint

    a = source_stats_config_fingerprint(["艾迪亚"], ["kimi"])
    b = source_stats_config_fingerprint(["艾迪亚", "AIDIYA"], ["kimi"])
    assert a != b
