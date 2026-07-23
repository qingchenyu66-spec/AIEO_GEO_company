"""add announcements tables and platform menu

Revision ID: e9f0a1b2c345
Revises: d8e9f0a1235
Create Date: 2026-07-23 10:40:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e9f0a1b2c345"
down_revision: Union[str, Sequence[str], None] = "d8e9f0a1235"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

WRITER_POSITIONS = ("PLATFORM_ADMIN", "PLATFORM_OPERATION")


def upgrade() -> None:
    op.create_table(
        "geo_announcement",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False, comment="标题"),
        sa.Column("body_html", sa.Text(), nullable=False, comment="富文本 HTML"),
        sa.Column("targets_json", sa.JSON(), nullable=False, comment="受众目标列表"),
        sa.Column("tenant_ids_json", sa.JSON(), nullable=True, comment="指定企业 ID 列表"),
        sa.Column("status", sa.String(length=20), nullable=False, comment="draft/scheduled/published/off"),
        sa.Column("publish_at", sa.DateTime(), nullable=True, comment="计划/实际上线时间"),
        sa.Column("expire_at", sa.DateTime(), nullable=True, comment="失效时间"),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("sys_user.id"), nullable=True),
        sa.Column("updated_by_user_id", sa.Integer(), sa.ForeignKey("sys_user.id"), nullable=True),
        sa.Column("deleted", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_geo_announcement_status", "geo_announcement", ["status"])
    op.create_index("ix_geo_announcement_publish_at", "geo_announcement", ["publish_at"])
    op.create_index("ix_geo_announcement_expire_at", "geo_announcement", ["expire_at"])
    op.create_index("ix_geo_announcement_deleted", "geo_announcement", ["deleted"])

    op.create_table(
        "geo_announcement_ack",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("sys_user.id"), nullable=False),
        sa.Column("announcement_id", sa.Integer(), sa.ForeignKey("geo_announcement.id"), nullable=False),
        sa.Column("acked_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "announcement_id", name="uq_geo_announcement_ack"),
    )
    op.create_index("ix_geo_announcement_ack_user_id", "geo_announcement_ack", ["user_id"])
    op.create_index("ix_geo_announcement_ack_announcement_id", "geo_announcement_ack", ["announcement_id"])

    op.create_table(
        "geo_announcement_media",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("uploader_user_id", sa.Integer(), sa.ForeignKey("sys_user.id"), nullable=True),
        sa.Column("original_name", sa.String(length=255), nullable=False),
        sa.Column("stored_name", sa.String(length=64), nullable=False),
        sa.Column("file_ext", sa.String(length=20), nullable=False),
        sa.Column("content_type", sa.String(length=120), nullable=True),
        sa.Column("file_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("storage_path", sa.String(length=500), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False, server_default="file"),
        sa.Column("deleted", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    conn = op.get_bind()
    conn.exec_driver_sql(
        """
        INSERT INTO sys_menu (
            menu_code, menu_name, identity_type, route_path, icon, sort_order, is_visible, status, deleted
        )
        SELECT 'platform.announcements', '系统公告', 'PLATFORM', '/platform/announcements', 'Megaphone', 36, 1, 1, 0
        FROM DUAL
        WHERE NOT EXISTS (
            SELECT 1 FROM sys_menu WHERE menu_code = 'platform.announcements' AND deleted = 0
        )
        """
    )
    conn.exec_driver_sql(
        """
        INSERT INTO sys_menu_config (
            menu_code, menu_name, identity_type, sort_order, is_visible, icon, route_path, remark, deleted
        )
        SELECT
            'platform.announcements', '系统公告', 'PLATFORM', 36, 1, 'Megaphone', '/platform/announcements',
            '编辑并发布公告到运营端/客户端', 0
        FROM DUAL
        WHERE NOT EXISTS (
            SELECT 1 FROM sys_menu_config WHERE menu_code = 'platform.announcements' AND deleted = 0
        )
        """
    )
    positions_sql = ", ".join(f"'{code}'" for code in WRITER_POSITIONS)
    conn.exec_driver_sql(
        f"""
        INSERT INTO sys_position_menu (position_id, menu_id, can_create, can_update, can_delete, can_export)
        SELECT p.id, m.id, 1, 1, 1, 1
        FROM sys_position p
        JOIN sys_menu m ON m.menu_code = 'platform.announcements' AND m.deleted = 0
        WHERE p.deleted = 0 AND p.identity_type = 'PLATFORM'
          AND p.position_code IN ({positions_sql})
          AND NOT EXISTS (
              SELECT 1 FROM sys_position_menu pm
              WHERE pm.position_id = p.id AND pm.menu_id = m.id
          )
        """
    )
    conn.exec_driver_sql(
        f"""
        INSERT INTO sys_user_identity_menu (
            identity_id, menu_id, can_create, can_update, can_delete, can_export
        )
        SELECT ui.id, m.id, 1, 1, 1, 1
        FROM sys_user_identity ui
        JOIN sys_position p ON p.id = ui.position_id AND p.deleted = 0
        JOIN sys_menu m ON m.menu_code = 'platform.announcements' AND m.deleted = 0
        WHERE ui.deleted = 0
          AND p.position_code IN ({positions_sql})
          AND NOT EXISTS (
              SELECT 1 FROM sys_user_identity_menu uim
              WHERE uim.identity_id = ui.id AND uim.menu_id = m.id
          )
        """
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.exec_driver_sql(
        """
        DELETE uim FROM sys_user_identity_menu uim
        JOIN sys_menu m ON m.id = uim.menu_id
        WHERE m.menu_code = 'platform.announcements'
        """
    )
    conn.exec_driver_sql(
        """
        DELETE pm FROM sys_position_menu pm
        JOIN sys_menu m ON m.id = pm.menu_id
        WHERE m.menu_code = 'platform.announcements'
        """
    )
    conn.exec_driver_sql("DELETE FROM sys_menu_config WHERE menu_code = 'platform.announcements'")
    conn.exec_driver_sql("DELETE FROM sys_menu WHERE menu_code = 'platform.announcements'")
    op.drop_table("geo_announcement_media")
    op.drop_table("geo_announcement_ack")
    op.drop_table("geo_announcement")
