"""Tests for operation audit operator resolution."""

from types import SimpleNamespace

from app.middleware.operation_audit import build_audit_description, resolve_audit_operator


def test_resolve_audit_operator_without_token() -> None:
    request = SimpleNamespace(
        headers={},
        cookies={},
    )
    name, user_id, tenant_id = resolve_audit_operator(request)  # type: ignore[arg-type]
    assert name == "未登录用户"
    assert user_id is None
    assert tenant_id is None


def test_build_audit_description_switch_identity() -> None:
    request = SimpleNamespace(method="POST", url=SimpleNamespace(path="/api/v1/auth/switch-identity"), query_params={})
    assert build_audit_description(request) == "切换登录身份：切换到其他已授权身份"  # type: ignore[arg-type]
