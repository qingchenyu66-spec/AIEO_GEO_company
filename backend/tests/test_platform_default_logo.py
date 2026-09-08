"""平台默认 Logo：复用 tenant_logo_service 磁盘规范。"""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import CurrentSession, get_current_session
from app.main import app
from app.services import tenant_logo_service as logo_svc


@pytest.fixture
def platform_logo_client(monkeypatch, tmp_path):
    monkeypatch.setattr(logo_svc, "STORAGE_ROOT", tmp_path / "tenant-logos")
    session = CurrentSession(
        user=type("U", (), {"id": 1, "display_name": "admin"})(),
        identity=type("I", (), {"id": 1, "identity_type": "PLATFORM", "position_id": 1})(),
    )
    app.dependency_overrides[get_current_session] = lambda: session
    monkeypatch.setattr(
        "app.api.v1.endpoints.management.require_system_config_access",
        lambda *a, **k: None,
    )
    monkeypatch.setattr("app.api.v1.endpoints.management.write_management_log", lambda *a, **k: None)
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


def test_platform_logo_upload_get_clear(platform_logo_client, tmp_path):
    client = platform_logo_client
    png = io.BytesIO(b"\x89PNG\r\n\x1a\n" + b"x" * 64)

    meta0 = client.get("/api/v1/management/platform-brand/logo/meta")
    assert meta0.status_code == 200
    assert meta0.json()["data"]["has_logo"] is False

    upload = client.post(
        "/api/v1/management/platform-brand/logo",
        files={"file": ("logo.png", png, "image/png")},
    )
    assert upload.status_code == 200, upload.text
    assert upload.json()["data"]["has_logo"] is True

    stored = tmp_path / "tenant-logos" / "_platform" / "logo.png"
    assert stored.is_file()

    fetch = client.get("/api/v1/management/platform-brand/logo")
    assert fetch.status_code == 200
    assert fetch.headers["content-type"].startswith("image/")

    cleared = client.delete("/api/v1/management/platform-brand/logo")
    assert cleared.status_code == 200
    assert cleared.json()["data"]["has_logo"] is False
    assert not stored.exists()
