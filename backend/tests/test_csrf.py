"""CSRF 双提交 Cookie 校验。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app

client = TestClient(app)


def test_csrf_blocks_cookie_mutation_without_header() -> None:
    settings.auth_csrf_enabled = True
    settings.auth_expose_token_in_body = False
    try:
        client.cookies.set("geo_access_token", "fake-token")
        client.cookies.set("geo_csrf_token", "token-a")
        blocked = client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": "token-b"})
        assert blocked.status_code == 403
    finally:
        settings.auth_csrf_enabled = False
        settings.auth_expose_token_in_body = True
        client.cookies.clear()
