"""seed customer position menu grants for credit enterprise

Revision ID: x9y0z1a23456
Revises: w8x9y0z12345
Create Date: 2026-08-27
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "x9y0z1a23456"
down_revision: Union[str, Sequence[str], None] = "w8x9y0z12345"
branch_labels = None
depends_on = None

GRANTS = {
    "enterprise_admin": {
        "customer.enterprise_monitor": (1, 1, 0, 1),
        "customer.enterprise_members": (1, 1, 1, 1),
        "customer.enterprise_credit": (0, 1, 0, 1),
        "customer.enterprise_audit": (0, 0, 0, 1),
    },
    "enterprise_configurator": {
        "customer.enterprise_monitor": (0, 1, 0, 1),
        "customer.enterprise_credit": (0, 0, 0, 1),
        "customer.enterprise_audit": (0, 0, 0, 1),
    },
    "enterprise_viewer": {
        "customer.enterprise_monitor": (0, 0, 0, 1),
        "customer.enterprise_credit": (0, 0, 0, 1),
        "customer.enterprise_audit": (0, 0, 0, 1),
    },
}


def upgrade() -> None:
    conn = op.get_bind()
    for pos_code, menus in GRANTS.items():
        for menu_code, (c, u, d, e) in menus.items():
            conn.exec_driver_sql(
                f"""
                INSERT INTO sys_customer_position_menu (position_id, menu_id, can_create, can_update, can_delete, can_export)
                SELECT p.id, m.id, {c}, {u}, {d}, {e}
                FROM sys_customer_position p
                JOIN sys_menu m ON m.menu_code = '{menu_code}' AND m.deleted = 0
                WHERE p.position_code = '{pos_code}' AND p.tenant_id IS NULL AND p.deleted = 0
                  AND NOT EXISTS (
                    SELECT 1 FROM sys_customer_position_menu cpm
                    WHERE cpm.position_id = p.id AND cpm.menu_id = m.id
                  )
                """
            )


def downgrade() -> None:
    conn = op.get_bind()
    conn.exec_driver_sql(
        """
        DELETE cpm FROM sys_customer_position_menu cpm
        JOIN sys_customer_position p ON p.id = cpm.position_id
        JOIN sys_menu m ON m.id = cpm.menu_id
        WHERE p.tenant_id IS NULL
          AND m.menu_code LIKE 'customer.enterprise%'
        """
    )
