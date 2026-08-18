"""Regression: autoflush=False 时职位菜单须先 flush，再同步身份。"""

from __future__ import annotations

import uuid

from sqlalchemy import delete, select

from app.core.database import SessionLocal
from app.models.permission import Menu, Position, PositionMenu, UserIdentityMenu
from app.models.user import User
from app.models.user_identity import UserIdentity
from app.schemas.permission import MenuGrantItem
from app.services.menu_permission_service import (
    heal_empty_identity_menus,
    sync_identity_menus_for_position,
    sync_position_menu_grants,
)


def test_sync_position_then_identity_keeps_menus_under_autoflush_false():
    code = f"itest_pos_{uuid.uuid4().hex[:10]}"
    position_id = user_id = identity_id = None
    with SessionLocal() as db:
        assert db.autoflush is False
        try:
            menu = db.scalar(
                select(Menu).where(
                    Menu.menu_code == "platform.snapshot_backfill",
                    Menu.identity_type == "PLATFORM",
                    Menu.deleted.is_(False),
                    Menu.status.is_(True),
                )
            )
            assert menu is not None

            position = Position(
                position_code=code,
                position_name=code,
                identity_type="PLATFORM",
                role_code="PLATFORM_SALES",
                description="pytest flush sync",
                allowed_monitor_platforms_json=[],
                status=True,
                deleted=False,
            )
            db.add(position)
            db.flush()
            position_id = int(position.id)

            user = User(
                username=f"u_{code}"[:50],
                password_hash="x",
                display_name="pytest",
                status=True,
                deleted=False,
            )
            db.add(user)
            db.flush()
            user_id = int(user.id)

            identity = UserIdentity(
                identity_code=f"id_{code}",
                user_id=user.id,
                tenant_id=None,
                position_id=position.id,
                identity_type="PLATFORM",
                identity_name="销售测",
                role_code="PLATFORM_SALES",
                is_default=True,
                status=True,
                deleted=False,
            )
            db.add(identity)
            db.flush()
            identity_id = int(identity.id)

            # 旧身份菜单：同步时应被职位模板覆盖，而不是整表删空
            db.add(
                UserIdentityMenu(
                    identity_id=identity.id,
                    menu_id=menu.id,
                    can_create=False,
                    can_update=False,
                    can_delete=False,
                    can_export=True,
                )
            )
            db.flush()

            grants = [
                MenuGrantItem(
                    menu_id=menu.id,
                    menu_code=menu.menu_code,
                    can_create=False,
                    can_update=True,
                    can_delete=False,
                    can_export=True,
                )
            ]
            # 与 management_update_position 同序：先职位菜单，再同步身份
            sync_position_menu_grants(
                db,
                position.id,
                grants,
                identity_type="PLATFORM",
                writable=True,
            )
            synced = sync_identity_menus_for_position(db, position.id)
            db.flush()

            pos_rows = list(db.scalars(select(PositionMenu).where(PositionMenu.position_id == position.id)))
            id_rows = list(
                db.scalars(select(UserIdentityMenu).where(UserIdentityMenu.identity_id == identity.id))
            )
            assert synced == 1
            assert len(pos_rows) == 1
            assert len(id_rows) == 1
            assert id_rows[0].menu_id == menu.id
            assert id_rows[0].can_update is True
            assert id_rows[0].can_export is True
        finally:
            db.rollback()
            if identity_id is not None:
                db.execute(delete(UserIdentityMenu).where(UserIdentityMenu.identity_id == identity_id))
                db.execute(delete(UserIdentity).where(UserIdentity.id == identity_id))
            if user_id is not None:
                db.execute(delete(User).where(User.id == user_id))
            if position_id is not None:
                db.execute(delete(PositionMenu).where(PositionMenu.position_id == position_id))
                db.execute(delete(Position).where(Position.id == position_id))
            db.commit()


def test_heal_empty_identity_menus_restores_only_empty():
    code = f"itest_heal_{uuid.uuid4().hex[:10]}"
    position_id = user_id = empty_id = filled_id = None
    with SessionLocal() as db:
        assert db.autoflush is False
        try:
            menu = db.scalar(
                select(Menu).where(
                    Menu.menu_code == "platform.snapshot_backfill",
                    Menu.identity_type == "PLATFORM",
                    Menu.deleted.is_(False),
                    Menu.status.is_(True),
                )
            )
            assert menu is not None

            position = Position(
                position_code=code,
                position_name=code,
                identity_type="PLATFORM",
                role_code="PLATFORM_SALES",
                description="pytest heal empty",
                allowed_monitor_platforms_json=[],
                status=True,
                deleted=False,
            )
            db.add(position)
            db.flush()
            position_id = int(position.id)

            user = User(
                username=f"u_{code}"[:50],
                password_hash="x",
                display_name="pytest",
                status=True,
                deleted=False,
            )
            db.add(user)
            db.flush()
            user_id = int(user.id)

            empty = UserIdentity(
                identity_code=f"empty_{code}",
                user_id=user.id,
                tenant_id=None,
                position_id=position.id,
                identity_type="PLATFORM",
                identity_name="空菜单",
                role_code="PLATFORM_SALES",
                is_default=True,
                status=True,
                deleted=False,
            )
            filled = UserIdentity(
                identity_code=f"filled_{code}",
                user_id=user.id,
                tenant_id=None,
                position_id=position.id,
                identity_type="PLATFORM",
                identity_name="已有菜单",
                role_code="PLATFORM_SALES",
                is_default=False,
                status=True,
                deleted=False,
            )
            db.add(empty)
            db.add(filled)
            db.flush()
            empty_id = int(empty.id)
            filled_id = int(filled.id)

            db.add(
                PositionMenu(
                    position_id=position.id,
                    menu_id=menu.id,
                    can_create=True,
                    can_update=True,
                    can_delete=False,
                    can_export=True,
                )
            )
            db.add(
                UserIdentityMenu(
                    identity_id=filled.id,
                    menu_id=menu.id,
                    can_create=False,
                    can_update=False,
                    can_delete=False,
                    can_export=True,
                )
            )
            db.flush()

            healed = heal_empty_identity_menus(db)
            db.flush()

            empty_rows = list(
                db.scalars(select(UserIdentityMenu).where(UserIdentityMenu.identity_id == empty.id))
            )
            filled_rows = list(
                db.scalars(select(UserIdentityMenu).where(UserIdentityMenu.identity_id == filled.id))
            )
            assert healed >= 1
            assert len(empty_rows) == 1
            assert empty_rows[0].menu_id == menu.id
            assert empty_rows[0].can_update is True
            assert len(filled_rows) == 1
            assert filled_rows[0].can_update is False
        finally:
            db.rollback()
            for iid in (empty_id, filled_id):
                if iid is not None:
                    db.execute(delete(UserIdentityMenu).where(UserIdentityMenu.identity_id == iid))
                    db.execute(delete(UserIdentity).where(UserIdentity.id == iid))
            if user_id is not None:
                db.execute(delete(User).where(User.id == user_id))
            if position_id is not None:
                db.execute(delete(PositionMenu).where(PositionMenu.position_id == position_id))
                db.execute(delete(Position).where(Position.id == position_id))
            db.commit()
