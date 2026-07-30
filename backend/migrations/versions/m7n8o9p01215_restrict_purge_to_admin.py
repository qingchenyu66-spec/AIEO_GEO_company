"""restrict platform.audit.purge grants to PLATFORM_ADMIN only

Revision ID: m7n8o9p01215
Revises: l6m7n8o90114
Create Date: 2026-07-30
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "m7n8o9p01215"
down_revision: Union[str, Sequence[str], None] = "l6m7n8o90114"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PURGE = "platform.audit.purge"
ADMIN_POSITION = "PLATFORM_ADMIN"


def upgrade() -> None:
    conn = op.get_bind()
    # 2026-07-30 - 彻底删除仅管理员 - 收回非 PLATFORM_ADMIN 的职位/身份授权
    conn.exec_driver_sql(
        f"""
        DELETE pm FROM sys_position_menu pm
        JOIN sys_menu m ON m.id = pm.menu_id AND m.menu_code = '{PURGE}'
        JOIN sys_position p ON p.id = pm.position_id
        WHERE p.position_code <> '{ADMIN_POSITION}' OR p.deleted = 1
        """
    )
    conn.exec_driver_sql(
        f"""
        DELETE uim FROM sys_user_identity_menu uim
        JOIN sys_menu m ON m.id = uim.menu_id AND m.menu_code = '{PURGE}'
        JOIN sys_user_identity ui ON ui.id = uim.identity_id
        LEFT JOIN sys_position p ON p.id = ui.position_id AND p.deleted = 0
        WHERE p.id IS NULL OR p.position_code <> '{ADMIN_POSITION}'
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
        UPDATE sys_position_menu pm
        JOIN sys_position p ON p.id = pm.position_id AND p.position_code = '{ADMIN_POSITION}'
        JOIN sys_menu m ON m.id = pm.menu_id AND m.menu_code = '{PURGE}'
        SET pm.can_delete = 1, pm.can_create = 0, pm.can_update = 0, pm.can_export = 0
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
    conn.exec_driver_sql(
        f"""
        UPDATE sys_user_identity_menu uim
        JOIN sys_user_identity ui ON ui.id = uim.identity_id
        JOIN sys_position p ON p.id = ui.position_id AND p.position_code = '{ADMIN_POSITION}'
        JOIN sys_menu m ON m.id = uim.menu_id AND m.menu_code = '{PURGE}'
        SET uim.can_delete = 1, uim.can_create = 0, uim.can_update = 0, uim.can_export = 0
        """
    )
    conn.exec_driver_sql(
        f"""
        UPDATE sys_menu_config
        SET remark = '仅平台管理员；备份后清除监测历史与客户账号'
        WHERE menu_code = '{PURGE}' AND deleted = 0
        """
    )


def downgrade() -> None:
    # 不回放「有停服权即授权」；downgrade 仅保留菜单与管理员授权
    pass
