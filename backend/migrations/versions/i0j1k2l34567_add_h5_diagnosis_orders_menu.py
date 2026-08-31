"""add platform H5 diagnosis orders menu and grants

Revision ID: i0j1k2l34567
Revises: h9i0j1k23456
Create Date: 2026-08-31 16:20:00.000000

2026-08-31 - 方案 C：独立「H5订单」菜单 + 职位/身份授权，进权限配置
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "i0j1k2l34567"
down_revision: Union[str, Sequence[str], None] = "h9i0j1k23456"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_MENU_CODE = "platform.h5_diagnosis_orders"
_POSITIONS = ("PLATFORM_ADMIN", "PLATFORM_OPERATION", "PLATFORM_SALES")


def upgrade() -> None:
    conn = op.get_bind()
    conn.exec_driver_sql(
        f"""
        INSERT INTO sys_menu (
            menu_code, menu_name, identity_type, route_path, icon, sort_order, is_visible, status, deleted
        )
        SELECT '{_MENU_CODE}', 'H5订单', 'PLATFORM', '/platform/h5-diagnosis-orders', 'Receipt', 37, 1, 1, 0
        FROM DUAL
        WHERE NOT EXISTS (
            SELECT 1 FROM sys_menu WHERE menu_code = '{_MENU_CODE}' AND deleted = 0
        )
        """
    )
    conn.exec_driver_sql(
        f"""
        INSERT INTO sys_menu_config (
            menu_code, menu_name, identity_type, sort_order, is_visible, icon, route_path, remark, deleted
        )
        SELECT
            '{_MENU_CODE}', 'H5订单', 'PLATFORM', 37, 1, 'Receipt', '/platform/h5-diagnosis-orders',
            'H5 付费诊断订单：支付状态、金额、关联售前诊断', 0
        FROM DUAL
        WHERE NOT EXISTS (
            SELECT 1 FROM sys_menu_config WHERE menu_code = '{_MENU_CODE}' AND deleted = 0
        )
        """
    )
    conn.exec_driver_sql(
        f"""
        INSERT INTO sys_role_menu (role_id, menu_id)
        SELECT r.id, m.id
        FROM sys_role r
        JOIN sys_menu m ON m.menu_code = '{_MENU_CODE}' AND m.deleted = 0
        WHERE r.identity_type = 'PLATFORM' AND r.deleted = 0
          AND NOT EXISTS (
              SELECT 1 FROM sys_role_menu rm
              WHERE rm.role_id = r.id AND rm.menu_id = m.id
          )
        """
    )
    pos_sql = ", ".join(f"'{code}'" for code in _POSITIONS)
    conn.exec_driver_sql(
        f"""
        INSERT INTO sys_position_menu (position_id, menu_id, can_create, can_update, can_delete, can_export)
        SELECT p.id, m.id, 0, 0, 0, 1
        FROM sys_position p
        JOIN sys_menu m ON m.menu_code = '{_MENU_CODE}' AND m.deleted = 0
        WHERE p.position_code IN ({pos_sql})
          AND p.deleted = 0
          AND NOT EXISTS (
              SELECT 1 FROM sys_position_menu pm
              WHERE pm.position_id = p.id AND pm.menu_id = m.id
          )
        """
    )
    # 平台身份直接授权，避免仅岗位包未刷新时侧栏看不到
    conn.exec_driver_sql(
        f"""
        INSERT INTO sys_user_identity_menu (
            identity_id, menu_id, can_create, can_update, can_delete, can_export
        )
        SELECT ui.id, m.id, 0, 0, 0, 1
        FROM sys_user_identity ui
        JOIN sys_menu m ON m.menu_code = '{_MENU_CODE}' AND m.deleted = 0
        WHERE ui.identity_type = 'PLATFORM' AND ui.deleted = 0
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
        WHERE m.menu_code = '{_MENU_CODE}'
        """
    )
    conn.exec_driver_sql(
        f"""
        DELETE pm FROM sys_position_menu pm
        JOIN sys_menu m ON m.id = pm.menu_id
        WHERE m.menu_code = '{_MENU_CODE}'
        """
    )
    conn.exec_driver_sql(
        f"""
        DELETE rm FROM sys_role_menu rm
        JOIN sys_menu m ON m.id = rm.menu_id
        WHERE m.menu_code = '{_MENU_CODE}'
        """
    )
    conn.exec_driver_sql(
        f"UPDATE sys_menu_config SET deleted = 1 WHERE menu_code = '{_MENU_CODE}'"
    )
    conn.exec_driver_sql(
        f"UPDATE sys_menu SET deleted = 1 WHERE menu_code = '{_MENU_CODE}'"
    )
