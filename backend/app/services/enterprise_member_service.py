"""Credit 企业成员 CRUD（租户范围，走 CustomerPosition 菜单模板）。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.services.auth_service import mark_password_changed
from app.models.permission import CustomerPosition, CustomerPositionMenu, Menu, UserIdentityMenu
from app.models.user import User
from app.models.user_identity import UserIdentity
from app.services.management_service import _reject_garbled_text

PORTAL_MENU_CODES = (
    "customer.workspace",
    "customer.brand_analysis",
    "customer.realtime",
    "customer.competitor",
    "customer.sources",
    "customer.reports",
    "customer.knowledge",
)

_SKIP_IDENTITY_MENU_CODES = {
    "customer.goods_cards",
    "customer.enterprise_config",
    "customer.enterprise_monitor",
    "customer.enterprise_members",
    "customer.enterprise_credit",
    "customer.enterprise_audit",
}


def _validate_position(db: Session, tenant_id: int, position_id: int) -> CustomerPosition:
    position = db.scalar(
        select(CustomerPosition).where(
            CustomerPosition.id == position_id,
            CustomerPosition.deleted.is_(False),
            CustomerPosition.status.is_(True),
        )
    )
    if position is None:
        raise ValueError("职位不存在")
    if position.tenant_id is not None and position.tenant_id != tenant_id:
        raise ValueError("职位不属于本企业")
    return position


def replace_identity_menus_from_customer_position(db: Session, identity_id: int, position_id: int) -> None:
    # 2026-08-27 - 成员改职位 - 按 CustomerPositionMenu 重建身份菜单
    db.query(UserIdentityMenu).filter(UserIdentityMenu.identity_id == identity_id).delete(synchronize_session=False)
    position_rows = list(
        db.scalars(select(CustomerPositionMenu).where(CustomerPositionMenu.position_id == position_id))
    )
    granted_menu_ids = {row.menu_id for row in position_rows}
    skip_ids = {
        menu.id
        for menu in db.scalars(
            select(Menu).where(Menu.menu_code.in_(tuple(_SKIP_IDENTITY_MENU_CODES)), Menu.deleted.is_(False))
        )
    }
    for row in position_rows:
        if row.menu_id in skip_ids:
            continue
        db.add(
            UserIdentityMenu(
                identity_id=identity_id,
                menu_id=row.menu_id,
                can_create=bool(row.can_create),
                can_update=bool(row.can_update),
                can_delete=bool(row.can_delete),
                can_export=bool(row.can_export),
            )
        )
    base_menus = list(
        db.scalars(
            select(Menu).where(
                Menu.identity_type == "CUSTOMER",
                Menu.menu_code.in_(PORTAL_MENU_CODES),
                Menu.deleted.is_(False),
                Menu.status.is_(True),
            )
        )
    )
    for menu in base_menus:
        if menu.id in granted_menu_ids:
            continue
        if menu.menu_code == "customer.knowledge":
            # 2026-09-09 - 补洞只给查看，不抬上传/编辑；写权限须来自职位模板
            flags = {"can_create": False, "can_update": False, "can_delete": False, "can_export": True}
        else:
            flags = {"can_create": False, "can_update": False, "can_delete": False, "can_export": True}
        db.add(UserIdentityMenu(identity_id=identity_id, menu_id=menu.id, **flags))
    db.flush()


def list_tenant_customer_identities(db: Session, tenant_id: int) -> list[UserIdentity]:
    return list(
        db.scalars(
            select(UserIdentity).where(
                UserIdentity.tenant_id == tenant_id,
                UserIdentity.identity_type == "CUSTOMER",
                UserIdentity.deleted.is_(False),
            )
        )
    )


def get_tenant_member_identity(db: Session, tenant_id: int, identity_id: int) -> UserIdentity:
    identity = db.scalar(
        select(UserIdentity).where(
            UserIdentity.id == identity_id,
            UserIdentity.tenant_id == tenant_id,
            UserIdentity.identity_type == "CUSTOMER",
            UserIdentity.deleted.is_(False),
        )
    )
    if identity is None:
        raise ValueError("成员不存在")
    return identity


def create_enterprise_member(
    db: Session,
    *,
    tenant_id: int,
    display_name: str,
    username: str,
    password: str,
    customer_position_id: int,
    operator_user_id: int,
) -> UserIdentity:
    _reject_garbled_text(display_name, "用户姓名")
    username = str(username or "").strip()
    exists = db.scalar(select(User).where(User.username == username))
    if exists is not None:
        raise ValueError("账号已存在")
    if len(password or "") < 8:
        raise ValueError("密码至少 8 位")
    position = _validate_position(db, tenant_id, customer_position_id)
    user = User(
        username=username,
        password_hash=hash_password(password),
        display_name=display_name,
        created_by=operator_user_id,
    )
    db.add(user)
    db.flush()
    identity = UserIdentity(
        identity_code=f"CUSTOMER_{user.id}_customer",
        user_id=user.id,
        tenant_id=tenant_id,
        identity_type="CUSTOMER",
        identity_name=position.position_name,
        role_code="customer",
        customer_position_id=position.id,
        is_default=True,
    )
    db.add(identity)
    db.flush()
    replace_identity_menus_from_customer_position(db, identity.id, position.id)
    db.commit()
    db.refresh(identity)
    return identity


ADMIN_POSITION_CODE = "enterprise_admin"


def update_enterprise_member(
    db: Session,
    *,
    tenant_id: int,
    identity_id: int,
    display_name: str,
    customer_position_id: int,
    status: bool,
    current_identity_id: int,
) -> UserIdentity:
    if identity_id == current_identity_id and not status:
        raise ValueError("不能停用当前登录账号")
    _reject_garbled_text(display_name, "用户姓名")
    identity = get_tenant_member_identity(db, tenant_id, identity_id)
    position = _validate_position(db, tenant_id, customer_position_id)
    # 2026-09-09 - 降级/停用唯一管理员与删除同一守卫
    was_admin = False
    if identity.customer_position_id:
        old_pos = db.get(CustomerPosition, identity.customer_position_id)
        was_admin = bool(old_pos and old_pos.position_code == ADMIN_POSITION_CODE and identity.status)
    becoming_non_admin = position.position_code != ADMIN_POSITION_CODE or not status
    if was_admin and becoming_non_admin:
        if _active_admin_count(db, tenant_id, exclude_identity_id=identity_id) < 1:
            raise ValueError("企业须保留至少一名管理员")
    user = db.get(User, identity.user_id)
    if user is None:
        raise ValueError("用户不存在")
    user.display_name = display_name
    user.status = status
    identity.identity_name = position.position_name
    identity.customer_position_id = position.id
    identity.status = status
    replace_identity_menus_from_customer_position(db, identity.id, position.id)
    db.commit()
    db.refresh(identity)
    return identity


def _identity_is_admin(db: Session, identity: UserIdentity) -> bool:
    if not identity.customer_position_id or not identity.status:
        return False
    position = db.get(CustomerPosition, identity.customer_position_id)
    return bool(position and position.position_code == ADMIN_POSITION_CODE and not position.deleted)


def reset_enterprise_member_password(
    db: Session,
    *,
    tenant_id: int,
    identity_id: int,
    password: str,
    current_identity_id: int,
) -> None:
    if len(password or "") < 8:
        raise ValueError("密码至少 8 位")
    operator = get_tenant_member_identity(db, tenant_id, current_identity_id)
    if not _identity_is_admin(db, operator):
        raise ValueError("仅企业管理员可重置成员密码")
    identity = get_tenant_member_identity(db, tenant_id, identity_id)
    if _identity_is_admin(db, identity) and identity_id != current_identity_id:
        raise ValueError("不能重置其他管理员的密码")
    user = db.get(User, identity.user_id)
    if user is None:
        raise ValueError("用户不存在")
    user.password_hash = hash_password(password)
    user.must_change_password = False
    mark_password_changed(user)
    db.commit()


def _active_admin_count(db: Session, tenant_id: int, *, exclude_identity_id: int | None = None) -> int:
    rows = db.execute(
        select(UserIdentity.id)
        .join(CustomerPosition, UserIdentity.customer_position_id == CustomerPosition.id)
        .where(
            UserIdentity.tenant_id == tenant_id,
            UserIdentity.identity_type == "CUSTOMER",
            UserIdentity.deleted.is_(False),
            UserIdentity.status.is_(True),
            CustomerPosition.position_code == ADMIN_POSITION_CODE,
            CustomerPosition.deleted.is_(False),
        )
    ).all()
    return sum(1 for (ident_id,) in rows if ident_id != exclude_identity_id)


def remove_enterprise_member(
    db: Session,
    *,
    tenant_id: int,
    identity_id: int,
    current_identity_id: int,
) -> None:
    if identity_id == current_identity_id:
        raise ValueError("不能删除当前登录账号")
    identity = get_tenant_member_identity(db, tenant_id, identity_id)
    if identity.customer_position_id:
        position = db.get(CustomerPosition, identity.customer_position_id)
        if position and position.position_code == ADMIN_POSITION_CODE:
            # 2026-08-27 - 删成员须留至少一名管理员
            if _active_admin_count(db, tenant_id, exclude_identity_id=identity_id) < 1:
                raise ValueError("企业须保留至少一名管理员")
    user = db.get(User, identity.user_id)
    if user is None:
        raise ValueError("用户不存在")
    identity.deleted = True
    identity.status = False
    user.deleted = True
    user.status = False
    db.commit()
