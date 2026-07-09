from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.core.config import settings
from app.core.security_baseline import openapi_enabled, validate_security_baseline


def configure_security_middleware(app: FastAPI) -> None:
    validate_security_baseline()
    if settings.is_production and settings.trusted_hosts:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins or [],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-CSRF-Token", "X-Requested-With"],
    )


def build_fastapi_kwargs() -> dict:
    expose_docs = openapi_enabled()
    return {
        "title": settings.app_name,
        "version": "0.1.0",
        "debug": settings.debug,
        "docs_url": "/docs" if expose_docs else None,
        "redoc_url": "/redoc" if expose_docs else None,
        "openapi_url": "/openapi.json" if expose_docs else None,
    }
