"""已下线平台菜单常量与过滤逻辑。"""

from unittest.mock import MagicMock

from app.services.menu_permission_service import (
    RETIRED_PLATFORM_MENU_CODES,
    _allowed_actions_for_menu,
    is_retired_menu_code,
)
from app.services.permission_service import list_menus_by_identity_type


def test_retired_platform_menu_codes():
    assert "platform.plans" in RETIRED_PLATFORM_MENU_CODES
    assert "platform.admins" in RETIRED_PLATFORM_MENU_CODES
    assert "platform.diagnosis" in RETIRED_PLATFORM_MENU_CODES
    assert not is_retired_menu_code("platform.dashboard")


def test_retired_menus_have_no_allowed_actions():
    for code in RETIRED_PLATFORM_MENU_CODES:
        assert _allowed_actions_for_menu(code, "PLATFORM") == frozenset()


def test_list_menus_excludes_retired():
    db = MagicMock()
    active = MagicMock(menu_code="platform.dashboard")
    retired = MagicMock(menu_code="platform.plans")
    db.scalars.return_value = [active, retired]
    menus = list_menus_by_identity_type(db, "PLATFORM")
    assert [menu.menu_code for menu in menus] == ["platform.dashboard"]
