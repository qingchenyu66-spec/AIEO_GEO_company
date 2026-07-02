"""Redis-backed global rate limiter for shared external APIs."""

from __future__ import annotations

import logging
import time
from typing import Literal

from redis.exceptions import RedisError

from app.core.config import settings
from app.core.redis_client import get_redis_client, prefixed_key

logger = logging.getLogger(__name__)

RateCategory = Literal["submit", "sync", "default"]


def _limit_for_category(category: RateCategory) -> int:
    if category == "submit":
        return settings.molizhishu_submit_rate_per_minute
    if category == "sync":
        return settings.molizhishu_sync_rate_per_minute
    return min(settings.molizhishu_submit_rate_per_minute, settings.molizhishu_sync_rate_per_minute)


def _minute_bucket_key(category: RateCategory) -> str:
    bucket = time.strftime("%Y%m%d%H%M")
    return prefixed_key(f"rl:molizhishu:{category}:{bucket}")


def acquire_molizhishu_rate_limit(category: RateCategory = "default") -> None:
    """Block until the current minute bucket has capacity, or raise TimeoutError."""
    limit = max(1, _limit_for_category(category))
    max_wait = max(0.0, settings.molizhishu_rate_limit_max_wait_seconds)
    deadline = time.monotonic() + max_wait

    while True:
        client = get_redis_client()
        if client is None:
            return

        key = _minute_bucket_key(category)
        try:
            count = int(client.incr(key))
            if count == 1:
                client.expire(key, 120)
            if count <= limit:
                return
            client.decr(key)
        except RedisError as exc:
            logger.warning("Rate limiter unavailable, category=%s error=%s", category, exc)
            return

        if time.monotonic() >= deadline:
            raise TimeoutError(f"模力指数 {category} 调用超过全局限流 {limit}/min，等待超时")

        time.sleep(0.25)
