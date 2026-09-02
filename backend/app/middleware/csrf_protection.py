"""Cookie 登录态下的 CSRF 防护（双提交 Cookie）。"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.auth_cookie import AUTH_COOKIE_NAME, CSRF_COOKIE_NAME, CSRF_HEADER_NAME
from app.core.config import settings

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_EXEMPT_PREFIXES = (
    "/api/v1/auth/login",
    "/api/v1/auth/select-identity",
    "/health",
    "/api/v1/health",
    "/api/v1/monitor/molizhishu/callback",
    "/api/v1/wechat-pay/notify",
    "/api/v1/alipay/notify",
    "/api/v1/alipay/return",
    "/api/v1/h5/diagnosis",
)


class CsrfProtectionMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        if not settings.auth_cookie_enabled or not settings.auth_csrf_enabled:
            return await call_next(request)
        if request.method in _SAFE_METHODS:
            return await call_next(request)
        path = request.url.path
        if any(path.startswith(prefix) for prefix in _EXEMPT_PREFIXES):
            return await call_next(request)
        auth_header = request.headers.get("authorization", "")
        if auth_header.lower().startswith("bearer "):
            return await call_next(request)
        if not request.cookies.get(AUTH_COOKIE_NAME):
            return await call_next(request)
        csrf_cookie = request.cookies.get(CSRF_COOKIE_NAME)
        csrf_header = request.headers.get(CSRF_HEADER_NAME)
        if not csrf_cookie or not csrf_header or csrf_cookie != csrf_header:
            return JSONResponse(status_code=403, content={"detail": "CSRF 校验失败，请刷新页面后重试"})
        return await call_next(request)
