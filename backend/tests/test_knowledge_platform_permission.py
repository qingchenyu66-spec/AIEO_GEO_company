"""Self-check: platform knowledge upload permission + API smoke."""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.menu_permission_service import sanitize_menu_grant_flags

client = TestClient(app)


def test_audit_files_sanitize_allows_create_and_update():
    flags = sanitize_menu_grant_flags(
        "platform.audit.files",
        "PLATFORM",
        can_create=True,
        can_update=True,
        can_delete=True,
        can_export=True,
    )
    assert flags == {
        "can_create": True,
        "can_update": True,
        "can_delete": False,
        "can_export": True,
    }


def _platform_headers() -> dict[str, str]:
    login = client.post("/api/v1/auth/login", json={"username": "demo", "password": "Geo@2026"})
    assert login.status_code == 200, login.text
    data = login.json()["data"]
    token = data.get("session", {}).get("access_token") or data.get("access_token")
    assert token
    return {"Authorization": f"Bearer {token}"}


def test_demo_session_audit_files_grant_export_only_by_default():
    headers = _platform_headers()
    me = client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    menus = me.json()["data"]["menus"]
    files_menu = next((m for m in menus if m.get("menu_code") == "platform.audit.files"), None)
    if files_menu is None:
        pytest.skip("demo 账号未授权 platform.audit.files")
    assert files_menu["can_export"] is True
    assert files_menu["can_create"] is False
    assert files_menu["can_update"] is False


def test_platform_upload_blocked_without_files_create():
    headers = _platform_headers()
    me = client.get("/api/v1/auth/me", headers=headers)
    files_menu = next(
        (m for m in me.json()["data"]["menus"] if m.get("menu_code") == "platform.audit.files"),
        None,
    )
    if files_menu and files_menu.get("can_create"):
        pytest.skip("demo 已具备上传权限，跳过 403 用例")

    tenants = client.get("/api/v1/management/tenants", headers=headers)
    assert tenants.status_code == 200, tenants.text
    rows = tenants.json()["data"]
    if not rows:
        pytest.skip("无企业可测")
    tenant_id = rows[0]["id"]

    response = client.post(
        "/api/v1/knowledge/files",
        headers=headers,
        data={"tenant_id": str(tenant_id)},
        files={"file": ("selfcheck.txt", io.BytesIO(b"geo knowledge selfcheck"), "text/plain")},
    )
    assert response.status_code == 403, response.text
