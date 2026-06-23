from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_dual_identity_login_and_select() -> None:
    login = client.post("/api/v1/auth/login", json={"username": "demo", "password": "Geo@2026"})
    assert login.status_code == 200
    data = login.json()["data"]
    assert data["requires_identity_selection"] is True
    assert len(data["identities"]) == 2

    platform_identity = next(item for item in data["identities"] if item["identity_type"] == "PLATFORM")
    selected = client.post("/api/v1/auth/select-identity", json={"ticket": data["ticket"], "identity_id": platform_identity["id"]})
    assert selected.status_code == 200
    session = selected.json()["data"]
    assert session["identity"]["identity_type"] == "PLATFORM"

    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {session['access_token']}"})
    assert me.status_code == 200
    assert me.json()["data"]["identity"]["identity_type"] == "PLATFORM"

    customer_identity = next(item for item in session["identities"] if item["identity_type"] == "CUSTOMER")
    switched = client.post(
        "/api/v1/auth/switch-identity",
        json={"identity_id": customer_identity["id"]},
        headers={"Authorization": f"Bearer {session['access_token']}"},
    )
    assert switched.status_code == 200
    assert switched.json()["data"]["identity"]["identity_type"] == "CUSTOMER"


def test_single_identity_login() -> None:
    login = client.post("/api/v1/auth/login", json={"username": "client", "password": "Client@2026"})
    assert login.status_code == 200
    data = login.json()["data"]
    assert data["requires_identity_selection"] is False
    assert data["session"]["identity"]["identity_type"] == "CUSTOMER"
