"""grant platform.audit.purge to PLATFORM_ADMIN role identities without position

Revision ID: n8o9p0q12316
Revises: m7n8o9p01215
Create Date: 2026-07-30
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "n8o9p0q12316"
down_revision: Union[str, Sequence[str], None] = "m7n8o9p01215"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PURGE = "platform.audit.purge"


def upgrade() -> None:
    conn = op.get_bind()
    # 2026-07-30 - demo 等无职位但 role=PLATFORM_ADMIN 的身份也给彻底删除权
    conn.exec_driver_sql(
        f"""
        INSERT INTO sys_user_identity_menu (
            identity_id, menu_id, can_create, can_update, can_delete, can_export
        )
        SELECT ui.id, tm.id, 0, 0, 1, 0
        FROM sys_user_identity ui
        JOIN sys_menu tm ON tm.menu_code = '{PURGE}' AND tm.deleted = 0
        WHERE ui.deleted = 0
          AND ui.identity_type = 'PLATFORM'
          AND UPPER(ui.role_code) = 'PLATFORM_ADMIN'
          AND NOT EXISTS (
            SELECT 1 FROM sys_user_identity_menu x
            WHERE x.identity_id = ui.id AND x.menu_id = tm.id
          )
        """
    )


def downgrade() -> None:
    pass
