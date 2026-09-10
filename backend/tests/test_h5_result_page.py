"""H5 自助结果页 + ready 短信钩子。"""

from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.database import SessionLocal
from app.main import app
from app.models.h5_diagnosis_order import H5DiagnosisOrder
from app.models.lead_diagnosis import LeadDiagnosis
from sqlalchemy import select

client = TestClient(app)


def _create_paid_order(monkeypatch, *, phone: str = "13900139001", openid: str = "pytest-openid-result") -> dict:
    monkeypatch.setattr(settings, "wechat_pay_dev_mode", True)
    monkeypatch.setattr(
        "app.services.lead_diagnosis_service.submit_due_lead_run",
        lambda *args, **kwargs: None,
    )
    client.cookies.set("geo_h5_wx_openid", openid)
    create_resp = client.post(
        "/api/v1/h5/diagnosis/orders",
        json={
            "contact_phone": phone,
            "brand_name": "结果页品牌",
            "prompts": ["蛋白粉推荐"],
        },
    )
    assert create_resp.status_code == 200, create_resp.text
    out_trade_no = create_resp.json()["data"]["out_trade_no"]
    paid_resp = client.post(f"/api/v1/h5/diagnosis/orders/{out_trade_no}/dev-paid")
    assert paid_resp.status_code == 200, paid_resp.text
    return paid_resp.json()["data"]


def test_h5_result_via_openid_cookie(monkeypatch) -> None:
    data = _create_paid_order(monkeypatch)
    out_trade_no = data["out_trade_no"]
    resp = client.get(f"/api/v1/h5/diagnosis/orders/{out_trade_no}/result")
    assert resp.status_code == 200, resp.text
    body = resp.json()["data"]
    assert body["out_trade_no"] == out_trade_no
    assert body["ready"] is False
    assert body["progress"]["total_runs"] >= 1


def test_h5_result_forbidden_without_auth(monkeypatch) -> None:
    data = _create_paid_order(monkeypatch, openid="pytest-openid-result-2")
    out_trade_no = data["out_trade_no"]
    # 清掉 openid cookie，模拟短信外链无凭证访问
    client.cookies.clear()
    monkeypatch.setattr(settings, "wechat_pay_dev_mode", False)
    resp = client.get(f"/api/v1/h5/diagnosis/orders/{out_trade_no}/result")
    assert resp.status_code == 403


def test_h5_result_unlock_by_phone_tail(monkeypatch) -> None:
    phone = "13900139088"
    data = _create_paid_order(monkeypatch, phone=phone, openid="pytest-openid-result-3")
    out_trade_no = data["out_trade_no"]
    client.cookies.clear()
    monkeypatch.setattr(settings, "wechat_pay_dev_mode", False)

    bad = client.post(
        f"/api/v1/h5/diagnosis/orders/{out_trade_no}/result/unlock",
        json={"phone_tail": "0000"},
    )
    assert bad.status_code == 403

    ok = client.post(
        f"/api/v1/h5/diagnosis/orders/{out_trade_no}/result/unlock",
        json={"phone_tail": phone[-4:]},
    )
    assert ok.status_code == 200, ok.text
    token = ok.json()["data"]["access_token"]
    assert token

    result = client.get(
        f"/api/v1/h5/diagnosis/orders/{out_trade_no}/result",
        params={"t": token},
    )
    assert result.status_code == 200
    assert result.json()["data"]["brand_name"] == "结果页品牌"


def test_h5_result_unlock_by_full_phone(monkeypatch) -> None:
    phone = "13900139099"
    data = _create_paid_order(monkeypatch, phone=phone, openid="pytest-openid-result-phone")
    out_trade_no = data["out_trade_no"]
    client.cookies.clear()
    monkeypatch.setattr(settings, "wechat_pay_dev_mode", False)

    bad = client.post("/api/v1/h5/diagnosis/result/unlock", json={"contact_phone": "13800000000"})
    assert bad.status_code == 400

    ok = client.post("/api/v1/h5/diagnosis/result/unlock", json={"contact_phone": phone})
    assert ok.status_code == 200, ok.text
    body = ok.json()["data"]
    assert body["out_trade_no"] == out_trade_no
    assert body["access_token"]

    result = client.get(
        f"/api/v1/h5/diagnosis/orders/{out_trade_no}/result",
        params={"t": body["access_token"]},
    )
    assert result.status_code == 200
    assert result.json()["data"]["brand_name"] == "结果页品牌"


def test_notify_h5_ready_sms_idempotent_skip_when_disabled(monkeypatch) -> None:
    data = _create_paid_order(monkeypatch, phone="13900139111", openid="pytest-openid-result-sms")
    lead_id = data["lead_diagnosis_id"]
    assert lead_id

    monkeypatch.setattr(settings, "aliyun_sms_enabled", False)
    from app.services.h5_result_service import notify_h5_order_ready_sms

    db = SessionLocal()
    try:
        first = notify_h5_order_ready_sms(db, int(lead_id))
        assert first["status"] == "skip"
        assert first["reason"] == "sms_disabled"
        order = db.scalar(
            select(H5DiagnosisOrder).where(H5DiagnosisOrder.out_trade_no == data["out_trade_no"])
        )
        assert order is not None
        assert order.result_access_token
        assert order.sms_ready_sent_at is None

        # 假装已发送，再次调用应幂等 skip
        order.sms_ready_sent_at = datetime.utcnow()
        db.commit()
        second = notify_h5_order_ready_sms(db, int(lead_id))
        assert second["status"] == "skip"
        assert second["reason"] == "already_sent"
    finally:
        db.close()


def test_aliyun_sms_sign_shape() -> None:
    from app.services.aliyun_sms_service import _percent_encode, _sign

    assert "%2B" in _percent_encode("a+b")
    sig = _sign("secret", "GET&%2F&x")
    assert isinstance(sig, str) and len(sig) > 10
