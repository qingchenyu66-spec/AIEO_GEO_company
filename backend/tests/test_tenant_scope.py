"""Tests for analytics tenant scope."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.services.tenant_scope import (
    ensure_platform_tenant_read_access,
    resolve_analytics_tenant_id,
    resolve_and_guard_analytics_tenant,
)


def _session(identity_type: str, tenant_id: int | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        identity=SimpleNamespace(identity_type=identity_type, tenant_id=tenant_id),
    )


def test_resolve_analytics_tenant_id_customer_uses_identity() -> None:
    current = _session("CUSTOMER", 6)
    assert resolve_analytics_tenant_id(current, None) == 6
    assert resolve_analytics_tenant_id(current, 99) == 6


def test_resolve_analytics_tenant_id_customer_without_tenant_raises() -> None:
    current = _session("CUSTOMER", None)
    with pytest.raises(ValueError, match="未绑定企业"):
        resolve_analytics_tenant_id(current, None)


def test_resolve_analytics_tenant_id_platform_requires_tenant() -> None:
    current = _session("PLATFORM", None)
    with pytest.raises(ValueError, match="需要指定企业"):
        resolve_analytics_tenant_id(current, None)
    assert resolve_analytics_tenant_id(current, 6) == 6


def test_ensure_platform_tenant_read_access_skips_customer() -> None:
    current = _session("CUSTOMER", 6)
    db = MagicMock()
    ensure_platform_tenant_read_access(db, current, 6)


def test_ensure_platform_tenant_read_access_requires_menu() -> None:
    current = _session("PLATFORM", None)
    current.user = SimpleNamespace(id=1)
    current.identity.id = 9
    db = MagicMock()
    with (
        patch("app.services.tenant_scope.ensure_tenant"),
        patch("app.services.tenant_scope.has_identity_menu_permission", return_value=False),
    ):
        with pytest.raises(PermissionError, match="查看权限"):
            ensure_platform_tenant_read_access(db, current, 6)


def test_resolve_and_guard_analytics_tenant_platform() -> None:
    current = _session("PLATFORM", None)
    current.user = SimpleNamespace(id=1)
    current.identity.id = 9
    db = MagicMock()
    with (
        patch("app.services.tenant_scope.ensure_tenant"),
        patch("app.services.tenant_scope.has_identity_menu_permission", return_value=True),
    ):
        assert resolve_and_guard_analytics_tenant(db, current, 6) == 6
