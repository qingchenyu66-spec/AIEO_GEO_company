"""HTTP 联调：销售提交 → 驳回 → resubmit → 通过（售前诊断）。"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
MARK = "联调驳回复活"


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


def test_approval_resubmit_chain_lead_diagnosis() -> None:
    sales_token = _login("Yangbojing", position_code="PLATFORM_SALES")
    reviewer_token = _login("demo")
    brand = f"{MARK}-{uuid.uuid4().hex[:8]}"
    create_body = {
        "brand_name": brand,
        "prompts": ["LED广告公司推荐", "公交广告公司哪家好", "广告公司排名", "本地广告服务", "品牌介绍"],
        "competitors": ["竞品A"],
        "platforms": ["doubao"],
        "region_codes": [],
        "contact_note": "初次提交",
        "schedule_days": 3,
        "start_immediately": False,
    }
    created = client.post(
        "/api/v1/lead-diagnosis",
        json=create_body,
        headers={"Authorization": f"Bearer {sales_token}"},
    )
    assert created.status_code == 200, created.text
    data = created.json()["data"]
    assert data.get("pending_approval") is True, data
    approval_id = int(data["id"])

    rejected = client.post(
        f"/api/v1/approvals/{approval_id}/reject",
        json={"comment": "请补充竞品与平台"},
        headers={"Authorization": f"Bearer {reviewer_token}"},
    )
    assert rejected.status_code == 200, rejected.text
    rejected_data = rejected.json()["data"]
    assert rejected_data.get("status") == "rejected"

    create_body["competitors"] = ["竞品A", "竞品B"]
    create_body["platforms"] = ["doubao", "kimi"]
    create_body["contact_note"] = "已补竞品和平台"
    resubmitted = client.post(
        f"/api/v1/approvals/{approval_id}/resubmit",
        json={"body": create_body},
        headers={"Authorization": f"Bearer {sales_token}"},
    )
    assert resubmitted.status_code == 200, resubmitted.text
    pending = resubmitted.json()["data"]
    assert pending.get("status") == "pending"
    assert pending.get("resubmitted") is True
    body = pending.get("lead_adopted_body") or (pending.get("payload") or {}).get("body") or {}
    assert body.get("competitors") == ["竞品A", "竞品B"]

    approved = client.post(
        f"/api/v1/approvals/{approval_id}/approve",
        json={"comment": "联调通过"},
        headers={"Authorization": f"Bearer {reviewer_token}"},
    )
    assert approved.status_code == 200, approved.text
    approved_data = approved.json()["data"]
    assert approved_data.get("status") == "approved"
    executed = approved_data.get("executed_result") or {}
    assert executed.get("id") or (executed.get("result") or {}).get("id")

    final = client.get(
        f"/api/v1/approvals/{approval_id}",
        headers={"Authorization": f"Bearer {reviewer_token}"},
    )
    assert final.status_code == 200, final.text
    final_data = final.json()["data"]
    assert final_data.get("status") == "approved"
    assert len(final_data.get("rejection_history") or []) >= 1
