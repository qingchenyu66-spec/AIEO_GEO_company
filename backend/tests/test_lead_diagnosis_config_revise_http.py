"""HTTP 全链路：售前诊断任务配置修改（时间段 / 平台地区锁定 / 权限）。"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
MARK = "任务配置修改联调"


def _login(username: str, password: str = "Geo@2026", *, position_code: str | None = None) -> str:
    login = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert login.status_code == 200, login.text
    data = login.json()["data"]
    if not data.get("requires_identity_selection"):
        token = (data.get("session") or {}).get("access_token")
        assert token
        return str(token)
    identities = data.get("identities") or []
    if position_code:
        picked = next((i for i in identities if i.get("position_code") == position_code), None)
        assert picked is not None, identities
        identity_id = int(picked["id"])
    else:
        identity_id = int(identities[0]["id"])
    selected = client.post(
        "/api/v1/auth/select-identity",
        json={"ticket": data["ticket"], "identity_id": identity_id},
    )
    assert selected.status_code == 200, selected.text
    token = selected.json()["data"].get("access_token")
    assert token
    return str(token)


def _future_slots(count: int = 4) -> list[str]:
    base = datetime.now().replace(second=0, microsecond=0) + timedelta(days=2)
    return [(base + timedelta(hours=5 * i)).strftime("%Y-%m-%dT%H:%M") for i in range(count)]


def _create_and_approve_lead(*, sales_token: str, reviewer_token: str, brand: str) -> int:
    create_body = {
        "brand_name": brand,
        "prompts": ["LED广告公司推荐", "公交广告公司哪家好", "广告公司排名", "本地广告服务", "品牌介绍"],
        "competitors": ["初始竞品"],
        "platforms": ["doubao"],
        "region_codes": [],
        "contact_note": "配置修改联调",
        "schedule_days": 3,
        "start_immediately": False,
    }
    created = client.post(
        "/api/v1/lead-diagnosis",
        json=create_body,
        headers={"Authorization": f"Bearer {sales_token}"},
    )
    assert created.status_code == 200, created.text
    approval_id = int(created.json()["data"]["id"])
    approved = client.post(
        f"/api/v1/approvals/{approval_id}/approve",
        json={"comment": "联调通过"},
        headers={"Authorization": f"Bearer {reviewer_token}"},
    )
    assert approved.status_code == 200, approved.text
    executed = approved.json()["data"].get("executed_result") or {}
    lead_id = int(executed.get("id") or (executed.get("result") or {}).get("id"))
    assert lead_id > 0
    return lead_id


def test_lead_config_revise_full_chain() -> None:
    sales_token = _login("Yangbojing", position_code="PLATFORM_SALES")
    reviewer_token = _login("demo")
    brand = f"{MARK}-{uuid.uuid4().hex[:8]}"
    lead_id = _create_and_approve_lead(
        sales_token=sales_token,
        reviewer_token=reviewer_token,
        brand=brand,
    )

    detail = client.get(
        f"/api/v1/lead-diagnosis/{lead_id}",
        headers={"Authorization": f"Bearer {reviewer_token}"},
    )
    assert detail.status_code == 200, detail.text
    before = detail.json()["data"]
    assert before.get("platforms") == ["doubao"]
    initial_total = int(before.get("schedule_total_count") or 0)
    assert initial_total >= 1

    future_four = _future_slots(4)
    revised = client.post(
        f"/api/v1/lead-diagnosis/{lead_id}/revise-config",
        json={
            "competitors": ["竞品A", "竞品B"],
            "platforms": ["doubao", "kimi"],
            "region_codes": ["110000"],
            "schedule_datetimes": future_four,
            "contact_note": "运营已改配置",
        },
        headers={"Authorization": f"Bearer {reviewer_token}"},
    )
    assert revised.status_code == 200, revised.text
    data = revised.json()["data"]
    assert data.get("competitors") == ["竞品A", "竞品B"]
    assert data.get("platforms") == ["doubao"], "平台应锁定不可改"
    assert data.get("region_codes") in ([], None) or data.get("region_codes") == before.get("region_codes")
    assert data.get("schedule_datetimes") == future_four
    assert int(data.get("schedule_total_count") or 0) == len(future_four)
    assert data.get("contact_note") == "运营已改配置"
    assert data.get("prompts") == before.get("prompts")

    sales_revise = client.post(
        f"/api/v1/lead-diagnosis/{lead_id}/revise-config",
        json={"competitors": ["销售不可改"]},
        headers={"Authorization": f"Bearer {sales_token}"},
    )
    assert sales_revise.status_code == 403, sales_revise.text

    past = (datetime.now() - timedelta(days=1)).replace(second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M")
    future_one = _future_slots(1)[0]
    bad_time = client.post(
        f"/api/v1/lead-diagnosis/{lead_id}/revise-config",
        json={"schedule_datetimes": [past, future_one]},
        headers={"Authorization": f"Bearer {reviewer_token}"},
    )
    assert bad_time.status_code == 400, bad_time.text
    assert "当前时间" in bad_time.json().get("detail", "")
