"""操作日志和系统配置API端点。"""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func as sa_func
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentSession, get_current_session
from app.core.database import get_db
from app.models.ops import OperationLog, SystemConfig
from app.schemas.common import ApiResponse

router = APIRouter(prefix="/ops")


def require_platform(current: CurrentSession) -> None:
    if current.identity.identity_type != "PLATFORM":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="仅平台运营端可访问")


@router.get("/logs", response_model=ApiResponse[list[dict]])
def list_operation_logs(
    days: int = Query(default=7, ge=1, le=90),
    action_type: str | None = None,
    keyword: str | None = None,
    tenant_id: int | None = None,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[list[dict]]:
    """操作日志列表，支持按天数、操作类型、关键词和企业筛选。"""
    require_platform(current)
    since = datetime.utcnow() - timedelta(days=days)
    stmt = select(OperationLog).where(OperationLog.created_at >= since).order_by(OperationLog.id.desc())
    if action_type:
        stmt = stmt.where(OperationLog.action_type == action_type)
    if keyword:
        stmt = stmt.where(OperationLog.description.like(f"%{keyword}%"))
    if tenant_id:
        stmt = stmt.where(OperationLog.tenant_id == tenant_id)
    rows = list(db.scalars(stmt))
    return ApiResponse(data=[
        {
            "id": r.id,
            "operator_name": r.operator_name,
            "action_type": r.action_type,
            "description": r.description,
            "ip_address": r.ip_address,
            "risk_level": r.risk_level,
            "target_module": r.target_module,
            "tenant_id": r.tenant_id,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ])


@router.get("/configs", response_model=ApiResponse[list[dict]])
def list_system_configs(
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[list[dict]]:
    """系统配置列表。"""
    require_platform(current)
    rows = list(db.scalars(select(SystemConfig).where(SystemConfig.status.is_(True)).order_by(SystemConfig.id.asc())))
    return ApiResponse(data=[
        {
            "id": r.id,
            "config_key": r.config_key,
            "config_value": r.config_value,
            "description": r.description,
            "updated_by": r.updated_by,
            "status": r.status,
            "updated_at": r.updated_at.isoformat(),
        }
        for r in rows
    ])


@router.put("/configs/{config_id}", response_model=ApiResponse[dict])
def update_system_config(
    config_id: int,
    payload: dict,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """更新系统配置项。"""
    require_platform(current)
    config = db.scalar(select(SystemConfig).where(SystemConfig.id == config_id))
    if config is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="配置项不存在")
    new_value = payload.get("config_value")
    if new_value is not None:
        config.config_value = str(new_value)
    config.updated_by = current.user.display_name or current.identity.identity_name
    db.commit()
    db.refresh(config)
    return ApiResponse(data={"id": config.id, "config_key": config.config_key, "config_value": config.config_value})


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
