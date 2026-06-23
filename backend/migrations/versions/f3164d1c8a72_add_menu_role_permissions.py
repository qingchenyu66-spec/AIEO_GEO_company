"""add menu role permissions

Revision ID: f3164d1c8a72
Revises: c87e82bf1dcb
Create Date: 2026-06-22 13:52:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f3164d1c8a72"
down_revision: Union[str, Sequence[str], None] = "c87e82bf1dcb"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建菜单、角色、角色菜单、身份菜单权限表。"""
    op.create_table(
        "sys_menu",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="菜单主键ID"),
        sa.Column("menu_code", sa.String(length=80), nullable=False, comment="菜单唯一编码"),
        sa.Column("menu_name", sa.String(length=80), nullable=False, comment="菜单显示名称"),
        sa.Column("identity_type", sa.String(length=20), nullable=False, comment="适用身份类型：PLATFORM平台端，CUSTOMER客户端"),
        sa.Column("parent_id", sa.Integer(), nullable=True, comment="父级菜单ID，一级菜单为空"),
        sa.Column("route_path", sa.String(length=120), nullable=False, comment="前端路由或页面锚点"),
        sa.Column("icon", sa.String(length=50), nullable=False, comment="前端图标标识"),
        sa.Column("sort_order", sa.Integer(), nullable=False, comment="排序值，越小越靠前"),
        sa.Column("is_visible", sa.Boolean(), nullable=False, comment="是否在左侧菜单展示"),
        sa.Column("status", sa.Boolean(), nullable=False, comment="是否启用"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False, comment="更新时间"),
        sa.Column("deleted", sa.Boolean(), nullable=False, comment="逻辑删除"),
        sa.ForeignKeyConstraint(["parent_id"], ["sys_menu.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("menu_code", name="uk_sys_menu_code"),
        comment="系统菜单资源表",
    )
    op.create_index(op.f("ix_sys_menu_deleted"), "sys_menu", ["deleted"], unique=False)
    op.create_index(op.f("ix_sys_menu_identity_type"), "sys_menu", ["identity_type"], unique=False)
    op.create_index(op.f("ix_sys_menu_parent_id"), "sys_menu", ["parent_id"], unique=False)

    op.create_table(
        "sys_role",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="角色主键ID"),
        sa.Column("role_code", sa.String(length=50), nullable=False, comment="角色唯一编码"),
        sa.Column("role_name", sa.String(length=80), nullable=False, comment="角色显示名称"),
        sa.Column("identity_type", sa.String(length=20), nullable=False, comment="适用身份类型：PLATFORM平台端，CUSTOMER客户端"),
        sa.Column("data_scope", sa.String(length=20), nullable=False, comment="数据范围：ALL全部，TENANT本企业，SELF本人创建"),
        sa.Column("description", sa.String(length=255), nullable=True, comment="角色说明"),
        sa.Column("status", sa.Boolean(), nullable=False, comment="是否启用"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False, comment="更新时间"),
        sa.Column("deleted", sa.Boolean(), nullable=False, comment="逻辑删除"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("role_code", name="uk_sys_role_code"),
        comment="系统角色表",
    )
    op.create_index(op.f("ix_sys_role_deleted"), "sys_role", ["deleted"], unique=False)
    op.create_index(op.f("ix_sys_role_identity_type"), "sys_role", ["identity_type"], unique=False)

    op.create_table(
        "sys_role_menu",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="角色菜单主键ID"),
        sa.Column("role_id", sa.Integer(), nullable=False, comment="角色ID"),
        sa.Column("menu_id", sa.Integer(), nullable=False, comment="菜单ID"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False, comment="创建时间"),
        sa.ForeignKeyConstraint(["menu_id"], ["sys_menu.id"]),
        sa.ForeignKeyConstraint(["role_id"], ["sys_role.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("role_id", "menu_id", name="uk_sys_role_menu"),
        comment="角色菜单授权表",
    )
    op.create_index(op.f("ix_sys_role_menu_menu_id"), "sys_role_menu", ["menu_id"], unique=False)
    op.create_index(op.f("ix_sys_role_menu_role_id"), "sys_role_menu", ["role_id"], unique=False)

    op.create_table(
        "sys_user_identity_menu",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="身份菜单主键ID"),
        sa.Column("identity_id", sa.Integer(), nullable=False, comment="用户身份ID"),
        sa.Column("menu_id", sa.Integer(), nullable=False, comment="菜单ID"),
        sa.Column("can_create", sa.Boolean(), nullable=False, comment="是否允许新建"),
        sa.Column("can_update", sa.Boolean(), nullable=False, comment="是否允许编辑"),
        sa.Column("can_delete", sa.Boolean(), nullable=False, comment="是否允许删除或禁用"),
        sa.Column("can_export", sa.Boolean(), nullable=False, comment="是否允许导出"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False, comment="创建时间"),
        sa.ForeignKeyConstraint(["identity_id"], ["sys_user_identity.id"]),
        sa.ForeignKeyConstraint(["menu_id"], ["sys_menu.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("identity_id", "menu_id", name="uk_sys_identity_menu"),
        comment="用户身份菜单权限表",
    )
    op.create_index(op.f("ix_sys_user_identity_menu_identity_id"), "sys_user_identity_menu", ["identity_id"], unique=False)
    op.create_index(op.f("ix_sys_user_identity_menu_menu_id"), "sys_user_identity_menu", ["menu_id"], unique=False)


def downgrade() -> None:
    """回滚菜单权限相关表。"""
    op.drop_index(op.f("ix_sys_user_identity_menu_menu_id"), table_name="sys_user_identity_menu")
    op.drop_index(op.f("ix_sys_user_identity_menu_identity_id"), table_name="sys_user_identity_menu")
    op.drop_table("sys_user_identity_menu")
    op.drop_index(op.f("ix_sys_role_menu_role_id"), table_name="sys_role_menu")
    op.drop_index(op.f("ix_sys_role_menu_menu_id"), table_name="sys_role_menu")
    op.drop_table("sys_role_menu")
    op.drop_index(op.f("ix_sys_role_identity_type"), table_name="sys_role")
    op.drop_index(op.f("ix_sys_role_deleted"), table_name="sys_role")
    op.drop_table("sys_role")
    op.drop_index(op.f("ix_sys_menu_parent_id"), table_name="sys_menu")
    op.drop_index(op.f("ix_sys_menu_identity_type"), table_name="sys_menu")
    op.drop_index(op.f("ix_sys_menu_deleted"), table_name="sys_menu")
    op.drop_table("sys_menu")
