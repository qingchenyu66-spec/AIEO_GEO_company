"""Tests for request logging middleware and global exception handlers."""

from unittest.mock import MagicMock

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from app.core.exception_handlers import register_exception_handlers
from app.core.request_context import REQUEST_ID_HEADER
from app.middleware.request_logging import RequestLoggingMiddleware


def test_request_logging_adds_request_id_header() -> None:
    probe = FastAPI()
    probe.add_middleware(RequestLoggingMiddleware)

    @probe.get("/probe")
    def probe_route() -> dict[str, str]:
        return {"ok": "1"}

    client = TestClient(probe)
    response = client.get("/probe", headers={REQUEST_ID_HEADER: "test-req-1"})
    assert response.status_code == 200
    assert response.headers.get(REQUEST_ID_HEADER) == "test-req-1"


def test_request_logging_generates_request_id_when_missing() -> None:
    probe = FastAPI()
    probe.add_middleware(RequestLoggingMiddleware)

    @probe.get("/probe")
    def probe_route() -> dict[str, str]:
        return {"ok": "1"}

    client = TestClient(probe)
    response = client.get("/probe")
    assert response.status_code == 200
    assert response.headers.get(REQUEST_ID_HEADER)


def test_global_handler_sqlalchemy_error_returns_503_with_request_id() -> None:
    app = FastAPI()
    app.add_middleware(RequestLoggingMiddleware)
    register_exception_handlers(app)
    router = APIRouter()

    @router.get("/boom-db")
    def boom_db() -> None:
        raise SQLAlchemyError("db down")

    app.include_router(router)
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/boom-db")
    assert response.status_code == 503
    body = response.json()
    assert "数据服务" in body["detail"]
    assert body.get("request_id")
    assert response.headers.get(REQUEST_ID_HEADER) == body["request_id"]


def test_global_handler_unhandled_returns_500_with_request_id() -> None:
    app = FastAPI()
    app.add_middleware(RequestLoggingMiddleware)
    register_exception_handlers(app)
    router = APIRouter()

    @router.get("/boom")
    def boom() -> None:
        raise RuntimeError("unexpected")

    app.include_router(router)
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/boom")
    assert response.status_code == 500
    body = response.json()
    assert "内部错误" in body["detail"]
    assert body.get("request_id")
