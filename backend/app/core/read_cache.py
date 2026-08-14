"""读接口 JSON 缓存：miss 时单飞重建，减轻缓存击穿。

Redis 不可用时回退进程内 L1 缓存，禁止空等 wait（否则会白等满 wait_seconds）。
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from collections.abc import Callable, Iterable
from typing import Any, TypeVar

from app.core.redis_client import delete_cache, delete_cache_pattern, get_json_cache, redis_enabled, set_json_cache
from app.core.redis_client import redis_lock

logger = logging.getLogger(__name__)

T = TypeVar("T")

MANAGEMENT_OVERVIEW_CACHE_KEY = "management:overview:v2"
MANAGEMENT_OVERVIEW_CACHE_TTL = 180
# 重聚合块（平台统计/费用排行/客户累计）独立预缓存，任务同步不打掉
MANAGEMENT_OVERVIEW_ROLLUP_PREFIX = "management:overview:rollup:v1"
MANAGEMENT_OVERVIEW_ROLLUP_TTL = 600
# 方案 B：监测摘要 / 竞品对比用较长 TTL，补录与品牌变更会 invalidate
MONITOR_SUMMARY_CACHE_TTL = 300
WORKSPACE_BRIEF_CACHE_TTL = 45
CELERY_MONITOR_CACHE_TTL = 20
SENTIMENT_KEYWORDS_CACHE_TTL = 120
COMPETITOR_COMPARE_CACHE_TTL = 300
RANKING_MATRIX_CACHE_TTL = 300
# 客户信源全历史聚合贵；按截止日独立缓存，补录时 invalidate
SOURCE_STATS_CACHE_TTL = 6 * 3600
CACHE_BUILD_LOCK_TTL = 45
CACHE_BUILD_WAIT_SECONDS = 3.0
CACHE_BUILD_POLL_INTERVAL = 0.15

# ponytail: Redis AUTH/宕机时进程内兜底；上限防止无限涨（升级：LRU）
_MEMORY_CACHE: dict[str, tuple[float, Any]] = {}
_MEMORY_LOCK = threading.Lock()
_MEMORY_CACHE_MAX = 256


def _memory_get(key: str) -> Any | None:
    now = time.monotonic()
    with _MEMORY_LOCK:
        item = _MEMORY_CACHE.get(key)
        if item is None:
            return None
        expires_at, value = item
        if expires_at < now:
            _MEMORY_CACHE.pop(key, None)
            return None
        return value


def _memory_set(key: str, value: Any, ttl_seconds: int) -> None:
    # ponytail: Redis 作主存时 L1 短缓存即可；Redis 未启用/宕机时 L1 是主存，按请求 TTL（上限 6h）
    cap = 300 if redis_enabled() else min(max(int(ttl_seconds), 300), 6 * 3600)
    ttl = max(5, min(int(ttl_seconds), cap))
    expires_at = time.monotonic() + ttl
    with _MEMORY_LOCK:
        if len(_MEMORY_CACHE) >= _MEMORY_CACHE_MAX and key not in _MEMORY_CACHE:
            # 丢掉最早过期的一批
            oldest = sorted(_MEMORY_CACHE.items(), key=lambda kv: kv[1][0])[:64]
            for old_key, _ in oldest:
                _MEMORY_CACHE.pop(old_key, None)
        _MEMORY_CACHE[key] = (expires_at, value)


def _memory_delete_prefix(prefix: str) -> None:
    with _MEMORY_LOCK:
        for key in [k for k in _MEMORY_CACHE if k.startswith(prefix)]:
            _MEMORY_CACHE.pop(key, None)

def monitor_summary_cache_key(identity_type: str, tenant_key: str | int) -> str:
    return f"monitor:summary:v6:{identity_type}:{tenant_key}"


def ranking_matrix_cache_key(
    identity_type: str,
    tenant_id: int,
    *,
    platform: str | None,
    start_date: str | None,
    end_date: str | None,
    keyword: str | None,
    monitor_group: str | None,
    keyword_group: str | None,
    monitor_keyword: str | None,
    exposure_term: str | None,
    limit_rows: int,
) -> str:
    return (
        f"monitor:ranking-matrix:v2:{identity_type}:{tenant_id}:"
        f"{platform or 'all'}:{start_date or 'default'}:{end_date or 'default'}:"
        f"{keyword or '-'}:{monitor_group or '-'}:{keyword_group or '-'}:"
        f"{monitor_keyword or '-'}:{exposure_term or '-'}:{limit_rows}"
    )


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
    # v5：聚合行带 site 中文站名；升版本强制丢弃无 site 的旧缓存
    return f"monitor:source-stats:v5:{tenant_id}:{cutoff_day}:{config_fp}"


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
        # 2026-07-30 - v4：丢弃 v3 可能缓存的「无各端趋势切片」脏数据
        f"analytics:competitor-compare:v4:{identity_type}:{tenant_id}:"
        f"{platform_key}:{days}:{start_key}:{end_key}:{prompt_key}"
    )


def workspace_brief_cache_key(
    tenant_id: int,
    start_date: str | None = None,
    end_date: str | None = None,
    scope: str = "full",
    purpose: str = "geo",
) -> str:
    start_key = start_date or "default"
    end_key = end_date or "default"
    scope_key = scope if scope in ("full", "summary") else "full"
    purpose_key = purpose if purpose in ("geo", "brand_word") else "geo"
    return f"monitor:workspace-brief:v14:{tenant_id}:{start_key}:{end_key}:{scope_key}:{purpose_key}"


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
        f"analytics:sentiment-keywords:v3:{identity_type}:{tenant_id}:"
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
        _memory_set(key, cached, ttl_seconds)
        return cached

    mem = _memory_get(key)
    if mem is not None:
        return mem

    # Redis 未启用：直接建并写内存，避免走锁/等待逻辑
    if not redis_enabled():
        data = builder()
        _memory_set(key, data, ttl_seconds)
        return data

    lock_key = f"cache-build:{key}"
    with redis_lock(lock_key, ttl_seconds=lock_ttl_seconds) as acquired:
        if not acquired:
            # 锁被占用：等待持锁方写完；禁止全员直接 rebuild（惊群）
            cached = _wait_for_cache(key, wait_seconds=wait_seconds, poll_interval=poll_interval)
            if cached is not None:
                _memory_set(key, cached, ttl_seconds)
                return cached
            mem = _memory_get(key)
            if mem is not None:
                return mem
            with redis_lock(lock_key, ttl_seconds=lock_ttl_seconds) as retry_acquired:
                cached = get_json_cache(key)
                if cached is not None:
                    _memory_set(key, cached, ttl_seconds)
                    return cached
                mem = _memory_get(key)
                if mem is not None:
                    return mem
                if retry_acquired:
                    return _build_and_store(key, builder, ttl_seconds=ttl_seconds)
                # 仍无锁：再短等一轮；实在没有才单次兜底 rebuild（带短 TTL）
                cached = _wait_for_cache(
                    key,
                    wait_seconds=min(wait_seconds, 1.5),
                    poll_interval=poll_interval,
                )
                if cached is not None:
                    _memory_set(key, cached, ttl_seconds)
                    return cached
                logger.warning(
                    "Cache rebuild lock contention, single fallback build, key=%s",
                    key,
                )
                return _build_and_store(key, builder, ttl_seconds=min(int(ttl_seconds), 60))

        cached = get_json_cache(key)
        if cached is not None:
            _memory_set(key, cached, ttl_seconds)
            return cached
        mem = _memory_get(key)
        if mem is not None:
            return mem
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
        mem = _memory_get(key)
        if mem is not None:
            return mem
    return None


def _build_and_store(key: str, builder: Callable[[], T], *, ttl_seconds: int) -> T:
    data = builder()
    set_json_cache(key, data, ttl_seconds=ttl_seconds)
    _memory_set(key, data, ttl_seconds)
    return data


def invalidate_management_overview_cache() -> None:
    delete_cache(MANAGEMENT_OVERVIEW_CACHE_KEY)
    _memory_delete_prefix(MANAGEMENT_OVERVIEW_CACHE_KEY)
    delete_cache_pattern(f"{MANAGEMENT_OVERVIEW_ROLLUP_PREFIX}:*")
    _memory_delete_prefix(MANAGEMENT_OVERVIEW_ROLLUP_PREFIX)
    try:
        from app.core.database import SessionLocal
        from app.services.ops_overview_rollup_service import purge_overview_rollups

        db = SessionLocal()
        try:
            purge_overview_rollups(db)
            db.commit()
        finally:
            db.close()
    except Exception:
        logger.warning("purge ops_overview_rollup failed", exc_info=True)


def invalidate_dashboard_caches(
    tenant_id: int | None = None,
    *,
    bust_overview: bool = True,
) -> None:
    """补录/品牌变更等后清理读缓存。

    bust_overview=False：仅清监测摘要/工作台等，保留运营总览与重聚合预缓存
   （任务同步高频路径用，避免 overview 被打成冷缓存）。
    """
    if bust_overview:
        invalidate_management_overview_cache()
    if tenant_id is not None:
        delete_cache(monitor_summary_cache_key("CUSTOMER", tenant_id))
        delete_cache(workspace_brief_cache_key(tenant_id))
        delete_cache_pattern(f"monitor:workspace-brief:v2:{tenant_id}:*")
        delete_cache_pattern(f"monitor:workspace-brief:v3:{tenant_id}:*")
        delete_cache_pattern(f"monitor:workspace-brief:v4:{tenant_id}:*")
        delete_cache_pattern(f"monitor:workspace-brief:v5:{tenant_id}:*")
        delete_cache_pattern(f"monitor:workspace-brief:v6:{tenant_id}:*")
        delete_cache_pattern(f"monitor:workspace-brief:v7:{tenant_id}:*")
        delete_cache_pattern(f"monitor:workspace-brief:v8:{tenant_id}:*")
        delete_cache_pattern(f"monitor:workspace-brief:v9:{tenant_id}:*")
        delete_cache_pattern(f"monitor:workspace-brief:v10:{tenant_id}:*")
        delete_cache_pattern(f"monitor:workspace-brief:v11:{tenant_id}:*")
        delete_cache_pattern(f"monitor:workspace-brief:v12:{tenant_id}:*")
        # 2026-08-14 - brief 缓存升到 v14（词×平台改 kpi_rank）
        delete_cache_pattern(f"monitor:workspace-brief:v13:{tenant_id}:*")
        delete_cache_pattern(f"monitor:workspace-brief:v14:{tenant_id}:*")
        delete_cache_pattern(f"monitor:source-stats:v2:{tenant_id}:*")
        delete_cache_pattern(f"monitor:source-stats:v3:{tenant_id}:*")
        delete_cache_pattern(f"monitor:source-stats:v4:{tenant_id}:*")
        delete_cache_pattern(f"monitor:source-stats:v5:{tenant_id}:*")
        delete_cache_pattern(f"analytics:competitor-compare:v1:*:{tenant_id}:*")
        delete_cache_pattern(f"analytics:competitor-compare:v2:*:{tenant_id}:*")
        delete_cache_pattern(f"analytics:sentiment-keywords:v1:*:{tenant_id}:*")
        delete_cache_pattern(f"analytics:sentiment-keywords:v2:*:{tenant_id}:*")
        delete_cache_pattern(f"analytics:sentiment-keywords:v3:*:{tenant_id}:*")
        delete_cache_pattern(f"monitor:ranking-matrix:v1:*:{tenant_id}:*")
        delete_cache_pattern(f"monitor:ranking-matrix:v2:*:{tenant_id}:*")
        _memory_delete_prefix(f"monitor:summary:")
        _memory_delete_prefix(f"monitor:workspace-brief:")
        _memory_delete_prefix(f"monitor:source-stats:")
        _memory_delete_prefix(f"monitor:ranking-matrix:")
        _memory_delete_prefix(f"analytics:competitor-compare:")
        _memory_delete_prefix(f"analytics:sentiment-keywords:")
    delete_cache(monitor_summary_cache_key("PLATFORM", "platform"))
    delete_cache_pattern("analytics:competitor-compare:v1:PLATFORM:*")
    delete_cache_pattern("analytics:competitor-compare:v2:PLATFORM:*")
    delete_cache_pattern("monitor:ranking-matrix:v1:PLATFORM:*")
    delete_cache_pattern("monitor:ranking-matrix:v2:PLATFORM:*")
    _memory_delete_prefix("analytics:competitor-compare:")
    _memory_delete_prefix("monitor:ranking-matrix:")
