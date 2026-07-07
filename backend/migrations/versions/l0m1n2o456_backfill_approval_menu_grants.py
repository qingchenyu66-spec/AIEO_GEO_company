"""backfill approval menu grants to positions and identities

Revision ID: l0m1n2o456
Revises: k9l0m2n345
Create Date: 2026-07-07 09:30:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "l0m1n2o456"
down_revision: Union[str, Sequence[str], None] = "k9l0m2n345"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

APPROVER_POSITION_CODES = ("PLATFORM_ADMIN", "PLATFORM_OPERATION")
APPROVER_POSITION_NAMES = ("平台管理员", "运营")
ALL_TARGET_CODES = ("PLATFORM_ADMIN", "PLATFORM_OPERATION", "PLATFORM_SALES")
ALL_TARGET_NAMES = ("平台管理员", "运营", "销售")


def upgrade() -> None:
    bind = op.get_bind()
    menu_id = bind.execute(
        sa.text("SELECT id FROM sys_menu WHERE menu_code='platform.approvals' AND deleted=0")
    ).scalar()
    if menu_id is None:
        return

    codes_sql = ", ".join(f"'{code}'" for code in ALL_TARGET_CODES)
    names_sql = ", ".join(f"'{name}'" for name in ALL_TARGET_NAMES)
    approver_codes_sql = ", ".join(f"'{code}'" for code in APPROVER_POSITION_CODES)
    approver_names_sql = ", ".join(f"'{name}'" for name in APPROVER_POSITION_NAMES)

    bind.execute(
        sa.text(
            f"""
            INSERT INTO sys_position_menu (position_id, menu_id, can_create, can_update, can_delete, can_export)
            SELECT
                p.id,
                :menu_id,
                0,
                CASE
                    WHEN p.position_code IN ({approver_codes_sql})
                      OR p.position_name IN ({approver_names_sql})
                    THEN 1
                    ELSE 0
                END,
                0,
                1
            FROM sys_position p
            WHERE p.deleted = 0
              AND p.identity_type = 'PLATFORM'
              AND (
                    p.position_code IN ({codes_sql})
                    OR p.position_name IN ({names_sql})
              )
            ON DUPLICATE KEY UPDATE
                can_export = 1,
                can_update = GREATEST(
                    can_update,
                    VALUES(can_update)
                )
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
            JOIN sys_menu m ON m.id = pm.menu_id AND m.menu_code = 'platform.approvals' AND m.deleted = 0
            WHERE ui.deleted = 0
              AND ui.status = 1
              AND ui.identity_type = 'PLATFORM'
              AND ui.position_id IS NOT NULL
              AND NOT EXISTS (
                    SELECT 1
                    FROM sys_user_identity_menu existing
                    WHERE existing.identity_id = ui.id AND existing.menu_id = pm.menu_id
              )
            """
        )
    )


def downgrade() -> None:
    pass
