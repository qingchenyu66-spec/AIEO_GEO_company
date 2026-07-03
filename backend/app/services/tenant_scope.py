"""租户范围解析：分析类读接口统一规则。"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.api.dependencies import CurrentSession
from app.services.brand_service import ensure_tenant
from app.services.menu_permission_service import has_identity_menu_permission

logger = logging.getLogger(__name__)

ANALYTICS_READ_MENU = "platform.competitor"


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
    """平台端按企业读数据：校验企业存在 + 菜单查看权限，并记审计日志。"""
    if current.identity.identity_type != "PLATFORM":
        return
    ensure_tenant(db, tenant_id)
    if not has_identity_menu_permission(db, current.identity.id, menu_code, action):
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
