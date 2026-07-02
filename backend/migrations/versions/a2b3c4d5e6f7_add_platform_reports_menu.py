"""add platform reports menu and grant report generate permission

Revision ID: a2b3c4d5e6f7
Revises: f1a2b3c4d5e6
Create Date: 2026-07-01 14:10:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = "a2b3c4d5e6f7"
down_revision: Union[str, Sequence[str], None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    conn.exec_driver_sql(
        """
        UPDATE sys_menu
        SET menu_name = '报告中心',
            identity_type = 'PLATFORM',
            route_path = '/platform/reports',
            icon = 'FileBarChart',
            sort_order = 38,
            is_visible = 1,
            status = 1,
            deleted = 0
        WHERE menu_code = 'platform.reports'
        """
    )

    conn.exec_driver_sql(
        """
        INSERT INTO sys_menu (
            menu_code, menu_name, identity_type, route_path, icon, sort_order, is_visible, status, deleted
        )
        SELECT 'platform.reports', '报告中心', 'PLATFORM', '/platform/reports', 'FileBarChart', 38, 1, 1, 0
        FROM DUAL
        WHERE NOT EXISTS (
            SELECT 1 FROM sys_menu WHERE menu_code = 'platform.reports'
        )
        """
    )

    conn.exec_driver_sql(
        """
        INSERT INTO sys_menu_config (
            menu_code, menu_name, identity_type, sort_order, is_visible, icon, route_path, remark, deleted
        )
        SELECT
            'platform.reports', '报告中心', 'PLATFORM', 38, 1, 'FileBarChart', '/platform/reports',
            '运营端生成、预览并导出客户报告', 0
        FROM DUAL
        WHERE NOT EXISTS (
            SELECT 1 FROM sys_menu_config WHERE menu_code = 'platform.reports' AND deleted = 0
        )
        """
    )

    conn.exec_driver_sql(
        """
        INSERT INTO sys_role_menu (role_id, menu_id)
        SELECT r.id, m.id
        FROM sys_role r
        JOIN sys_menu m ON m.menu_code = 'platform.reports' AND m.deleted = 0
        WHERE r.identity_type = 'PLATFORM' AND r.deleted = 0
          AND NOT EXISTS (
              SELECT 1 FROM sys_role_menu rm
              WHERE rm.role_id = r.id AND rm.menu_id = m.id
          )
        """
    )

    conn.exec_driver_sql(
        """
        INSERT INTO sys_user_identity_menu (
            identity_id, menu_id, can_create, can_update, can_delete, can_export
        )
        SELECT ui.id, m.id, 1, 1, 0, 1
        FROM sys_user_identity ui
        JOIN sys_menu m ON m.menu_code = 'platform.reports' AND m.deleted = 0
        WHERE ui.identity_type = 'PLATFORM' AND ui.deleted = 0
          AND NOT EXISTS (
              SELECT 1 FROM sys_user_identity_menu uim
              WHERE uim.identity_id = ui.id AND uim.menu_id = m.id
          )
        """
    )

    conn.exec_driver_sql(
        """
        UPDATE sys_user_identity_menu uim
        JOIN sys_menu m ON m.id = uim.menu_id
        JOIN sys_user_identity ui ON ui.id = uim.identity_id
        SET uim.can_create = 1, uim.can_update = 1
        WHERE m.menu_code = 'customer.reports'
          AND m.deleted = 0
          AND ui.identity_type = 'CUSTOMER'
          AND ui.deleted = 0
        """
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.exec_driver_sql(
        """
        DELETE uim FROM sys_user_identity_menu uim
        JOIN sys_menu m ON m.id = uim.menu_id
        WHERE m.menu_code = 'platform.reports'
        """
    )
    conn.exec_driver_sql(
        """
        DELETE rm FROM sys_role_menu rm
        JOIN sys_menu m ON m.id = rm.menu_id
        WHERE m.menu_code = 'platform.reports'
        """
    )
    conn.exec_driver_sql("DELETE FROM sys_menu_config WHERE menu_code = 'platform.reports'")
    conn.exec_driver_sql("DELETE FROM sys_menu WHERE menu_code = 'platform.reports'")
