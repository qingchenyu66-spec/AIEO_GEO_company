"""sync identity menu grants from bound positions

Revision ID: t8u9v0w234
Revises: s7t8u9v123
Create Date: 2026-07-10 17:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "t8u9v0w234"
down_revision: Union[str, Sequence[str], None] = "s7t8u9v123"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            DELETE uim
            FROM sys_user_identity_menu uim
            INNER JOIN sys_user_identity ui ON ui.id = uim.identity_id
            WHERE ui.position_id IS NOT NULL
              AND ui.deleted = 0
            """
        )
    )
    bind.execute(
        sa.text(
            """
            INSERT INTO sys_user_identity_menu
                (identity_id, menu_id, can_create, can_update, can_delete, can_export)
            SELECT
                ui.id,
                pm.menu_id,
                pm.can_create,
                pm.can_update,
                pm.can_delete,
                pm.can_export
            FROM sys_user_identity ui
            INNER JOIN sys_position_menu pm ON pm.position_id = ui.position_id
            WHERE ui.deleted = 0
              AND ui.status = 1
              AND ui.position_id IS NOT NULL
              AND (
                    pm.can_create = 1
                 OR pm.can_update = 1
                 OR pm.can_delete = 1
                 OR pm.can_export = 1
              )
            """
        )
    )


def downgrade() -> None:
    pass
