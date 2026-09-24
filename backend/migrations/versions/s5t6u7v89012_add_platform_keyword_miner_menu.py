"""add platform keyword miner menu for ops workbench

Revision ID: s5t6u7v89012
Revises: r4s5t6u78901
Create Date: 2026-09-24 14:55:00.000000

本地先挂运营侧栏「GEO 选词」；页面内嵌独立 keyword-miner 服务。
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "s5t6u7v89012"
down_revision: Union[str, Sequence[str], None] = "r4s5t6u78901"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

MENU_CODE = "platform.keyword_miner"


def upgrade() -> None:
    conn = op.get_bind()

    conn.exec_driver_sql(
        f"""
        UPDATE sys_menu
        SET menu_name = 'GEO选词',
            identity_type = 'PLATFORM',
            route_path = '/platform/keyword-miner',
            icon = 'Sparkles',
            sort_order = 36,
            is_visible = 1,
            status = 1,
            deleted = 0
        WHERE menu_code = '{MENU_CODE}'
        """
    )

    conn.exec_driver_sql(
        f"""
        INSERT INTO sys_menu (
            menu_code, menu_name, identity_type, route_path, icon, sort_order, is_visible, status, deleted
        )
        SELECT '{MENU_CODE}', 'GEO选词', 'PLATFORM', '/platform/keyword-miner', 'Sparkles', 36, 1, 1, 0
        FROM DUAL
        WHERE NOT EXISTS (
            SELECT 1 FROM sys_menu WHERE menu_code = '{MENU_CODE}'
        )
        """
    )

    conn.exec_driver_sql(
        f"""
        INSERT INTO sys_menu_config (
            menu_code, menu_name, identity_type, sort_order, is_visible, icon, route_path, remark, deleted
        )
        SELECT
            '{MENU_CODE}', 'GEO选词', 'PLATFORM', 36, 1, 'Sparkles', '/platform/keyword-miner',
            '运营选词/拓词工作台(本地内嵌 keyword-miner)', 0
        FROM DUAL
        WHERE NOT EXISTS (
            SELECT 1 FROM sys_menu_config WHERE menu_code = '{MENU_CODE}' AND deleted = 0
        )
        """
    )

    conn.exec_driver_sql(
        f"""
        INSERT INTO sys_role_menu (role_id, menu_id)
        SELECT r.id, m.id
        FROM sys_role r
        JOIN sys_menu m ON m.menu_code = '{MENU_CODE}' AND m.deleted = 0
        WHERE r.identity_type = 'PLATFORM' AND r.deleted = 0
          AND NOT EXISTS (
              SELECT 1 FROM sys_role_menu rm
              WHERE rm.role_id = r.id AND rm.menu_id = m.id
          )
        """
    )

    # 职位 + 身份：本地职位码可能是 PLATFORM_POS_*，凡 PLATFORM* 职位都授权
    conn.exec_driver_sql(
        f"""
        INSERT INTO sys_position_menu (position_id, menu_id, can_create, can_update, can_delete, can_export)
        SELECT p.id, m.id, 1, 1, 0, 1
        FROM sys_position p
        JOIN sys_menu m ON m.menu_code = '{MENU_CODE}' AND m.deleted = 0
        WHERE p.deleted = 0 AND p.position_code LIKE 'PLATFORM%'
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
        SELECT ui.id, m.id, 1, 1, 0, 1
        FROM sys_user_identity ui
        JOIN sys_menu m ON m.menu_code = '{MENU_CODE}' AND m.deleted = 0
        WHERE ui.deleted = 0 AND ui.status = 1 AND ui.identity_type = 'PLATFORM'
          AND NOT EXISTS (
            SELECT 1 FROM sys_user_identity_menu uim
            WHERE uim.identity_id = ui.id AND uim.menu_id = m.id
          )
        """
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.exec_driver_sql(
        f"""
        DELETE uim FROM sys_user_identity_menu uim
        JOIN sys_menu m ON m.id = uim.menu_id
        WHERE m.menu_code = '{MENU_CODE}'
        """
    )
    conn.exec_driver_sql(
        f"""
        DELETE pm FROM sys_position_menu pm
        JOIN sys_menu m ON m.id = pm.menu_id
        WHERE m.menu_code = '{MENU_CODE}'
        """
    )
    conn.exec_driver_sql(
        f"""
        DELETE rm FROM sys_role_menu rm
        JOIN sys_menu m ON m.id = rm.menu_id
        WHERE m.menu_code = '{MENU_CODE}'
        """
    )
    conn.exec_driver_sql(f"DELETE FROM sys_menu_config WHERE menu_code = '{MENU_CODE}'")
    conn.exec_driver_sql(f"DELETE FROM sys_menu WHERE menu_code = '{MENU_CODE}'")
