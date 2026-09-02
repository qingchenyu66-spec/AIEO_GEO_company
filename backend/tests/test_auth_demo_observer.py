"""H5 一键体验观察号登录。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.services.observer_account import OBSERVER_USERNAME

client = TestClient(app)


def test_demo_observer_login_ok(monkeypatch) -> None:
    monkeypatch.setattr(settings, "h5_observer_demo_login_enabled", True)
    resp = client.post("/api/v1/auth/demo/observer")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["code"] == 0
    session = body["data"]["session"]
    assert session["user"]["username"] == OBSERVER_USERNAME
    assert session["identity"]["identity_type"] == "CUSTOMER"
    assert any(m.get("menu_code") == "customer.workspace" for m in session.get("menus") or [])


def test_demo_observer_login_disabled(monkeypatch) -> None:
    monkeypatch.setattr(settings, "h5_observer_demo_login_enabled", False)
    resp = client.post("/api/v1/auth/demo/observer")
    assert resp.status_code == 403
    assert "暂未开放" in str(resp.json().get("detail") or "")


def test_h5_config_exposes_observer_demo_flag() -> None:
    resp = client.get("/api/v1/h5/diagnosis/config")
    assert resp.status_code == 200
    assert "observer_demo_enabled" in resp.json()["data"]
