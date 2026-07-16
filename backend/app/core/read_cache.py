"""读接口 JSON 缓存：miss 时单飞重建，减轻缓存击穿。"""

from __future__ import annotations

import hashlib
import logging
import time
from collections.abc import Callable, Iterable
from typing import TypeVar

from app.core.redis_client import delete_cache, delete_cache_pattern, get_json_cache, redis_lock, set_json_cache

logger = logging.getLogger(__name__)

T = TypeVar("T")

MANAGEMENT_OVERVIEW_CACHE_KEY = "management:overview:v1"
MANAGEMENT_OVERVIEW_CACHE_TTL = 30
# 方案 B：监测摘要 / 竞品对比用较长 TTL，补录与品牌变更会 invalidate
MONITOR_SUMMARY_CACHE_TTL = 300
WORKSPACE_BRIEF_CACHE_TTL = 45
CELERY_MONITOR_CACHE_TTL = 20
SENTIMENT_KEYWORDS_CACHE_TTL = 120
COMPETITOR_COMPARE_CACHE_TTL = 300
# 客户信源全历史聚合贵；按截止日独立缓存，补录时 invalidate
SOURCE_STATS_CACHE_TTL = 6 * 3600
CACHE_BUILD_LOCK_TTL = 45
CACHE_BUILD_WAIT_SECONDS = 3.0
CACHE_BUILD_POLL_INTERVAL = 0.15


def monitor_summary_cache_key(identity_type: str, tenant_key: str | int) -> str:
    return f"monitor:summary:v3:{identity_type}:{tenant_key}"


def source_stats_config_fingerprint(
    exposure_terms: Iterable[str],
    platforms: Iterable[str],
) -> str:
    """露出词 + 购买平台变更时换 key，避免脏读旧聚合。"""
    terms = "|".join(sorted({str(t).strip() for t in exposure_terms if str(t).strip()}))
    plats = "|".join(sorted({str(p).strip() for p in platforms if str(p).strip()}))
    raw = f"{terms}#{plats}".encode("utf-8")
    return hashlib.sha1(raw).hexdigest()[:12]


def source_stats_cache_key(tenant_id: int, cutoff_day: str, config_fp: str = "default") -> str:
    return f"monitor:source-stats:v2:{tenant_id}:{cutoff_day}:{config_fp}"


def competitor_compare_cache_key(
    identity_type: str,
    tenant_id: int | str,
    *,
    platform: str | None,
    platforms: str | None,
    days: int,
    start_date: str | None,
    end_date: str | None,
    prompt: str | None,
) -> str:
    platform_key = platforms or platform or "all"
    prompt_key = prompt or "all"
    start_key = start_date or "default"
    end_key = end_date or "default"
    return (
        f"analytics:competitor-compare:v1:{identity_type}:{tenant_id}:"
        f"{platform_key}:{days}:{start_key}:{end_key}:{prompt_key}"
    )


def workspace_brief_cache_key(
    tenant_id: int,
    start_date: str | None = None,
    end_date: str | None = None,
) -> str:
    start_key = start_date or "default"
    end_key = end_date or "default"
    return f"monitor:workspace-brief:v2:{tenant_id}:{start_key}:{end_key}"


def celery_monitor_cache_key() -> str:
    return "celery:monitor:panel:v1"


def sentiment_keywords_cache_key(
    identity_type: str,
    tenant_id: int,
    *,
    platform: str | None,
    platforms: str | None,
    days: int,
    start_date: str | None,
    end_date: str | None,
    prompt: str | None,
    limit: int,
) -> str:
    platform_key = platforms or platform or "all"
    prompt_key = prompt or "all"
    start_key = start_date or "default"
    end_key = end_date or "default"
    return (
        f"analytics:sentiment-keywords:v1:{identity_type}:{tenant_id}:"
        f"{platform_key}:{days}:{start_key}:{end_key}:{prompt_key}:{limit}"
    )


def get_or_build_json_cache(
    key: str,
    builder: Callable[[], T],
    *,
    ttl_seconds: int,
    lock_ttl_seconds: int = CACHE_BUILD_LOCK_TTL,
    wait_seconds: float = CACHE_BUILD_WAIT_SECONDS,
    poll_interval: float = CACHE_BUILD_POLL_INTERVAL,
) -> T:
    """缓存命中直接返回；miss 时仅一个请求回源写缓存，其余短暂等待后读缓存。"""
    cached = get_json_cache(key)
    if cached is not None:
        return cached

    lock_key = f"cache-build:{key}"
    with redis_lock(lock_key, ttl_seconds=lock_ttl_seconds) as acquired:
        if not acquired:
            cached = _wait_for_cache(key, wait_seconds=wait_seconds, poll_interval=poll_interval)
            if cached is not None:
                return cached
            with redis_lock(lock_key, ttl_seconds=lock_ttl_seconds) as retry_acquired:
                cached = get_json_cache(key)
                if cached is not None:
                    return cached
                if retry_acquired:
                    return _build_and_store(key, builder, ttl_seconds=ttl_seconds)
                cached = _wait_for_cache(key, wait_seconds=wait_seconds, poll_interval=poll_interval)
                if cached is not None:
                    return cached
                logger.warning("Cache rebuild lock contention, fallback to direct build, key=%s", key)
                return builder()

        cached = get_json_cache(key)
        if cached is not None:
            return cached
        return _build_and_store(key, builder, ttl_seconds=ttl_seconds)


def _wait_for_cache(
    key: str,
    *,
    wait_seconds: float,
    poll_interval: float,
) -> object | None:
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        time.sleep(poll_interval)
        cached = get_json_cache(key)
        if cached is not None:
            return cached
    return None


def _build_and_store(key: str, builder: Callable[[], T], *, ttl_seconds: int) -> T:
    data = builder()
    set_json_cache(key, data, ttl_seconds=ttl_seconds)
    return data


def invalidate_management_overview_cache() -> None:
    delete_cache(MANAGEMENT_OVERVIEW_CACHE_KEY)


def invalidate_dashboard_caches(tenant_id: int | None = None) -> None:
    """补录/同步/品牌变更后清理运营总览、监测摘要、信源、竞品与工作台缓存。"""
    invalidate_management_overview_cache()
    if tenant_id is not None:
        delete_cache(monitor_summary_cache_key("CUSTOMER", tenant_id))
        delete_cache(workspace_brief_cache_key(tenant_id))
        delete_cache_pattern(f"monitor:workspace-brief:v2:{tenant_id}:*")
        delete_cache_pattern(f"monitor:source-stats:v2:{tenant_id}:*")
        delete_cache_pattern(f"analytics:competitor-compare:v1:*:{tenant_id}:*")
        delete_cache_pattern(f"analytics:sentiment-keywords:v1:*:{tenant_id}:*")
    delete_cache(monitor_summary_cache_key("PLATFORM", "platform"))
    delete_cache_pattern("analytics:competitor-compare:v1:PLATFORM:*")
