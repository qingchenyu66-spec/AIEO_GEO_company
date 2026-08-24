"""HTTP request logging with request_id and duration."""

from __future__ import annotations

import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.request_context import REQUEST_ID_HEADER, reset_request_id, set_request_id

logger = logging.getLogger("app.request")

_SKIP_PATHS = frozenset({"/", "/docs", "/redoc", "/openapi.json"})


def _should_log(path: str) -> bool:
    if path in _SKIP_PATHS:
        return False
    if path.endswith("/health"):
        return False
    return True


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())
        token = set_request_id(request_id)
        request.state.request_id = request_id
        start = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers[REQUEST_ID_HEADER] = request_id
            return response
        except Exception:
            duration_ms = int((time.perf_counter() - start) * 1000)
            if _should_log(request.url.path):
                logger.exception(
                    "request failed method=%s path=%s status=%s duration_ms=%s tenant_id=%s request_id=%s",
                    request.method,
                    request.url.path,
                    status_code,
                    duration_ms,
                    request.query_params.get("tenant_id") or "-",
                    request_id,
                )
            raise
        finally:
            duration_ms = int((time.perf_counter() - start) * 1000)
            path = request.url.path
            if _should_log(path):
                log_fn = logger.error if status_code >= 500 else logger.info
                log_fn(
                    "request method=%s path=%s status=%s duration_ms=%s tenant_id=%s request_id=%s",
                    request.method,
                    path,
                    status_code,
                    duration_ms,
                    request.query_params.get("tenant_id") or "-",
                    request_id,
                )
                # 2026-08-21 - 稳定性⑥：采样进 Redis 环，供 P95/告警
                try:
                    from app.services.stability_metrics_service import record_request_latency

                    record_request_latency(path, duration_ms, status_code)
                except Exception:
                    pass
            reset_request_id(token)
