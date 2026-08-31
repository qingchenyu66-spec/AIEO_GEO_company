"""9.9 H5 付费诊断公开接口烟测。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app

client = TestClient(app)


def test_h5_diagnosis_public_config() -> None:
    resp = client.get("/api/v1/h5/diagnosis/config")
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    data = body["data"]
    assert data["price_fen"] == 990
    assert isinstance(data["platforms"], list)
    assert data["platforms"]


def test_h5_diagnosis_order_rejects_invalid_phone() -> None:
    client.cookies.set("geo_h5_wx_openid", "pytest-openid-h5")
    resp = client.post(
        "/api/v1/h5/diagnosis/orders",
        json={
            "wechat_id": "wx_test_user",
            "contact_phone": "43646944949",
            "brand_name": "测试品牌",
            "prompts": ["蛋白粉推荐"],
        },
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "请填写正确的手机号"


def test_h5_diagnosis_order_accepts_without_wechat(monkeypatch) -> None:
    monkeypatch.setattr(settings, "wechat_pay_dev_mode", True)
    monkeypatch.setattr(
        "app.services.lead_diagnosis_service.submit_due_lead_run",
        lambda *args, **kwargs: None,
    )
    client.cookies.set("geo_h5_wx_openid", "pytest-openid-h5-nowx")
    resp = client.post(
        "/api/v1/h5/diagnosis/orders",
        json={
            "contact_phone": "13800138001",
            "brand_name": "无微信号品牌",
            "prompts": ["蛋白粉推荐"],
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["code"] == 0


def test_h5_diagnosis_order_dev_paid_flow(monkeypatch) -> None:
    monkeypatch.setattr(settings, "wechat_pay_dev_mode", True)
    monkeypatch.setattr(
        "app.services.lead_diagnosis_service.submit_due_lead_run",
        lambda *args, **kwargs: None,
    )
    client.cookies.set("geo_h5_wx_openid", "pytest-openid-h5")

    create_resp = client.post(
        "/api/v1/h5/diagnosis/orders",
        json={
            "wechat_id": "wx_test_user",
            "contact_phone": "13800138000",
            "brand_name": "H5测试品牌",
            "prompts": ["蛋白粉推荐", "蛋白粉哪家好"],
            "industry": "蛋白粉",
            "brand_aliases": "简称A, 简称B",
            "competitors": "竞品甲",
        },
    )
    assert create_resp.status_code == 200, create_resp.text
    create_body = create_resp.json()
    assert create_body["code"] == 0
    out_trade_no = create_body["data"]["out_trade_no"]
    assert create_body["data"]["pay_params"]["devAutoPaid"] is True

    paid_resp = client.post(f"/api/v1/h5/diagnosis/orders/{out_trade_no}/dev-paid")
    assert paid_resp.status_code == 200, paid_resp.text
    paid_body = paid_resp.json()
    assert paid_body["data"]["status"] == "paid"
    assert paid_body["data"]["lead_diagnosis_id"]

    from app.core.database import SessionLocal
    from app.models.lead_diagnosis import LeadDiagnosis

    db = SessionLocal()
    try:
        lead = db.get(LeadDiagnosis, paid_body["data"]["lead_diagnosis_id"])
        assert lead is not None
        assert list(lead.brand_aliases_json or []) == ["简称A", "简称B"]
        assert list(lead.competitors_json or []) == ["竞品甲"]
    finally:
        db.close()
