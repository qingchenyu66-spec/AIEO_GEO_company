"""支付回调守卫：金额/渠道/交易号/已支付规则。"""

from __future__ import annotations

import base64
import json
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from app.services.payment_notify_guard import (
    PaymentNotifyReject,
    assert_channel_match,
    assert_transaction_not_occupied,
    evaluate_paid_order_transaction,
    process_alipay_notify,
    process_wechat_pay_notify,
)
from app.services.wechat_pay_service import WechatPayError, verify_wechat_platform_notify


def test_assert_channel_match_uses_h5_form_json() -> None:
    order = SimpleNamespace(out_trade_no="H5X", form_json={"pay_channel": "alipay"})
    with pytest.raises(PaymentNotifyReject, match="支付渠道"):
        assert_channel_match(order=order, entry_channel="wechat")


def test_evaluate_paid_rejects_different_transaction() -> None:
    order = SimpleNamespace(
        out_trade_no="CR1",
        status="paid",
        ledger_id=1,
        transaction_id="TX-OLD",
        pay_channel="wechat",
    )
    with pytest.raises(PaymentNotifyReject, match="交易号不一致"):
        evaluate_paid_order_transaction(order=order, transaction_id="TX-NEW", channel="wechat")


def test_evaluate_paid_idempotent_same_transaction() -> None:
    order = SimpleNamespace(
        out_trade_no="CR1",
        status="paid",
        ledger_id=1,
        transaction_id="TX-1",
        pay_channel="wechat",
    )
    assert evaluate_paid_order_transaction(order=order, transaction_id="TX-1", channel="wechat") == "idempotent"


def test_evaluate_paid_empty_allows_bind() -> None:
    order = SimpleNamespace(
        out_trade_no="CR1",
        status="paid",
        ledger_id=1,
        transaction_id=None,
        pay_channel="wechat",
    )
    assert evaluate_paid_order_transaction(order=order, transaction_id="TX-BIND", channel="wechat") == "bind_empty"


def test_assert_transaction_occupied_credit(monkeypatch: pytest.MonkeyPatch) -> None:
    db = MagicMock()
    other = SimpleNamespace(out_trade_no="CR-OTHER")
    db.scalar.side_effect = [other]
    with pytest.raises(PaymentNotifyReject, match="已绑定其他订单"):
        assert_transaction_not_occupied(
            db,
            channel="wechat",
            transaction_id="TX-SHARED",
            out_trade_no="CR-NEW",
        )


def test_wechat_platform_verify_requires_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.wechat_pay_service.settings.wechat_pay_dev_mode", False)
    with pytest.raises(WechatPayError, match="缺少"):
        verify_wechat_platform_notify(headers={}, body=b"{}")


def test_wechat_platform_verify_accepts_valid_signature_and_rejects_tamper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")
    serial = "PUB_KEY_ID_TEST_1"
    timestamp = str(int(time.time()))
    nonce = "notify-nonce"
    body = b'{"id":"notify-1","resource":{}}'
    message = f"{timestamp}\n{nonce}\n{body.decode('utf-8')}\n".encode("utf-8")
    signature = base64.b64encode(
        private_key.sign(message, padding.PKCS1v15(), hashes.SHA256())
    ).decode("ascii")
    headers = {
        "Wechatpay-Timestamp": timestamp,
        "Wechatpay-Nonce": nonce,
        "Wechatpay-Serial": serial,
        "Wechatpay-Signature": signature,
    }
    monkeypatch.setattr(
        "app.services.wechat_pay_service.settings.wechat_pay_platform_public_key_map",
        json.dumps({serial: public_pem}),
    )
    monkeypatch.setattr("app.services.wechat_pay_service.settings.wechat_pay_platform_cert_map", "")
    monkeypatch.setattr("app.services.wechat_pay_service.settings.wechat_pay_notify_skew_seconds", 300)

    verify_wechat_platform_notify(headers=headers, body=body)

    with pytest.raises(WechatPayError, match="签名校验失败"):
        verify_wechat_platform_notify(headers=headers, body=body + b" ")


def test_wechat_platform_verify_rejects_expired_timestamp(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.wechat_pay_service.settings.wechat_pay_notify_skew_seconds", 300)
    headers = {
        "Wechatpay-Timestamp": str(int(time.time()) - 301),
        "Wechatpay-Nonce": "nonce",
        "Wechatpay-Serial": "PUB_KEY_ID_TEST_1",
        "Wechatpay-Signature": "unused",
    }
    with pytest.raises(WechatPayError, match="时间窗"):
        verify_wechat_platform_notify(headers=headers, body=b"{}")


def test_process_wechat_rejects_amount_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.payment_notify_guard.settings.wechat_pay_dev_mode", True)
    monkeypatch.setattr("app.services.payment_notify_guard.settings.wechat_pay_app_id", "wxapp")
    monkeypatch.setattr("app.services.payment_notify_guard.settings.wechat_pay_mch_id", "mch1")
    monkeypatch.setattr(
        "app.services.payment_notify_guard.decrypt_notify_resource",
        lambda resource: {
            "trade_state": "SUCCESS",
            "out_trade_no": "CRAMOUNT1",
            "transaction_id": "TX-1",
            "appid": "wxapp",
            "mchid": "mch1",
            "amount": {"total": 1, "currency": "CNY"},
        },
    )
    order = SimpleNamespace(
        out_trade_no="CRAMOUNT1",
        amount_fen=990,
        pay_channel="wechat",
        status="pending",
        ledger_id=None,
        transaction_id=None,
    )
    db = MagicMock()
    monkeypatch.setattr(
        "app.services.payment_notify_guard.is_credit_recharge_out_trade_no",
        lambda x: True,
    )
    monkeypatch.setattr(
        "app.services.payment_notify_guard.load_order_for_update",
        lambda *_a, **_k: order,
    )
    with pytest.raises(PaymentNotifyReject, match="实付金额"):
        process_wechat_pay_notify(db, body=b'{"resource":{}}', headers={})


def test_process_wechat_rejects_app_identity_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.payment_notify_guard.settings.wechat_pay_dev_mode", False)
    monkeypatch.setattr("app.services.payment_notify_guard.settings.wechat_pay_app_id", "expected-app")
    monkeypatch.setattr("app.services.payment_notify_guard.settings.wechat_pay_mch_id", "expected-mch")
    monkeypatch.setattr(
        "app.services.payment_notify_guard.verify_wechat_platform_notify",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        "app.services.payment_notify_guard.decrypt_notify_resource",
        lambda _resource: {
            "trade_state": "SUCCESS",
            "out_trade_no": "CRIDENTITY1",
            "transaction_id": "TX-IDENTITY-1",
            "appid": "wrong-app",
            "mchid": "expected-mch",
            "amount": {"total": 100, "currency": "CNY"},
        },
    )

    with pytest.raises(PaymentNotifyReject, match="appid"):
        process_wechat_pay_notify(MagicMock(), body=b'{"resource":{}}', headers={})


def test_process_alipay_requires_seller_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.payment_notify_guard.settings.alipay_seller_id", "")
    monkeypatch.setattr(
        "app.services.payment_notify_guard.verify_notify_signature",
        lambda params: True,
    )
    with pytest.raises(PaymentNotifyReject, match="ALIPAY_SELLER_ID"):
        process_alipay_notify(
            MagicMock(),
            params={
                "trade_status": "TRADE_SUCCESS",
                "out_trade_no": "CR1",
                "trade_no": "ALI1",
                "app_id": "app",
                "seller_id": "s",
                "total_amount": "1.00",
            },
        )


def test_process_alipay_rejects_fractional_fen(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.payment_notify_guard.settings.alipay_app_id", "app-1")
    monkeypatch.setattr("app.services.payment_notify_guard.settings.alipay_seller_id", "seller-1")
    monkeypatch.setattr(
        "app.services.payment_notify_guard.verify_notify_signature",
        lambda _params: True,
    )

    with pytest.raises(PaymentNotifyReject, match="total_amount"):
        process_alipay_notify(
            MagicMock(),
            params={
                "trade_status": "TRADE_SUCCESS",
                "out_trade_no": "CR1",
                "trade_no": "ALI1",
                "app_id": "app-1",
                "seller_id": "seller-1",
                "total_amount": "1.001",
            },
        )
