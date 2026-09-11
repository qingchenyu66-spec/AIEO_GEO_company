"""grant platform credit menus to admin/operation/sales identities

Revision ID: z1a2b3c45678
Revises: y0z1a2b34567
Create Date: 2026-08-27 14:10:00.000000

2026-08-27 - w8 只写了 role_menu，平台侧实际走 position/identity_menu，补授权
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "z1a2b3c45678"
down_revision: Union[str, Sequence[str], None] = "y0z1a2b34567"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (menu_code, positions, can_create, can_update, can_delete, can_export)
GRANTS = (
    ("platform.credit_ops_board", ("PLATFORM_ADMIN", "PLATFORM_OPERATION"), 0, 1, 0, 1),
    ("platform.tenant_credit_blocks", ("PLATFORM_ADMIN", "PLATFORM_OPERATION"), 0, 0, 0, 1),
    ("platform.tenant_credit", ("PLATFORM_ADMIN", "PLATFORM_OPERATION", "PLATFORM_SALES"), 0, 1, 0, 1),
)


def upgrade() -> None:
    conn = op.get_bind()
    for menu_code, positions, c, u, d, e in GRANTS:
        pos_sql = ", ".join(f"'{p}'" for p in positions)
        conn.exec_driver_sql(
            f"""
            INSERT INTO sys_position_menu (position_id, menu_id, can_create, can_update, can_delete, can_export)
            SELECT p.id, m.id, {c}, {u}, {d}, {e}
            FROM sys_position p
            JOIN sys_menu m ON m.menu_code = '{menu_code}' AND m.deleted = 0
            WHERE p.deleted = 0 AND p.position_code IN ({pos_sql})
              AND NOT EXISTS (
                SELECT 1 FROM sys_position_menu pm
                WHERE pm.position_id = p.id AND pm.menu_id = m.id
              )
            """
        )
        conn.exec_driver_sql(
            f"""
            INSERT INTO sys_user_identity_menu (identity_id, menu_id, can_create, can_update, can_delete, can_export)
            SELECT ui.id, m.id, {c}, {u}, {d}, {e}
            FROM sys_user_identity ui
            JOIN sys_position p ON p.id = ui.position_id AND p.deleted = 0
            JOIN sys_menu m ON m.menu_code = '{menu_code}' AND m.deleted = 0
            WHERE ui.deleted = 0 AND ui.status = 1
              AND p.position_code IN ({pos_sql})
              AND NOT EXISTS (
                SELECT 1 FROM sys_user_identity_menu uim
                WHERE uim.identity_id = ui.id AND uim.menu_id = m.id
              )
            """
        )
    # 企业算力入口在企业详情 Tab，侧边栏只保留「算力运营 + 提交拦截」
    conn.exec_driver_sql(
        """
        UPDATE sys_menu SET is_visible = 0
        WHERE menu_code = 'platform.tenant_credit' AND deleted = 0
        """
    )
    conn.exec_driver_sql(
        """
        UPDATE sys_menu_config SET is_visible = 0
        WHERE menu_code = 'platform.tenant_credit' AND deleted = 0
        """
    )


def downgrade() -> None:
    conn = op.get_bind()
    codes = ", ".join(f"'{row[0]}'" for row in GRANTS)
    conn.exec_driver_sql(
        f"""
        DELETE uim FROM sys_user_identity_menu uim
        JOIN sys_menu m ON m.id = uim.menu_id
        WHERE m.menu_code IN ({codes})
        """
    )
    conn.exec_driver_sql(
        f"""
        DELETE pm FROM sys_position_menu pm
        JOIN sys_menu m ON m.id = pm.menu_id
        WHERE m.menu_code IN ({codes})
        """
    )
    conn.exec_driver_sql(
        """
        UPDATE sys_menu SET is_visible = 1
        WHERE menu_code = 'platform.tenant_credit' AND deleted = 0
        """
    )
