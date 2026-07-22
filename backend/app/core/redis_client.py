"""Redis 基础能力封装：健康检查、JSON 缓存和分布式锁。

Redis 在本系统中是上线增强组件，不作为本地开发的硬依赖：
未启用或连接失败时，业务会自动回退到 MySQL 实时查询。
"""

from __future__ import annotations

import json
import logging
import uuid
from contextlib import contextmanager
from typing import Any, Iterator

from redis import Redis
from redis.exceptions import RedisError

from app.core.config import settings

logger = logging.getLogger(__name__)

_client: Redis | None = None


def redis_enabled() -> bool:
    """判断当前环境是否启用 Redis。"""
    return bool(settings.redis_enabled and settings.redis_url)


def get_redis_client() -> Redis | None:
    """懒加载 Redis 连接池，避免应用启动时因 Redis 不可用直接失败。"""
    global _client
    if not redis_enabled():
        return None
    if _client is None:
        _client = Redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_timeout=settings.redis_socket_timeout_seconds,
            socket_connect_timeout=settings.redis_socket_timeout_seconds,
            health_check_interval=30,
        )
        # ponytail: 配置了密码但本地 Redis 未设 requirepass → 每条命令 AUTH 失败；降级无密码重连
        try:
            _client.ping()
        except RedisError as exc:
            msg = str(exc).lower()
            if "auth" in msg or "password" in msg:
                logger.warning("Redis AUTH rejected, retry without password: %s", exc)
                try:
                    _client.close()
                except Exception:
                    pass
                bare = settings.redis_url
                if "@" in bare.split("://", 1)[-1]:
                    # redis://:pass@host:6379/0 → redis://host:6379/0
                    scheme, rest = bare.split("://", 1)
                    rest = rest.split("@", 1)[-1]
                    bare = f"{scheme}://{rest}"
                _client = Redis.from_url(
                    bare,
                    decode_responses=True,
                    socket_timeout=settings.redis_socket_timeout_seconds,
                    socket_connect_timeout=settings.redis_socket_timeout_seconds,
                    health_check_interval=30,
                )
            else:
                logger.warning("Redis ping failed: %s", exc)
    return _client


def prefixed_key(key: str) -> str:
    """统一 Redis key 前缀，避免多项目共用 Redis 时互相污染。"""
    prefix = settings.redis_key_prefix.strip(":")
    return f"{prefix}:{key}" if prefix else key


def redis_health() -> dict[str, Any]:
    """返回健康检查需要的 Redis 状态。"""
    if not redis_enabled():
        return {"enabled": False, "status": "disabled", "detail": "Redis 未启用"}
    client = get_redis_client()
    if client is None:
        return {"enabled": True, "status": "unavailable", "detail": "Redis 客户端未初始化"}
    try:
        pong = client.ping()
        return {"enabled": True, "status": "ready" if pong else "unavailable", "detail": "Redis 可连接"}
    except RedisError as exc:
        logger.warning("Redis health check failed: %s", exc)
        return {"enabled": True, "status": "unavailable", "detail": str(exc)}


def get_json_cache(key: str) -> Any | None:
    """读取 JSON 缓存；异常时直接返回 None，由调用方回源数据库。"""
    client = get_redis_client()
    if client is None:
        return None
    try:
        raw = client.get(prefixed_key(key))
        return json.loads(raw) if raw else None
    except (RedisError, json.JSONDecodeError, TypeError) as exc:
        logger.warning("Read Redis cache failed, key=%s, error=%s", key, exc)
        return None


def set_json_cache(key: str, value: Any, ttl_seconds: int | None = None) -> None:
    """写入 JSON 缓存；失败只记录日志，不影响主业务写库。"""
    client = get_redis_client()
    if client is None:
        return
    ttl = ttl_seconds or settings.redis_default_ttl_seconds
    try:
        client.setex(prefixed_key(key), ttl, json.dumps(value, ensure_ascii=False, default=str))
    except (RedisError, TypeError) as exc:
        logger.warning("Write Redis cache failed, key=%s, error=%s", key, exc)


def delete_cache(key: str) -> None:
    """删除单个缓存 key。"""
    client = get_redis_client()
    if client is None:
        return
    try:
        client.delete(prefixed_key(key))
    except RedisError as exc:
        logger.warning("Delete Redis cache failed, key=%s, error=%s", key, exc)


def delete_cache_pattern(pattern: str) -> None:
    """按模式删除缓存 key（用于同一资源多日期缓存失效）。"""
    client = get_redis_client()
    if client is None:
        return
    full_pattern = prefixed_key(pattern)
    try:
        for key in client.scan_iter(match=full_pattern, count=100):
            client.delete(key)
    except RedisError as exc:
        logger.warning("Delete Redis cache pattern failed, pattern=%s, error=%s", pattern, exc)


@contextmanager
def redis_lock(key: str, ttl_seconds: int | None = None) -> Iterator[bool]:
    """简单分布式锁。

    yield True 表示拿到锁；yield False 表示已有其他进程执行同一任务。
    释放时校验 token，避免误删其他进程续期后的锁。
    """
    client = get_redis_client()
    if client is None:
        yield True
        return

    lock_key = prefixed_key(f"lock:{key}")
    token = str(uuid.uuid4())
    ttl = ttl_seconds or settings.redis_scheduler_lock_ttl_seconds
    acquired = False
    try:
        acquired = bool(client.set(lock_key, token, ex=ttl, nx=True))
        yield acquired
    except RedisError as exc:
        logger.warning("Redis lock failed, key=%s, error=%s", key, exc)
        yield True
    finally:
        if acquired:
            try:
                client.eval(
                    "if redis.call('get', KEYS[1]) == ARGV[1] then "
                    "return redis.call('del', KEYS[1]) else return 0 end",
                    1,
                    lock_key,
                    token,
                )
            except RedisError as exc:
                logger.warning("Release Redis lock failed, key=%s, error=%s", key, exc)
