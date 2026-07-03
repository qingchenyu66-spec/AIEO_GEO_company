"""Tests for HTTP and fallback rate limiting."""

from unittest.mock import patch

import pytest
from fastapi import FastAPI, HTTPException, status
from fastapi.testclient import TestClient

from app.core.rate_limiter import RateLimitExceeded, acquire_rate_limit


def test_acquire_rate_limit_uses_local_fallback_when_redis_missing() -> None:
    with patch("app.core.rate_limiter.get_redis_client", return_value=None):
        acquire_rate_limit("test:scope", "key-a", 5)
        acquire_rate_limit("test:scope", "key-a", 5)


def test_acquire_rate_limit_local_fallback_blocks_excess() -> None:
    with patch("app.core.rate_limiter.get_redis_client", return_value=None):
        with patch("app.core.rate_limiter._local_fallback_limit", return_value=2):
            acquire_rate_limit("test:block", "ip-1", 10)
            acquire_rate_limit("test:block", "ip-1", 10)
            with pytest.raises(RateLimitExceeded):
                acquire_rate_limit("test:block", "ip-1", 10)


def test_login_rate_limit_returns_429() -> None:
    from app.api.v1.endpoints.auth import router as auth_router

    app = FastAPI()
    app.include_router(auth_router, prefix="/api/v1")

    with patch("app.api.v1.endpoints.auth.enforce_login_rate_limit") as guard:
        guard.side_effect = HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="too many")
        client = TestClient(app, raise_server_exceptions=False)
        response = client.post("/api/v1/auth/login", json={"username": "demo", "password": "secret1"})
        assert response.status_code == 429
