"""平台端只读预览客户工作台：鉴权与 tenant 解析。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.api.v1.endpoints import monitor as monitor_ep


def test_platform_workspace_brief_requires_tenant_id(monkeypatch: pytest.MonkeyPatch) -> None:
    current = SimpleNamespace(
        identity=SimpleNamespace(identity_type="PLATFORM", id=1, tenant_id=None),
        user=SimpleNamespace(id=1, display_name="ops", username="ops"),
    )
    monkeypatch.setattr(
        "app.services.tenant_scope.has_identity_menu_permission",
        lambda *_a, **_k: True,
    )

    with pytest.raises(HTTPException) as exc:
        monitor_ep.monitor_workspace_brief(
            start_date=None,
            end_date=None,
            tenant_id=None,
            record_access=False,
            current=current,
            db=MagicMock(),
        )
    assert exc.value.status_code == 400


def test_platform_workspace_brief_rejects_without_audit_menu(monkeypatch: pytest.MonkeyPatch) -> None:
    current = SimpleNamespace(
        identity=SimpleNamespace(identity_type="PLATFORM", id=1, tenant_id=None),
        user=SimpleNamespace(id=1, display_name="ops", username="ops"),
    )
    monkeypatch.setattr(
        "app.services.tenant_scope.has_identity_menu_permission",
        lambda *_a, **_k: False,
    )

    with pytest.raises(HTTPException) as exc:
        monitor_ep.monitor_workspace_brief(
            start_date=None,
            end_date=None,
            tenant_id=6,
            record_access=False,
            current=current,
            db=MagicMock(),
        )
    assert exc.value.status_code == 403


def test_platform_workspace_brief_uses_guarded_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    current = SimpleNamespace(
        identity=SimpleNamespace(identity_type="PLATFORM", id=1, tenant_id=None),
        user=SimpleNamespace(id=1, display_name="ops", username="ops"),
    )
    seen: dict[str, object] = {}

    monkeypatch.setattr(
        "app.services.tenant_scope.has_identity_menu_permission",
        lambda *_a, **_k: True,
    )
    monkeypatch.setattr(
        "app.services.tenant_scope.resolve_and_guard_tenant_id",
        lambda _db, _current, tenant_id: tenant_id,
    )
    monkeypatch.setattr(
        monitor_ep,
        "get_or_build_json_cache",
        lambda _key, builder, ttl_seconds=0: builder(),
    )

    def fake_brief(db, current, *, start_date=None, end_date=None, tenant_id=None):
        seen["tenant_id"] = tenant_id
        return {"ok": True, "tenant_id": tenant_id}

    monkeypatch.setattr(monitor_ep, "workspace_brief", fake_brief)

    resp = monitor_ep.monitor_workspace_brief(
        start_date=None,
        end_date=None,
        tenant_id=6,
        record_access=False,
        current=current,
        db=MagicMock(),
    )
    assert resp.data["ok"] is True
    assert seen["tenant_id"] == 6
