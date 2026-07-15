"""split system settings into grantable child menus

Revision ID: u9v0w1x345
Revises: t8u9v0w234
Create Date: 2026-07-15 10:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "u9v0w1x345"
down_revision: Union[str, Sequence[str], None] = "t8u9v0w234"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SETTINGS_CHILDREN = (
    ("platform.settings.secrets", "接口密钥", "/platform/settings/secrets", "Key", 91),
    ("platform.settings.schedule", "调度策略", "/platform/settings/schedule", "Timer", 92),
    ("platform.settings.cache_queue", "缓存与队列", "/platform/settings/cache-queue", "Database", 93),
    ("platform.settings.notification", "通知规则", "/platform/settings/notification", "Bell", 94),
    ("platform.settings.menu", "菜单权限", "/platform/settings/menu", "LayoutList", 95),
)


def upgrade() -> None:
    bind = op.get_bind()
    parent_id = bind.execute(
        sa.text("SELECT id FROM sys_menu WHERE menu_code='platform.settings' AND deleted=0 LIMIT 1")
    ).scalar()
    if parent_id is None:
        return

    for code, name, route, icon, sort_order in SETTINGS_CHILDREN:
        bind.execute(
            sa.text(
                """
                INSERT INTO sys_menu
                (menu_code, menu_name, identity_type, parent_id, route_path, icon, sort_order, is_visible, status, deleted)
                VALUES (:code, :name, 'PLATFORM', :parent_id, :route, :icon, :sort_order, 0, 1, 0)
                ON DUPLICATE KEY UPDATE
                  menu_name=VALUES(menu_name),
                  parent_id=VALUES(parent_id),
                  route_path=VALUES(route_path),
                  icon=VALUES(icon),
                  sort_order=VALUES(sort_order),
                  is_visible=0,
                  status=1,
                  deleted=0
                """
            ),
            {
                "code": code,
                "name": name,
                "parent_id": parent_id,
                "route": route,
                "icon": icon,
                "sort_order": sort_order,
            },
        )
        bind.execute(
            sa.text(
                """
                INSERT INTO sys_menu_config
                (menu_code, menu_name, identity_type, sort_order, is_visible, icon, route_path, remark, deleted)
                VALUES (:code, :name, 'PLATFORM', :sort_order, 0, :icon, :route, :remark, 0)
                ON DUPLICATE KEY UPDATE
                  menu_name=VALUES(menu_name),
                  sort_order=VALUES(sort_order),
                  is_visible=0,
                  icon=VALUES(icon),
                  route_path=VALUES(route_path),
                  deleted=0
                """
            ),
            {
                "code": code,
                "name": name,
                "sort_order": sort_order,
                "icon": icon,
                "route": route,
                "remark": f"系统配置 · {name}",
            },
        )

    child_ids = {
        code: bind.execute(
            sa.text("SELECT id FROM sys_menu WHERE menu_code=:code AND deleted=0 LIMIT 1"),
            {"code": code},
        ).scalar()
        for code, *_ in SETTINGS_CHILDREN
    }
    child_ids = {code: mid for code, mid in child_ids.items() if mid}

    # 已有系统配置权限的职位/身份：同步到全部子菜单
    position_rows = bind.execute(
        sa.text(
            """
            SELECT position_id, can_create, can_update, can_delete, can_export
            FROM sys_position_menu
            WHERE menu_id = :parent_id
            """
        ),
        {"parent_id": parent_id},
    ).mappings().all()
    for row in position_rows:
        for menu_id in child_ids.values():
            bind.execute(
                sa.text(
                    """
                    INSERT INTO sys_position_menu
                    (position_id, menu_id, can_create, can_update, can_delete, can_export)
                    VALUES (:position_id, :menu_id, :can_create, :can_update, :can_delete, :can_export)
                    ON DUPLICATE KEY UPDATE
                      can_create=VALUES(can_create),
                      can_update=VALUES(can_update),
                      can_delete=VALUES(can_delete),
                      can_export=VALUES(can_export)
                    """
                ),
                {
                    "position_id": row["position_id"],
                    "menu_id": menu_id,
                    "can_create": 0,
                    "can_update": int(bool(row["can_update"])),
                    "can_delete": 0,
                    "can_export": int(bool(row["can_export"] or row["can_update"])),
                },
            )

    identity_rows = bind.execute(
        sa.text(
            """
            SELECT identity_id, can_create, can_update, can_delete, can_export
            FROM sys_user_identity_menu
            WHERE menu_id = :parent_id
            """
        ),
        {"parent_id": parent_id},
    ).mappings().all()
    for row in identity_rows:
        for menu_id in child_ids.values():
            bind.execute(
                sa.text(
                    """
                    INSERT INTO sys_user_identity_menu
                    (identity_id, menu_id, can_create, can_update, can_delete, can_export)
                    VALUES (:identity_id, :menu_id, :can_create, :can_update, :can_delete, :can_export)
                    ON DUPLICATE KEY UPDATE
                      can_create=VALUES(can_create),
                      can_update=VALUES(can_update),
                      can_delete=VALUES(can_delete),
                      can_export=VALUES(can_export)
                    """
                ),
                {
                    "identity_id": row["identity_id"],
                    "menu_id": menu_id,
                    "can_create": 0,
                    "can_update": int(bool(row["can_update"])),
                    "can_delete": 0,
                    "can_export": int(bool(row["can_export"] or row["can_update"])),
                },
            )


def downgrade() -> None:
    bind = op.get_bind()
    codes = [code for code, *_ in SETTINGS_CHILDREN]
    menu_ids = bind.execute(
        sa.text("SELECT id FROM sys_menu WHERE menu_code IN :codes").bindparams(
            sa.bindparam("codes", expanding=True)
        ),
        {"codes": codes},
    ).scalars().all()
    for menu_id in menu_ids:
        bind.execute(sa.text("DELETE FROM sys_user_identity_menu WHERE menu_id=:menu_id"), {"menu_id": menu_id})
        bind.execute(sa.text("DELETE FROM sys_position_menu WHERE menu_id=:menu_id"), {"menu_id": menu_id})
        bind.execute(sa.text("DELETE FROM sys_role_menu WHERE menu_id=:menu_id"), {"menu_id": menu_id})
        bind.execute(sa.text("DELETE FROM sys_menu WHERE id=:menu_id"), {"menu_id": menu_id})
    bind.execute(
        sa.text("DELETE FROM sys_menu_config WHERE menu_code IN :codes").bindparams(
            sa.bindparam("codes", expanding=True)
        ),
        {"codes": codes},
    )
