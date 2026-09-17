"""Alipay precreate request transport checks."""

from __future__ import annotations

from typing import Any

import pytest

from app.services import alipay_pay_service as svc


class _FakeResp:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.status_code = 200
        self._payload = payload
        self.text = str(payload)
        self.content = b"{}"

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeClient:
    last_url = ""
    last_data: dict[str, str] | None = None
    last_headers: dict[str, str] | None = None

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def __enter__(self) -> "_FakeClient":
        return self

    def __exit__(self, *args: Any) -> None:
        return None

    def post(
        self,
        url: str,
        data: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> _FakeResp:
        _FakeClient.last_url = url
        _FakeClient.last_data = data
        _FakeClient.last_headers = headers
        return _FakeResp(
            {
                "alipay_trade_precreate_response": {
                    "code": "10000",
                    "qr_code": "https://qr.alipay.com/test",
                }
            }
        )


def test_precreate_puts_charset_in_gateway_query(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(svc.settings, "alipay_dev_mode", False)
    monkeypatch.setattr(svc.settings, "alipay_app_id", "2021006197673020")
    monkeypatch.setattr(svc.settings, "alipay_notify_url", "https://www.aieokj.com/api/v1/alipay/notify")
    monkeypatch.setattr(svc.settings, "alipay_private_key_path", "/tmp/x")
    monkeypatch.setattr(svc.settings, "alipay_public_key_path", "/tmp/y")
    monkeypatch.setattr(svc, "alipay_configured", lambda: True)
    monkeypatch.setattr(svc, "_sign_content", lambda content: "SIG")
    monkeypatch.setattr(svc.httpx, "Client", _FakeClient)

    qr = svc.create_precreate_qr_code(out_trade_no="T1", amount_fen=100, subject="算力充值")
    assert qr == "https://qr.alipay.com/test"
    assert _FakeClient.last_url.startswith("https://openapi.alipay.com/gateway.do?charset=")
    assert "charset=utf-8" in _FakeClient.last_url
    assert _FakeClient.last_data is not None
    assert _FakeClient.last_data.get("charset") == "utf-8"
    assert _FakeClient.last_data.get("sign") == "SIG"
    assert "utf-8" in ((_FakeClient.last_headers or {}).get("Content-Type") or "")
