"""add customer.brand_analysis menu for position permission config

Revision ID: z4a5b6c890
Revises: y3z4a5b789
Create Date: 2026-07-20 09:40:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = "z4a5b6c890"
down_revision: Union[str, Sequence[str], None] = "y3z4a5b789"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

MENU_CODE = "customer.brand_analysis"


def upgrade() -> None:
    conn = op.get_bind()

    conn.exec_driver_sql(
        f"""
        INSERT INTO sys_menu (
            menu_code, menu_name, identity_type, route_path, icon, sort_order, is_visible, status, deleted
        )
        SELECT '{MENU_CODE}', '品牌分析', 'CUSTOMER', '/customer/brand-analysis', 'FileText', 15, 1, 1, 0
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
            '{MENU_CODE}', '品牌分析', 'CUSTOMER', 15, 1, 'FileText', '/customer/brand-analysis',
            '客户侧品牌文字诊断报告', 0
        FROM DUAL
        WHERE NOT EXISTS (
            SELECT 1 FROM sys_menu_config WHERE menu_code = '{MENU_CODE}' AND deleted = 0
        )
        """
    )

    # Copy grants from 运营工作台 so existing客户职位默认可见，之后可在职位权限里单独配置
    conn.exec_driver_sql(
        f"""
        INSERT INTO sys_position_menu (
            position_id, menu_id, can_create, can_update, can_delete, can_export
        )
        SELECT pm.position_id, m_new.id, 0, 0, 0, 1
        FROM sys_position_menu pm
        JOIN sys_menu m_ws ON m_ws.id = pm.menu_id AND m_ws.menu_code = 'customer.workspace' AND m_ws.deleted = 0
        JOIN sys_menu m_new ON m_new.menu_code = '{MENU_CODE}' AND m_new.deleted = 0
        WHERE NOT EXISTS (
            SELECT 1 FROM sys_position_menu x
            WHERE x.position_id = pm.position_id AND x.menu_id = m_new.id
        )
        """
    )

    conn.exec_driver_sql(
        f"""
        INSERT INTO sys_user_identity_menu (
            identity_id, menu_id, can_create, can_update, can_delete, can_export
        )
        SELECT uim.identity_id, m_new.id, 0, 0, 0, 1
        FROM sys_user_identity_menu uim
        JOIN sys_menu m_ws ON m_ws.id = uim.menu_id AND m_ws.menu_code = 'customer.workspace' AND m_ws.deleted = 0
        JOIN sys_menu m_new ON m_new.menu_code = '{MENU_CODE}' AND m_new.deleted = 0
        WHERE NOT EXISTS (
            SELECT 1 FROM sys_user_identity_menu x
            WHERE x.identity_id = uim.identity_id AND x.menu_id = m_new.id
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
    conn.exec_driver_sql(f"DELETE FROM sys_menu_config WHERE menu_code = '{MENU_CODE}'")
    conn.exec_driver_sql(f"DELETE FROM sys_menu WHERE menu_code = '{MENU_CODE}'")
