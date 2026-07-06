"""操作日志和系统配置API端点。"""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentSession, get_current_session
from app.core.database import get_db
from app.models.ops import OperationLog
from app.schemas.common import ApiResponse
from app.services.operation_log_service import query_operation_logs, serialize_operation_logs

router = APIRouter(prefix="/ops")


def require_platform(current: CurrentSession) -> None:
    if current.identity.identity_type != "PLATFORM":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="仅平台运营端可访问")


@router.get("/logs", response_model=ApiResponse[dict])
def list_operation_logs(
    days: int = Query(default=7, ge=1, le=90),
    action_type: str | None = None,
    keyword: str | None = None,
    tenant_id: int | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """操作日志分页列表，支持按天数、操作类型、关键词和企业筛选。"""
    require_platform(current)
    since = datetime.utcnow() - timedelta(days=days)
    rows, total = query_operation_logs(
        db,
        since=since,
        action_type=action_type,
        keyword=keyword,
        tenant_id=tenant_id,
        page=page,
        page_size=page_size,
    )
    return ApiResponse(
        data={
            "items": serialize_operation_logs(db, rows),
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@router.get("/configs", response_model=ApiResponse[list[dict]], deprecated=True)
def list_system_configs(
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[list[dict]]:
    """已废弃：请使用 /management/system-configs。"""
    require_platform(current)
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="该接口已下线，请使用 /management/system-configs",
    )


@router.put("/configs/{config_id}", response_model=ApiResponse[dict], deprecated=True)
def update_system_config(
    config_id: int,
    payload: dict,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """已废弃：请使用 /management/system-configs/{id}。"""
    require_platform(current)
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="该接口已下线，请使用 /management/system-configs/{id}",
    )


def write_op_log(
    db: Session,
    operator_name: str,
    action_type: str,
    description: str,
    *,
    operator_user_id: int | None = None,
    ip_address: str | None = None,
    target_module: str | None = None,
    target_id: int | None = None,
    tenant_id: int | None = None,
    risk_level: str = "正常",
) -> OperationLog:
    """写入操作日志的辅助函数。"""
    log = OperationLog(
        operator_name=operator_name,
        action_type=action_type,
        description=description[:500],
        ip_address=ip_address,
        risk_level=risk_level,
        target_module=target_module,
        target_id=target_id,
        tenant_id=tenant_id,
        operator_user_id=operator_user_id,
    )
    db.add(log)
    db.flush()
    return log
