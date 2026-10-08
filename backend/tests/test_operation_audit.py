"""Tests for operation audit operator resolution."""

from types import SimpleNamespace

from app.middleware.operation_audit import (
    _should_audit,
    _skip_anonymous_probe,
    build_audit_description,
    resolve_audit_operator,
)


def test_resolve_audit_operator_without_token() -> None:
    request = SimpleNamespace(
        headers={},
        cookies={},
    )
    name, user_id, tenant_id = resolve_audit_operator(request)  # type: ignore[arg-type]
    assert name == "匿名请求"
    assert user_id is None
    assert tenant_id is None


def test_build_audit_description_switch_identity() -> None:
    request = SimpleNamespace(method="POST", url=SimpleNamespace(path="/api/v1/auth/switch-identity"), query_params={})
    assert build_audit_description(request) == "切换登录身份：切换到其他已授权身份"  # type: ignore[arg-type]


def test_molizhishu_callback_skipped_from_audit() -> None:
    assert _should_audit("POST", "/api/v1/monitor/molizhishu/callback") is False
    assert _should_audit("POST", "/api/v1/monitor/molizhishu/callback/") is False
    assert _should_audit("POST", "/api/v1/monitor/tasks") is True


def test_keyword_miner_paths_skipped_from_middleware_audit() -> None:
    """选词 API 整段跳过中间件; 业务审计由 service 显式写入."""
    assert _should_audit("PUT", "/api/v1/keyword-miner/jobs/4bd7dd5dcb5bf208") is False
    assert _should_audit("PUT", "/api/v1/keyword-miner/jobs/4bd7dd5dcb5bf208/") is False
    assert _should_audit("PUT", "/api/v1/keyword-miner/jobs/4bd7dd5dcb5bf208/edits") is False
    assert _should_audit("POST", "/api/v1/keyword-miner/examples/batch") is False
    assert _should_audit("PATCH", "/api/v1/keyword-miner/examples/9") is False


def test_unauthenticated_writes_not_audited() -> None:
    """未登录的写操作不落审计, 不论成功还是失败."""
    assert _skip_anonymous_probe(None, 200) is True
    assert _skip_anonymous_probe(None, 400) is True
    assert _skip_anonymous_probe(None, 404) is True
    assert _skip_anonymous_probe(None, 500) is True
    assert _skip_anonymous_probe(12, 404) is False
    assert _skip_anonymous_probe(12, 200) is False
