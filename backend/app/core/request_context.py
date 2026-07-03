"""Per-request context for logging and error responses."""

from __future__ import annotations

from contextvars import ContextVar

REQUEST_ID_HEADER = "X-Request-ID"

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)


def set_request_id(request_id: str):
    return _request_id.set(request_id)


def get_request_id() -> str | None:
    return _request_id.get()


def reset_request_id(token: object) -> None:
    _request_id.reset(token)  # type: ignore[arg-type]
