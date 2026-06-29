from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.permission import Menu, Position, PositionMenu, Role, RoleMenu, UserIdentityMenu
from app.models.user_identity import UserIdentity
from app.schemas.permission import MenuInfo


def get_identity_menus(db: Session, identity: UserIdentity) -> list[MenuInfo]:
    """读取当前身份的可见菜单。

    说明：菜单必须来自数据库，前端只负责渲染；这样后续新增菜单、调整权限时不需要改前端代码。
    """
    rows = db.execute(
        select(Menu, UserIdentityMenu)
        .join(UserIdentityMenu, UserIdentityMenu.menu_id == Menu.id)
        .where(
            UserIdentityMenu.identity_id == identity.id,
            Menu.identity_type == identity.identity_type,
            Menu.status.is_(True),
            Menu.deleted.is_(False),
        )
        .order_by(Menu.sort_order.asc(), Menu.id.asc())
    ).all()
    return [
        MenuInfo(
            id=menu.id,
            menu_code=menu.menu_code,
            menu_name=menu.menu_name,
            identity_type=menu.identity_type,
            route_path=menu.route_path,
            icon=menu.icon,
            sort_order=menu.sort_order,
            can_create=grant.can_create,
            can_update=grant.can_update,
            can_delete=grant.can_delete,
            can_export=grant.can_export,
        )
        for menu, grant in rows
    ]


def list_menus_by_identity_type(db: Session, identity_type: str) -> list[Menu]:
    """按身份类型读取可配置菜单，用于新增用户时勾选权限。"""
    return list(db.scalars(
        select(Menu)
        .where(Menu.identity_type == identity_type, Menu.status.is_(True), Menu.deleted.is_(False))
        .order_by(Menu.sort_order.asc(), Menu.id.asc())
    ))


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
    """重置某个身份的菜单权限。

    writable=True 用于平台端人员，允许创建、编辑、禁用；客户企业端默认只读展示，避免出现创建类入口。
    """
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


def replace_identity_menus_from_position(db: Session, identity_id: int, position_id: int, selected_menu_ids: list[int] | None = None) -> None:
    rows = list(db.execute(
        select(PositionMenu).where(PositionMenu.position_id == position_id)
    ).scalars().all())
    selected_set = set(selected_menu_ids or [])
    if selected_menu_ids is not None:
        rows = [row for row in rows if row.menu_id in selected_set]
    db.query(UserIdentityMenu).filter(UserIdentityMenu.identity_id == identity_id).delete(synchronize_session=False)
    for row in rows:
        selected_set.discard(row.menu_id)
        db.add(UserIdentityMenu(
            identity_id=identity_id,
            menu_id=row.menu_id,
            can_create=row.can_create,
            can_update=row.can_update,
            can_delete=row.can_delete,
            can_export=row.can_export,
        ))
    for menu_id in selected_set:
        db.add(UserIdentityMenu(
            identity_id=identity_id,
            menu_id=menu_id,
            can_create=False,
            can_update=False,
            can_delete=False,
            can_export=True,
        ))
