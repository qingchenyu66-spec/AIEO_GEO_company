"""方案 A：空白名单可清脏；非空白名单须 400。"""
from fastapi.testclient import TestClient

from app.main import app


def _token(client: TestClient) -> dict:
    r = client.post("/api/v1/auth/login", json={"username": "demo", "password": "Geo@2026"})
    assert r.status_code == 200
    data = r.json()["data"]
    token = (data.get("session") or {}).get("access_token") or client.cookies.get("geo_access_token")
    if not token and data.get("ticket"):
        pick = (data.get("identities") or [{}])[0]
        r2 = client.post(
            "/api/v1/auth/select-identity",
            json={"ticket": data["ticket"], "identity_id": pick["id"]},
        )
        body = r2.json()["data"]
        token = body.get("access_token") or (body.get("session") or {}).get("access_token")
        if not token:
            token = client.cookies.get("geo_access_token")
    assert token
    return {"Authorization": f"Bearer {token}"}


def test_credit_policy_empty_whitelist_ok_nonempty_rejected():
    # 2026-09-08 - 方案 A：空列表可清脏；非空白名单禁止写入
    from sqlalchemy import select

    from app.core.database import SessionLocal
    from app.models.tenant import Tenant

    db = SessionLocal()
    try:
        tenant = db.scalar(select(Tenant).where(Tenant.code == "AIDIYA_CREDIT_TEST", Tenant.deleted.is_(False)))
        assert tenant is not None
        tenant_id = tenant.id
    finally:
        db.close()

    client = TestClient(app)
    headers = _token(client)
    r = client.put(
        f"/api/v1/management/credit/tenants/{tenant_id}/policy",
        headers=headers,
        json={"platform_whitelist": []},
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["platform_whitelist"] == []

    r2 = client.put(
        f"/api/v1/management/credit/tenants/{tenant_id}/policy",
        headers=headers,
        json={"platform_whitelist": ["doubao"]},
    )
    assert r2.status_code == 400, r2.text
    assert "白名单" in (r2.json().get("detail") or "")
