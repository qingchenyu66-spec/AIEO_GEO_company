"""API 层统一异常转换。"""

from __future__ import annotations

import logging

from fastapi import HTTPException, status
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)


def molizhishu_upstream_error_detail(exc: Exception) -> str:
    """对外隐藏模力指数原始错误，避免泄露 token/URL 等敏感信息。"""
    logger.warning("molizhishu upstream error: %s", exc)
    return "模力指数服务暂时不可用，请稍后重试"


def raise_read_endpoint_error(exc: Exception, *, context: str) -> None:
    """读接口：业务校验 400，数据库异常 503 并记录日志。"""
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if isinstance(exc, PermissionError):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    if isinstance(exc, SQLAlchemyError):
        logger.exception("%s database error", context)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="数据服务暂时不可用，请稍后重试",
        ) from exc
    raise exc


def raise_write_endpoint_error(exc: Exception, *, context: str) -> None:
    """写接口：与读接口相同的业务/权限/数据库异常映射。"""
    raise_read_endpoint_error(exc, context=context)
