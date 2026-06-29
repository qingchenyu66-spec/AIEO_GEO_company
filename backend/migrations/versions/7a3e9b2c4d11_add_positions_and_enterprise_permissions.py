"""add positions and enterprise permission menus

Revision ID: 7a3e9b2c4d11
Revises: 2c9d7f1a4b80
Create Date: 2026-06-26 16:30:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "7a3e9b2c4d11"
down_revision = "2c9d7f1a4b80"
branch_labels = None
depends_on = None


PLATFORM_ENTERPRISE_MENUS = [
    ("platform.audit.list", "企业列表", "/platform/audit/list", "ClipboardCheck", 21),
    ("platform.audit.profile", "企业资料", "/platform/audit/profile", "ClipboardCheck", 22),
    ("platform.audit.keywords", "监测词配置", "/platform/audit/keywords", "Search", 23),
    ("platform.audit.models", "平台范围配置", "/platform/audit/models", "Database", 24),
    ("platform.audit.schedule", "监控计划配置", "/platform/audit/schedule", "SlidersHorizontal", 25),
    ("platform.audit.competitors", "竞品配置", "/platform/audit/competitors", "BarChart3", 26),
    ("platform.audit.files", "上传文件查看", "/platform/audit/files", "BookOpen", 27),
]

POSITIONS = [
    ("PLATFORM_ADMIN", "平台管理员", "PLATFORM", "PLATFORM_ADMIN", "全部平台运营权限", 10),
    ("PLATFORM_OPERATION", "运营", "PLATFORM", "PLATFORM_OPERATOR", "维护企业资料、监测词、计划和报告", 20),
    ("PLATFORM_SALES", "销售", "PLATFORM", "PLATFORM_OPERATOR", "查看企业、服务期和客户基础资料", 30),
    ("PLATFORM_DELIVERY", "交付", "PLATFORM", "PLATFORM_OPERATOR", "配置监测范围、任务计划和竞品资料", 40),
    ("CUSTOMER_ADMIN", "客户管理员", "CUSTOMER", "TENANT_ADMIN", "客户侧查看报告、监测结果并上传文件", 10),
]


def upgrade() -> None:
    op.create_table(
        "sys_position",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="职位ID"),
        sa.Column("position_code", sa.String(length=50), nullable=False, comment="职位编码"),
        sa.Column("position_name", sa.String(length=80), nullable=False, comment="职位名称"),
        sa.Column("identity_type", sa.String(length=20), nullable=False, comment="适用身份：PLATFORM/CUSTOMER"),
        sa.Column("role_code", sa.String(length=50), nullable=False, comment="默认角色编码"),
        sa.Column("description", sa.String(length=255), nullable=True, comment="职位说明"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0", comment="排序"),
        sa.Column("status", sa.Boolean(), nullable=False, server_default=sa.text("1"), comment="是否启用"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False, comment="更新时间"),
        sa.Column("deleted", sa.Boolean(), nullable=False, server_default=sa.text("0"), comment="逻辑删除"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("position_code", name="uk_sys_position_code"),
    )
    op.create_index("ix_sys_position_identity_type", "sys_position", ["identity_type"], unique=False)
    op.create_index("ix_sys_position_deleted", "sys_position", ["deleted"], unique=False)

    op.create_table(
        "sys_position_menu",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="职位菜单ID"),
        sa.Column("position_id", sa.Integer(), nullable=False, comment="职位ID"),
        sa.Column("menu_id", sa.Integer(), nullable=False, comment="菜单ID"),
        sa.Column("can_create", sa.Boolean(), nullable=False, server_default=sa.text("0"), comment="是否允许新建"),
        sa.Column("can_update", sa.Boolean(), nullable=False, server_default=sa.text("0"), comment="是否允许编辑"),
        sa.Column("can_delete", sa.Boolean(), nullable=False, server_default=sa.text("0"), comment="是否允许删除或停用"),
        sa.Column("can_export", sa.Boolean(), nullable=False, server_default=sa.text("1"), comment="是否允许导出"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False, comment="创建时间"),
        sa.ForeignKeyConstraint(["menu_id"], ["sys_menu.id"]),
        sa.ForeignKeyConstraint(["position_id"], ["sys_position.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("position_id", "menu_id", name="uk_sys_position_menu"),
    )
    op.create_index("ix_sys_position_menu_position_id", "sys_position_menu", ["position_id"], unique=False)
    op.create_index("ix_sys_position_menu_menu_id", "sys_position_menu", ["menu_id"], unique=False)

    op.add_column("sys_user_identity", sa.Column("position_id", sa.Integer(), nullable=True, comment="职位ID"))
    op.create_index("ix_sys_user_identity_position_id", "sys_user_identity", ["position_id"], unique=False)
    op.create_foreign_key("fk_sys_user_identity_position_id", "sys_user_identity", "sys_position", ["position_id"], ["id"])

    bind = op.get_bind()
    for code, name, path, icon, sort_order in PLATFORM_ENTERPRISE_MENUS:
        bind.execute(
            sa.text(
                """
                insert into sys_menu (menu_code, menu_name, identity_type, parent_id, route_path, icon, sort_order, is_visible, status, deleted)
                values (:code, :name, 'PLATFORM', null, :path, :icon, :sort_order, 0, 1, 0)
                on duplicate key update menu_name=values(menu_name), route_path=values(route_path), icon=values(icon),
                sort_order=values(sort_order), is_visible=0, status=1, deleted=0
                """
            ),
            {"code": code, "name": name, "path": path, "icon": icon, "sort_order": sort_order},
        )

    for code, name, identity_type, role_code, description, sort_order in POSITIONS:
        bind.execute(
            sa.text(
                """
                insert into sys_position (position_code, position_name, identity_type, role_code, description, sort_order, status, deleted)
                values (:code, :name, :identity_type, :role_code, :description, :sort_order, 1, 0)
                on duplicate key update position_name=values(position_name), identity_type=values(identity_type),
                role_code=values(role_code), description=values(description), sort_order=values(sort_order), status=1, deleted=0
                """
            ),
            {
                "code": code,
                "name": name,
                "identity_type": identity_type,
                "role_code": role_code,
                "description": description,
                "sort_order": sort_order,
            },
        )

    platform_menu_ids = bind.execute(sa.text("select id, menu_code from sys_menu where identity_type='PLATFORM' and deleted=0")).mappings().all()
    customer_menu_ids = bind.execute(sa.text("select id, menu_code from sys_menu where identity_type='CUSTOMER' and deleted=0")).mappings().all()
    menu_map = {row["menu_code"]: row["id"] for row in [*platform_menu_ids, *customer_menu_ids]}
    position_rows = bind.execute(sa.text("select id, position_code from sys_position where deleted=0")).mappings().all()
    position_map = {row["position_code"]: row["id"] for row in position_rows}

    grants = {
        "PLATFORM_ADMIN": [
            code for code in menu_map.keys()
            if code not in {"platform.sentiment", "platform.competitor", "platform.sources", "platform.reports"}
        ],
        "PLATFORM_OPERATION": [
            "platform.dashboard", "platform.audit", "platform.audit.list", "platform.audit.profile",
            "platform.audit.keywords", "platform.audit.models", "platform.audit.schedule",
            "platform.audit.competitors", "platform.audit.files", "platform.diagnosis",
            "platform.logs",
        ],
        "PLATFORM_SALES": [
            "platform.dashboard", "platform.audit", "platform.audit.list", "platform.audit.profile",
        ],
        "PLATFORM_DELIVERY": [
            "platform.dashboard", "platform.audit", "platform.audit.list", "platform.audit.keywords",
            "platform.audit.models", "platform.audit.schedule", "platform.audit.competitors",
            "platform.logs",
        ],
        "CUSTOMER_ADMIN": [code for code in menu_map if code.startswith("customer.")],
    }
    for position_code, codes in grants.items():
        position_id = position_map.get(position_code)
        if not position_id:
            continue
        for menu_code in codes:
            menu_id = menu_map.get(menu_code)
            if not menu_id:
                continue
            writable = position_code == "PLATFORM_ADMIN" or (
                position_code == "PLATFORM_OPERATION" and menu_code.startswith("platform.audit")
            ) or (
                position_code == "PLATFORM_DELIVERY" and menu_code in {
                    "platform.audit.keywords",
                    "platform.audit.models",
                    "platform.audit.schedule",
                    "platform.audit.competitors",
                }
            )
            bind.execute(
                sa.text(
                    """
                    insert ignore into sys_position_menu
                    (position_id, menu_id, can_create, can_update, can_delete, can_export)
                    values (:position_id, :menu_id, :can_create, :can_update, :can_delete, 1)
                    """
                ),
                {
                    "position_id": position_id,
                    "menu_id": menu_id,
                    "can_create": writable,
                    "can_update": writable,
                    "can_delete": writable,
                },
            )


def downgrade() -> None:
    op.drop_constraint("fk_sys_user_identity_position_id", "sys_user_identity", type_="foreignkey")
    op.drop_index("ix_sys_user_identity_position_id", table_name="sys_user_identity")
    op.drop_column("sys_user_identity", "position_id")
    op.drop_index("ix_sys_position_menu_menu_id", table_name="sys_position_menu")
    op.drop_index("ix_sys_position_menu_position_id", table_name="sys_position_menu")
    op.drop_table("sys_position_menu")
    op.drop_index("ix_sys_position_deleted", table_name="sys_position")
    op.drop_index("ix_sys_position_identity_type", table_name="sys_position")
    op.drop_table("sys_position")
