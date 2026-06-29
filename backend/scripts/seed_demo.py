from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models.brand import BrandAsset, BrandCompetitor
from app.models.permission import Menu, Role, RoleMenu, UserIdentityMenu
from app.models.tenant import Tenant
from app.models.user import User
from app.models.user_identity import UserIdentity
from app.models.menu_config import MenuConfig

PLATFORM_MENUS = [
    ("platform.dashboard", "运营总览", "/platform/dashboard", "Gauge", 10, True),
    ("platform.audit", "企业管理", "/platform/audit", "ClipboardCheck", 20, True),
    ("platform.users", "用户管理", "/platform/users", "Users", 30, True),
    ("platform.users.create", "用户新增", "/platform/users/create", "Users", 31, True),
    ("platform.users.list", "用户列表", "/platform/users/list", "Users", 32, True),
    ("platform.users.create.platform", "新增平台运营端用户", "/platform/users/create/platform", "ShieldCheck", 311,
     False),
    ("platform.users.create.customer", "新增客户企业端用户", "/platform/users/create/customer", "Building2", 312,
     False),
    ("platform.diagnosis", "品牌诊断", "/platform/diagnosis", "ClipboardCheck", 39, True),
    ("platform.plans", "套餐额度", "/platform/plans", "SlidersHorizontal", 40, True),
    ("platform.admins", "管理员账号", "/platform/admins", "UserCog", 50, True),
    ("platform.models", "模型平台", "/platform/models", "Database", 60, True),
    ("platform.alerts", "预警阈值", "/platform/alerts", "BellRing", 70, True),
    ("platform.logs", "操作日志", "/platform/logs", "Activity", 80, True),
    ("platform.settings", "系统配置", "/platform/settings", "Settings", 90, True),
]

CUSTOMER_MENUS = [
    ("customer.workspace", "运营工作台", "/customer/workspace", "Gauge", 10, True),
    ("customer.realtime", "实时检测", "/customer/realtime", "Search", 30, True),
    ("customer.sentiment", "舆情监控", "/customer/sentiment", "BarChart3", 60, True),
    ("customer.links", "推广链接检测", "/customer/links", "Link2", 70, True),
    ("customer.diagnosis", "品牌诊断", "/customer/diagnosis", "ClipboardCheck", 80, True),
    ("customer.competitor", "竞品分析", "/customer/competitor", "BarChart3", 90, True),
    ("customer.sources", "信源分析", "/customer/sources", "Database", 100, True),
    ("customer.reports", "报告中心", "/customer/reports", "FileBarChart", 110, True),
    ("customer.knowledge", "企业知识库", "/customer/knowledge", "BookOpen", 120, True),
]


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
    else:
        user.display_name = display_name
        user.status = True
        user.deleted = False
    return user


def add_identity(db, *, user: User, code: str, identity_type: str, name: str, role: str, tenant: Tenant | None,
                 default: bool) -> None:
    identity = db.scalar(select(UserIdentity).where(UserIdentity.identity_code == code))
    if identity is None:
        identity = UserIdentity(identity_code=code, user_id=user.id, identity_type=identity_type)
        db.add(identity)
    identity.user_id = user.id
    identity.tenant_id = tenant.id if tenant else None
    identity.identity_name = name
    identity.role_code = role
    identity.is_default = default
    identity.status = True
    identity.deleted = False
    db.flush()


def upsert_role(db, *, code: str, name: str, identity_type: str, data_scope: str, description: str) -> Role:
    role = db.scalar(select(Role).where(Role.role_code == code))
    if role is None:
        role = Role(role_code=code, role_name=name, identity_type=identity_type, data_scope=data_scope,
                    description=description)
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


def upsert_menu(db, *, identity_type: str, item: tuple[str, str, str, str, int, bool]) -> Menu:
    code, name, path, icon, sort_order, is_visible = item
    menu = db.scalar(select(Menu).where(Menu.menu_code == code))
    if menu is None:
        menu = Menu(menu_code=code, menu_name=name, identity_type=identity_type, route_path=path, icon=icon,
                    sort_order=sort_order)
        db.add(menu)
    menu.menu_name = name
    menu.identity_type = identity_type
    menu.route_path = path
    menu.icon = icon
    menu.sort_order = sort_order
    menu.is_visible = is_visible
    menu.status = True
    menu.deleted = False
    db.flush()
    return menu


def bind_role_menus(db, role: Role, menus: list[Menu]) -> None:
    for menu in menus:
        exists = db.scalar(select(RoleMenu).where(RoleMenu.role_id == role.id, RoleMenu.menu_id == menu.id))
        if exists is None:
            db.add(RoleMenu(role_id=role.id, menu_id=menu.id))
    db.flush()


def grant_identity_menus(db, identity: UserIdentity, menus: list[Menu], *, writable: bool) -> None:
    for menu in menus:
        exists = db.scalar(select(UserIdentityMenu).where(UserIdentityMenu.identity_id == identity.id,
                                                          UserIdentityMenu.menu_id == menu.id))
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
    asset = db.scalar(select(BrandAsset).where(BrandAsset.tenant_id == tenant.id))
    if asset is None:
        asset = BrandAsset(
            tenant_id=tenant.id,
            company_full_name=tenant.name,
            brand_name="AIEO",
            brand_short_name="艾亿欧",
            monitor_keywords_json=[],
            aliases_json=[],
            product_keywords_json=[],
            monitored_platforms_json=[],
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
    asset.monitored_platforms_json = ["doubao_mobile", "deepseek_mobile", "yuanbao", "kimi", "baiduai"]
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


def seed_menu_configs(db) -> None:
    """初始化菜单配置"""
    menus_to_seed = [
        # PLATFORM 菜单
        ("platform.dashboard", "运营总览", "PLATFORM", 10, True, "Gauge", "/platform/dashboard", "平台运营数据概览"),
        ("platform.audit", "企业管理", "PLATFORM", 20, True, "ClipboardCheck", "/platform/audit", "客户企业信息维护"),
        ("platform.users", "用户管理", "PLATFORM", 30, True, "Users", "/platform/users", "账号和权限管理"),
        ("platform.users.create", "用户新增", "PLATFORM", 31, True, "Users", "/platform/users/create", "创建新用户"),
        ("platform.users.list", "用户列表", "PLATFORM", 32, True, "Users", "/platform/users/list", "查看用户列表"),
        ("platform.diagnosis", "品牌诊断", "PLATFORM", 39, True, "ClipboardCheck", "/platform/diagnosis",
         "AI 生成诊断报告"),
        ("platform.plans", "套餐额度", "PLATFORM", 40, True, "SlidersHorizontal", "/platform/plans", "套餐管理"),
        ("platform.admins", "管理员账号", "PLATFORM", 50, True, "UserCog", "/platform/admins", "管理员管理"),
        ("platform.models", "模型平台", "PLATFORM", 60, True, "Database", "/platform/models", "模型配置"),
        ("platform.alerts", "预警阈值", "PLATFORM", 70, True, "BellRing", "/platform/alerts", "告警设置"),
        ("platform.logs", "操作日志", "PLATFORM", 80, True, "Activity", "/platform/logs", "系统审计日志"),
        ("platform.settings", "系统配置", "PLATFORM", 90, True, "Settings", "/platform/settings", "平台参数配置"),

        # CUSTOMER 菜单
        ("customer.workspace", "运营工作台", "CUSTOMER", 10, True, "Gauge", "/customer/workspace", "企业监测数据看板"),
        ("customer.realtime", "实时检测", "CUSTOMER", 30, True, "Search", "/customer/realtime", "最新检测结果"),
        ("customer.sentiment", "舆情监控", "CUSTOMER", 60, True, "BarChart3", "/customer/sentiment", "舆情情感分布"),
        ("customer.links", "推广链接检测", "CUSTOMER", 70, True, "Link2", "/customer/links", "推广链接监测"),
        ("customer.diagnosis", "品牌诊断", "CUSTOMER", 80, True, "ClipboardCheck", "/customer/diagnosis",
         "AI 诊断建议"),
        ("customer.competitor", "竞品分析", "CUSTOMER", 90, True, "BarChart3", "/customer/competitor", "竞品排名对比"),
        ("customer.sources", "信源分析", "CUSTOMER", 100, True, "Database", "/customer/sources", "数据来源统计"),
        ("customer.reports", "报告中心", "CUSTOMER", 110, True, "FileBarChart", "/customer/reports", "检测报告查看"),
        ("customer.knowledge", "企业知识库", "CUSTOMER", 120, True, "BookOpen", "/customer/knowledge", "企业文档管理"),
    ]

    for menu_code, menu_name, identity_type, sort_order, is_visible, icon, route_path, remark in menus_to_seed:
        config = db.scalar(select(MenuConfig).where(MenuConfig.menu_code == menu_code))
        if config is None:
            config = MenuConfig(
                menu_code=menu_code,
                menu_name=menu_name,
                identity_type=identity_type,
                sort_order=sort_order,
                is_visible=is_visible,
                icon=icon,
                route_path=route_path,
                remark=remark,
            )
            db.add(config)
        else:
            config.menu_name = menu_name
            config.sort_order = sort_order
            config.is_visible = is_visible
            config.icon = icon
            config.route_path = route_path
            config.remark = remark

    print(f"✅ 已初始化 {len(menus_to_seed)} 项菜单配置")


def main() -> None:
    with SessionLocal() as db:
        tenant = get_or_create_tenant(db)

        platform_role = upsert_role(db, code="PLATFORM_ADMIN", name="平台运营管理员", identity_type="PLATFORM",
                                    data_scope="ALL", description="可管理全部企业、用户、套餐、模型和系统配置")
        platform_operator_role = upsert_role(db, code="PLATFORM_OPERATOR", name="平台运营专员",
                                             identity_type="PLATFORM", data_scope="SELF",
                                             description="只能查看和管理本人创建的用户与任务")
        tenant_role = upsert_role(db, code="TENANT_ADMIN", name="客户企业管理员", identity_type="CUSTOMER",
                                  data_scope="TENANT", description="客户企业端只读展示和报表查看")

        platform_menus = [upsert_menu(db, identity_type="PLATFORM", item=item) for item in PLATFORM_MENUS]
        customer_menus = [upsert_menu(db, identity_type="CUSTOMER", item=item) for item in CUSTOMER_MENUS]
        bind_role_menus(db, platform_role, platform_menus)
        bind_role_menus(db, platform_operator_role, [
            menu for menu in platform_menus
            if
            menu.menu_code in {"platform.dashboard", "platform.users", "platform.users.create", "platform.users.list",
                               "platform.users.create.customer", "platform.logs"}
        ])
        bind_role_menus(db, tenant_role, customer_menus)

        demo = get_or_create_user(db, "demo", "Geo@2026", "王明")
        add_identity(db, user=demo, code="DEMO_PLATFORM", identity_type="PLATFORM", name="平台运营管理员",
                     role="PLATFORM_ADMIN", tenant=None, default=True)
        add_identity(db, user=demo, code="DEMO_CUSTOMER", identity_type="CUSTOMER", name="AIEO 企业管理员",
                     role="TENANT_ADMIN", tenant=tenant, default=False)

        platform = get_or_create_user(db, "platform", "Admin@2026", "平台管理员")
        add_identity(db, user=platform, code="PLATFORM_ONLY", identity_type="PLATFORM", name="平台运营管理员",
                     role="PLATFORM_ADMIN", tenant=None, default=True)

        client = get_or_create_user(db, "client", "Client@2026", "企业管理员")
        add_identity(db, user=client, code="CUSTOMER_ONLY", identity_type="CUSTOMER", name="AIEO 企业管理员",
                     role="TENANT_ADMIN", tenant=tenant, default=True)

        for identity in db.scalars(
                select(UserIdentity).where(UserIdentity.identity_type == "PLATFORM", UserIdentity.deleted.is_(False))):
            grant_identity_menus(db, identity, platform_menus, writable=True)
        for identity in db.scalars(
                select(UserIdentity).where(UserIdentity.identity_type == "CUSTOMER", UserIdentity.deleted.is_(False))):
            grant_identity_menus(db, identity, customer_menus, writable=False)

        seed_brand_assets(db, tenant)

        seed_menu_configs(db)

        db.commit()
        print("Demo accounts seeded: demo, platform, client")


if __name__ == "__main__":
    main()
