"""HttpOnly Cookie 登录态与 CSRF Cookie 辅助。"""

from __future__ import annotations

import secrets

from fastapi import Response

from app.core.config import settings

AUTH_COOKIE_NAME = "geo_access_token"
CSRF_COOKIE_NAME = "geo_csrf_token"
CSRF_HEADER_NAME = "X-CSRF-Token"


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def _cookie_secure() -> bool:
    # Controlled only by AUTH_COOKIE_SECURE. Do not force Secure from APP_ENV:
    # HTTP cutover (IP / pre-cert) would drop cookies and look like "login failed".
    return bool(settings.auth_cookie_secure)


def set_auth_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=AUTH_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=_cookie_secure(),
        samesite=settings.auth_cookie_samesite,
        max_age=settings.access_token_expire_minutes * 60,
        path="/",
    )


def set_csrf_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=token,
        httponly=False,
        secure=_cookie_secure(),
        samesite=settings.auth_cookie_samesite,
        max_age=settings.access_token_expire_minutes * 60,
        path="/",
    )


def clear_auth_cookie(response: Response) -> None:
    response.delete_cookie(key=AUTH_COOKIE_NAME, path="/")


def clear_csrf_cookie(response: Response) -> None:
    response.delete_cookie(key=CSRF_COOKIE_NAME, path="/")
