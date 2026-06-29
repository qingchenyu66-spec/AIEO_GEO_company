"""add position management menu

Revision ID: 8c5f0a1b2d33
Revises: 7a3e9b2c4d11
Create Date: 2026-06-26 17:20:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "8c5f0a1b2d33"
down_revision = "7a3e9b2c4d11"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    settings_id = bind.execute(sa.text("select id from sys_menu where menu_code='platform.settings' limit 1")).scalar()
    bind.execute(
        sa.text(
            """
            insert into sys_menu (menu_code, menu_name, identity_type, parent_id, route_path, icon, sort_order, is_visible, status, deleted)
            values ('platform.positions', '职位管理', 'PLATFORM', :parent_id, '/platform/settings/positions', 'UserCog', 91, 1, 1, 0)
            on duplicate key update menu_name=values(menu_name), parent_id=values(parent_id), route_path=values(route_path),
            icon=values(icon), sort_order=values(sort_order), is_visible=1, status=1, deleted=0
            """
        ),
        {"parent_id": settings_id},
    )
    menu_id = bind.execute(sa.text("select id from sys_menu where menu_code='platform.positions' limit 1")).scalar()
    if not menu_id:
        return

    role_ids = bind.execute(
        sa.text("select id from sys_role where role_code in ('PLATFORM_ADMIN') and deleted=0")
    ).scalars().all()
    for role_id in role_ids:
        bind.execute(
            sa.text("insert ignore into sys_role_menu (role_id, menu_id) values (:role_id, :menu_id)"),
            {"role_id": role_id, "menu_id": menu_id},
        )

    position_ids = bind.execute(
        sa.text("select id from sys_position where position_code in ('PLATFORM_ADMIN') and deleted=0")
    ).scalars().all()
    for position_id in position_ids:
        bind.execute(
            sa.text(
                """
                insert ignore into sys_position_menu
                (position_id, menu_id, can_create, can_update, can_delete, can_export)
                values (:position_id, :menu_id, 1, 1, 1, 1)
                """
            ),
            {"position_id": position_id, "menu_id": menu_id},
        )

    identity_ids = bind.execute(
        sa.text("select id from sys_user_identity where identity_type='PLATFORM' and role_code='PLATFORM_ADMIN' and deleted=0")
    ).scalars().all()
    for identity_id in identity_ids:
        bind.execute(
            sa.text(
                """
                insert ignore into sys_user_identity_menu
                (identity_id, menu_id, can_create, can_update, can_delete, can_export)
                values (:identity_id, :menu_id, 1, 1, 1, 1)
                """
            ),
            {"identity_id": identity_id, "menu_id": menu_id},
        )


def downgrade() -> None:
    bind = op.get_bind()
    menu_id = bind.execute(sa.text("select id from sys_menu where menu_code='platform.positions' limit 1")).scalar()
    if menu_id:
        bind.execute(sa.text("delete from sys_user_identity_menu where menu_id=:menu_id"), {"menu_id": menu_id})
        bind.execute(sa.text("delete from sys_position_menu where menu_id=:menu_id"), {"menu_id": menu_id})
        bind.execute(sa.text("delete from sys_role_menu where menu_id=:menu_id"), {"menu_id": menu_id})
        bind.execute(sa.text("delete from sys_menu where id=:menu_id"), {"menu_id": menu_id})
