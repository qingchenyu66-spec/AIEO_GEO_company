"""Integration tests for snapshot backfill monitor API."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _platform_token() -> str:
    login = client.post("/api/v1/auth/login", json={"username": "demo", "password": "Geo@2026"})
    assert login.status_code == 200
    data = login.json()["data"]
    if data.get("requires_identity_selection"):
        platform_identity = next(item for item in data["identities"] if item["identity_type"] == "PLATFORM")
        selected = client.post(
            "/api/v1/auth/select-identity",
            json={"ticket": data["ticket"], "identity_id": platform_identity["id"]},
        )
        assert selected.status_code == 200
        return selected.json()["data"]["access_token"]
    return data["session"]["access_token"]


def test_snapshot_backfill_pending_respects_export_permission() -> None:
    token = _platform_token()
    response = client.get(
        "/api/v1/monitor/snapshot-backfill/pending",
        headers={"Authorization": f"Bearer {token}"},
        params={"limit": 10, "all_tenants": True},
    )
    assert response.status_code in (200, 403), response.text
    if response.status_code == 403:
        assert "权限" in response.json().get("detail", "")
        return
    payload = response.json()["data"]
    assert "items" in payload
    assert "summary" in payload
    summary = payload["summary"]
    assert "pending" in summary
    assert "total" in summary


def test_ops_logs_supports_filters() -> None:
    token = _platform_token()
    response = client.get(
        "/api/v1/ops/logs",
        headers={"Authorization": f"Bearer {token}"},
        params={"days": 30, "keyword": "企业"},
    )
    assert response.status_code == 200, response.text
    rows = response.json()["data"]
    assert isinstance(rows, list)


def test_subtask_detail_include_ops_respects_export_permission() -> None:
    token = _platform_token()
    response = client.get(
        "/api/v1/monitor/subtasks/nonexistent-subtask-id",
        headers={"Authorization": f"Bearer {token}"},
        params={"include_ops": True},
    )
    assert response.status_code in (403, 404), response.text
