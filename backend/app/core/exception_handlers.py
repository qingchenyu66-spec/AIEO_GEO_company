"""Global API exception handlers."""

from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.core.request_context import get_request_id

logger = logging.getLogger(__name__)


def _error_body(detail: str, request: Request) -> dict[str, str | None]:
    request_id = getattr(request.state, "request_id", None) or get_request_id()
    return {"detail": detail, "request_id": request_id}


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(SQLAlchemyError)
    async def sqlalchemy_error_handler(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        logger.exception(
            "database error path=%s request_id=%s",
            request.url.path,
            get_request_id(),
        )
        return JSONResponse(
            status_code=503,
            content=_error_body("数据服务暂时不可用，请稍后重试", request),
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        if isinstance(exc, HTTPException):
            return await http_exception_handler(request, exc)
        logger.exception(
            "unhandled error path=%s request_id=%s",
            request.url.path,
            get_request_id(),
        )
        return JSONResponse(
            status_code=500,
            content=_error_body("服务内部错误，请稍后重试", request),
        )
