"""grant platform credit menus to role identities without position

Revision ID: a2b3c4d56789
Revises: z1a2b3c45678
Create Date: 2026-08-27 14:30:00.000000

2026-08-27 - demo 等无 position_id 但 role=PLATFORM_ADMIN 的身份也要看到算力运营
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "a2b3c4d56789"
down_revision: Union[str, Sequence[str], None] = "z1a2b3c45678"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (menu_code, roles, can_create, can_update, can_delete, can_export)
GRANTS = (
    ("platform.credit_ops_board", ("PLATFORM_ADMIN", "PLATFORM_OPERATION"), 0, 1, 0, 1),
    ("platform.tenant_credit_blocks", ("PLATFORM_ADMIN", "PLATFORM_OPERATION"), 0, 0, 0, 1),
    ("platform.tenant_credit", ("PLATFORM_ADMIN", "PLATFORM_OPERATION", "PLATFORM_SALES"), 0, 1, 0, 1),
)


def upgrade() -> None:
    conn = op.get_bind()
    for menu_code, roles, c, u, d, e in GRANTS:
        role_sql = ", ".join(f"'{r}'" for r in roles)
        conn.exec_driver_sql(
            f"""
            INSERT INTO sys_user_identity_menu (
                identity_id, menu_id, can_create, can_update, can_delete, can_export
            )
            SELECT ui.id, m.id, {c}, {u}, {d}, {e}
            FROM sys_user_identity ui
            JOIN sys_menu m ON m.menu_code = '{menu_code}' AND m.deleted = 0
            WHERE ui.deleted = 0
              AND ui.status = 1
              AND ui.identity_type = 'PLATFORM'
              AND UPPER(ui.role_code) IN ({role_sql})
              AND NOT EXISTS (
                SELECT 1 FROM sys_user_identity_menu x
                WHERE x.identity_id = ui.id AND x.menu_id = m.id
              )
            """
        )


def downgrade() -> None:
    conn = op.get_bind()
    codes = ", ".join(f"'{row[0]}'" for row in GRANTS)
    conn.exec_driver_sql(
        f"""
        DELETE uim FROM sys_user_identity_menu uim
        JOIN sys_menu m ON m.id = uim.menu_id
        JOIN sys_user_identity ui ON ui.id = uim.identity_id
        WHERE m.menu_code IN ({codes})
          AND ui.position_id IS NULL
          AND ui.identity_type = 'PLATFORM'
        """
    )
