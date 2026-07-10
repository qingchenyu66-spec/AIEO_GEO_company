"""repair platform.audit.list stop-service menu grants

Revision ID: r6s7t8u012
Revises: q5r6s7t901
Create Date: 2026-07-10 15:20:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "r6s7t8u012"
down_revision: Union[str, Sequence[str], None] = "q5r6s7t901"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

WRITABLE_POSITION_CODES = ("PLATFORM_ADMIN", "PLATFORM_OPERATION")
WRITABLE_POSITION_NAMES = ("平台管理员", "运营")


def upgrade() -> None:
    bind = op.get_bind()
    menu_id = bind.execute(
        sa.text("SELECT id FROM sys_menu WHERE menu_code='platform.audit.list' AND deleted=0")
    ).scalar()
    if menu_id is None:
        return

    codes_sql = ", ".join(f"'{code}'" for code in WRITABLE_POSITION_CODES)
    names_sql = ", ".join(f"'{name}'" for name in WRITABLE_POSITION_NAMES)

    bind.execute(
        sa.text(
            f"""
            INSERT INTO sys_position_menu (position_id, menu_id, can_create, can_update, can_delete, can_export)
            SELECT
                p.id,
                :menu_id,
                0,
                CASE
                    WHEN p.position_code IN ({codes_sql}) OR p.position_name IN ({names_sql}) THEN 1
                    ELSE 0
                END,
                CASE
                    WHEN p.position_code IN ({codes_sql}) OR p.position_name IN ({names_sql}) THEN 1
                    ELSE 0
                END,
                1
            FROM sys_position p
            WHERE p.deleted = 0
              AND p.identity_type = 'PLATFORM'
            ON DUPLICATE KEY UPDATE
                can_export = 1,
                can_update = GREATEST(can_update, VALUES(can_update)),
                can_delete = GREATEST(can_delete, VALUES(can_delete))
            """
        ),
        {"menu_id": menu_id},
    )

    bind.execute(
        sa.text(
            """
            UPDATE sys_user_identity_menu uim
            JOIN sys_user_identity ui ON ui.id = uim.identity_id
            JOIN sys_position_menu pm ON pm.position_id = ui.position_id AND pm.menu_id = uim.menu_id
            SET
                uim.can_export = pm.can_export,
                uim.can_update = pm.can_update,
                uim.can_delete = pm.can_delete,
                uim.can_create = pm.can_create
            WHERE ui.deleted = 0
              AND ui.status = 1
              AND ui.identity_type = 'PLATFORM'
              AND ui.position_id IS NOT NULL
              AND uim.menu_id = :menu_id
            """
        ),
        {"menu_id": menu_id},
    )

    bind.execute(
        sa.text(
            """
            INSERT INTO sys_user_identity_menu (identity_id, menu_id, can_create, can_update, can_delete, can_export)
            SELECT ui.id, pm.menu_id, pm.can_create, pm.can_update, pm.can_delete, pm.can_export
            FROM sys_user_identity ui
            JOIN sys_position_menu pm ON pm.position_id = ui.position_id
            WHERE ui.deleted = 0
              AND ui.status = 1
              AND ui.identity_type = 'PLATFORM'
              AND ui.position_id IS NOT NULL
              AND pm.menu_id = :menu_id
              AND NOT EXISTS (
                    SELECT 1
                    FROM sys_user_identity_menu existing
                    WHERE existing.identity_id = ui.id AND existing.menu_id = pm.menu_id
              )
            """
        ),
        {"menu_id": menu_id},
    )


def downgrade() -> None:
    pass
