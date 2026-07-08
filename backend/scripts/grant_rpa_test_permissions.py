"""Grant RPA test menus to the platform test identity (idempotent)."""

from __future__ import annotations

from sqlalchemy import text

from app.core.database import SessionLocal

RPA_USERNAME = "platform"
EXTRA_MENUS = (
    "platform.snapshot_backfill",
    "platform.competitor",
    "platform.sources",
    "platform.approvals",
)

RESTORE_MENUS = {
    "platform.competitor": ("品牌洞察", "/platform/competitor", "BarChart3", 33),
    "platform.sources": ("信源分析", "/platform/sources", "Link", 34),
}

MENU_FLAGS = {
    "platform.snapshot_backfill": (True, True, False, False),  # export, update
    "platform.competitor": (True, False, False, False),
    "platform.sources": (True, False, False, False),
    "platform.approvals": (True, True, False, False),
}


def main() -> None:
    db = SessionLocal()
    try:
        row = db.execute(
            text(
                """
                SELECT ui.id AS identity_id
                FROM sys_user u
                JOIN sys_user_identity ui ON ui.user_id = u.id AND ui.deleted = 0
                WHERE u.username = :username AND u.deleted = 0
                LIMIT 1
                """
            ),
            {"username": RPA_USERNAME},
        ).first()
        if not row:
            print(f"user {RPA_USERNAME!r} not found")
            return
        identity_id = row.identity_id
        for menu_code, (menu_name, route_path, icon, sort_order) in RESTORE_MENUS.items():
            restored = db.execute(
                text(
                    """
                    UPDATE sys_menu
                    SET deleted = 0, menu_name = :menu_name, route_path = :route_path,
                        icon = :icon, sort_order = :sort_order, is_visible = 1, status = 1
                    WHERE menu_code = :menu_code AND deleted = 1
                    """
                ),
                {
                    "menu_code": menu_code,
                    "menu_name": menu_name,
                    "route_path": route_path,
                    "icon": icon,
                    "sort_order": sort_order,
                },
            )
            if restored.rowcount:
                print(f"restored menu {menu_code}")
        for menu_code in EXTRA_MENUS:
            menu = db.execute(
                text(
                    """
                    SELECT id FROM sys_menu
                    WHERE menu_code = :menu_code AND deleted = 0
                    LIMIT 1
                    """
                ),
                {"menu_code": menu_code},
            ).first()
            if not menu:
                print(f"skip missing menu {menu_code}")
                continue
            can_export, can_update, can_create, can_delete = MENU_FLAGS.get(
                menu_code, (True, False, False, False)
            )
            menu_id = menu.id
            exists = db.execute(
                text(
                    """
                    SELECT id FROM sys_user_identity_menu
                    WHERE identity_id = :identity_id AND menu_id = :menu_id
                    LIMIT 1
                    """
                ),
                {"identity_id": identity_id, "menu_id": menu_id},
            ).first()
            if exists:
                db.execute(
                    text(
                        """
                        UPDATE sys_user_identity_menu
                        SET can_export = :can_export,
                            can_update = :can_update,
                            can_create = :can_create,
                            can_delete = :can_delete
                        WHERE id = :id
                        """
                    ),
                    {
                        "id": exists.id,
                        "can_export": int(can_export),
                        "can_update": int(can_update),
                        "can_create": int(can_create),
                        "can_delete": int(can_delete),
                    },
                )
                print(f"updated {menu_code} for identity {identity_id}")
            else:
                db.execute(
                    text(
                        """
                        INSERT INTO sys_user_identity_menu (
                            identity_id, menu_id, can_create, can_update, can_delete, can_export
                        ) VALUES (
                            :identity_id, :menu_id, :can_create, :can_update, :can_delete, :can_export
                        )
                        """
                    ),
                    {
                        "identity_id": identity_id,
                        "menu_id": menu_id,
                        "can_export": int(can_export),
                        "can_update": int(can_update),
                        "can_create": int(can_create),
                        "can_delete": int(can_delete),
                    },
                )
                print(f"granted {menu_code} for identity {identity_id}")
        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    main()
