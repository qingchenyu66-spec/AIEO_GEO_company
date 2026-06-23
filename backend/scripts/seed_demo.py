from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models.brand import BrandAsset, BrandCompetitor
from app.models.permission import Menu, Role, RoleMenu, UserIdentityMenu
from app.models.tenant import Tenant
from app.models.user import User
from app.models.user_identity import UserIdentity


def get_or_create_tenant(db) -> Tenant:
    tenant = db.scalar(select(Tenant).where(Tenant.code == "AIEO_DEMO"))
    if tenant is None:
        tenant = Tenant(name="北京艾亿欧科技有限公司", code="AIEO_DEMO")
        db.add(tenant)
        db.flush()
    return tenant


def get_or_create_user(db, username: str, password: str, display_name: str) -> User:
    user = db.scalar(select(User).where(User.username == username))
    if user is None:
        user = User(username=username, password_hash=hash_password(password), display_name=display_name)
        db.add(user)
        db.flush()
    return user


def add_identity(db, *, user: User, code: str, identity_type: str, name: str, role: str, tenant: Tenant | None, default: bool) -> None:
    exists = db.scalar(select(UserIdentity).where(UserIdentity.identity_code == code))
    if exists is None:
        db.add(UserIdentity(
            identity_code=code,
            user_id=user.id,
            tenant_id=tenant.id if tenant else None,
            identity_type=identity_type,
            identity_name=name,
            role_code=role,
            is_default=default,
        ))
        db.flush()


PLATFORM_MENUS = [
    ("platform.dashboard", "运营总览", "/platform/dashboard", "Gauge", 10),
    ("platform.audit", "企业管理", "/platform/audit", "ClipboardCheck", 20),
    ("platform.users", "用户管理", "/platform/users", "Users", 30),
    ("platform.users.create", "用户新增", "/platform/users/create", "Users", 31),
    ("platform.users.list", "用户列表", "/platform/users/list", "Users", 32),
    ("platform.plans", "套餐额度", "/platform/plans", "SlidersHorizontal", 40),
    ("platform.admins", "管理员账号", "/platform/admins", "UserCog", 50),
    ("platform.models", "模型平台", "/platform/models", "Database", 60),
    ("platform.alerts", "预警阈值", "/platform/alerts", "BellRing", 70),
    ("platform.logs", "操作日志", "/platform/logs", "Activity", 80),
    ("platform.settings", "系统配置", "/platform/settings", "Settings", 90),
]

CUSTOMER_MENUS = [
    ("customer.workspace", "运营工作台", "/customer/workspace", "Gauge", 10),
    ("customer.realtime", "实时检测", "/customer/realtime", "Search", 30),
    ("customer.batch", "批量监控", "/customer/batch", "Layers3", 40),
    ("customer.geo", "GEO监测", "/customer/geo", "Activity", 50),
    ("customer.sentiment", "舆情监控", "/customer/sentiment", "BarChart3", 60),
    ("customer.links", "推广链接检测", "/customer/links", "Link2", 70),
    ("customer.diagnosis", "品牌诊断", "/customer/diagnosis", "ClipboardCheck", 80),
    ("customer.competitor", "竞品分析", "/customer/competitor", "BarChart3", 90),
    ("customer.sources", "引用来源", "/customer/sources", "Database", 100),
    ("customer.reports", "报告中心", "/customer/reports", "FileBarChart", 110),
    ("customer.knowledge", "企业知识库", "/customer/knowledge", "BookOpen", 120),
]


def upsert_role(db, *, code: str, name: str, identity_type: str, data_scope: str, description: str) -> Role:
    """创建或更新角色，保证演示环境可以重复执行种子脚本。"""
    role = db.scalar(select(Role).where(Role.role_code == code))
    if role is None:
        role = Role(role_code=code, role_name=name, identity_type=identity_type, data_scope=data_scope, description=description)
        db.add(role)
    else:
        role.role_name = name
        role.identity_type = identity_type
        role.data_scope = data_scope
        role.description = description
        role.status = True
        role.deleted = False
    db.flush()
    return role


def upsert_menu(db, *, identity_type: str, item: tuple[str, str, str, str, int]) -> Menu:
    """创建或更新菜单，菜单必须入库后才能做权限分配。"""
    code, name, path, icon, sort_order = item
    menu = db.scalar(select(Menu).where(Menu.menu_code == code))
    if menu is None:
        menu = Menu(menu_code=code, menu_name=name, identity_type=identity_type, route_path=path, icon=icon, sort_order=sort_order)
        db.add(menu)
    else:
        menu.menu_name = name
        menu.identity_type = identity_type
        menu.route_path = path
        menu.icon = icon
        menu.sort_order = sort_order
        menu.is_visible = True
        menu.status = True
        menu.deleted = False
    db.flush()
    return menu


def bind_role_menus(db, role: Role, menus: list[Menu]) -> None:
    """绑定角色默认菜单，新增用户未单独选择菜单时会继承这组权限。"""
    for menu in menus:
        exists = db.scalar(select(RoleMenu).where(RoleMenu.role_id == role.id, RoleMenu.menu_id == menu.id))
        if exists is None:
            db.add(RoleMenu(role_id=role.id, menu_id=menu.id))
    db.flush()


def grant_identity_menus(db, identity: UserIdentity, menus: list[Menu], *, writable: bool) -> None:
    """给已有演示身份补齐菜单权限。"""
    for menu in menus:
        exists = db.scalar(select(UserIdentityMenu).where(UserIdentityMenu.identity_id == identity.id, UserIdentityMenu.menu_id == menu.id))
        if exists is None:
            db.add(UserIdentityMenu(
                identity_id=identity.id,
                menu_id=menu.id,
                can_create=writable,
                can_update=writable,
                can_delete=writable,
                can_export=True,
            ))
    db.flush()


def seed_brand_assets(db, tenant: Tenant) -> None:
    """为演示企业初始化品牌资产和竞品库；可重复执行。"""
    asset = db.scalar(select(BrandAsset).where(BrandAsset.tenant_id == tenant.id, BrandAsset.deleted.is_(False)))
    if asset is None:
        asset = BrandAsset(
            tenant_id=tenant.id,
            company_full_name=tenant.name,
            brand_name="AIEO",
            brand_short_name="艾亿欧",
            monitor_keywords_json=[],
            aliases_json=[],
            product_keywords_json=[],
            schedule_times_json=[],
            schedule_weekdays_json=[],
            schedule_month_days_json=[],
        )
        db.add(asset)
    asset.company_full_name = tenant.name
    asset.brand_name = "AIEO"
    asset.brand_short_name = "艾亿欧"
    asset.monitor_keywords_json = ["AIEO", "艾亿欧", "GEO优化", "AI平台推广监测"]
    asset.aliases_json = ["北京艾亿欧科技有限公司", "艾亿欧科技"]
    asset.product_keywords_json = ["品牌诊断", "实时检测", "报告交付", "竞品分析"]
    asset.official_url = "https://www.aieo.cn"
    asset.description = "演示企业品牌资产，用于自动提交 GEO 检测任务。"
    asset.schedule_type = "daily_times"
    asset.schedule_times_json = ["09:30", "14:30", "20:30"]
    asset.schedule_frequency = 3
    asset.schedule_weekdays_json = []
    asset.schedule_month_days_json = []
    asset.status = True
    asset.deleted = False

    for name, short_name in [("模力指数", "模力"), ("新榜", "新榜"), ("秒针系统", "秒针"), ("智推时代", "智推")]:
        exists = db.scalar(
            select(BrandCompetitor).where(
                BrandCompetitor.tenant_id == tenant.id,
                BrandCompetitor.name == name,
                BrandCompetitor.deleted.is_(False),
            )
        )
        if exists is None:
            db.add(BrandCompetitor(
                tenant_id=tenant.id,
                name=name,
                short_name=short_name,
                aliases_json=[short_name],
                category="直接竞品",
            ))
    db.flush()


def main() -> None:
    with SessionLocal() as db:
        tenant = get_or_create_tenant(db)

        platform_role = upsert_role(db, code="PLATFORM_ADMIN", name="平台运营管理员", identity_type="PLATFORM", data_scope="ALL", description="可管理全部企业、用户、套餐、模型和系统配置")
        platform_operator_role = upsert_role(db, code="PLATFORM_OPERATOR", name="平台运营专员", identity_type="PLATFORM", data_scope="SELF", description="只能查看和管理本人创建的用户与任务")
        tenant_role = upsert_role(db, code="TENANT_ADMIN", name="客户企业管理员", identity_type="CUSTOMER", data_scope="TENANT", description="客户企业端只读展示和报表查看")

        platform_menus = [upsert_menu(db, identity_type="PLATFORM", item=item) for item in PLATFORM_MENUS]
        customer_menus = [upsert_menu(db, identity_type="CUSTOMER", item=item) for item in CUSTOMER_MENUS]
        bind_role_menus(db, platform_role, platform_menus)
        bind_role_menus(db, platform_operator_role, [menu for menu in platform_menus if menu.menu_code in {"platform.dashboard", "platform.users", "platform.users.create", "platform.users.list", "platform.logs"}])
        bind_role_menus(db, tenant_role, customer_menus)

        demo = get_or_create_user(db, "demo", "Geo@2026", "王明")
        add_identity(db, user=demo, code="DEMO_PLATFORM", identity_type="PLATFORM", name="平台运营管理员", role="PLATFORM_ADMIN", tenant=None, default=True)
        add_identity(db, user=demo, code="DEMO_CUSTOMER", identity_type="CUSTOMER", name="AIEO 企业管理员", role="TENANT_ADMIN", tenant=tenant, default=False)

        platform = get_or_create_user(db, "platform", "Admin@2026", "平台管理员")
        add_identity(db, user=platform, code="PLATFORM_ONLY", identity_type="PLATFORM", name="平台运营管理员", role="PLATFORM_ADMIN", tenant=None, default=True)

        client = get_or_create_user(db, "client", "Client@2026", "企业管理员")
        add_identity(db, user=client, code="CUSTOMER_ONLY", identity_type="CUSTOMER", name="AIEO 企业管理员", role="TENANT_ADMIN", tenant=tenant, default=True)

        for identity in db.scalars(select(UserIdentity).where(UserIdentity.identity_type == "PLATFORM", UserIdentity.deleted.is_(False))):
            grant_identity_menus(db, identity, platform_menus, writable=True)
        for identity in db.scalars(select(UserIdentity).where(UserIdentity.identity_type == "CUSTOMER", UserIdentity.deleted.is_(False))):
            grant_identity_menus(db, identity, customer_menus, writable=False)

        seed_brand_assets(db, tenant)

        db.commit()
        print("Demo accounts seeded: demo, platform, client")


if __name__ == "__main__":
    main()
