"""repair user create permission tree and user-list assignable reads

Revision ID: s7t8u9v123
Revises: r6s7t8u012
Create Date: 2026-07-10 16:10:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "s7t8u9v123"
down_revision: Union[str, Sequence[str], None] = "r6s7t8u012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ROUTE_ONLY_CODES = ("platform.users", "platform.users.create")


def upgrade() -> None:
    bind = op.get_bind()

    route_menu_ids = bind.execute(
        sa.text(
            """
            SELECT id FROM sys_menu
            WHERE menu_code IN ('platform.users', 'platform.users.create')
              AND deleted = 0
            """
        )
    ).scalars().all()
    if route_menu_ids:
        ids_sql = ", ".join(str(item) for item in route_menu_ids)
        bind.execute(sa.text(f"DELETE FROM sys_position_menu WHERE menu_id IN ({ids_sql})"))
        bind.execute(sa.text(f"DELETE FROM sys_user_identity_menu WHERE menu_id IN ({ids_sql})"))

    positions_menu_id = bind.execute(
        sa.text("SELECT id FROM sys_menu WHERE menu_code='platform.positions' AND deleted=0")
    ).scalar()
    users_list_menu_id = bind.execute(
        sa.text("SELECT id FROM sys_menu WHERE menu_code='platform.users.list' AND deleted=0")
    ).scalar()
    create_platform_menu_id = bind.execute(
        sa.text("SELECT id FROM sys_menu WHERE menu_code='platform.users.create.platform' AND deleted=0")
    ).scalar()
    create_customer_menu_id = bind.execute(
        sa.text("SELECT id FROM sys_menu WHERE menu_code='platform.users.create.customer' AND deleted=0")
    ).scalar()

    if positions_menu_id is None:
        return

    bind.execute(
        sa.text(
            """
            INSERT INTO sys_position_menu (position_id, menu_id, can_create, can_update, can_delete, can_export)
            SELECT DISTINCT
                pm.position_id,
                :positions_menu_id,
                0, 0, 0, 1
            FROM sys_position_menu pm
            JOIN sys_menu m ON m.id = pm.menu_id
            WHERE pm.can_export = 1 OR pm.can_update = 1 OR pm.can_create = 1 OR pm.can_delete = 1
              AND (
                    m.menu_code = 'platform.users.list'
                    OR m.menu_code = 'platform.users.create.platform'
                    OR m.menu_code = 'platform.users.create.customer'
              )
            ON DUPLICATE KEY UPDATE can_export = 1
            """
        ),
        {
            "positions_menu_id": positions_menu_id,
        },
    )

    for menu_id in (users_list_menu_id, create_platform_menu_id, create_customer_menu_id):
        if menu_id is None:
            continue
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
                        SELECT 1 FROM sys_user_identity_menu existing
                        WHERE existing.identity_id = ui.id AND existing.menu_id = pm.menu_id
                  )
                """
            ),
            {"menu_id": menu_id},
        )

    sync_ids = [item for item in (users_list_menu_id, create_platform_menu_id, create_customer_menu_id, positions_menu_id) if item is not None]
    if sync_ids:
        ids_sql = ", ".join(str(item) for item in sync_ids)
        bind.execute(
            sa.text(
                f"""
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
                  AND uim.menu_id IN ({ids_sql})
                """
            )
        )


def downgrade() -> None:
    pass
