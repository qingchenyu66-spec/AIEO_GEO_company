"""move position management under user management

Revision ID: 9d2a4c6e7f80
Revises: 8c5f0a1b2d33
Create Date: 2026-06-26 18:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "9d2a4c6e7f80"
down_revision = "8c5f0a1b2d33"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    users_id = bind.execute(sa.text("select id from sys_menu where menu_code='platform.users' limit 1")).scalar()
    bind.execute(
        sa.text(
            """
            update sys_menu
            set parent_id=:parent_id, route_path='/platform/users/positions', sort_order=33, is_visible=1, status=1, deleted=0
            where menu_code='platform.positions'
            """
        ),
        {"parent_id": users_id},
    )


def downgrade() -> None:
    bind = op.get_bind()
    settings_id = bind.execute(sa.text("select id from sys_menu where menu_code='platform.settings' limit 1")).scalar()
    bind.execute(
        sa.text(
            """
            update sys_menu
            set parent_id=:parent_id, route_path='/platform/settings/positions', sort_order=91
            where menu_code='platform.positions'
            """
        ),
        {"parent_id": settings_id},
    )
