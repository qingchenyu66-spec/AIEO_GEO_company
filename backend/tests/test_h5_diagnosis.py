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


def test_h5_schedule_runs_clamp_and_days() -> None:
    from app.core.lead_diagnosis_config import clamp_h5_schedule_runs, h5_runs_to_schedule_days

    assert clamp_h5_schedule_runs(1) == 1
    assert clamp_h5_schedule_runs(0) == 1
    assert clamp_h5_schedule_runs(99) == 90
    assert h5_runs_to_schedule_days(1) == 1
    assert h5_runs_to_schedule_days(3) == 1
    assert h5_runs_to_schedule_days(4) == 2


def test_lead_schedule_rounds_honors_h5_schedule_runs() -> None:
    from datetime import date, datetime
    from types import SimpleNamespace

    from app.services.lead_diagnosis_service import _iter_schedule_slot_rounds, _schedule_rounds_per_region

    lead = SimpleNamespace(
        lead_context_json={"schedule_runs": "1", "source": "h5_paid_diagnosis"},
        schedule_days=3,
        schedule_times_json=["09:30", "14:30", "20:30"],
        diagnosis_date=date.today(),
        created_at=datetime.now().replace(hour=0, minute=0, second=0, microsecond=0),
        region_codes_json=[],
    )
    assert _schedule_rounds_per_region(lead) == 1
    assert len(list(_iter_schedule_slot_rounds(lead))) == 1


def test_normalize_lead_context_keeps_schedule_runs() -> None:
    from app.schemas.lead_diagnosis import normalize_lead_context

    ctx = normalize_lead_context({"source": "h5_paid_diagnosis", "schedule_runs": 1})
    assert ctx["schedule_runs"] == "1"
    ctx2 = normalize_lead_context({"source": "lead_diagnosis_create"})
    assert "schedule_runs" not in ctx2


def test_h5_public_config_exposes_schedule_runs() -> None:
    resp = client.get("/api/v1/h5/diagnosis/config")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert int(data["schedule_runs"]) >= 1
    assert int(data["schedule_total"]) == int(data["schedule_runs"])


def test_h5_native_order_dev_mode(monkeypatch) -> None:
    monkeypatch.setattr(settings, "wechat_pay_dev_mode", True)
    client.cookies.clear()
    resp = client.post(
        "/api/v1/h5/diagnosis/orders",
        json={
            "contact_phone": "13800138002",
            "brand_name": "扫码测试品牌",
            "prompts": ["蛋白粉推荐"],
            "pay_trade_type": "native",
            "pay_channel": "wechat",
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["pay_trade_type"] == "native"
    assert data["code_url"]
    assert data.get("dev_auto_paid") is True


def test_h5_alipay_precreate_order_dev_mode(monkeypatch) -> None:
    monkeypatch.setattr(settings, "alipay_dev_mode", True)
    monkeypatch.setattr(settings, "alipay_app_id", "2021006197673020")
    client.cookies.clear()
    resp = client.post(
        "/api/v1/h5/diagnosis/orders",
        json={
            "contact_phone": "13800138005",
            "brand_name": "支付宝扫码测试",
            "prompts": ["蛋白粉推荐"],
            "pay_trade_type": "precreate",
            "pay_channel": "alipay",
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["pay_channel"] == "alipay"
    assert data["pay_trade_type"] == "precreate"
    assert data["code_url"]
    assert data.get("dev_auto_paid") is True


def test_h5_wechat_mweb_not_ready(monkeypatch) -> None:
    monkeypatch.setattr(settings, "wechat_pay_dev_mode", True)
    client.cookies.clear()
    resp = client.post(
        "/api/v1/h5/diagnosis/orders",
        json={
            "contact_phone": "13800138006",
            "brand_name": "微信H5未开通",
            "prompts": ["蛋白粉推荐"],
            "pay_trade_type": "mweb",
            "pay_channel": "wechat",
        },
    )
    assert resp.status_code == 400
    assert "即将开通" in resp.json()["detail"]


def test_h5_alipay_wap_order_dev_mode(monkeypatch) -> None:
    monkeypatch.setattr(settings, "alipay_dev_mode", True)
    monkeypatch.setattr(settings, "alipay_app_id", "2021006197673020")
    monkeypatch.setattr(settings, "alipay_return_url", "https://www.aieokj.com/api/v1/alipay/return")
    client.cookies.clear()
    resp = client.post(
        "/api/v1/h5/diagnosis/orders",
        json={
            "contact_phone": "13800138004",
            "brand_name": "支付宝测试品牌",
            "prompts": ["蛋白粉推荐"],
            "pay_trade_type": "wap",
            "pay_channel": "alipay",
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["pay_channel"] == "alipay"
    assert data["pay_trade_type"] == "wap"
    assert data["pay_url"]
    assert data.get("dev_auto_paid") is True


def test_h5_jsapi_order_requires_openid(monkeypatch) -> None:
    monkeypatch.setattr(settings, "wechat_pay_dev_mode", False)
    client.cookies.clear()
    resp = client.post(
        "/api/v1/h5/diagnosis/orders",
        json={
            "contact_phone": "13800138003",
            "brand_name": "无授权品牌",
            "prompts": ["蛋白粉推荐"],
            "pay_trade_type": "jsapi",
        },
    )
    assert resp.status_code == 400
    assert "授权" in resp.json()["detail"]


def test_list_h5_diagnosis_orders_service() -> None:
    from app.core.database import SessionLocal
    from app.services.h5_diagnosis_service import list_h5_diagnosis_orders

    db = SessionLocal()
    try:
        data = list_h5_diagnosis_orders(db, page=1, page_size=5)
        assert "items" in data
        assert "total" in data
        assert isinstance(data["items"], list)
        if data["items"]:
            row = data["items"][0]
            assert "contact_phone" in row
            assert "out_trade_no" in row
            assert "prompts" in row
            assert "platforms" in row
            phone = str(row.get("contact_phone") or "")
            if phone:
                assert "*" not in phone
    finally:
        db.close()


def test_admin_orders_requires_auth() -> None:
    client.cookies.clear()
    resp = client.get("/api/v1/h5/diagnosis/admin/orders")
    assert resp.status_code in {401, 403}


def test_fulfill_idempotent_same_lead(monkeypatch) -> None:
    """P0：重复履约不新建第二份售前诊断。"""
    monkeypatch.setattr(settings, "wechat_pay_dev_mode", True)
    monkeypatch.setattr(
        "app.services.lead_diagnosis_service.submit_due_lead_run",
        lambda *args, **kwargs: None,
    )
    client.cookies.set("geo_h5_wx_openid", "pytest-openid-h5-idem")
    create_resp = client.post(
        "/api/v1/h5/diagnosis/orders",
        json={
            "contact_phone": "13800138010",
            "brand_name": "幂等履约品牌",
            "prompts": ["蛋白粉推荐"],
        },
    )
    assert create_resp.status_code == 200, create_resp.text
    out_trade_no = create_resp.json()["data"]["out_trade_no"]

    first = client.post(f"/api/v1/h5/diagnosis/orders/{out_trade_no}/dev-paid")
    assert first.status_code == 200, first.text
    lead_id = first.json()["data"]["lead_diagnosis_id"]
    assert lead_id

    from app.core.database import SessionLocal
    from app.services.h5_diagnosis_service import fulfill_h5_order_paid

    db = SessionLocal()
    try:
        second = fulfill_h5_order_paid(
            db,
            out_trade_no=out_trade_no,
            wx_transaction_id="DEV-REPEAT",
        )
        assert second["status"] == "paid"
        assert second["lead_diagnosis_id"] == lead_id
    finally:
        db.close()


def test_fulfill_repairs_paid_without_lead(monkeypatch) -> None:
    """P0：已 paid 但缺 lead_diagnosis_id 时，重放履约应补建。"""
    monkeypatch.setattr(settings, "wechat_pay_dev_mode", True)
    monkeypatch.setattr(
        "app.services.lead_diagnosis_service.submit_due_lead_run",
        lambda *args, **kwargs: None,
    )
    client.cookies.set("geo_h5_wx_openid", "pytest-openid-h5-repair")
    create_resp = client.post(
        "/api/v1/h5/diagnosis/orders",
        json={
            "contact_phone": "13800138011",
            "brand_name": "补建诊断品牌",
            "prompts": ["蛋白粉哪家好"],
        },
    )
    assert create_resp.status_code == 200, create_resp.text
    out_trade_no = create_resp.json()["data"]["out_trade_no"]

    from datetime import datetime

    from app.core.database import SessionLocal
    from app.models.h5_diagnosis_order import H5DiagnosisOrder
    from app.services.h5_diagnosis_service import fulfill_h5_order_paid
    from sqlalchemy import select

    db = SessionLocal()
    try:
        order = db.scalar(select(H5DiagnosisOrder).where(H5DiagnosisOrder.out_trade_no == out_trade_no))
        assert order is not None
        # 模拟：钱已到账、诊断未挂上
        order.status = "paid"
        order.wx_transaction_id = "DEV-GAP"
        order.paid_at = datetime.utcnow()
        order.lead_diagnosis_id = None
        db.commit()

        repaired = fulfill_h5_order_paid(
            db,
            out_trade_no=out_trade_no,
            wx_transaction_id="DEV-GAP-RETRY",
        )
        assert repaired["status"] == "paid"
        assert repaired["lead_diagnosis_id"]
    finally:
        db.close()


def test_h5_order_snapshot_has_schedule_runs_and_platforms(monkeypatch) -> None:
    """P0：下单快照带监测次数与平台，供履约追踪。"""
    monkeypatch.setattr(settings, "wechat_pay_dev_mode", True)
    monkeypatch.setattr(
        "app.services.lead_diagnosis_service.submit_due_lead_run",
        lambda *args, **kwargs: None,
    )
    client.cookies.set("geo_h5_wx_openid", "pytest-openid-h5-snap")
    create_resp = client.post(
        "/api/v1/h5/diagnosis/orders",
        json={
            "contact_phone": "13800138012",
            "brand_name": "快照配置品牌",
            "prompts": ["蛋白粉推荐"],
        },
    )
    assert create_resp.status_code == 200, create_resp.text
    out_trade_no = create_resp.json()["data"]["out_trade_no"]

    from app.core.database import SessionLocal
    from app.models.h5_diagnosis_order import H5DiagnosisOrder
    from sqlalchemy import select

    db = SessionLocal()
    try:
        order = db.scalar(select(H5DiagnosisOrder).where(H5DiagnosisOrder.out_trade_no == out_trade_no))
        assert order is not None
        platforms = list(order.platforms_json or [])
        assert platforms
        form = order.form_json if isinstance(order.form_json, dict) else {}
        assert int(form.get("schedule_runs") or 0) >= 1
    finally:
        db.close()
