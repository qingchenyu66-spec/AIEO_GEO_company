"""竞品分析问题下拉含历史词。"""

from fastapi.testclient import TestClient

from app.main import app
from app.services.competitor_analytics_service import _build_compare_prompt_options

client = TestClient(app)


def test_build_compare_prompt_options_appends_retired_prompts() -> None:
    options = _build_compare_prompt_options(
        ["仍在监测"],
        {"仍在监测", "旧监测词A"},
    )
    assert options == [
        {"prompt": "仍在监测", "retired": False},
        {"prompt": "旧监测词A", "retired": True},
    ]


def _demo_platform_headers() -> dict[str, str]:
    login = client.post("/api/v1/auth/login", json={"username": "demo", "password": "Geo@2026"})
    assert login.status_code == 200, login.text
    body = login.json()["data"]
    if body.get("requires_identity_selection"):
        platform = next(i for i in body["identities"] if i["identity_type"] == "PLATFORM")
        picked = client.post(
            "/api/v1/auth/select-identity",
            json={"identity_id": platform["id"], "ticket": body["ticket"]},
        )
        token = picked.json()["data"]["access_token"]
    else:
        token = body["session"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_competitor_compare_prompt_options_shape() -> None:
    headers = _demo_platform_headers()
    resp = client.get(
        "/api/v1/analytics/competitor-compare",
        headers=headers,
        params={"tenant_id": 14, "days": 7},
    )
    assert resp.status_code == 200, resp.text
    options = resp.json()["data"].get("prompt_options") or []
    assert isinstance(options, list)
    if options:
        assert isinstance(options[0], dict)
        assert "prompt" in options[0]
        assert "retired" in options[0]
