"""平台端客户门户预览：tenant 解析与鉴权。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services import tenant_scope


def test_resolve_customer_preview_rejects_non_platform() -> None:
    current = SimpleNamespace(
        identity=SimpleNamespace(identity_type="CUSTOMER", id=1, tenant_id=6),
        user=SimpleNamespace(id=1),
    )
    with pytest.raises(PermissionError):
        tenant_scope.resolve_customer_preview_tenant_id(MagicMock(), current, 6)


def test_resolve_customer_preview_requires_tenant_id() -> None:
    current = SimpleNamespace(
        identity=SimpleNamespace(identity_type="PLATFORM", id=1, tenant_id=None),
        user=SimpleNamespace(id=1),
    )
    with pytest.raises(ValueError, match="需指定企业"):
        tenant_scope.resolve_customer_preview_tenant_id(MagicMock(), current, None)


def test_resolve_customer_preview_requires_audit_menu(monkeypatch: pytest.MonkeyPatch) -> None:
    current = SimpleNamespace(
        identity=SimpleNamespace(identity_type="PLATFORM", id=1, tenant_id=None),
        user=SimpleNamespace(id=1),
    )
    monkeypatch.setattr(tenant_scope, "has_identity_menu_permission", lambda *_a, **_k: False)
    with pytest.raises(PermissionError, match="无权预览"):
        tenant_scope.resolve_customer_preview_tenant_id(MagicMock(), current, 6)


def test_resolve_customer_preview_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    current = SimpleNamespace(
        identity=SimpleNamespace(identity_type="PLATFORM", id=1, tenant_id=None),
        user=SimpleNamespace(id=1),
    )
    monkeypatch.setattr(tenant_scope, "has_identity_menu_permission", lambda *_a, **_k: True)
    monkeypatch.setattr(tenant_scope, "resolve_and_guard_tenant_id", lambda *_a, **_k: 6)
    assert tenant_scope.resolve_customer_preview_tenant_id(MagicMock(), current, 6) == 6
