"""add platform.audit.purge for thorough tenant delete permission

Revision ID: l6m7n8o90114
Revises: k5l6m7n89013
Create Date: 2026-07-30

与「停止服务」拆开；默认仅授予 PLATFORM_ADMIN（平台管理员）。
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "l6m7n8o90114"
down_revision: Union[str, Sequence[str], None] = "k5l6m7n89013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PURGE = "platform.audit.purge"
ADMIN_POSITION = "PLATFORM_ADMIN"


def upgrade() -> None:
    conn = op.get_bind()
    # 2026-07-30 - 彻底删除企业权限与停服拆分；仅平台管理员
    conn.exec_driver_sql(
        f"""
        INSERT INTO sys_menu (
            menu_code, menu_name, identity_type, route_path, icon, sort_order, is_visible, status, deleted
        )
        SELECT '{PURGE}', '彻底删除企业', 'PLATFORM', '/platform/audit/purge', 'Trash2', 222, 0, 1, 0
        FROM DUAL
        WHERE NOT EXISTS (
            SELECT 1 FROM sys_menu WHERE menu_code = '{PURGE}' AND deleted = 0
        )
        """
    )
    conn.exec_driver_sql(
        f"""
        INSERT INTO sys_menu_config (
            menu_code, menu_name, identity_type, sort_order, is_visible, icon, route_path, remark, deleted
        )
        SELECT
            '{PURGE}', '彻底删除企业', 'PLATFORM', 222, 0, 'Trash2', '/platform/audit/purge',
            '仅平台管理员；备份后清除监测历史与客户账号', 0
        FROM DUAL
        WHERE NOT EXISTS (
            SELECT 1 FROM sys_menu_config WHERE menu_code = '{PURGE}' AND deleted = 0
        )
        """
    )
    conn.exec_driver_sql(
        f"""
        INSERT INTO sys_position_menu (
            position_id, menu_id, can_create, can_update, can_delete, can_export
        )
        SELECT p.id, tm.id, 0, 0, 1, 0
        FROM sys_position p
        JOIN sys_menu tm ON tm.menu_code = '{PURGE}' AND tm.deleted = 0
        WHERE p.deleted = 0
          AND p.position_code = '{ADMIN_POSITION}'
          AND NOT EXISTS (
            SELECT 1 FROM sys_position_menu x
            WHERE x.position_id = p.id AND x.menu_id = tm.id
          )
        """
    )
    conn.exec_driver_sql(
        f"""
        INSERT INTO sys_user_identity_menu (
            identity_id, menu_id, can_create, can_update, can_delete, can_export
        )
        SELECT ui.id, tm.id, 0, 0, 1, 0
        FROM sys_user_identity ui
        JOIN sys_position p ON p.id = ui.position_id AND p.deleted = 0 AND p.position_code = '{ADMIN_POSITION}'
        JOIN sys_menu tm ON tm.menu_code = '{PURGE}' AND tm.deleted = 0
        WHERE ui.deleted = 0
          AND NOT EXISTS (
            SELECT 1 FROM sys_user_identity_menu x
            WHERE x.identity_id = ui.id AND x.menu_id = tm.id
          )
        """
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.exec_driver_sql(
        f"""
        DELETE uim FROM sys_user_identity_menu uim
        JOIN sys_menu m ON m.id = uim.menu_id
        WHERE m.menu_code = '{PURGE}'
        """
    )
    conn.exec_driver_sql(
        f"""
        DELETE pm FROM sys_position_menu pm
        JOIN sys_menu m ON m.id = pm.menu_id
        WHERE m.menu_code = '{PURGE}'
        """
    )
    conn.exec_driver_sql(f"UPDATE sys_menu SET deleted = 1, is_visible = 0 WHERE menu_code = '{PURGE}'")
    conn.exec_driver_sql(f"UPDATE sys_menu_config SET deleted = 1, is_visible = 0 WHERE menu_code = '{PURGE}'")
