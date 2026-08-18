from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.permission import Menu, Position, PositionMenu, Role, RoleMenu, UserIdentityMenu
from app.models.user_identity import UserIdentity
from app.schemas.permission import MenuInfo
from app.services.menu_permission_service import (
    get_identity_menus as build_identity_menus,
    is_retired_menu_code,
    replace_identity_menus_from_position,
)


def get_identity_menus(db: Session, identity: UserIdentity) -> list[MenuInfo]:
    return build_identity_menus(db, identity)


def list_menus_by_identity_type(db: Session, identity_type: str) -> list[Menu]:
    """按身份类型读取可配置菜单，用于新增用户时勾选权限。"""
    return [
        menu
        for menu in db.scalars(
            select(Menu)
            .where(Menu.identity_type == identity_type, Menu.status.is_(True), Menu.deleted.is_(False))
            .order_by(Menu.sort_order.asc(), Menu.id.asc())
        )
        if not is_retired_menu_code(menu.menu_code)
    ]


def list_roles_by_identity_type(db: Session, identity_type: str) -> list[Role]:
    """按身份类型读取角色下拉选项。"""
    return list(db.scalars(
        select(Role)
        .where(Role.identity_type == identity_type, Role.status.is_(True), Role.deleted.is_(False))
        .order_by(Role.id.asc())
    ))


def list_positions_by_identity_type(db: Session, identity_type: str) -> list[Position]:
    return list(db.scalars(
        select(Position)
        .where(Position.identity_type == identity_type, Position.status.is_(True), Position.deleted.is_(False))
        .order_by(Position.sort_order.asc(), Position.id.asc())
    ))


def default_menu_ids_for_position(db: Session, position_id: int) -> list[int]:
    return list(db.scalars(
        select(PositionMenu.menu_id)
        .where(PositionMenu.position_id == position_id)
    ))


def default_menu_ids_for_role(db: Session, role_code: str) -> list[int]:
    """读取角色默认菜单，前端未传 menu_ids 时使用。"""
    return list(db.scalars(
        select(RoleMenu.menu_id)
        .join(Role, Role.id == RoleMenu.role_id)
        .where(Role.role_code == role_code, Role.status.is_(True), Role.deleted.is_(False))
    ))


def replace_identity_menus(db: Session, identity_id: int, menu_ids: list[int], *, writable: bool) -> None:
    """重置某个身份的菜单权限（兼容旧逻辑）。"""
    db.query(UserIdentityMenu).filter(UserIdentityMenu.identity_id == identity_id).delete(synchronize_session=False)
    for menu_id in menu_ids:
        db.add(UserIdentityMenu(
            identity_id=identity_id,
            menu_id=menu_id,
            can_create=writable,
            can_update=writable,
            can_delete=writable,
            can_export=True,
        ))
    # 2026-08-11 - 同会话读身份菜单可能空 - autoflush=False 下写完即 flush
    db.flush()


__all__ = [
    "get_identity_menus",
    "list_menus_by_identity_type",
    "list_roles_by_identity_type",
    "list_positions_by_identity_type",
    "default_menu_ids_for_position",
    "default_menu_ids_for_role",
    "replace_identity_menus",
    "replace_identity_menus_from_position",
]
