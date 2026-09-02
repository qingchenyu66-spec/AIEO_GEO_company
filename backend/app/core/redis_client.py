"""Redis 基础能力封装：健康检查、JSON 缓存和分布式锁。

Redis 在本系统中是上线增强组件，不作为本地开发的硬依赖：
未启用或连接失败时，业务会自动回退到 MySQL 实时查询。
"""

from __future__ import annotations

import json
import logging
import uuid
from contextlib import contextmanager
from typing import Any, Callable, Iterator, TypeVar
from urllib.parse import urlparse, urlunparse

from redis import Redis
from redis.exceptions import RedisError

from app.core.config import settings

logger = logging.getLogger(__name__)

_client: Redis | None = None
T = TypeVar("T")


def redis_enabled() -> bool:
    """判断当前环境是否启用 Redis。"""
    return bool(settings.redis_enabled and settings.redis_url)


def _is_auth_redis_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "auth" in msg or "no password is set" in msg


def bare_redis_url(url: str) -> str:
    """去掉空密码 userinfo，避免 redis-py 对无 requirepass 实例发 AUTH。"""
    parsed = urlparse(url)
    if not parsed.scheme:
        return url
    if parsed.username is None and parsed.password is None:
        return url
    if parsed.password:
        return url
    host = parsed.hostname or "127.0.0.1"
    port = f":{parsed.port}" if parsed.port else ""
    netloc = f"{host}{port}"
    return urlunparse((parsed.scheme, netloc, parsed.path or "", "", parsed.query, parsed.fragment))


def redis_url_without_auth(url: str) -> str:
    """去掉 URL 中的账号密码（本地 Redis 无 requirepass 时 Celery/redis-py 误带 AUTH 用）。"""
    # 2026-09-02 - Client sent AUTH, but no password is set - 入队/缓存统一去认证重试
    parsed = urlparse(url)
    if not parsed.scheme:
        return url
    if parsed.username is None and parsed.password is None:
        return url
    host = parsed.hostname or "127.0.0.1"
    port = f":{parsed.port}" if parsed.port else ""
    netloc = f"{host}{port}"
    return urlunparse((parsed.scheme, netloc, parsed.path or "", "", parsed.query, parsed.fragment))


def _new_redis_client(url: str) -> Redis:
    return Redis.from_url(
        bare_redis_url(url),
        decode_responses=True,
        socket_timeout=settings.redis_socket_timeout_seconds,
        socket_connect_timeout=settings.redis_socket_timeout_seconds,
        health_check_interval=30,
    )


def reset_redis_client() -> None:
    global _client
    if _client is not None:
        try:
            _client.close()
        except Exception:
            pass
    _client = None


def get_redis_client() -> Redis | None:
    """懒加载 Redis 连接池，避免应用启动时因 Redis 不可用直接失败。"""
    global _client
    if not redis_enabled():
        return None
    if _client is None:
        _client = _new_redis_client(settings.redis_url)
        try:
            _client.ping()
        except RedisError as exc:
            if _is_auth_redis_error(exc):
                # 2026-08-27 - 本地无密码 Redis 勿发 AUTH；与生产同代码，仅规范化 URL
                # 2026-09-02 - 误带非空密码也会触发 no password is set，须去掉认证段重试
                logger.warning("Redis AUTH rejected, retry without auth: %s", exc)
                reset_redis_client()
                _client = _new_redis_client(redis_url_without_auth(settings.redis_url))
                try:
                    _client.ping()
                except RedisError as retry_exc:
                    logger.warning("Redis ping failed after bare URL: %s", retry_exc)
            else:
                logger.warning("Redis ping failed: %s", exc)
    return _client


def _redis_command(action: Callable[[Redis], T], *, op: str, key: str = "") -> T | None:
    """AUTH 失败时重置连接并重试一次。"""
    client = get_redis_client()
    if client is None:
        return None
    try:
        return action(client)
    except RedisError as exc:
        if not _is_auth_redis_error(exc):
            raise
        logger.warning("Redis %s AUTH failed, retry once key=%s error=%s", op, key, exc)
        reset_redis_client()
        client = get_redis_client()
        if client is None:
            return None
        return action(client)


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
    try:
        raw = _redis_command(lambda client: client.get(prefixed_key(key)), op="get", key=key)
        return json.loads(raw) if raw else None
    except (RedisError, json.JSONDecodeError, TypeError) as exc:
        logger.warning("Read Redis cache failed, key=%s, error=%s", key, exc)
        return None


def set_json_cache(key: str, value: Any, ttl_seconds: int | None = None) -> None:
    """写入 JSON 缓存；失败只记录日志，不影响主业务写库。"""
    ttl = ttl_seconds or settings.redis_default_ttl_seconds
    payload = json.dumps(value, ensure_ascii=False, default=str)
    try:
        _redis_command(
            lambda client: client.setex(prefixed_key(key), ttl, payload),
            op="setex",
            key=key,
        )
    except (RedisError, TypeError) as exc:
        logger.warning("Write Redis cache failed, key=%s, error=%s", key, exc)


def delete_cache(key: str) -> None:
    """删除单个缓存 key。"""
    try:
        _redis_command(lambda client: client.delete(prefixed_key(key)), op="delete", key=key)
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

    Redis 未启用（本地）：fail-open（yield True），避免开发机无 Redis 卡死。
    Redis 已启用但命令失败：fail-closed（yield False），避免多 Worker 重叠扫任务。
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
        acquired = bool(
            _redis_command(
                lambda c: c.set(lock_key, token, ex=ttl, nx=True),
                op="lock",
                key=key,
            )
        )
        yield acquired
    except RedisError as exc:
        if _is_auth_redis_error(exc):
            logger.warning("Redis lock AUTH failed (fail-open), key=%s, error=%s", key, exc)
            yield True
            return
        # ponytail: 非 AUTH 的 Redis 抖动仍 fail-closed，避免多 Worker 重叠扫任务
        logger.warning("Redis lock failed (fail-closed), key=%s, error=%s", key, exc)
        yield False
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
