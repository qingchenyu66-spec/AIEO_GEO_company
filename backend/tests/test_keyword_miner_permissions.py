"""GEO 选词范例权限与挖词出站校验."""

from __future__ import annotations

import importlib.util
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services import keyword_miner_service as kms


def test_require_examples_need_update_uses_write_actions(monkeypatch):
    seen: list[tuple[str, tuple[str, ...]]] = []

    def fake_has(_db, _identity_id, menu_code, actions):
        seen.append((menu_code, tuple(actions)))
        return False

    monkeypatch.setattr(kms, "has_any_identity_menu_permission", fake_has)
    monkeypatch.setattr(kms, "require_platform", lambda _c: None)
    current = SimpleNamespace(identity=SimpleNamespace(id=1))
    with pytest.raises(PermissionError):
        kms._require_examples(MagicMock(), current, need_update=True)
    assert seen
    assert seen[0][1] == ("can_update", "can_create")
    assert "can_export" not in seen[0][1]


def test_require_examples_read_allows_export(monkeypatch):
    seen: list[tuple[str, ...]] = []

    def fake_has(_db, _identity_id, menu_code, actions):
        seen.append(tuple(actions))
        return "can_export" in actions

    monkeypatch.setattr(kms, "has_any_identity_menu_permission", fake_has)
    monkeypatch.setattr(kms, "require_platform", lambda _c: None)
    current = SimpleNamespace(identity=SimpleNamespace(id=1))
    kms._require_examples(MagicMock(), current, need_update=False)
    assert seen[0] == ("can_export", "can_create", "can_update")


def _load_miner_app():
    path = Path(__file__).resolve().parents[2] / "services" / "keyword-miner" / "app.py"
    spec = importlib.util.spec_from_file_location("keyword_miner_app_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def test_validate_mine_payload_rejects_empty():
    app = _load_miner_app()
    with pytest.raises(ValueError, match="至少填写"):
        app.validate_mine_payload({})
    with pytest.raises(ValueError, match="平台"):
        app.validate_mine_payload({"company": "艾迪亚", "platforms": []})


def test_validate_mine_payload_rejects_private_web_url():
    app = _load_miner_app()
    with pytest.raises(ValueError, match="内网"):
        app.validate_mine_payload({
            "company": "艾迪亚",
            "platforms": ["kimi"],
            "web_url": "http://127.0.0.1/secret",
        })


def test_dingtalk_webhook_host_whitelist():
    app = _load_miner_app()
    assert app.is_allowed_dingtalk_webhook(
        "https://oapi.dingtalk.com/robot/send?access_token=x"
    )
    assert not app.is_allowed_dingtalk_webhook("http://oapi.dingtalk.com/robot/send?access_token=x")
    assert not app.is_allowed_dingtalk_webhook("https://evil.example.com/hook")
    assert not app.is_allowed_dingtalk_webhook("https://127.0.0.1/hook")


def test_safe_redirect_handler_blocks_private_target():
    app = _load_miner_app()
    handler = app._SafeRedirectHandler()
    assert handler.max_redirections == 3
    assert handler.max_repeats == 3
    req = urllib.request.Request("https://example.com/start")
    with pytest.raises(urllib.error.HTTPError) as ei:
        handler.redirect_request(
            req, None, 302, "Found", {}, "http://127.0.0.1/meta"
        )
    assert ei.value.code == 403


def test_touch_examples_increments_use_count(monkeypatch):
    row = SimpleNamespace(id=9, use_count=2, status="active")
    db = MagicMock()
    db.scalars.return_value.all.return_value = [row]
    monkeypatch.setattr(kms, "_require_workbench", lambda *_a, **_k: None)
    current = SimpleNamespace(identity=SimpleNamespace(id=1), user=SimpleNamespace(id=1))
    out = kms.touch_examples(db, current, [9, 9, "x", 0])
    assert out["updated"] == 1
    assert row.use_count == 3
