"""写接口操作审计：覆盖未显式写日志的 POST/PUT/PATCH/DELETE。"""

from __future__ import annotations

import logging
from typing import Callable

from sqlalchemy import select
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.auth_cookie import AUTH_COOKIE_NAME
from app.core.database import SessionLocal
from app.core.security import decode_token
from app.models.ops import OperationLog
from app.models.user import User
from app.models.user_identity import UserIdentity
from app.services.operation_log_labels import action_type_for_method, build_friendly_audit_description, module_from_api_path

logger = logging.getLogger("app.audit")

_SKIP_PREFIXES = (
    "/docs",
    "/redoc",
    "/openapi.json",
)
_SKIP_EXPLICIT_AUDIT_PREFIXES = (
    "/api/v1/management/",
    "/api/v1/knowledge/",
    "/api/v1/reports/",
)
_SKIP_PATHS = frozenset({"/", "/api/v1/auth/login", "/api/v1/auth/select-identity"})
_MUTATING = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def _should_audit(method: str, path: str) -> bool:
    if method not in _MUTATING:
        return False
    if path in _SKIP_PATHS:
        return False
    if any(path.startswith(prefix) for prefix in _SKIP_EXPLICIT_AUDIT_PREFIXES):
        return False
    return not any(path.startswith(prefix) for prefix in _SKIP_PREFIXES)


def _client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return None


def _access_token_from_request(request: Request) -> str | None:
    auth_header = request.headers.get("authorization") or ""
    if auth_header.lower().startswith("bearer "):
        token = auth_header[7:].strip()
        if token:
            return token
    cookie_token = request.cookies.get(AUTH_COOKIE_NAME)
    if cookie_token:
        return cookie_token
    return None


def resolve_audit_operator(request: Request) -> tuple[str, int | None, int | None]:
    """从 Cookie 或 Bearer 解析当前操作人（与 get_current_session 一致）。"""
    token = _access_token_from_request(request)
    if not token:
        return "未登录用户", None, None
    try:
        payload = decode_token(token)
    except ValueError:
        return "登录凭证无效", None, None
    if payload.get("scope") != "access":
        return "未登录用户", None, None

    user_id = int(payload["sub"])
    identity_id = int(payload.get("identity_id") or 0)
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.id == user_id, User.status.is_(True)))
        identity = None
        if identity_id:
            identity = db.scalar(
                select(UserIdentity).where(
                    UserIdentity.id == identity_id,
                    UserIdentity.user_id == user_id,
                    UserIdentity.status.is_(True),
                    UserIdentity.deleted.is_(False),
                )
            )
        if user is None:
            return "未知用户", None, None
        operator_name = user.display_name or (identity.identity_name if identity else None) or user.username
        tenant_id = identity.tenant_id if identity else None
        return operator_name, user.id, tenant_id
    finally:
        db.close()


def build_audit_description(request: Request) -> str:
    return build_friendly_audit_description(
        request.method,
        request.url.path,
        dict(request.query_params),
    )


class OperationAuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if not _should_audit(request.method, request.url.path):
            return await call_next(request)

        response = await call_next(request)
        if response.status_code >= 400:
            return response

        operator_name, operator_user_id, tenant_id_from_token = resolve_audit_operator(request)
        tenant_id = tenant_id_from_token
        tenant_query = request.query_params.get("tenant_id")
        if tenant_query and tenant_query.isdigit():
            tenant_id = int(tenant_query)

        db = SessionLocal()
        try:
            db.add(
                OperationLog(
                    operator_name=operator_name[:64],
                    action_type=action_type_for_method(request.method),
                    description=build_audit_description(request)[:500],
                    ip_address=_client_ip(request),
                    risk_level="普通",
                    target_module=module_from_api_path(request.url.path),
                    tenant_id=tenant_id,
                    operator_user_id=operator_user_id,
                )
            )
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("operation audit write failed path=%s", request.url.path)
        finally:
            db.close()
        return response
