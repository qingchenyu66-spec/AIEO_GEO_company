"""Integration tests for lead diagnosis API."""

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


def test_lead_diagnosis_list_returns_200_with_region_code_field() -> None:
    token = _platform_token()
    response = client.get(
        "/api/v1/lead-diagnosis/list",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    rows = response.json()["data"]
    assert isinstance(rows, list)
    if rows:
        assert "region_codes" in rows[0]
        phone = rows[0].get("contact_phone")
        if phone:
            assert "****" in phone or "*" in phone
        if rows[0].get("creator"):
            assert "display_name" in rows[0]["creator"]
