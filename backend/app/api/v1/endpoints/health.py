from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.celery_health import celery_health
from app.core.celery_queue_monitor import get_queue_monitor_snapshot
from app.core.config import settings
from app.core.database import get_db
from app.core.redis_client import redis_health
from app.schemas.common import ApiResponse
from app.services.system_service import check_database

router = APIRouter()


@router.get("/health", response_model=ApiResponse[dict])
def health_check(db: Session = Depends(get_db)) -> ApiResponse[dict]:
    database_ready = check_database(db)
    redis_status = redis_health()
    celery_status = celery_health()
    queue_snapshot = get_queue_monitor_snapshot() if settings.celery_enabled else None
    return ApiResponse(
        data={
            "service": settings.app_name,
            "environment": settings.app_env,
            "api": "ready",
            "database": "ready" if database_ready else "unavailable",
            "redis": redis_status,
            "celery": celery_status,
            "celery_queues": queue_snapshot,
            "timestamp": datetime.now(UTC).isoformat(),
        }
    )
