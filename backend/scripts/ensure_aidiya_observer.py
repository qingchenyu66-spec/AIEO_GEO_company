"""本地：创建/修复艾迪亚公用观察账号（幂等）。

登录名「艾迪亚」/ 密码 123456；绑租户「艾迪亚控股集团有限公司」；
菜单客户侧全开但只读（知识库可上传）；平台白名单由 observer_account 写死 kimi/yuanbao。

用法（backend 目录）:
  $env:PYTHONPATH="..."
  .\\.venv\\Scripts\\python.exe -m scripts.ensure_aidiya_observer
"""

from __future__ import annotations

from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models.permission import Menu, Position, PositionMenu, UserIdentityMenu
from app.models.tenant import Tenant
from app.models.user import User
from app.models.user_identity import UserIdentity
from app.services.menu_permission_service import replace_identity_menus_from_position
from app.services.observer_account import (
    OBSERVER_PLATFORMS,
    OBSERVER_TENANT_NAME,
    OBSERVER_USERNAME,
)

POSITION_CODE = "CUSTOMER_AIDIYA_OBSERVER"
POSITION_NAME = "艾迪亚观察账号"
ROLE_CODE = "TENANT_ADMIN"
PASSWORD = "123456"

# 客户门户常用菜单；隐藏/空壳的也挂上看看权限（仍只读）
CUSTOMER_MENU_CODES = (
    "customer.workspace",
    "customer.brand_analysis",
    "customer.realtime",
    "customer.competitor",
    "customer.sources",
    "customer.reports",
    "customer.knowledge",
)


def _ensure_position(db) -> Position:
    position = db.scalar(select(Position).where(Position.position_code == POSITION_CODE))
    if position is None:
        position = Position(
            position_code=POSITION_CODE,
            position_name=POSITION_NAME,
            identity_type="CUSTOMER",
            role_code=ROLE_CODE,
            description="公用观察：只读+知识库上传；平台范围见账号硬编码",
            allowed_monitor_platforms_json=sorted(OBSERVER_PLATFORMS),
            sort_order=90,
            status=True,
            deleted=False,
        )
        db.add(position)
        db.flush()
    else:
        position.position_name = POSITION_NAME
        position.role_code = ROLE_CODE
        position.allowed_monitor_platforms_json = sorted(OBSERVER_PLATFORMS)
        position.status = True
        position.deleted = False
        db.flush()

    menus = {
        m.menu_code: m
        for m in db.scalars(
            select(Menu).where(
                Menu.identity_type == "CUSTOMER",
                Menu.menu_code.in_(CUSTOMER_MENU_CODES),
                Menu.deleted.is_(False),
            )
        )
    }
    db.query(PositionMenu).filter(PositionMenu.position_id == position.id).delete(synchronize_session=False)
    for code in CUSTOMER_MENU_CODES:
        menu = menus.get(code)
        if menu is None:
            print(f"skip missing menu {code}")
            continue
        can_create = code == "customer.knowledge"
        can_update = False
        can_delete = False
        db.add(
            PositionMenu(
                position_id=position.id,
                menu_id=menu.id,
                can_export=True,
                can_create=can_create,
                can_update=can_update,
                can_delete=can_delete,
            )
        )
    db.flush()
    return position


def _ensure_user(db, tenant: Tenant, position: Position) -> User:
    user = db.scalar(select(User).where(User.username == OBSERVER_USERNAME))
    if user is None:
        user = User(
            username=OBSERVER_USERNAME,
            password_hash=hash_password(PASSWORD),
            display_name=OBSERVER_USERNAME,
            status=True,
            deleted=False,
            # 公用观察号：不强制改密，避免多人登录互踢改密
            must_change_password=False,
        )
        db.add(user)
        db.flush()
    else:
        user.password_hash = hash_password(PASSWORD)
        user.display_name = OBSERVER_USERNAME
        user.status = True
        user.deleted = False
        user.must_change_password = False
        db.flush()

    identity = db.scalar(
        select(UserIdentity).where(
            UserIdentity.user_id == user.id,
            UserIdentity.identity_type == "CUSTOMER",
        )
    )
    if identity is None:
        identity = UserIdentity(
            identity_code=f"CUSTOMER_{user.id}_{ROLE_CODE}_OBS",
            user_id=user.id,
            tenant_id=tenant.id,
            position_id=position.id,
            identity_type="CUSTOMER",
            identity_name=POSITION_NAME,
            role_code=ROLE_CODE,
            is_default=True,
            status=True,
            deleted=False,
        )
        db.add(identity)
        db.flush()
    else:
        identity.tenant_id = tenant.id
        identity.position_id = position.id
        identity.identity_name = POSITION_NAME
        identity.role_code = ROLE_CODE
        identity.is_default = True
        identity.status = True
        identity.deleted = False
        db.flush()

    replace_identity_menus_from_position(db, identity.id, position.id)
    return user


def main() -> None:
    with SessionLocal() as db:
        tenant = db.scalar(
            select(Tenant).where(
                Tenant.name == OBSERVER_TENANT_NAME,
                Tenant.deleted.is_(False),
            )
        )
        if tenant is None:
            tenant = db.scalar(
                select(Tenant).where(
                    Tenant.name.like("%艾迪亚%"),
                    Tenant.deleted.is_(False),
                )
            )
        if tenant is None:
            raise SystemExit(f"未找到企业：{OBSERVER_TENANT_NAME}")

        position = _ensure_position(db)
        user = _ensure_user(db, tenant, position)
        db.commit()
        print(
            f"ok user_id={user.id} username={user.username!r} "
            f"tenant_id={tenant.id} tenant={tenant.name!r} "
            f"platforms={sorted(OBSERVER_PLATFORMS)}"
        )


if __name__ == "__main__":
    main()
