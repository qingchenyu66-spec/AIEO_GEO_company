"""split user create identity permissions

Revision ID: b1c2d3e4f560
Revises: 9d2a4c6e7f80
Create Date: 2026-06-26 19:10:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "b1c2d3e4f560"
down_revision = "9d2a4c6e7f80"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    users_id = bind.execute(sa.text("select id from sys_menu where menu_code='platform.users' limit 1")).scalar()
    create_id = bind.execute(sa.text("select id from sys_menu where menu_code='platform.users.create' limit 1")).scalar()
    bind.execute(sa.text("update sys_menu set parent_id=:parent_id where menu_code in ('platform.users.create','platform.users.list','platform.positions')"), {"parent_id": users_id})

    items = [
        ("platform.users.create.platform", "新增平台运营端用户", "/platform/users/create/platform", "ShieldCheck", 311),
        ("platform.users.create.customer", "新增客户企业端用户", "/platform/users/create/customer", "Building2", 312),
    ]
    for code, name, route, icon, sort_order in items:
        bind.execute(
            sa.text(
                """
                insert into sys_menu (menu_code, menu_name, identity_type, parent_id, route_path, icon, sort_order, is_visible, status, deleted)
                values (:code, :name, 'PLATFORM', :parent_id, :route, :icon, :sort_order, 0, 1, 0)
                on duplicate key update menu_name=values(menu_name), parent_id=values(parent_id), route_path=values(route_path),
                icon=values(icon), sort_order=values(sort_order), is_visible=0, status=1, deleted=0
                """
            ),
            {"code": code, "name": name, "parent_id": users_id, "route": route, "icon": icon, "sort_order": sort_order},
        )

    platform_create_id = bind.execute(sa.text("select id from sys_menu where menu_code='platform.users.create.platform' limit 1")).scalar()
    customer_create_id = bind.execute(sa.text("select id from sys_menu where menu_code='platform.users.create.customer' limit 1")).scalar()

    # Positions that could already enter the user-create page can at least create customer-side users.
    position_ids = bind.execute(sa.text("select position_id from sys_position_menu where menu_id=:create_id"), {"create_id": create_id}).scalars().all()
    for position_id in position_ids:
        bind.execute(
            sa.text(
                """
                insert ignore into sys_position_menu
                (position_id, menu_id, can_create, can_update, can_delete, can_export)
                values (:position_id, :menu_id, 1, 1, 0, 1)
                """
            ),
            {"position_id": position_id, "menu_id": customer_create_id},
        )

    admin_position_ids = bind.execute(sa.text("select id from sys_position where identity_type='PLATFORM' and role_code='PLATFORM_ADMIN' and deleted=0")).scalars().all()
    for position_id in admin_position_ids:
        bind.execute(
            sa.text(
                """
                insert ignore into sys_position_menu
                (position_id, menu_id, can_create, can_update, can_delete, can_export)
                values (:position_id, :menu_id, 1, 1, 0, 1)
                """
            ),
            {"position_id": position_id, "menu_id": platform_create_id},
        )

    identity_ids = bind.execute(sa.text("select identity_id from sys_user_identity_menu where menu_id=:create_id"), {"create_id": create_id}).scalars().all()
    for identity_id in identity_ids:
        bind.execute(
            sa.text(
                """
                insert ignore into sys_user_identity_menu
                (identity_id, menu_id, can_create, can_update, can_delete, can_export)
                values (:identity_id, :menu_id, 1, 1, 0, 1)
                """
            ),
            {"identity_id": identity_id, "menu_id": customer_create_id},
        )

    admin_identity_ids = bind.execute(sa.text("select id from sys_user_identity where identity_type='PLATFORM' and role_code='PLATFORM_ADMIN' and deleted=0")).scalars().all()
    for identity_id in admin_identity_ids:
        bind.execute(
            sa.text(
                """
                insert ignore into sys_user_identity_menu
                (identity_id, menu_id, can_create, can_update, can_delete, can_export)
                values (:identity_id, :menu_id, 1, 1, 0, 1)
                """
            ),
            {"identity_id": identity_id, "menu_id": platform_create_id},
        )


def downgrade() -> None:
    bind = op.get_bind()
    menu_ids = bind.execute(sa.text("select id from sys_menu where menu_code in ('platform.users.create.platform','platform.users.create.customer')")).scalars().all()
    for menu_id in menu_ids:
        bind.execute(sa.text("delete from sys_user_identity_menu where menu_id=:menu_id"), {"menu_id": menu_id})
        bind.execute(sa.text("delete from sys_position_menu where menu_id=:menu_id"), {"menu_id": menu_id})
        bind.execute(sa.text("delete from sys_role_menu where menu_id=:menu_id"), {"menu_id": menu_id})
        bind.execute(sa.text("delete from sys_menu where id=:menu_id"), {"menu_id": menu_id})
