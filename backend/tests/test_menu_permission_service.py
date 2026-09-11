"""Tests for menu permission sync helpers."""

from types import SimpleNamespace

from app.services.menu_permission_service import (
    ROUTE_ONLY_MENU_CODES,
    ensure_identity_menus_from_position,
    heal_empty_identity_menus,
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
