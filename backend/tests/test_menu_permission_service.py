"""Tests for menu permission sync helpers."""

from types import SimpleNamespace

from app.services.menu_permission_service import ensure_identity_menus_from_position, sync_identity_menus_for_position


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
