"""2026-09-02 - credit 助手缺失时 /auth 会话不得 500。"""
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.api.v1.endpoints import auth as auth_ep


def test_session_payload_survives_missing_credit_helper(monkeypatch) -> None:
    user = SimpleNamespace(id=1, username="xin", display_name="Xin", must_change_password=False)
    identity = SimpleNamespace(
        id=10,
        identity_type="CUSTOMER",
        identity_name="客户",
        role_code="customer",
        position_id=None,
        tenant_id=99,
        tenant=None,
        is_default=True,
    )
    db = MagicMock()
    monkeypatch.setattr(auth_ep, "ensure_identity_menus_from_position", lambda *_a, **_k: False)
    monkeypatch.setattr(auth_ep, "get_identity_menus", lambda *_a, **_k: [])
    monkeypatch.setattr(
        "app.services.menu_permission_service.identity_allowed_monitor_platforms",
        lambda *_a, **_k: [],
    )
    monkeypatch.setattr(auth_ep, "create_access_token", lambda *_a, **_k: "tok")
    monkeypatch.setattr(auth_ep, "identity_info", lambda ident, _db: {"id": ident.id})
    # 无 credit_customer_includes_today 属性 → from-import 抛 ImportError
    monkeypatch.setitem(sys.modules, "app.services.monitor_service", SimpleNamespace())

    payload = auth_ep.session_payload(db, user, identity, [identity])
    assert payload["customer_includes_today"] is False
    assert payload["access_token"] == "tok"
