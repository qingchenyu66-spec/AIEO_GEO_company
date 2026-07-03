"""平台操作日志写入，供管理端与监测运营模块共用。"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.api.dependencies import CurrentSession
from app.models.ops import OperationLog


def write_operation_log(
    db: Session,
    current: CurrentSession,
    action_type: str,
    description: str,
    *,
    target_module: str | None = None,
    target_id: int | None = None,
    tenant_id: int | None = None,
    risk_level: str = "正常",
    ip_address: str | None = None,
) -> OperationLog:
    operator_name = (
        current.user.display_name
        or current.identity.identity_name
        or current.user.username
        or "未知用户"
    )
    log = OperationLog(
        operator_name=operator_name,
        action_type=action_type,
        description=description[:500],
        ip_address=ip_address,
        risk_level=risk_level,
        target_module=target_module,
        target_id=target_id,
        tenant_id=tenant_id,
        operator_user_id=current.user.id,
    )
    db.add(log)
    db.flush()
    return log
