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


def test_management_overview_returns_recent_tasks() -> None:
    token = _platform_token()
    response = client.get(
        "/api/v1/management/overview",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.json()["data"]
    assert "kpis" in payload
    assert "recent_tasks" in payload
    assert isinstance(payload["recent_tasks"], list)
    assert "molizhishu_balance" in payload
