"""平台操作日志写入，供管理端与监测运营模块共用。"""

from __future__ import annotations

from collections.abc import Iterable

from datetime import datetime

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentSession
from app.models.ops import OperationLog
from app.models.tenant import Tenant
from app.services.operation_log_labels import (
    humanize_action_type,
    humanize_description,
    humanize_target_module,
)


def tenant_names_by_id(db: Session, tenant_ids: Iterable[int | None]) -> dict[int, str]:
    ids = sorted({item for item in tenant_ids if item})
    if not ids:
        return {}
    rows = db.execute(
        select(Tenant.id, Tenant.name).where(Tenant.id.in_(ids), Tenant.deleted.is_(False))
    )
    return {row.id: row.name for row in rows}


def build_operation_log_filters(
    *,
    since: datetime | None = None,
    action_type: str | None = None,
    keyword: str | None = None,
    tenant_id: int | None = None,
):
    stmt = select(OperationLog)
    if since is not None:
        stmt = stmt.where(OperationLog.created_at >= since)
    if action_type:
        stmt = stmt.where(OperationLog.action_type == action_type)
    if keyword:
        stmt = stmt.where(OperationLog.description.like(f"%{keyword}%"))
    if tenant_id:
        stmt = stmt.where(OperationLog.tenant_id == tenant_id)
    return stmt


def query_operation_logs(
    db: Session,
    *,
    since: datetime | None = None,
    action_type: str | None = None,
    keyword: str | None = None,
    tenant_id: int | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[OperationLog], int]:
    base = build_operation_log_filters(
        since=since,
        action_type=action_type,
        keyword=keyword,
        tenant_id=tenant_id,
    )
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    offset = max(page - 1, 0) * page_size
    rows = list(
        db.scalars(
            base.order_by(OperationLog.id.desc()).offset(offset).limit(page_size)
        )
    )
    return rows, int(total)


def serialize_operation_log(item: OperationLog, *, tenant_name: str | None = None) -> dict:
    description = humanize_description(item.description)
    return {
        "id": item.id,
        "operator_name": item.operator_name,
        "action_type": humanize_action_type(item.action_type),
        "description": description,
        "ip_address": item.ip_address,
        "risk_level": item.risk_level,
        "target_module": humanize_target_module(item.target_module, description=item.description),
        "tenant_id": item.tenant_id,
        "tenant_name": tenant_name,
        "created_at": item.created_at.isoformat(),
    }


def serialize_operation_logs(db: Session, rows: list[OperationLog]) -> list[dict]:
    name_map = tenant_names_by_id(db, [item.tenant_id for item in rows])
    return [
        serialize_operation_log(
            item,
            tenant_name=name_map.get(item.tenant_id) if item.tenant_id else None,
        )
        for item in rows
    ]


def client_ip_from_request(request: Request | None) -> str | None:
    if request is None:
        return None
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return None


def write_named_operation_log(
    db: Session,
    *,
    action_type: str,
    description: str,
    operator_name: str,
    tenant_id: int | None,
    operator_user_id: int | None = None,
    target_module: str | None = None,
    target_id: int | None = None,
    risk_level: str = "正常",
    ip_address: str | None = None,
) -> OperationLog:
    """无 CurrentSession 时写企业操作记录（登录、支付回调）。"""
    log = OperationLog(
        operator_name=(operator_name or "未知用户")[:64],
        action_type=action_type[:40],
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


def record_customer_login(db: Session, *, user, identity, request: Request | None = None) -> OperationLog | None:
    """客户身份进入企业时记一条登录。平台身份和未选企业的登录不记。"""
    if str(getattr(identity, "identity_type", "") or "") != "CUSTOMER":
        return None
    tenant_id = getattr(identity, "tenant_id", None)
    if not tenant_id:
        return None
    operator_name = (
        getattr(user, "display_name", None)
        or getattr(identity, "identity_name", None)
        or getattr(user, "username", None)
        or "未知用户"
    )
    return write_named_operation_log(
        db,
        action_type="登录",
        description="登录成功",
        operator_name=str(operator_name),
        operator_user_id=getattr(user, "id", None),
        tenant_id=int(tenant_id),
        target_module="登录",
        ip_address=client_ip_from_request(request),
    )


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


def write_business_audit(
    db: Session,
    current: CurrentSession,
    action_type: str,
    description: str,
    *,
    request: Request | None = None,
    target_module: str,
    target_id: int | None = None,
    tenant_id: int | None = None,
    risk_level: str = "正常",
) -> OperationLog:
    """关键业务写操作审计（知识库、报告等）。"""
    return write_operation_log(
        db,
        current,
        action_type,
        description,
        target_module=target_module,
        target_id=target_id,
        tenant_id=tenant_id,
        risk_level=risk_level,
        ip_address=client_ip_from_request(request),
    )
