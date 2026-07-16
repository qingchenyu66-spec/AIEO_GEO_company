"""Tests for read-cache singleflight helper."""

from unittest.mock import patch

from app.core.read_cache import (
    MANAGEMENT_OVERVIEW_CACHE_KEY,
    get_or_build_json_cache,
    invalidate_dashboard_caches,
    monitor_summary_cache_key,
    source_stats_cache_key,
    workspace_brief_cache_key,
)


def test_get_or_build_returns_cached_without_builder() -> None:
    calls = {"count": 0}

    def builder() -> dict:
        calls["count"] += 1
        return {"built": True}

    with patch("app.core.read_cache.get_json_cache", return_value={"cached": True}):
        result = get_or_build_json_cache("demo:key", builder, ttl_seconds=30)

    assert result == {"cached": True}
    assert calls["count"] == 0


def test_get_or_build_stores_on_miss() -> None:
    stored: dict[str, object] = {}

    def fake_set(key: str, value: object, ttl_seconds: int | None = None) -> None:
        stored[key] = value

    with (
        patch("app.core.read_cache.get_json_cache", side_effect=[None, None]),
        patch("app.core.read_cache.set_json_cache", side_effect=fake_set),
        patch("app.core.read_cache.redis_lock") as lock_mock,
    ):
        lock_mock.return_value.__enter__.return_value = True
        lock_mock.return_value.__exit__.return_value = None
        result = get_or_build_json_cache("demo:miss", lambda: {"v": 1}, ttl_seconds=20)

    assert result == {"v": 1}
    assert stored["demo:miss"] == {"v": 1}


def test_invalidate_dashboard_caches_deletes_summary_and_overview() -> None:
    deleted: list[str] = []
    patterns: list[str] = []

    with (
        patch("app.core.read_cache.delete_cache", side_effect=lambda key: deleted.append(key)),
        patch("app.core.read_cache.delete_cache_pattern", side_effect=lambda key: patterns.append(key)),
    ):
        invalidate_dashboard_caches(tenant_id=6)

    assert MANAGEMENT_OVERVIEW_CACHE_KEY in deleted
    assert monitor_summary_cache_key("CUSTOMER", 6) in deleted
    assert workspace_brief_cache_key(6) in deleted
    assert monitor_summary_cache_key("PLATFORM", "platform") in deleted
    assert "monitor:workspace-brief:v2:6:*" in patterns
    assert "monitor:source-stats:v2:6:*" in patterns
    assert "monitor:source-stats:v3:6:*" in patterns
    assert "monitor:source-stats:v4:6:*" in patterns
    assert "analytics:competitor-compare:v1:*:6:*" in patterns


def test_source_stats_cache_key_includes_cutoff_day() -> None:
    assert source_stats_cache_key(6, "2026-07-13", "abc123") == "monitor:source-stats:v4:6:2026-07-13:abc123"
