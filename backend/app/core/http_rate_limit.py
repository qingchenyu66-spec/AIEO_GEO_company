"""HTTP endpoint rate limiting helpers."""

from __future__ import annotations

from fastapi import HTTPException, Request, status

from app.api.dependencies import CurrentSession
from app.core.config import settings
from app.core.rate_limiter import RateLimitExceeded, acquire_rate_limit


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def enforce_login_rate_limit(request: Request) -> None:
    try:
        acquire_rate_limit(
            "auth:login",
            client_ip(request),
            settings.http_login_rate_per_minute,
        )
    except RateLimitExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="登录尝试过于频繁，请稍后再试",
        ) from exc


def enforce_overview_rate_limit(request: Request, current: CurrentSession) -> None:
    key = f"{current.identity.id}:{client_ip(request)}"
    try:
        acquire_rate_limit(
            "mgmt:overview",
            key,
            settings.http_overview_rate_per_minute,
        )
    except RateLimitExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="总览刷新过于频繁，请稍后再试",
        ) from exc
