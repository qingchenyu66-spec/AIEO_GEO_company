"""租户范围解析：分析类读接口统一规则。"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentSession
from app.models.permission import Position
from app.models.tenant import Tenant
from app.models.user_identity import UserIdentity
from app.services.menu_permission_service import has_identity_menu_permission

logger = logging.getLogger(__name__)

ANALYTICS_READ_MENU = "platform.competitor"


def ensure_tenant(db: Session, tenant_id: int) -> Tenant:
    tenant = db.scalar(select(Tenant).where(Tenant.id == tenant_id, Tenant.deleted.is_(False)))
    if tenant is None:
        raise ValueError("企业不存在")
    return tenant


def is_sales_identity(db: Session, identity: UserIdentity) -> bool:
    if identity.identity_type != "PLATFORM" or identity.position_id is None:
        return False
    position = db.scalar(
        select(Position).where(
            Position.id == identity.position_id,
            Position.deleted.is_(False),
        )
    )
    if position is None:
        return False
    # 权限判断使用稳定编码，避免职位名称被改后导致销售可见全部企业。
    return position.position_code == "PLATFORM_SALES"


def is_platform_admin_identity(db: Session, identity: UserIdentity) -> bool:
    """平台管理员职位（或 role_code 兜底）。"""
    if identity.identity_type != "PLATFORM":
        return False
    if identity.position_id is not None:
        position = db.scalar(
            select(Position).where(
                Position.id == identity.position_id,
                Position.deleted.is_(False),
            )
        )
        if position is not None and position.position_code == "PLATFORM_ADMIN":
            return True
    return str(identity.role_code or "").upper() == "PLATFORM_ADMIN"


def is_platform_operation_identity(db: Session, identity: UserIdentity) -> bool:
    """运营职位：显式 PLATFORM_OPERATION，或非销售且非管理员的平台账号。"""
    if identity.identity_type != "PLATFORM":
        return False
    if is_sales_identity(db, identity) or is_platform_admin_identity(db, identity):
        return False
    if identity.position_id is not None:
        position = db.scalar(
            select(Position).where(
                Position.id == identity.position_id,
                Position.deleted.is_(False),
            )
        )
        if position is not None and position.position_code == "PLATFORM_OPERATION":
            return True
        if position is not None:
            # 交付等其他平台职位：按运营侧开关收通知
            return True
    return True


def ensure_sales_tenant_access(db: Session, current: CurrentSession, tenant_id: int) -> None:
    """销售身份只能访问归属本账号的企业。"""
    if current.identity.identity_type != "PLATFORM":
        return
    if not is_sales_identity(db, current.identity):
        return
    tenant = db.scalar(
        select(Tenant).where(
            Tenant.id == tenant_id,
            Tenant.deleted.is_(False),
        )
    )
    if tenant is None:
        raise ValueError("企业不存在")
    if tenant.owner_user_id != current.user.id:
        raise PermissionError("当前账号无权访问该企业数据")


def resolve_analytics_tenant_id(current: CurrentSession, requested_tenant_id: int | None) -> int:
    """客户身份强制绑定企业；平台身份必须显式指定 tenant_id。"""
    if current.identity.identity_type == "CUSTOMER":
        if current.identity.tenant_id is None:
            raise ValueError("当前客户身份未绑定企业")
        return current.identity.tenant_id
    if requested_tenant_id is None:
        raise ValueError("平台端需要指定企业")
    return requested_tenant_id


def ensure_platform_tenant_read_access(
    db: Session,
    current: CurrentSession,
    tenant_id: int,
    *,
    menu_code: str = ANALYTICS_READ_MENU,
    action: str = "can_export",
) -> None:
    """平台端按企业读数据：校验企业存在 + 销售归属 + 菜单查看权限，并记审计日志。"""
    if current.identity.identity_type != "PLATFORM":
        return
    ensure_tenant(db, tenant_id)
    ensure_sales_tenant_access(db, current, tenant_id)
    if not has_identity_menu_permission(db, current.identity.id, menu_code, action):
        # 有企业管理查看权即可按企业只读分析（客户门户预览 / 运营核对）
        if not has_identity_menu_permission(db, current.identity.id, "platform.audit.list", "can_export"):
            raise PermissionError("当前账号没有该数据范围的查看权限")
    logger.info(
        "platform tenant read identity_id=%s user_id=%s tenant_id=%s menu=%s",
        current.identity.id,
        current.user.id,
        tenant_id,
        menu_code,
    )


def resolve_and_guard_analytics_tenant(
    db: Session,
    current: CurrentSession,
    requested_tenant_id: int | None,
    *,
    menu_code: str = ANALYTICS_READ_MENU,
) -> int:
    """解析租户并校验平台读权限。"""
    tenant_id = resolve_analytics_tenant_id(current, requested_tenant_id)
    ensure_platform_tenant_read_access(db, current, tenant_id, menu_code=menu_code)
    return tenant_id


def sales_owned_lead_diagnosis_task_ids(db: Session, user_id: int) -> list[str]:
    """销售账号创建的售前诊断关联监测 task_id 列表。"""
    from app.models.lead_diagnosis import LeadDiagnosis, LeadDiagnosisRun

    rows = db.scalars(
        select(LeadDiagnosisRun.task_id)
        .join(LeadDiagnosis, LeadDiagnosis.id == LeadDiagnosisRun.lead_diagnosis_id)
        .where(
            LeadDiagnosis.deleted.is_(False),
            LeadDiagnosis.created_by_user_id == user_id,
            LeadDiagnosisRun.task_id.isnot(None),
        )
    )
    return list(rows)


def ensure_lead_diagnosis_task_access(db: Session, current: CurrentSession, task_id: str) -> None:
    """销售只能访问本人创建的售前诊断关联监测任务。"""
    from app.models.lead_diagnosis import LeadDiagnosis, LeadDiagnosisRun

    if current.identity.identity_type != "PLATFORM":
        raise PermissionError("无权访问该监测数据")
    if not is_sales_identity(db, current.identity):
        return
    owner_id = db.scalar(
        select(LeadDiagnosis.created_by_user_id)
        .join(LeadDiagnosisRun, LeadDiagnosisRun.lead_diagnosis_id == LeadDiagnosis.id)
        .where(
            LeadDiagnosisRun.task_id == task_id,
            LeadDiagnosis.deleted.is_(False),
        )
    )
    if owner_id is None:
        raise PermissionError("无权访问该监测数据")
    if owner_id != current.user.id:
        raise PermissionError("无权访问该售前诊断监测数据")


def assert_monitor_task_access(
    db: Session,
    current: CurrentSession,
    tenant_id: int | None,
    *,
    task_id: str | None = None,
) -> None:
    """监测任务读路径：客户绑定租户；平台销售仅看名下企业或本人售前诊断任务。"""
    if current.identity.identity_type == "CUSTOMER":
        if tenant_id is None or current.identity.tenant_id != tenant_id:
            raise PermissionError("无权访问该企业监测数据")
        return
    if tenant_id is not None:
        ensure_sales_tenant_access(db, current, tenant_id)
        return
    if task_id:
        ensure_lead_diagnosis_task_access(db, current, task_id)
        return
    if is_sales_identity(db, current.identity):
        raise PermissionError("无权访问该监测数据")


def resolve_and_guard_tenant_id(
    db: Session,
    current: CurrentSession,
    requested_tenant_id: int | None,
) -> int:
    """解析 tenant_id 并校验企业存在 + 销售归属（平台/客户通用入口）。"""
    tenant_id = resolve_analytics_tenant_id(current, requested_tenant_id)
    ensure_tenant(db, tenant_id)
    ensure_sales_tenant_access(db, current, tenant_id)
    return tenant_id


def resolve_customer_preview_tenant_id(
    db: Session,
    current: CurrentSession,
    requested_tenant_id: int | None,
) -> int:
    """平台端客户门户只读预览：需企业管理查看权 + 销售归属。"""
    if current.identity.identity_type != "PLATFORM":
        raise PermissionError("仅平台端可预览客户门户")
    if requested_tenant_id is None:
        raise ValueError("平台端预览需指定企业")
    if not has_identity_menu_permission(db, current.identity.id, "platform.audit.list", "can_export"):
        raise PermissionError("当前账号无权预览客户门户")
    return resolve_and_guard_tenant_id(db, current, requested_tenant_id)


def guard_tenant_resource_access(db: Session, current: CurrentSession, tenant_id: int) -> None:
    """按资源 tenant_id 校验销售归属（file/report/diagnosis 等）。"""
    ensure_tenant(db, tenant_id)
    ensure_sales_tenant_access(db, current, tenant_id)


def sales_owned_tenant_ids(db: Session, current: CurrentSession) -> list[int] | None:
    """销售返回名下企业 ID 列表；非销售平台身份返回 None（不限制）。"""
    if current.identity.identity_type != "PLATFORM":
        return None
    if not is_sales_identity(db, current.identity):
        return None
    rows = db.scalars(
        select(Tenant.id).where(
            Tenant.deleted.is_(False),
            Tenant.owner_user_id == current.user.id,
        )
    )
    return list(rows)
