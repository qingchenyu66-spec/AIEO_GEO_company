from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.schemas.common import ApiResponse
from app.services.system_service import check_database

router = APIRouter()


@router.get("/health", response_model=ApiResponse[dict])
def health_check(db: Session = Depends(get_db)) -> ApiResponse[dict]:
    database_ready = check_database(db)
    return ApiResponse(
        data={
            "service": settings.app_name,
            "environment": settings.app_env,
            "api": "ready",
            "database": "ready" if database_ready else "unavailable",
            "timestamp": datetime.now(UTC).isoformat(),
        }
    )

