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
    "platform.audit.regions": "platform.audit",
    "platform.audit.keywords": "platform.audit",
    "platform.audit.models": "platform.audit",
    "platform.audit.purge": "platform.audit",
    "platform.audit.schedule": "platform.audit",
    "platform.audit.competitors": "platform.audit",
    "platform.audit.files": "platform.audit",
    "platform.users.list": "platform.users",
    "platform.users.create.platform": "platform.users.create",
    "platform.users.create.customer": "platform.users.create",
    "platform.users.create": "platform.users",
    "platform.positions": "platform.users",
    "platform.settings.secrets": "platform.settings",
    "platform.settings.schedule": "platform.settings",
    "platform.settings.cache_queue": "platform.settings",
    "platform.settings.notification": "platform.settings",
    "platform.settings.menu": "platform.settings",
}

# 职位权限配置里不单独勾选的路由父菜单（只配置子项动作，父菜单自动推导）
ROUTE_ONLY_MENU_CODES = frozenset({
    "platform.audit",
    "platform.users",
    "platform.users.create",
    "platform.settings",
})

SETTINGS_CHILD_MENU_CODES = (
    "platform.settings.secrets",
    "platform.settings.schedule",
    "platform.settings.cache_queue",
    "platform.settings.notification",
    "platform.settings.menu",
)

SETTINGS_CATEGORY_BY_MENU = {
    "platform.settings.secrets": "secrets",
    "platform.settings.schedule": "schedule",
    "platform.settings.cache_queue": "cache_queue",
    "platform.settings.notification": "notification",
    "platform.settings.menu": "menu",
}

REPORT_MENU_BY_IDENTITY = {
    "PLATFORM": "platform.reports",
    "CUSTOMER": "customer.reports",
}

# 已下线平台菜单：保留 sys_menu 记录便于历史审计，但不展示、不可分配权限
RETIRED_PLATFORM_MENU_CODES = frozenset({
    "platform.plans",
    "platform.admins",
    "platform.diagnosis",
})


def is_retired_menu_code(menu_code: str) -> bool:
    return menu_code in RETIRED_PLATFORM_MENU_CODES

# 与前端 menuPermissionMatrix 对齐：各菜单允许的动作
MENU_ALLOWED_ACTIONS: dict[str, frozenset[str]] = {
    "platform.dashboard": frozenset({"can_export"}),
    "platform.audit.list": frozenset({"can_export", "can_update", "can_delete"}),
    "platform.audit.profile": frozenset({"can_export", "can_update"}),
    "platform.audit.regions": frozenset({"can_export", "can_update"}),
    "platform.audit.keywords": frozenset({"can_export", "can_update"}),
    "platform.audit.models": frozenset({"can_export", "can_update"}),
    "platform.audit.purge": frozenset({"can_delete"}),
    "platform.audit.schedule": frozenset({"can_export", "can_update"}),
    "platform.audit.competitors": frozenset({"can_export", "can_update"}),
    "platform.audit.files": frozenset({"can_export", "can_create", "can_update"}),
    "platform.competitor": frozenset({"can_export"}),
    "platform.sources": frozenset({"can_export"}),
    "platform.diagnosis": frozenset({"can_export"}),
    "platform.lead_diagnosis": frozenset({"can_export", "can_create"}),
    "platform.h5_diagnosis_orders": frozenset({"can_export"}),
    "platform.snapshot_backfill": frozenset({"can_export", "can_update"}),
    "platform.reports": frozenset({"can_export", "can_create", "can_update"}),
    "platform.models": frozenset({"can_export"}),
    "platform.alerts": frozenset({"can_export", "can_update"}),
    "platform.logs": frozenset({"can_export"}),
    "platform.settings": frozenset({"can_export", "can_update"}),
    "platform.settings.secrets": frozenset({"can_export", "can_update"}),
    "platform.settings.schedule": frozenset({"can_export", "can_update"}),
    "platform.settings.cache_queue": frozenset({"can_export", "can_update"}),
    "platform.settings.notification": frozenset({"can_export", "can_update"}),
    "platform.settings.menu": frozenset({"can_export", "can_update"}),
    "platform.users.list": frozenset({"can_export", "can_update", "can_delete"}),
    "platform.users.create.platform": frozenset({"can_create"}),
    "platform.users.create.customer": frozenset({"can_create"}),
    "platform.positions": frozenset({"can_export", "can_update", "can_delete"}),
    "platform.approvals": frozenset({"can_export", "can_update"}),
    "platform.announcements": frozenset({"can_export", "can_create", "can_update", "can_delete"}),
    "customer.workspace": frozenset({"can_export"}),
    "customer.brand_analysis": frozenset({"can_export"}),
    "customer.realtime": frozenset({"can_export"}),
    "customer.goods_cards": frozenset({"can_export"}),
    "customer.links": frozenset({"can_export"}),
    "customer.diagnosis": frozenset({"can_export"}),
    "customer.competitor": frozenset({"can_export"}),
    "customer.sources": frozenset({"can_export"}),
    "customer.reports": frozenset({"can_export"}),
    "customer.knowledge": frozenset({"can_export", "can_create", "can_update"}),
}


def _allowed_actions_for_menu(menu_code: str, identity_type: str) -> frozenset[str]:
    if is_retired_menu_code(menu_code):
        return frozenset()
    if menu_code in MENU_ALLOWED_ACTIONS:
        return MENU_ALLOWED_ACTIONS[menu_code]
    if menu_code.startswith("platform.audit."):
        if menu_code == "platform.audit.list":
            return frozenset({"can_export", "can_update", "can_delete"})
        return frozenset({"can_export", "can_update"})
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


def normalize_allowed_monitor_platforms(raw: list[str] | None) -> list[str]:
    from app.core.platform_order import sort_platform_codes

    codes: list[str] = []
    seen: set[str] = set()
    for item in raw or []:
        code = str(item or "").strip()
        if not code or code in seen:
            continue
        seen.add(code)
        codes.append(code)
    return sort_platform_codes(codes)


def identity_allowed_monitor_platforms(db: Session, identity: UserIdentity) -> list[str]:
    """会话用：直接读职位平台白名单（按职位不同）；无职位则空。"""
    # 2026-08-07 - 艾迪亚观察号写死平台白名单 - 优先于职位 JSON，避免空职位漏约束
    from app.services.observer_account import observer_platforms_for_user_id

    forced = observer_platforms_for_user_id(db, identity.user_id)
    if forced is not None:
        return normalize_allowed_monitor_platforms(list(forced))

    # 2026-07-30 - 不再用 models.can_update 当大门；白名单即权限
    if not identity.position_id:
        return []
    from app.models.permission import Position

    position = db.scalar(
        select(Position).where(Position.id == identity.position_id, Position.deleted.is_(False))
    )
    if position is None:
        return []
    return normalize_allowed_monitor_platforms(
        list(getattr(position, "allowed_monitor_platforms_json", None) or [])
    )


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

    while True:
        missing_parents = {
            parent_code
            for code in by_code
            if (parent_code := ROUTE_PARENT_BY_CHILD.get(code)) and parent_code not in by_code
        }
        if not missing_parents:
            break
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
            if not parent_code or parent_code in by_code:
                continue
            parent_base = parent_lookup.get(parent_code)
            if parent_base is None:
                continue
            synthesized = _menu_with_grant(parent_base, can_create=False, can_update=False, can_delete=False, can_export=False)
            synthesized = merge_grant_flags(synthesized, item)
            by_code[parent_code] = merge_grant_flags(by_code.get(parent_code), synthesized)

    items = list(by_code.values())
    items = [item for item in items if not is_retired_menu_code(item.menu_code)]
    # 2026-08-07 - 观察号会话剔除推广链接/品牌诊断
    from app.services.observer_account import OBSERVER_HIDDEN_MENU_CODES, observer_platforms_for_user_id

    if observer_platforms_for_user_id(db, identity.user_id) is not None:
        items = [item for item in items if item.menu_code not in OBSERVER_HIDDEN_MENU_CODES]
    # 2026-09-01 - 商品卡未开通企业侧栏不出现该菜单
    if identity.identity_type == "CUSTOMER" and identity.tenant_id:
        from app.models.tenant import Tenant

        tenant = db.scalar(select(Tenant).where(Tenant.id == identity.tenant_id, Tenant.deleted.is_(False)))
        if tenant is None or not bool(getattr(tenant, "goods_card_enabled", False)):
            items = [item for item in items if item.menu_code != "customer.goods_cards"]
    items.sort(key=lambda item: (item.sort_order, item.id))
    return items


def position_menu_grants(db: Session, position_id: int) -> list[MenuGrantItem]:
    return position_menu_grants_map(db, [position_id]).get(position_id, [])


def position_menu_grants_map(db: Session, position_ids: list[int]) -> dict[int, list[MenuGrantItem]]:
    if not position_ids:
        return {}
    rows = db.execute(
        select(PositionMenu, Menu)
        .join(Menu, Menu.id == PositionMenu.menu_id)
        .where(PositionMenu.position_id.in_(position_ids), Menu.deleted.is_(False))
        .order_by(Menu.sort_order.asc(), Menu.id.asc())
    ).all()
    grants_map: dict[int, list[MenuGrantItem]] = {position_id: [] for position_id in position_ids}
    for grant, menu in rows:
        if is_retired_menu_code(menu.menu_code):
            continue
        if not grant_has_access(
            can_create=grant.can_create,
            can_update=grant.can_update,
            can_delete=grant.can_delete,
            can_export=grant.can_export,
        ):
            continue
        grants_map.setdefault(grant.position_id, []).append(
            MenuGrantItem(
                menu_id=menu.id,
                menu_code=menu.menu_code,
                can_create=grant.can_create,
                can_update=grant.can_update,
                can_delete=grant.can_delete,
                can_export=grant.can_export,
            )
        )
    return grants_map


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
            if is_retired_menu_code(menu_code) or menu_code in ROUTE_ONLY_MENU_CODES:
                continue
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
    else:
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

    # 2026-08-11 - 保存职位后身份菜单被清空 - autoflush=False 下先 flush 再同步身份
    db.flush()


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
    # 2026-08-11 - 同会话读身份菜单可能空 - autoflush=False 下写完即 flush
    db.flush()


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


def _grant_signature_rows(rows) -> set[tuple[int, bool, bool, bool, bool]]:
    signature: set[tuple[int, bool, bool, bool, bool]] = set()
    for row in rows:
        if not grant_has_access(
            can_create=bool(row.can_create),
            can_update=bool(row.can_update),
            can_delete=bool(row.can_delete),
            can_export=bool(row.can_export),
        ):
            continue
        signature.add(
            (
                int(row.menu_id),
                bool(row.can_create),
                bool(row.can_update),
                bool(row.can_delete),
                bool(row.can_export),
            )
        )
    return signature


def identity_menus_match_position(db: Session, identity_id: int, position_id: int) -> bool:
    position_rows = db.scalars(select(PositionMenu).where(PositionMenu.position_id == position_id))
    identity_rows = db.scalars(select(UserIdentityMenu).where(UserIdentityMenu.identity_id == identity_id))
    return _grant_signature_rows(position_rows) == _grant_signature_rows(identity_rows)


def ensure_identity_menus_from_position(db: Session, identity: UserIdentity) -> bool:
    """已绑定职位时，身份菜单与职位模板不一致则从职位同步（登录/me 时自愈）。"""
    if identity.position_id is None:
        return False
    position_has_grant = db.scalar(
        select(PositionMenu.id).where(PositionMenu.position_id == identity.position_id).limit(1)
    )
    if position_has_grant is None:
        return False
    if identity_menus_match_position(db, identity.id, identity.position_id):
        return False
    replace_identity_menus_from_position(db, identity.id, identity.position_id)
    return True


def heal_empty_identity_menus(db: Session) -> int:
    """只补「身份菜单行为空、职位模板仍在」的记录，不覆盖已有个性化授权。

    登录 /me 会逐人自愈，但已清空的行在用户进门户前一直 403；保存职位才会全员同步。
    """
    identities = list(
        db.scalars(
            select(UserIdentity).where(
                UserIdentity.deleted.is_(False),
                UserIdentity.status.is_(True),
                UserIdentity.position_id.isnot(None),
            )
        )
    )
    healed = 0
    for identity in identities:
        has_menu = db.scalar(
            select(UserIdentityMenu.id).where(UserIdentityMenu.identity_id == identity.id).limit(1)
        )
        if has_menu is not None:
            continue
        # 2026-08-18 - 保存职位清空身份菜单后不会自愈 - 空表按职位模板补回，有授权的不动
        if ensure_identity_menus_from_position(db, identity):
            healed += 1
    return healed


def require_platform_menu_permission(
    db: Session,
    current,
    menu_code: str,
    action: str,
    *,
    detail: str | None = None,
) -> None:
    from app.api.dependencies import CurrentSession

    session: CurrentSession = current
    if session.identity.identity_type != "PLATFORM":
        raise PermissionError("仅平台运营端可访问")
    if not has_identity_menu_permission(db, session.identity.id, menu_code, action):
        raise PermissionError(detail or "当前身份无权执行此操作")


def has_settings_menu_permission(
    db: Session,
    identity_id: int,
    action: str = "can_export",
    *,
    category: str | None = None,
) -> bool:
    """系统配置：父菜单或对应分类子菜单任一命中即可。"""
    if has_identity_menu_permission(db, identity_id, "platform.settings", action):
        return True
    if category:
        menu_code = next(
            (code for code, cat in SETTINGS_CATEGORY_BY_MENU.items() if cat == category),
            None,
        )
        if menu_code and has_identity_menu_permission(db, identity_id, menu_code, action):
            return True
        return False
    return any(
        has_identity_menu_permission(db, identity_id, code, action)
        for code in SETTINGS_CHILD_MENU_CODES
    )


def accessible_settings_categories(
    db: Session,
    identity_id: int,
    action: str = "can_export",
) -> set[str] | None:
    """None = 拥有父菜单（全部分类）；空 set = 无权；其它 = 仅这些分类。"""
    if has_identity_menu_permission(db, identity_id, "platform.settings", action):
        return None
    return {
        cat
        for code, cat in SETTINGS_CATEGORY_BY_MENU.items()
        if has_identity_menu_permission(db, identity_id, code, action)
    }


def require_health_ops_access(db: Session, current) -> None:
    from app.api.dependencies import CurrentSession

    session: CurrentSession = current
    if session.identity.identity_type != "PLATFORM":
        raise PermissionError("仅平台运营端可访问")
    if not has_settings_menu_permission(db, session.identity.id, "can_export", category="cache_queue"):
        raise PermissionError("当前账号无权查看运维健康详情")


def require_knowledge_permission(db: Session, current, action: str) -> None:
    from app.api.dependencies import CurrentSession

    session: CurrentSession = current
    if session.identity.identity_type == "CUSTOMER":
        if not has_identity_menu_permission(db, session.identity.id, "customer.knowledge", action):
            raise PermissionError("无权操作企业知识库")
        return
    if action == "can_export":
        if not has_identity_menu_permission(db, session.identity.id, "platform.audit.files", "can_export"):
            raise PermissionError("无权查看企业知识库")
        return
    if action == "can_create":
        if not has_identity_menu_permission(db, session.identity.id, "platform.audit.files", "can_create"):
            raise PermissionError("无权上传企业知识库")
        return
    if not has_identity_menu_permission(db, session.identity.id, "platform.audit.files", "can_update"):
        raise PermissionError("无权维护企业知识库")


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


def sync_goods_card_menu_for_tenant(db: Session, tenant_id: int, *, enabled: bool) -> int:
    """开通商品卡时给该企业客户身份补「商品卡」查看权；关闭只靠企业开关过滤侧栏。

    2026-09-01 - 只开开关不授菜单会导致客户侧栏空白，开通时自动补 grant。
    2026-09-02 - 登录/me 会按职位模板覆盖身份菜单 - 职位模板也需补商品卡，否则 grant 被冲掉。
    """
    if not enabled:
        return 0
    menu = db.scalar(
        select(Menu).where(
            Menu.menu_code == "customer.goods_cards",
            Menu.deleted.is_(False),
            Menu.status.is_(True),
        )
    )
    if menu is None:
        return 0
    identities = list(
        db.scalars(
            select(UserIdentity).where(
                UserIdentity.tenant_id == tenant_id,
                UserIdentity.identity_type == "CUSTOMER",
                UserIdentity.deleted.is_(False),
            )
        )
    )
    added = 0
    position_ids = {identity.position_id for identity in identities if identity.position_id}
    for position_id in position_ids:
        exists = db.scalar(
            select(PositionMenu).where(
                PositionMenu.position_id == position_id,
                PositionMenu.menu_id == menu.id,
            )
        )
        if exists is None:
            db.add(
                PositionMenu(
                    position_id=position_id,
                    menu_id=menu.id,
                    can_create=False,
                    can_update=False,
                    can_delete=False,
                    can_export=True,
                )
            )
            added += 1
        elif not grant_has_access(
            can_create=exists.can_create,
            can_update=exists.can_update,
            can_delete=exists.can_delete,
            can_export=exists.can_export,
        ):
            exists.can_export = True
            added += 1
    for identity in identities:
        exists = db.scalar(
            select(UserIdentityMenu).where(
                UserIdentityMenu.identity_id == identity.id,
                UserIdentityMenu.menu_id == menu.id,
            )
        )
        if exists is None:
            db.add(
                UserIdentityMenu(
                    identity_id=identity.id,
                    menu_id=menu.id,
                    can_create=False,
                    can_update=False,
                    can_delete=False,
                    can_export=True,
                )
            )
            added += 1
        elif not grant_has_access(
            can_create=exists.can_create,
            can_update=exists.can_update,
            can_delete=exists.can_delete,
            can_export=exists.can_export,
        ):
            exists.can_export = True
            added += 1
    if added:
        db.flush()
    return added


def get_tenant_customer_preview_menus(db: Session, tenant_id: int) -> list[MenuInfo]:
    """平台预览客户侧栏：合并该企业客户身份菜单（含商品卡开关过滤）。"""
    from app.models.tenant import Tenant

    tenant = db.scalar(select(Tenant).where(Tenant.id == tenant_id, Tenant.deleted.is_(False)))
    if tenant is None:
        return []
    identities = list(
        db.scalars(
            select(UserIdentity).where(
                UserIdentity.tenant_id == tenant_id,
                UserIdentity.identity_type == "CUSTOMER",
                UserIdentity.deleted.is_(False),
            )
        )
    )
    merged: dict[str, MenuInfo] = {}
    for identity in identities:
        for item in get_identity_menus(db, identity):
            merged[item.menu_code] = merge_grant_flags(merged.get(item.menu_code), item)
    items = list(merged.values())
    items.sort(key=lambda item: (item.sort_order, item.id))
    return items

