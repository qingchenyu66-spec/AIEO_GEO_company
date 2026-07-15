"""Redis-backed rate limiter with in-process fallback when Redis is unavailable."""

from __future__ import annotations

import logging
import threading
import time
from typing import Literal

from redis.exceptions import RedisError

from app.core.config import settings
from app.core.redis_client import get_redis_client, prefixed_key

logger = logging.getLogger(__name__)

RateCategory = Literal["submit", "sync", "default"]


class RateLimitExceeded(Exception):
    """Raised when a rate limit bucket is exhausted."""


class _LocalMinuteRateLimiter:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: dict[str, tuple[str, int]] = {}

    def try_acquire(self, key: str, limit: int) -> bool:
        bucket = time.strftime("%Y%m%d%H%M")
        with self._lock:
            stored = self._counts.get(key)
            if stored is None or stored[0] != bucket:
                self._counts[key] = (bucket, 1)
                return True
            count = stored[1] + 1
            if count > limit:
                return False
            self._counts[key] = (bucket, count)
            return True


_local_limiter = _LocalMinuteRateLimiter()


def _limit_for_category(category: RateCategory) -> int:
    from app.services.system_config_service import get_runtime_config

    if category == "submit":
        return int(get_runtime_config("molizhishu_submit_rate_per_minute"))
    if category == "sync":
        return int(get_runtime_config("molizhishu_sync_rate_per_minute"))
    return min(
        int(get_runtime_config("molizhishu_submit_rate_per_minute")),
        int(get_runtime_config("molizhishu_sync_rate_per_minute")),
    )


def _minute_bucket_key(prefix: str, category: str) -> str:
    bucket = time.strftime("%Y%m%d%H%M")
    return prefixed_key(f"rl:{prefix}:{category}:{bucket}")


def _local_fallback_limit(limit_per_minute: int) -> int:
    ratio = max(0.1, min(1.0, settings.rate_limit_local_fallback_ratio))
    return max(1, int(limit_per_minute * ratio))


def _acquire_local(scope: str, key: str, limit_per_minute: int) -> None:
    local_key = f"{scope}:{key}"
    local_limit = _local_fallback_limit(limit_per_minute)
    if _local_limiter.try_acquire(local_key, local_limit):
        return
    logger.warning("Rate limit exceeded (local fallback) scope=%s key=%s limit=%s", scope, key, local_limit)
    raise RateLimitExceeded(f"{scope} rate limit exceeded")


def acquire_rate_limit(scope: str, key: str, limit_per_minute: int) -> None:
    """Acquire one HTTP/action token for the current minute bucket."""
    limit = max(1, limit_per_minute)
    redis_key = _minute_bucket_key("http", f"{scope}:{key}")
    client = get_redis_client()
    if client is None:
        logger.warning("HTTP rate limiter Redis unavailable, using local fallback scope=%s", scope)
        _acquire_local(scope, key, limit)
        return

    try:
        count = int(client.incr(redis_key))
        if count == 1:
            client.expire(redis_key, 120)
        if count <= limit:
            return
        client.decr(redis_key)
        raise RateLimitExceeded(f"{scope} rate limit exceeded")
    except RedisError as exc:
        logger.warning("HTTP rate limiter Redis error, using local fallback scope=%s error=%s", scope, exc)
        _acquire_local(scope, key, limit)


def acquire_molizhishu_rate_limit(category: RateCategory = "default") -> None:
    """Block until the current minute bucket has capacity, or raise TimeoutError."""
    from app.services.system_config_service import get_runtime_config

    limit = max(1, _limit_for_category(category))
    max_wait = max(0.0, float(get_runtime_config("molizhishu_rate_limit_max_wait_seconds")))
    deadline = time.monotonic() + max_wait

    while True:
        client = get_redis_client()
        if client is None:
            logger.warning("Molizhishu rate limiter Redis unavailable, using local fallback category=%s", category)
            _acquire_local("molizhishu", category, limit)
            return

        key = _minute_bucket_key("molizhishu", category)
        try:
            count = int(client.incr(key))
            if count == 1:
                client.expire(key, 120)
            if count <= limit:
                return
            client.decr(key)
        except RedisError as exc:
            logger.warning("Molizhishu rate limiter Redis error, using local fallback category=%s error=%s", category, exc)
            _acquire_local("molizhishu", category, limit)
            return

        if time.monotonic() >= deadline:
            raise TimeoutError(f"监测接口 {category} 调用超过全局限流 {limit}/min，等待超时")

        time.sleep(0.25)
