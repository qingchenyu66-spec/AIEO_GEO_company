"""Tests for menu permission sync helpers."""

from types import SimpleNamespace

from app.services.menu_permission_service import (
    ROUTE_ONLY_MENU_CODES,
    ensure_identity_menus_from_position,
    sanitize_menu_grant_flags,
    sync_identity_menus_for_position,
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
