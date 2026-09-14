"""Tests for menu permission sync helpers."""

from types import SimpleNamespace

from app.schemas.permission import MenuInfo
from app.services.menu_permission_service import (
    ROUTE_ONLY_MENU_CODES,
    _filter_items_by_menu_config_visibility,
    _keep_in_session_despite_config_hidden,
    ensure_identity_menus_from_position,
    heal_empty_identity_menus,
    merge_grant_flags,
    sanitize_menu_grant_flags,
    sync_identity_menus_for_position,
    sync_menu_row_from_config,
)


def test_audit_list_allows_stop_service_delete_flag():
    flags = sanitize_menu_grant_flags(
        "platform.audit.list",
        "PLATFORM",
        can_create=False,
        can_update=True,
        can_delete=True,
        can_export=True,
    )
    assert flags == {
        "can_create": False,
        "can_update": True,
        "can_delete": True,
        "can_export": True,
    }


def test_users_create_menu_is_route_only_not_assignable():
    assert "platform.users.create" in ROUTE_ONLY_MENU_CODES


def test_settings_parent_is_route_only_children_assignable():
    assert "platform.settings" in ROUTE_ONLY_MENU_CODES
    for code in (
        "platform.settings.secrets",
        "platform.settings.schedule",
        "platform.settings.cache_queue",
        "platform.settings.notification",
        "platform.settings.menu",
    ):
        assert code not in ROUTE_ONLY_MENU_CODES
        flags = sanitize_menu_grant_flags(
            code,
            "PLATFORM",
            can_create=True,
            can_update=True,
            can_delete=True,
            can_export=True,
        )
    assert flags == {
        "can_create": False,
        "can_update": True,
        "can_delete": False,
        "can_export": True,
    }


def test_product_capability_codes_are_not_position_grants():
    from app.services.menu_permission_service import is_product_capability_menu_code

    assert is_product_capability_menu_code("customer.goods_cards")
    assert is_product_capability_menu_code("customer.enterprise_config")
    assert not is_product_capability_menu_code("customer.workspace")
    assert not is_product_capability_menu_code("platform.credit_ops_board")


def test_users_create_child_does_not_get_export_flag():
    flags = sanitize_menu_grant_flags(
        "platform.users.create.platform",
        "PLATFORM",
        can_create=True,
        can_update=True,
        can_delete=True,
        can_export=True,
    )
    assert flags == {
        "can_create": True,
        "can_update": False,
        "can_delete": False,
        "can_export": False,
    }


def test_sync_identity_menus_for_position_calls_replace(monkeypatch):
    calls: list[tuple[int, int]] = []

    def fake_replace(db, identity_id, position_id, selected_menu_ids=None):
        calls.append((identity_id, position_id))

    monkeypatch.setattr(
        "app.services.menu_permission_service.replace_identity_menus_from_position",
        fake_replace,
    )

    class FakeScalars:
        def __init__(self, values):
            self._values = values

        def __iter__(self):
            return iter(self._values)

    class FakeSession:
        def scalars(self, stmt):
            return FakeScalars([11, 12])

    count = sync_identity_menus_for_position(FakeSession(), 5)
    assert count == 2
    assert calls == [(11, 5), (12, 5)]


def test_ensure_identity_menus_from_position_syncs_when_drift(monkeypatch):
    replace_calls: list[tuple[int, int]] = []

    def fake_match(db, identity_id, position_id):
        return False

    def fake_replace(db, identity_id, position_id, selected_menu_ids=None):
        replace_calls.append((identity_id, position_id))

    class FakeScalar:
        def __init__(self, value):
            self._value = value

        def limit(self, _n):
            return self

        def __bool__(self):
            return self._value is not None

    class FakeSession:
        def scalar(self, _stmt):
            return FakeScalar(1)

    monkeypatch.setattr(
        "app.services.menu_permission_service.identity_menus_match_position",
        fake_match,
    )
    monkeypatch.setattr(
        "app.services.menu_permission_service.replace_identity_menus_from_position",
        fake_replace,
    )

    identity = SimpleNamespace(id=9, position_id=3)
    changed = ensure_identity_menus_from_position(FakeSession(), identity)
    assert changed is True
    assert replace_calls == [(9, 3)]


def test_ensure_identity_menus_from_position_skips_when_matched(monkeypatch):
    replace_calls: list[tuple[int, int]] = []

    def fake_match(db, identity_id, position_id):
        return True

    def fake_replace(db, identity_id, position_id, selected_menu_ids=None):
        replace_calls.append((identity_id, position_id))

    class FakeScalar:
        def limit(self, _n):
            return self

    class FakeSession:
        def scalar(self, _stmt):
            return FakeScalar()

    monkeypatch.setattr(
        "app.services.menu_permission_service.identity_menus_match_position",
        fake_match,
    )
    monkeypatch.setattr(
        "app.services.menu_permission_service.replace_identity_menus_from_position",
        fake_replace,
    )

    identity = SimpleNamespace(id=9, position_id=3)
    changed = ensure_identity_menus_from_position(FakeSession(), identity)
    assert changed is False
    assert replace_calls == []


def test_heal_empty_identity_menus_skips_non_empty(monkeypatch):
    empty = SimpleNamespace(id=1, position_id=3)
    filled = SimpleNamespace(id=2, position_id=3)
    ensure_ids: list[int] = []
    menu_hits = iter([None, 88])

    class FakeScalars:
        def __iter__(self):
            return iter([empty, filled])

    class FakeSession:
        def scalars(self, _stmt):
            return FakeScalars()

        def scalar(self, _stmt):
            return next(menu_hits)

    monkeypatch.setattr(
        "app.services.menu_permission_service.ensure_identity_menus_from_position",
        lambda _db, identity: ensure_ids.append(identity.id) or True,
    )

    count = heal_empty_identity_menus(FakeSession())
    assert count == 1
    assert ensure_ids == [1]


def test_sync_menu_row_from_config_overwrites_sys_menu_name():
    menu = SimpleNamespace(
        menu_code="customer.workspace",
        identity_type="CUSTOMER",
        menu_name="运营工作台",
        sort_order=10,
        icon="Old",
        route_path="/old",
    )
    config = SimpleNamespace(
        menu_code="customer.workspace",
        identity_type="CUSTOMER",
        menu_name="品牌概览",
        sort_order=10,
        icon="LayoutDashboard",
        route_path="/customer/workspace",
    )

    class FakeSession:
        def scalar(self, _stmt):
            return menu

    synced = sync_menu_row_from_config(FakeSession(), config)
    assert synced is menu
    assert menu.menu_name == "品牌概览"
    assert menu.icon == "LayoutDashboard"
    assert menu.route_path == "/customer/workspace"
    assert menu.sort_order == 10


def test_session_keeps_nested_permissions_when_config_hidden():
    assert _keep_in_session_despite_config_hidden("platform.settings.secrets")
    assert _keep_in_session_despite_config_hidden("platform.audit.purge")
    assert _keep_in_session_despite_config_hidden("platform.credit_ops_board")
    assert _keep_in_session_despite_config_hidden("platform.tenant_credit")
    assert _keep_in_session_despite_config_hidden("customer.enterprise_credit")
    assert not _keep_in_session_despite_config_hidden("customer.links")
    assert not _keep_in_session_despite_config_hidden("customer.diagnosis")
    assert not _keep_in_session_despite_config_hidden("customer.goods_cards")


def test_goods_card_product_permission_requires_tenant_flag():
    from app.services.menu_permission_service import _has_goods_card_product_permission

    identity = SimpleNamespace(id=9, identity_type="CUSTOMER", tenant_id=3)
    tenant_on = SimpleNamespace(id=3, deleted=False, goods_card_enabled=True)
    tenant_off = SimpleNamespace(id=3, deleted=False, goods_card_enabled=False)

    class FakeSession:
        def __init__(self, tenant):
            self._tenant = tenant

        def get(self, model, key):
            name = getattr(model, "__name__", str(model))
            if "UserIdentity" in name or key == 9:
                return identity
            if "Tenant" in name or key == 3:
                return self._tenant
            return None

    assert _has_goods_card_product_permission(FakeSession(tenant_on), 9, "can_export") is True
    assert _has_goods_card_product_permission(FakeSession(tenant_on), 9, "can_update") is False
    assert _has_goods_card_product_permission(FakeSession(tenant_off), 9, "can_export") is False


def test_filter_menu_config_visibility_keeps_settings_children():
    items = [
        SimpleNamespace(menu_code="platform.settings.secrets", menu_name="接口密钥"),
        SimpleNamespace(menu_code="customer.links", menu_name="推广链接"),
        SimpleNamespace(menu_code="platform.reports", menu_name="报告中心"),
    ]
    configs = {
        "platform.settings.secrets": SimpleNamespace(menu_code="platform.settings.secrets", is_visible=False),
        "customer.links": SimpleNamespace(menu_code="customer.links", is_visible=False),
        "platform.reports": SimpleNamespace(menu_code="platform.reports", is_visible=True),
    }

    class FakeScalars:
        def __init__(self, values):
            self._values = values

        def __iter__(self):
            return iter(self._values)

    class FakeSession:
        def scalars(self, _stmt):
            return FakeScalars(configs.values())

    kept = _filter_items_by_menu_config_visibility(FakeSession(), items, "PLATFORM")
    codes = [item.menu_code for item in kept]
    assert "platform.settings.secrets" in codes
    assert "platform.reports" in codes
    assert "customer.links" not in codes


def test_merge_grant_flags_keeps_parent_sidebar_flag():
    parent = MenuInfo(
        id=1,
        menu_code="platform.settings",
        menu_name="系统配置",
        identity_type="PLATFORM",
        route_path="/portal/settings",
        icon="Setting",
        sort_order=90,
        can_create=False,
        can_update=False,
        can_delete=False,
        can_export=False,
        show_in_sidebar=True,
    )
    child = MenuInfo(
        id=2,
        menu_code="platform.settings.secrets",
        menu_name="接口密钥",
        identity_type="PLATFORM",
        route_path="/portal/settings",
        icon="Key",
        sort_order=91,
        can_create=False,
        can_update=True,
        can_delete=False,
        can_export=True,
        show_in_sidebar=False,
    )
    merged = merge_grant_flags(parent, child)
    assert merged.show_in_sidebar is True
    assert merged.sort_order == 90
    assert merged.can_update is True
    assert merged.can_export is True


def test_credit_ops_board_allows_update_flag():
    flags = sanitize_menu_grant_flags(
        "platform.credit_ops_board",
        "PLATFORM",
        can_create=True,
        can_update=True,
        can_delete=True,
        can_export=True,
    )
    assert flags == {
        "can_create": False,
        "can_update": True,
        "can_delete": False,
        "can_export": True,
    }