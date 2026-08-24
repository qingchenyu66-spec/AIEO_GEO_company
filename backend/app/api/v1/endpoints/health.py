"""Health check endpoints."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentSession, get_current_session
from app.api.http_errors import raise_read_endpoint_error
from app.core.celery_health import celery_health
from app.core.celery_queue_monitor import get_queue_monitor_snapshot
from app.core.config import settings
from app.core.database import get_db
from app.core.redis_client import redis_health
from app.schemas.common import ApiResponse
from app.services.molizhishu_client import MolizhishuApiError, MolizhishuClient
from app.services.menu_permission_service import require_health_ops_access
from app.services.playwright_health import playwright_chromium_health
from app.services.system_service import check_database

router = APIRouter()


def _molizhishu_health(*, public: bool = False) -> dict:
    from app.services.system_config_service import get_runtime_config

    if not str(get_runtime_config("molizhishu_token") or "").strip():
        return {"configured": False, "status": "skipped", "detail": "未配置 MOLIZHISHU_TOKEN"}
    try:
        payload = MolizhishuClient().ping()
        balance = (payload.get("data") or {}).get("currentBalance")
        result = {"configured": True, "status": "ready", "detail": "监测 API 可连接"}
        if not public:
            result["balance"] = balance
        return result
    except MolizhishuApiError:
        return {"configured": True, "status": "error", "detail": "监测 API 连接异常"}
    except Exception:
        return {"configured": True, "status": "error", "detail": "监测 API 探测失败"}


def _public_health_payload(db: Session) -> dict:
    database_ready = check_database(db)
    return {
        "service": settings.app_name,
        "api": "ready" if database_ready else "degraded",
        "database": "ready" if database_ready else "unavailable",
        "timestamp": datetime.now(UTC).isoformat(),
    }


def _detailed_health_payload(db: Session) -> dict:
    database_ready = check_database(db)
    redis_status = redis_health()
    celery_status = celery_health()
    queue_snapshot = get_queue_monitor_snapshot() if settings.celery_enabled else None
    stability = None
    try:
        from app.services.stability_metrics_service import collect_stability_metrics

        stability = collect_stability_metrics(db)
    except Exception:
        stability = {"status": "error", "detail": "稳定性指标采集失败"}
    return {
        "service": settings.app_name,
        "environment": settings.app_env,
        "api": "ready",
        "database": "ready" if database_ready else "unavailable",
        "redis": redis_status,
        "celery": celery_status,
        "molizhishu": _molizhishu_health(public=False),
        "playwright_chromium": playwright_chromium_health(),
        "celery_queues": queue_snapshot,
        "stability": stability,
        "timestamp": datetime.now(UTC).isoformat(),
    }


@router.get("/health", response_model=ApiResponse[dict])
def health_check(db: Session = Depends(get_db)) -> ApiResponse[dict]:
    """公开存活探测：不含余额、队列、环境等敏感信息。"""
    return ApiResponse(data=_public_health_payload(db))


@router.get("/health/ops", response_model=ApiResponse[dict])
def health_check_ops(
    db: Session = Depends(get_db),
    current: CurrentSession = Depends(get_current_session),
) -> ApiResponse[dict]:
    """运营详细健康检查（需登录且具备系统配置查看权限）。"""
    try:
        require_health_ops_access(db, current)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except Exception as exc:
        raise_read_endpoint_error(exc, context="health.ops")
    return ApiResponse(data=_detailed_health_payload(db))
