"""remove platform.logs menu grant from sales position

Revision ID: p4q5r6s890
Revises: o3p4q5r789
Create Date: 2026-07-07 12:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "p4q5r6s890"
down_revision: Union[str, Sequence[str], None] = "o3p4q5r789"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    menu_id = bind.execute(
        sa.text("SELECT id FROM sys_menu WHERE menu_code='platform.logs' AND deleted=0")
    ).scalar()
    if menu_id is None:
        return

    bind.execute(
        sa.text(
            """
            DELETE pm FROM sys_position_menu pm
            JOIN sys_position p ON p.id = pm.position_id AND p.deleted = 0
            WHERE pm.menu_id = :menu_id
              AND (p.position_code = 'PLATFORM_SALES' OR p.position_name = '销售')
            """
        ),
        {"menu_id": menu_id},
    )

    bind.execute(
        sa.text(
            """
            DELETE uim FROM sys_user_identity_menu uim
            JOIN sys_user_identity ui ON ui.id = uim.identity_id AND ui.deleted = 0
            JOIN sys_position p ON p.id = ui.position_id AND p.deleted = 0
            WHERE uim.menu_id = :menu_id
              AND (p.position_code = 'PLATFORM_SALES' OR p.position_name = '销售')
            """
        ),
        {"menu_id": menu_id},
    )


def downgrade() -> None:
    bind = op.get_bind()
    menu_id = bind.execute(
        sa.text("SELECT id FROM sys_menu WHERE menu_code='platform.logs' AND deleted=0")
    ).scalar()
    position_id = bind.execute(
        sa.text(
            """
            SELECT id FROM sys_position
            WHERE deleted = 0 AND (position_code = 'PLATFORM_SALES' OR position_name = '销售')
            LIMIT 1
            """
        )
    ).scalar()
    if menu_id is None or position_id is None:
        return

    bind.execute(
        sa.text(
            """
            INSERT INTO sys_position_menu (position_id, menu_id, can_create, can_update, can_delete, can_export)
            SELECT :position_id, :menu_id, 0, 0, 0, 1
            FROM DUAL
            WHERE NOT EXISTS (
                SELECT 1 FROM sys_position_menu
                WHERE position_id = :position_id AND menu_id = :menu_id
            )
            """
        ),
        {"position_id": position_id, "menu_id": menu_id},
    )

    bind.execute(
        sa.text(
            """
            INSERT INTO sys_user_identity_menu (identity_id, menu_id, can_create, can_update, can_delete, can_export)
            SELECT ui.id, pm.menu_id, pm.can_create, pm.can_update, pm.can_delete, pm.can_export
            FROM sys_user_identity ui
            JOIN sys_position_menu pm ON pm.position_id = ui.position_id
            JOIN sys_menu m ON m.id = pm.menu_id AND m.menu_code = 'platform.logs' AND m.deleted = 0
            WHERE ui.deleted = 0
              AND ui.position_id = :position_id
              AND NOT EXISTS (
                  SELECT 1 FROM sys_user_identity_menu uim
                  WHERE uim.identity_id = ui.id AND uim.menu_id = pm.menu_id
              )
            """
        ),
        {"position_id": position_id},
    )
