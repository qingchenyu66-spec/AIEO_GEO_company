"""Celery broker health check helpers."""

from __future__ import annotations

from typing import Any

from app.core.config import settings


def celery_health() -> dict[str, Any]:
    if not settings.celery_enabled:
        return {
            "enabled": False,
            "status": "disabled",
            "detail": "Celery 未启用",
            "broker_url": settings.celery_broker_url,
        }
    try:
        from redis import Redis
        from redis.exceptions import RedisError

        client = Redis.from_url(
            settings.celery_broker_url,
            decode_responses=True,
            socket_timeout=settings.redis_socket_timeout_seconds,
            socket_connect_timeout=settings.redis_socket_timeout_seconds,
        )
        pong = client.ping()
        return {
            "enabled": True,
            "status": "ready" if pong else "unavailable",
            "detail": "Celery broker 可连接",
            "broker_url": settings.celery_broker_url,
        }
    except RedisError as exc:
        return {
            "enabled": True,
            "status": "unavailable",
            "detail": str(exc),
            "broker_url": settings.celery_broker_url,
        }
    except Exception as exc:
        return {
            "enabled": True,
            "status": "unavailable",
            "detail": str(exc),
            "broker_url": settings.celery_broker_url,
        }
