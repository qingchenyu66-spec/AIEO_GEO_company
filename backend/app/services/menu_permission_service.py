"""菜单动作权限——职位配置、身份会话与 API 鉴权共用。"""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.menu_config import MenuConfig
from app.models.permission import Menu, PositionMenu, UserIdentityMenu
from app.models.user_identity import UserIdentity
from app.schemas.permission import MenuGrantItem, MenuInfo

# 子权限菜单 → 侧边栏路由菜单（有子权限则自动展示父级菜单）
ROUTE_PARENT_BY_CHILD: dict[str, str] = {
    "platform.audit.list": "platform.audit",
    "platform.audit.profile": "platform.audit",
    "platform.audit.keywords": "platform.audit",
    "platform.audit.models": "platform.audit",
    "platform.audit.schedule": "platform.audit",
    "platform.audit.competitors": "platform.audit",
    "platform.audit.files": "platform.audit",
    "platform.users.list": "platform.users",
    "platform.users.create.platform": "platform.users",
    "platform.users.create.customer": "platform.users",
    "platform.positions": "platform.users",
}

# 职位权限配置里不单独勾选的路由父菜单（只配置子项动作，父菜单自动推导）
ROUTE_ONLY_MENU_CODES = frozenset({"platform.audit", "platform.users"})

REPORT_MENU_BY_IDENTITY = {
    "PLATFORM": "platform.reports",
    "CUSTOMER": "customer.reports",
}

# 与前端 menuPermissionMatrix 对齐：各菜单允许的动作
MENU_ALLOWED_ACTIONS: dict[str, frozenset[str]] = {
    "platform.dashboard": frozenset({"can_export"}),
    "platform.audit.list": frozenset({"can_export"}),
    "platform.audit.profile": frozenset({"can_export", "can_update"}),
    "platform.audit.keywords": frozenset({"can_export", "can_update"}),
    "platform.audit.models": frozenset({"can_export", "can_update"}),
    "platform.audit.schedule": frozenset({"can_export", "can_update"}),
    "platform.audit.competitors": frozenset({"can_export", "can_update"}),
    "platform.audit.files": frozenset({"can_export"}),
    "platform.competitor": frozenset({"can_export"}),
    "platform.sources": frozenset({"can_export"}),
    "platform.diagnosis": frozenset({"can_export"}),
    "platform.lead_diagnosis": frozenset({"can_export", "can_create"}),
    "platform.snapshot_backfill": frozenset({"can_export", "can_update"}),
    "platform.reports": frozenset({"can_export", "can_create", "can_update"}),
    "platform.plans": frozenset({"can_export"}),
    "platform.admins": frozenset({"can_export"}),
    "platform.models": frozenset({"can_export"}),
    "platform.alerts": frozenset({"can_export", "can_update"}),
    "platform.logs": frozenset({"can_export"}),
    "platform.settings": frozenset({"can_export", "can_update"}),
    "platform.users.list": frozenset({"can_export", "can_update", "can_delete"}),
    "platform.users.create.platform": frozenset({"can_create"}),
    "platform.users.create.customer": frozenset({"can_create"}),
    "platform.positions": frozenset({"can_export", "can_update", "can_delete"}),
    "customer.workspace": frozenset({"can_export"}),
    "customer.realtime": frozenset({"can_export"}),
    "customer.links": frozenset({"can_export"}),
    "customer.diagnosis": frozenset({"can_export"}),
    "customer.competitor": frozenset({"can_export"}),
    "customer.sources": frozenset({"can_export"}),
    "customer.reports": frozenset({"can_export"}),
    "customer.knowledge": frozenset({"can_export", "can_create", "can_update"}),
}


def _allowed_actions_for_menu(menu_code: str, identity_type: str) -> frozenset[str]:
    if menu_code in MENU_ALLOWED_ACTIONS:
        return MENU_ALLOWED_ACTIONS[menu_code]
    if menu_code.startswith("platform.audit."):
        return frozenset({"can_export"}) if menu_code == "platform.audit.list" else frozenset({"can_export", "can_update"})
    if identity_type == "CUSTOMER":
        return frozenset({"can_export"})
    return frozenset({"can_export"})


def sanitize_menu_grant_flags(
    menu_code: str,
    identity_type: str,
    *,
    can_create: bool,
    can_update: bool,
    can_delete: bool,
    can_export: bool,
) -> dict[str, bool]:
    """保存职位权限时剔除菜单不支持的动作，避免 DB 里出现「假权限」。"""
    allowed = _allowed_actions_for_menu(menu_code, identity_type)
    return {
        "can_create": can_create and "can_create" in allowed,
        "can_update": can_update and "can_update" in allowed,
        "can_delete": can_delete and "can_delete" in allowed,
        "can_export": can_export and "can_export" in allowed,
    }


def grant_has_access(*, can_create: bool, can_update: bool, can_delete: bool, can_export: bool) -> bool:
    return bool(can_create or can_update or can_delete or can_export)


def merge_grant_flags(current: MenuInfo | None, incoming: MenuInfo) -> MenuInfo:
    if current is None:
        return incoming
    return MenuInfo(
        id=current.id,
        menu_code=current.menu_code,
        menu_name=current.menu_name,
        identity_type=current.identity_type,
        route_path=current.route_path,
        icon=current.icon,
        sort_order=current.sort_order,
        can_create=current.can_create or incoming.can_create,
        can_update=current.can_update or incoming.can_update,
        can_delete=current.can_delete or incoming.can_delete,
        can_export=current.can_export or incoming.can_export,
    )


def _menu_with_grant(
    base: MenuInfo,
    *,
    can_create: bool,
    can_update: bool,
    can_delete: bool,
    can_export: bool,
) -> MenuInfo:
    return MenuInfo(
        id=base.id,
        menu_code=base.menu_code,
        menu_name=base.menu_name,
        identity_type=base.identity_type,
        route_path=base.route_path,
        icon=base.icon,
        sort_order=base.sort_order,
        can_create=can_create,
        can_update=can_update,
        can_delete=can_delete,
        can_export=can_export,
    )


def _menu_display(menu: Menu, config: MenuConfig | None) -> MenuInfo:
    return MenuInfo(
        id=menu.id,
        menu_code=menu.menu_code,
        menu_name=(config.menu_name if config and config.menu_name else menu.menu_name),
        identity_type=menu.identity_type,
        route_path=(config.route_path if config and config.route_path else menu.route_path),
        icon=(config.icon if config and config.icon else menu.icon),
        sort_order=(config.sort_order if config is not None else menu.sort_order),
    )


def has_identity_menu_permission(
    db: Session,
    identity_id: int,
    menu_code: str,
    action: str = "can_create",
) -> bool:
    grant = db.execute(
        select(UserIdentityMenu)
        .join(Menu, Menu.id == UserIdentityMenu.menu_id)
        .where(
            UserIdentityMenu.identity_id == identity_id,
            Menu.menu_code == menu_code,
            Menu.status.is_(True),
            Menu.deleted.is_(False),
        )
    ).scalar_one_or_none()
    return bool(grant and getattr(grant, action, False))


def has_any_identity_menu_permission(
    db: Session,
    identity_id: int,
    menu_code: str,
    actions: tuple[str, ...],
) -> bool:
    return any(has_identity_menu_permission(db, identity_id, menu_code, action) for action in actions)


def get_identity_menus(db: Session, identity: UserIdentity) -> list[MenuInfo]:
    """读取身份可见菜单：至少一项动作权限为真；子权限自动推导父级路由菜单。"""
    rows = db.execute(
        select(Menu, UserIdentityMenu, MenuConfig)
        .join(UserIdentityMenu, UserIdentityMenu.menu_id == Menu.id)
        .outerjoin(
            MenuConfig,
            (MenuConfig.menu_code == Menu.menu_code)
            & (MenuConfig.identity_type == Menu.identity_type)
            & (MenuConfig.deleted.is_(False)),
        )
        .where(
            UserIdentityMenu.identity_id == identity.id,
            Menu.identity_type == identity.identity_type,
            Menu.status.is_(True),
            Menu.deleted.is_(False),
            or_(
                UserIdentityMenu.can_create.is_(True),
                UserIdentityMenu.can_update.is_(True),
                UserIdentityMenu.can_delete.is_(True),
                UserIdentityMenu.can_export.is_(True),
            ),
        )
        .order_by(Menu.sort_order.asc(), Menu.id.asc())
    ).all()

    by_code: dict[str, MenuInfo] = {}
    for menu, grant, config in rows:
        base = _menu_display(menu, config)
        item = _menu_with_grant(
            base,
            can_create=bool(grant.can_create),
            can_update=bool(grant.can_update),
            can_delete=bool(grant.can_delete),
            can_export=bool(grant.can_export),
        )
        by_code[item.menu_code] = merge_grant_flags(by_code.get(item.menu_code), item)

    missing_parents = {
        parent_code
        for code in by_code
        if (parent_code := ROUTE_PARENT_BY_CHILD.get(code)) and parent_code not in by_code
    }
    if missing_parents:
        parent_rows = db.execute(
            select(Menu, MenuConfig)
            .outerjoin(
                MenuConfig,
                (MenuConfig.menu_code == Menu.menu_code)
                & (MenuConfig.identity_type == Menu.identity_type)
                & (MenuConfig.deleted.is_(False)),
            )
            .where(
                Menu.menu_code.in_(missing_parents),
                Menu.identity_type == identity.identity_type,
                Menu.status.is_(True),
                Menu.deleted.is_(False),
            )
        ).all()
        parent_lookup = {menu.menu_code: _menu_display(menu, config) for menu, config in parent_rows}
        for code, item in list(by_code.items()):
            parent_code = ROUTE_PARENT_BY_CHILD.get(code)
            if not parent_code:
                continue
            parent_base = parent_lookup.get(parent_code)
            if parent_base is None:
                continue
            synthesized = _menu_with_grant(parent_base, can_create=False, can_update=False, can_delete=False, can_export=False)
            synthesized = merge_grant_flags(synthesized, item)
            by_code[parent_code] = merge_grant_flags(by_code.get(parent_code), synthesized)

    items = list(by_code.values())
    items.sort(key=lambda item: (item.sort_order, item.id))
    return items


def position_menu_grants(db: Session, position_id: int) -> list[MenuGrantItem]:
    rows = db.execute(
        select(PositionMenu, Menu)
        .join(Menu, Menu.id == PositionMenu.menu_id)
        .where(PositionMenu.position_id == position_id, Menu.deleted.is_(False))
        .order_by(Menu.sort_order.asc(), Menu.id.asc())
    ).all()
    grants: list[MenuGrantItem] = []
    for grant, menu in rows:
        if not grant_has_access(
            can_create=grant.can_create,
            can_update=grant.can_update,
            can_delete=grant.can_delete,
            can_export=grant.can_export,
        ):
            continue
        grants.append(
            MenuGrantItem(
                menu_id=menu.id,
                menu_code=menu.menu_code,
                can_create=grant.can_create,
                can_update=grant.can_update,
                can_delete=grant.can_delete,
                can_export=grant.can_export,
            )
        )
    return grants


def sync_position_menu_grants(
    db: Session,
    position_id: int,
    menu_grants: list[MenuGrantItem | dict],
    *,
    identity_type: str,
    menu_ids: list[int] | None = None,
    writable: bool = True,
) -> None:
    """保存职位权限。优先 menu_grants；兼容旧版 menu_ids。"""
    db.query(PositionMenu).filter(PositionMenu.position_id == position_id).delete(synchronize_session=False)
    valid_menu_ids = set(
        db.scalars(
            select(Menu.id).where(
                Menu.identity_type == identity_type,
                Menu.status.is_(True),
                Menu.deleted.is_(False),
            )
        )
    )

    if menu_grants:
        menu_code_map = {
            row.id: row.menu_code
            for row in db.scalars(
                select(Menu).where(
                    Menu.identity_type == identity_type,
                    Menu.status.is_(True),
                    Menu.deleted.is_(False),
                )
            )
        }
        for raw in menu_grants:
            item = raw if isinstance(raw, MenuGrantItem) else MenuGrantItem.model_validate(raw)
            if item.menu_id not in valid_menu_ids:
                continue
            menu_code = menu_code_map.get(item.menu_id, "")
            flags = sanitize_menu_grant_flags(
                menu_code,
                identity_type,
                can_create=item.can_create,
                can_update=item.can_update,
                can_delete=item.can_delete,
                can_export=item.can_export,
            )
            if not grant_has_access(**flags):
                continue
            db.add(
                PositionMenu(
                    position_id=position_id,
                    menu_id=item.menu_id,
                    **flags,
                )
            )
        return

    for menu_id in menu_ids or []:
        if menu_id not in valid_menu_ids:
            continue
        db.add(
            PositionMenu(
                position_id=position_id,
                menu_id=menu_id,
                can_create=writable,
                can_update=writable,
                can_delete=writable,
                can_export=True,
            )
        )


def replace_identity_menus_from_position(
    db: Session,
    identity_id: int,
    position_id: int,
    selected_menu_ids: list[int] | None = None,
) -> None:
    rows = list(
        db.scalars(select(PositionMenu).where(PositionMenu.position_id == position_id))
    )
    selected_set = set(selected_menu_ids or [])
    if selected_menu_ids is not None:
        rows = [row for row in rows if row.menu_id in selected_set]
    db.query(UserIdentityMenu).filter(UserIdentityMenu.identity_id == identity_id).delete(synchronize_session=False)
    for row in rows:
        if not grant_has_access(
            can_create=row.can_create,
            can_update=row.can_update,
            can_delete=row.can_delete,
            can_export=row.can_export,
        ):
            continue
        selected_set.discard(row.menu_id)
        db.add(
            UserIdentityMenu(
                identity_id=identity_id,
                menu_id=row.menu_id,
                can_create=row.can_create,
                can_update=row.can_update,
                can_delete=row.can_delete,
                can_export=row.can_export,
            )
        )
    for menu_id in selected_set:
        db.add(
            UserIdentityMenu(
                identity_id=identity_id,
                menu_id=menu_id,
                can_create=False,
                can_update=False,
                can_delete=False,
                can_export=True,
            )
        )


def sync_identity_menus_for_position(db: Session, position_id: int) -> int:
    """职位权限变更后，同步到所有绑定该职位的身份。"""
    identity_ids = list(
        db.scalars(
            select(UserIdentity.id).where(
                UserIdentity.position_id == position_id,
                UserIdentity.deleted.is_(False),
                UserIdentity.status.is_(True),
            )
        )
    )
    for identity_id in identity_ids:
        replace_identity_menus_from_position(db, identity_id, position_id)
    return len(identity_ids)


def ensure_identity_menus_from_position(db: Session, identity: UserIdentity) -> bool:
    """身份菜单为空但已绑定职位时，从职位模板补全（防止历史数据或同步失败）。"""
    if identity.position_id is None:
        return False
    has_grant = db.scalar(
        select(UserIdentityMenu.id).where(UserIdentityMenu.identity_id == identity.id).limit(1)
    )
    if has_grant is not None:
        return False
    position_has_grant = db.scalar(
        select(PositionMenu.id).where(PositionMenu.position_id == identity.position_id).limit(1)
    )
    if position_has_grant is None:
        return False
    replace_identity_menus_from_position(db, identity.id, identity.position_id)
    return True


def require_snapshot_backfill_permission(
    db: Session,
    current,
    action: str = "can_export",
) -> None:
    from app.api.dependencies import CurrentSession

    session: CurrentSession = current
    if session.identity.identity_type != "PLATFORM":
        raise PermissionError("仅平台运营端可访问快照补录")
    if not has_identity_menu_permission(db, session.identity.id, "platform.snapshot_backfill", action):
        raise PermissionError("当前身份无快照补录权限")


def require_report_permission(db: Session, current, action: str) -> None:
    from app.api.dependencies import CurrentSession

    session: CurrentSession = current
    identity_type = session.identity.identity_type
    menu_code = REPORT_MENU_BY_IDENTITY.get(identity_type)
    if not menu_code:
        raise ValueError("无权操作")
    if identity_type == "CUSTOMER" and action == "can_create":
        raise ValueError("客户无权生成报告")
    if not has_identity_menu_permission(db, session.identity.id, menu_code, action):
        raise ValueError("无权操作")


def require_report_access(db: Session, current) -> None:
    identity_type = current.identity.identity_type
    menu_code = REPORT_MENU_BY_IDENTITY.get(identity_type)
    if not menu_code:
        raise ValueError("无权查看")
    if not has_any_identity_menu_permission(
        db,
        current.identity.id,
        menu_code,
        ("can_export", "can_create", "can_update"),
    ):
        raise ValueError("无权查看")
