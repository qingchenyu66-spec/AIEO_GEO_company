from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1.router import api_router
from app.core.app_factory import build_fastapi_kwargs, configure_security_middleware, openapi_enabled
from app.core.config import settings
from app.core.database import SessionLocal
from app.core.exception_handlers import register_exception_handlers
from app.middleware.csrf_protection import CsrfProtectionMiddleware
from app.middleware.operation_audit import OperationAuditMiddleware
from app.middleware.request_logging import RequestLoggingMiddleware
from app.schemas.common import ApiResponse
from app.services.system_config_service import bootstrap_and_apply


@asynccontextmanager
async def lifespan(_app: FastAPI):
    db = SessionLocal()
    try:
        bootstrap_and_apply(db)
    finally:
        db.close()
    yield


app = FastAPI(lifespan=lifespan, **build_fastapi_kwargs())
configure_security_middleware(app)
app.add_middleware(CsrfProtectionMiddleware)
app.add_middleware(OperationAuditMiddleware)
app.add_middleware(RequestLoggingMiddleware)

register_exception_handlers(app)

app.include_router(api_router, prefix=settings.api_v1_prefix)


@app.get("/", response_model=ApiResponse[dict])
def root() -> ApiResponse[dict]:
    docs_path = "/docs" if openapi_enabled() else None
    return ApiResponse(data={"service": settings.app_name, "docs": docs_path, "version": "0.1.0"})


@app.get("/health", response_model=ApiResponse[dict])
def root_health() -> ApiResponse[dict]:
    return ApiResponse(data={"status": "ok"})
