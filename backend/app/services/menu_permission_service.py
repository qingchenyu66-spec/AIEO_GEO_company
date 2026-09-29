"""菜单动作权限——职位配置、身份会话与 API 鉴权共用。"""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.menu_config import MenuConfig
from app.models.permission import CustomerPositionMenu, Menu, PositionMenu, UserIdentityMenu
from app.models.tenant import Tenant
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
    # 2026-09-09 - 企业配置子 Tab 推导父级，侧栏才露出「企业配置」
    "customer.enterprise_monitor": "customer.enterprise_config",
    "customer.enterprise_members": "customer.enterprise_config",
    "customer.enterprise_credit": "customer.enterprise_config",
    "customer.enterprise_audit": "customer.enterprise_config",
    "platform.keyword_miner.workbench": "platform.keyword_miner",
    "platform.keyword_miner.examples": "platform.keyword_miner",
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
    # 与前端 menuPermissionMatrix 对齐; 缺省会只剩 can_export, 职位一保存就洗掉写权限
    "platform.keyword_miner": frozenset({"can_export", "can_update", "can_create"}),
    "platform.keyword_miner.workbench": frozenset({"can_export", "can_update", "can_create"}),
    "platform.keyword_miner.examples": frozenset({"can_export", "can_update", "can_create", "can_delete"}),
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
    "platform.credit_ops_board": frozenset({"can_export", "can_update"}),
    "platform.tenant_credit": frozenset({"can_export", "can_update"}),
    "platform.tenant_credit_blocks": frozenset({"can_export"}),
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
        show_in_sidebar=current.show_in_sidebar,
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
        show_in_sidebar=base.show_in_sidebar,
    )


def _menu_display(menu: Menu, config: MenuConfig | None) -> MenuInfo:
    show_in_sidebar = True
    if config is not None and hasattr(config, "show_in_sidebar"):
        show_in_sidebar = bool(config.show_in_sidebar)
    return MenuInfo(
        id=menu.id,
        menu_code=menu.menu_code,
        menu_name=(config.menu_name if config and config.menu_name else menu.menu_name),
        identity_type=menu.identity_type,
        route_path=(config.route_path if config and config.route_path else menu.route_path),
        icon=(config.icon if config and config.icon else menu.icon),
        sort_order=(config.sort_order if config is not None else menu.sort_order),
        show_in_sidebar=show_in_sidebar,
    )


def sync_menu_row_from_config(db: Session, config: MenuConfig) -> Menu | None:
    """菜单配置是唯一展示口径：改配置时回写 sys_menu，避免两套名称漂移。"""
    menu = db.scalar(
        select(Menu).where(
            Menu.menu_code == config.menu_code,
            Menu.identity_type == config.identity_type,
            Menu.deleted.is_(False),
        )
    )
    if menu is None:
        return None
    if config.menu_name:
        menu.menu_name = config.menu_name
    menu.sort_order = int(config.sort_order or 0)
    if config.icon:
        menu.icon = config.icon
    if config.route_path:
        menu.route_path = config.route_path
    return menu


def sync_all_menus_from_configs(db: Session) -> int:
    """把全部未删除的 MenuConfig 回写到对应 sys_menu。"""
    updated = 0
    rows = list(db.scalars(select(MenuConfig).where(MenuConfig.deleted.is_(False))))
    for config in rows:
        if sync_menu_row_from_config(db, config) is not None:
            updated += 1
    return updated


def _is_enterprise_config_child_menu(menu_code: str) -> bool:
    return menu_code.startswith("customer.enterprise_") and menu_code != "customer.enterprise_config"


# 产品能力：不写职位/身份授权表，由企业开通 + 客户职位动态给
PRODUCT_CAPABILITY_MENU_CODES = frozenset({
    "customer.goods_cards",
    "customer.enterprise_config",
    "customer.enterprise_monitor",
    "customer.enterprise_members",
    "customer.enterprise_credit",
    "customer.enterprise_audit",
})


def is_product_capability_menu_code(menu_code: str) -> bool:
    return menu_code in PRODUCT_CAPABILITY_MENU_CODES


# 侧栏不单独露出、但会话里必须保留的页内权限（Tab / 按钮），与 MenuConfig.is_visible=0 不冲突
_SESSION_KEEP_WHEN_CONFIG_HIDDEN = frozenset({
    *SETTINGS_CHILD_MENU_CODES,
    "platform.audit.purge",
    "platform.credit_ops_board",
    "platform.tenant_credit",
    "platform.tenant_credit_blocks",
})


def _keep_in_session_despite_config_hidden(menu_code: str) -> bool:
    """页内权限项：配置里停用侧栏入口，不等于从会话权限里抹掉。"""
    if _is_enterprise_config_child_menu(menu_code):
        return True
    return menu_code in _SESSION_KEEP_WHEN_CONFIG_HIDDEN


def _filter_items_by_menu_config_visibility(
    db: Session,
    items: list[MenuInfo],
    identity_type: str,
) -> list[MenuInfo]:
    """MenuConfig.is_visible=false 表示功能关闭，不进会话。

    页内权限项（系统配置子项等）功能仍开、仅侧栏隐藏时靠 show_in_sidebar=0，
    旧数据 is_visible=0 仍用 keep 名单保住会话。
    """
    if not items:
        return items
    configs = {
        row.menu_code: row
        for row in db.scalars(
            select(MenuConfig).where(
                MenuConfig.identity_type == identity_type,
                MenuConfig.deleted.is_(False),
            )
        )
    }
    out: list[MenuInfo] = []
    for item in items:
        if _keep_in_session_despite_config_hidden(item.menu_code):
            out.append(item)
            continue
        cfg = configs.get(item.menu_code)
        if cfg is not None and not bool(cfg.is_visible):
            continue
        out.append(item)
    return out


def has_identity_menu_permission(
    db: Session,
    identity_id: int,
    menu_code: str,
    action: str = "can_create",
) -> bool:
    # 2026-09-09 - 方案甲：企业配置权限不读身份落库，按 credit + 客户职位动态判定
    if _is_enterprise_config_menu_code(menu_code):
        return _has_derived_enterprise_menu_permission(db, identity_id, menu_code, action)
    # 2026-09-14 - 商品卡：企业开通开关管有没有，不读职位勾选
    if menu_code == "customer.goods_cards":
        return _has_goods_card_product_permission(db, identity_id, action)
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


def _has_goods_card_product_permission(db: Session, identity_id: int, action: str) -> bool:
    """商品卡是企业产品能力：开通即客户身份可查看，不靠职位矩阵勾选。"""
    allowed = _allowed_actions_for_menu("customer.goods_cards", "CUSTOMER")
    if action not in allowed:
        return False
    identity = db.get(UserIdentity, identity_id)
    if identity is None or identity.identity_type != "CUSTOMER" or not identity.tenant_id:
        return False
    tenant = db.get(Tenant, int(identity.tenant_id))
    return bool(tenant and not bool(getattr(tenant, "deleted", False)) and getattr(tenant, "goods_card_enabled", False))


def _is_enterprise_config_menu_code(menu_code: str) -> bool:
    return menu_code == "customer.enterprise_config" or menu_code.startswith("customer.enterprise_")


def _has_derived_enterprise_menu_permission(
    db: Session,
    identity_id: int,
    menu_code: str,
    action: str,
) -> bool:
    identity = db.get(UserIdentity, identity_id)
    if identity is None:
        return False
    from app.services.billing_mode_service import resolve_enterprise_menu_grants_for_identity

    grants = resolve_enterprise_menu_grants_for_identity(db, identity)
    if not grants:
        return False
    if menu_code == "customer.enterprise_config":
        # 父级：任一子项具备对应动作（读用 export）即视为可进企业配置
        if action == "can_export":
            return any(
                bool(flags.get("can_export") or flags.get("can_update") or flags.get("can_create"))
                for flags in grants.values()
            )
        return any(bool(flags.get(action)) for flags in grants.values())
    flags = grants.get(menu_code)
    return bool(flags and flags.get(action))


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


def catalog_listed_platform_codes(db: Session) -> list[str]:
    """目录仍上架的平台 code（空白名单=不限制时用）。"""
    from app.models.platform import GeoPlatform

    rows = db.scalars(
        select(GeoPlatform).where(
            GeoPlatform.deleted.is_(False),
            GeoPlatform.catalog_listed.is_(True),
        )
    ).all()
    return normalize_allowed_monitor_platforms([row.platform_code for row in rows])


def identity_allowed_monitor_platforms(db: Session, identity: UserIdentity) -> list[str]:
    """会话用：直接读职位平台白名单（按职位不同）；无职位则空。"""
    # 2026-08-07 - 艾迪亚观察号写死平台白名单 - 优先于职位 JSON，避免空职位漏约束
    from app.services.observer_account import observer_platforms_for_user_id

    forced = observer_platforms_for_user_id(db, identity.user_id)
    if forced is not None:
        return normalize_allowed_monitor_platforms(list(forced))

    # 2026-09-04 - 算力自助：会话平台 = 目录上架全部（不设白名单限额）
    # 2026-09-07 - 方案 A：忽略历史 platform_whitelist_json，避免暗开关继续限平台
    if str(getattr(identity, "identity_type", "") or "").upper() == "CUSTOMER" and identity.tenant_id:
        tenant = db.get(Tenant, int(identity.tenant_id))
        if tenant is not None and (getattr(tenant, "billing_mode", None) or "hosted") == "credit":
            return catalog_listed_platform_codes(db)

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
        # 2026-09-09 - 方案甲：落库里的 enterprise_* 忽略，改由 credit 动态合并
        if _is_enterprise_config_menu_code(menu.menu_code):
            continue
        base = _menu_display(menu, config)
        item = _menu_with_grant(
            base,
            can_create=bool(grant.can_create),
            can_update=bool(grant.can_update),
            can_delete=bool(grant.can_delete),
            can_export=bool(grant.can_export),
        )
        by_code[item.menu_code] = merge_grant_flags(by_code.get(item.menu_code), item)

    _merge_derived_enterprise_menus(db, identity, by_code)

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
    items = _filter_items_by_menu_config_visibility(db, items, identity.identity_type)
    # 2026-08-07 - 观察号会话剔除推广链接/品牌诊断
    from app.services.observer_account import OBSERVER_HIDDEN_MENU_CODES, observer_platforms_for_user_id

    if observer_platforms_for_user_id(db, identity.user_id) is not None:
        items = [item for item in items if item.menu_code not in OBSERVER_HIDDEN_MENU_CODES]
    # 2026-09-14 - 商品卡：企业开通才注入会话，职位勾选不再决定有没有
    items = _apply_goods_card_product_gate(db, identity, items)
    items.sort(key=lambda item: (item.sort_order, item.id))
    return items


def _apply_goods_card_product_gate(
    db: Session,
    identity: UserIdentity,
    items: list[MenuInfo],
) -> list[MenuInfo]:
    """先去掉落库里的商品卡，再按企业开通开关注入查看权。"""
    rows = [item for item in items if item.menu_code != "customer.goods_cards"]
    if identity.identity_type != "CUSTOMER" or not identity.tenant_id:
        return rows
    tenant = db.scalar(select(Tenant).where(Tenant.id == identity.tenant_id, Tenant.deleted.is_(False)))
    if tenant is None or not bool(getattr(tenant, "goods_card_enabled", False)):
        return rows
    menu_row = db.execute(
        select(Menu, MenuConfig)
        .outerjoin(
            MenuConfig,
            (MenuConfig.menu_code == Menu.menu_code)
            & (MenuConfig.identity_type == Menu.identity_type)
            & (MenuConfig.deleted.is_(False)),
        )
        .where(
            Menu.menu_code == "customer.goods_cards",
            Menu.identity_type == "CUSTOMER",
            Menu.status.is_(True),
            Menu.deleted.is_(False),
        )
    ).first()
    if menu_row is None:
        return rows
    menu, config = menu_row
    if config is not None and not bool(config.is_visible):
        return rows
    base = _menu_display(menu, config)
    rows.append(
        _menu_with_grant(
            base,
            can_create=False,
            can_update=False,
            can_delete=False,
            can_export=True,
        )
    )
    return rows


def _merge_derived_enterprise_menus(
    db: Session,
    identity: UserIdentity,
    by_code: dict[str, MenuInfo],
) -> None:
    """credit 客户：按客户职位把企业配置子菜单并入会话菜单（再由 ROUTE_PARENT 推父级）。"""
    from app.services.billing_mode_service import resolve_enterprise_menu_grants_for_identity

    grants = resolve_enterprise_menu_grants_for_identity(db, identity)
    if not grants:
        return
    menu_rows = db.execute(
        select(Menu, MenuConfig)
        .outerjoin(
            MenuConfig,
            (MenuConfig.menu_code == Menu.menu_code)
            & (MenuConfig.identity_type == Menu.identity_type)
            & (MenuConfig.deleted.is_(False)),
        )
        .where(
            Menu.menu_code.in_(list(grants.keys())),
            Menu.identity_type == "CUSTOMER",
            Menu.status.is_(True),
            Menu.deleted.is_(False),
        )
    ).all()
    for menu, config in menu_rows:
        flags = grants.get(menu.menu_code) or {}
        if not grant_has_access(
            can_create=bool(flags.get("can_create")),
            can_update=bool(flags.get("can_update")),
            can_delete=bool(flags.get("can_delete")),
            can_export=bool(flags.get("can_export")),
        ):
            continue
        base = _menu_display(menu, config)
        item = _menu_with_grant(
            base,
            can_create=bool(flags.get("can_create")),
            can_update=bool(flags.get("can_update")),
            can_delete=bool(flags.get("can_delete")),
            can_export=bool(flags.get("can_export")),
        )
        by_code[item.menu_code] = merge_grant_flags(by_code.get(item.menu_code), item)


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
            if is_product_capability_menu_code(menu_code):
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


def _product_capability_menu_ids(db: Session) -> set[int]:
    return set(
        db.scalars(
            select(Menu.id).where(
                Menu.menu_code.in_(tuple(PRODUCT_CAPABILITY_MENU_CODES)),
                Menu.deleted.is_(False),
            )
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
    skip_ids = _product_capability_menu_ids(db)
    db.query(UserIdentityMenu).filter(UserIdentityMenu.identity_id == identity_id).delete(synchronize_session=False)
    for row in rows:
        if row.menu_id in skip_ids:
            selected_set.discard(row.menu_id)
            continue
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
        if menu_id in skip_ids:
            continue
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


def _grant_signature_rows(rows, *, skip_product: bool = False) -> set[tuple[int, bool, bool, bool, bool]]:
    signature: set[tuple[int, bool, bool, bool, bool]] = set()
    for row in rows:
        if skip_product:
            menu_code = getattr(row, "menu_code", None)
            if menu_code and is_product_capability_menu_code(str(menu_code)):
                continue
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
    skip_ids = _product_capability_menu_ids(db)
    position_rows = [
        row
        for row in db.scalars(select(PositionMenu).where(PositionMenu.position_id == position_id))
        if row.menu_id not in skip_ids
    ]
    identity_rows = [
        row
        for row in db.scalars(select(UserIdentityMenu).where(UserIdentityMenu.identity_id == identity_id))
        if row.menu_id not in skip_ids
    ]
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



_CUSTOMER_PORTAL_MENU_CODES = (
    "customer.workspace",
    "customer.brand_analysis",
    "customer.realtime",
    "customer.competitor",
    "customer.sources",
    "customer.reports",
    "customer.knowledge",
)


def _derive_route_parent_menus(db: Session, by_code: dict[str, MenuInfo], identity_type: str) -> None:
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
                Menu.identity_type == identity_type,
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
            synthesized = _menu_with_grant(
                parent_base, can_create=False, can_update=False, can_delete=False, can_export=False
            )
            synthesized = merge_grant_flags(synthesized, item)
            by_code[parent_code] = merge_grant_flags(by_code.get(parent_code), synthesized)


def _filter_customer_menus_for_tenant(db: Session, items: list[MenuInfo], tenant) -> list[MenuInfo]:
    rows = [item for item in items if not is_retired_menu_code(item.menu_code)]
    if (tenant.billing_mode or "hosted") != "credit":
        rows = [item for item in rows if not item.menu_code.startswith("customer.enterprise")]
    # 2026-09-14 - 商品卡只看企业开通，不看职位勾选
    rows = [item for item in rows if item.menu_code != "customer.goods_cards"]
    if bool(getattr(tenant, "goods_card_enabled", False)):
        menu_row = db.execute(
            select(Menu, MenuConfig)
            .outerjoin(
                MenuConfig,
                (MenuConfig.menu_code == Menu.menu_code)
                & (MenuConfig.identity_type == Menu.identity_type)
                & (MenuConfig.deleted.is_(False)),
            )
            .where(
                Menu.menu_code == "customer.goods_cards",
                Menu.identity_type == "CUSTOMER",
                Menu.status.is_(True),
                Menu.deleted.is_(False),
            )
        ).first()
        if menu_row is not None:
            menu, config = menu_row
            if config is None or bool(config.is_visible):
                base = _menu_display(menu, config)
                rows.append(
                    _menu_with_grant(
                        base,
                        can_create=False,
                        can_update=False,
                        can_delete=False,
                        can_export=True,
                    )
                )
    rows.sort(key=lambda item: (item.sort_order, item.id))
    return rows


def _customer_menus_from_admin_position(db: Session, tenant) -> list[MenuInfo]:
    """无客户账号时，用 enterprise_admin 职位模板推导可见菜单。"""
    from app.models.permission import CustomerPosition, CustomerPositionMenu

    position = db.scalar(
        select(CustomerPosition).where(
            CustomerPosition.tenant_id.is_(None),
            CustomerPosition.position_code == "enterprise_admin",
            CustomerPosition.deleted.is_(False),
        )
    )
    if position is None:
        return []
    granted_menu_ids: set[int] = set()
    by_code: dict[str, MenuInfo] = {}
    rows = db.execute(
        select(CustomerPositionMenu, Menu, MenuConfig)
        .join(Menu, Menu.id == CustomerPositionMenu.menu_id)
        .outerjoin(
            MenuConfig,
            (MenuConfig.menu_code == Menu.menu_code)
            & (MenuConfig.identity_type == Menu.identity_type)
            & (MenuConfig.deleted.is_(False)),
        )
        .where(
            CustomerPositionMenu.position_id == position.id,
            Menu.identity_type == "CUSTOMER",
            Menu.deleted.is_(False),
            Menu.status.is_(True),
        )
    ).all()
    for grant, menu, config in rows:
        granted_menu_ids.add(menu.id)
        if not grant_has_access(
            can_create=bool(grant.can_create),
            can_update=bool(grant.can_update),
            can_delete=bool(grant.can_delete),
            can_export=bool(grant.can_export),
        ):
            continue
        if config is not None and not bool(config.is_visible) and not _keep_in_session_despite_config_hidden(menu.menu_code):
            continue
        base = _menu_display(menu, config)
        item = _menu_with_grant(
            base,
            can_create=bool(grant.can_create),
            can_update=bool(grant.can_update),
            can_delete=bool(grant.can_delete),
            can_export=bool(grant.can_export),
        )
        by_code[item.menu_code] = merge_grant_flags(by_code.get(item.menu_code), item)
    hole_rows = db.execute(
        select(Menu, MenuConfig)
        .outerjoin(
            MenuConfig,
            (MenuConfig.menu_code == Menu.menu_code)
            & (MenuConfig.identity_type == Menu.identity_type)
            & (MenuConfig.deleted.is_(False)),
        )
        .where(
            Menu.identity_type == "CUSTOMER",
            Menu.menu_code.in_(_CUSTOMER_PORTAL_MENU_CODES),
            Menu.deleted.is_(False),
            Menu.status.is_(True),
        )
    ).all()
    for menu, config in hole_rows:
        if menu.id in granted_menu_ids or menu.menu_code in by_code:
            continue
        # 有配置且停用：不补进侧栏
        if config is not None and not bool(config.is_visible):
            continue
        base = _menu_display(menu, config)
        if menu.menu_code == "customer.knowledge":
            # 2026-09-09 - 补洞只给查看，不抬上传/编辑；写权限须来自职位模板
            flags = {"can_create": False, "can_update": False, "can_delete": False, "can_export": True}
        elif menu.menu_code == "customer.enterprise_config":
            flags = {"can_create": False, "can_update": False, "can_delete": False, "can_export": True}
        else:
            flags = {"can_create": False, "can_update": False, "can_delete": False, "can_export": True}
        item = _menu_with_grant(base, **flags)
        by_code[item.menu_code] = merge_grant_flags(by_code.get(item.menu_code), item)
    _derive_route_parent_menus(db, by_code, "CUSTOMER")
    filtered = _filter_items_by_menu_config_visibility(db, list(by_code.values()), "CUSTOMER")
    return _filter_customer_menus_for_tenant(db, filtered, tenant)


def get_tenant_customer_preview_menus(db: Session, tenant_id: int) -> list[MenuInfo]:
    # 2026-08-27 - 客户门户预览跟真实客户权限走，合并企业下全部客户身份可见菜单
    from app.models.tenant import Tenant
    from app.models.user_identity import UserIdentity

    tenant = db.scalar(select(Tenant).where(Tenant.id == tenant_id, Tenant.deleted.is_(False)))
    if tenant is None:
        raise ValueError("企业不存在")
    identities = list(
        db.scalars(
            select(UserIdentity).where(
                UserIdentity.tenant_id == tenant_id,
                UserIdentity.identity_type == "CUSTOMER",
                UserIdentity.deleted.is_(False),
                UserIdentity.status.is_(True),
            )
        )
    )
    merged: dict[str, MenuInfo] = {}
    if identities:
        for identity in identities:
            for item in get_identity_menus(db, identity):
                merged[item.menu_code] = merge_grant_flags(merged.get(item.menu_code), item)
        return _filter_customer_menus_for_tenant(db, list(merged.values()), tenant)
    return _customer_menus_from_admin_position(db, tenant)


def sync_goods_card_menu_for_tenant(db: Session, tenant_id: int, *, enabled: bool) -> int:
    """开通商品卡时的兼容补丁。

    2026-09-14 - 会话已按企业开通开关注入商品卡，不再依赖职位勾选；
    此函数保留为空操作计数，避免调用方改动，旧 grant 可继续留着不影响。
    """
    del db, tenant_id  # 兼容签名；会话注入不再写职位/身份 grant
    if not enabled:
        return 0
    return 0

