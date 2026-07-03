from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_root() -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["code"] == 0


def test_health() -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["data"]["database"] == "ready"


def test_api_responses_include_request_id_header() -> None:
    response = client.get("/api/v1/health")
    assert response.headers.get("X-Request-ID")

