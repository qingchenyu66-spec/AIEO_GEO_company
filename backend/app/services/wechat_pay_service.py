"""微信支付 APIv3（JSAPI）最小封装。"""

from __future__ import annotations

import base64
import json
import secrets
import time
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography import x509

from app.core.config import settings

_WECHAT_PAY_HOST = "https://api.mch.weixin.qq.com"


class WechatPayError(RuntimeError):
    pass


def wechat_pay_configured() -> bool:
    return bool(
        settings.wechat_pay_mch_id
        and settings.wechat_pay_app_id
        and settings.wechat_pay_api_v3_key
        and settings.wechat_pay_cert_key_path
        and len(settings.wechat_pay_api_v3_key) == 32
    )


@lru_cache(maxsize=1)
def _merchant_serial_no() -> str:
    cert_path = settings.wechat_pay_cert_path.strip()
    if not cert_path:
        raise WechatPayError("未配置 WECHAT_PAY_CERT_PATH，无法读取商户证书序列号")
    data = Path(cert_path).read_bytes()
    cert = x509.load_pem_x509_certificate(data, default_backend())
    return format(cert.serial_number, "X")


@lru_cache(maxsize=1)
def _private_key():
    key_path = settings.wechat_pay_cert_key_path.strip()
    if not key_path:
        raise WechatPayError("未配置 WECHAT_PAY_CERT_KEY_PATH")
    data = Path(key_path).read_bytes()
    return serialization.load_pem_private_key(data, password=None, backend=default_backend())


def _sign_message(message: str) -> str:
    signature = _private_key().sign(
        message.encode("utf-8"),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    return base64.b64encode(signature).decode("ascii")


def _auth_headers(method: str, url_path: str, body: str = "") -> dict[str, str]:
    timestamp = str(int(time.time()))
    nonce = secrets.token_hex(16)
    message = f"{method}\n{url_path}\n{timestamp}\n{nonce}\n{body}\n"
    signature = _sign_message(message)
    token = (
        f'WECHATPAY2-SHA256-RSA2048 mchid="{settings.wechat_pay_mch_id}",'
        f'nonce_str="{nonce}",signature="{signature}",timestamp="{timestamp}",'
        f'serial_no="{_merchant_serial_no()}"'
    )
    return {"Authorization": token, "Content-Type": "application/json", "Accept": "application/json"}


def build_jsapi_pay_params(prepay_id: str) -> dict[str, str]:
    timestamp = str(int(time.time()))
    nonce = secrets.token_hex(16)
    package = f"prepay_id={prepay_id}"
    message = f"{settings.wechat_pay_app_id}\n{timestamp}\n{nonce}\n{package}\n"
    return {
        "appId": settings.wechat_pay_app_id,
        "timeStamp": timestamp,
        "nonceStr": nonce,
        "package": package,
        "signType": "RSA",
        "paySign": _sign_message(message),
    }


def create_jsapi_prepay(
    *,
    out_trade_no: str,
    openid: str,
    amount_fen: int,
    description: str,
    notify_url: str | None = None,
) -> str:
    if settings.wechat_pay_dev_mode:
        return f"dev_prepay_{out_trade_no}"

    if not wechat_pay_configured():
        raise WechatPayError("微信支付尚未配置完整")

    notify = (notify_url or settings.wechat_pay_notify_url or "").strip()
    if not notify:
        raise WechatPayError("未配置 WECHAT_PAY_NOTIFY_URL")

    payload = {
        "appid": settings.wechat_pay_app_id,
        "mchid": settings.wechat_pay_mch_id,
        "description": description[:127],
        "out_trade_no": out_trade_no,
        "notify_url": notify,
        "amount": {"total": int(amount_fen), "currency": "CNY"},
        "payer": {"openid": openid},
    }
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    path = "/v3/pay/transactions/jsapi"
    headers = _auth_headers("POST", path, body)
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(f"{_WECHAT_PAY_HOST}{path}", content=body.encode("utf-8"), headers=headers)
    if resp.status_code >= 400:
        raise WechatPayError(f"微信下单失败: {resp.status_code} {resp.text}")
    data = resp.json()
    prepay_id = str(data.get("prepay_id") or "").strip()
    if not prepay_id:
        raise WechatPayError("微信下单未返回 prepay_id")
    return prepay_id


def decrypt_notify_resource(resource: dict[str, Any]) -> dict[str, Any]:
    key = settings.wechat_pay_api_v3_key.encode("utf-8")
    nonce = str(resource.get("nonce") or "").encode("utf-8")
    associated_data = str(resource.get("associated_data") or "").encode("utf-8")
    ciphertext = base64.b64decode(str(resource.get("ciphertext") or ""))
    plaintext = AESGCM(key).decrypt(nonce, ciphertext, associated_data)
    return json.loads(plaintext.decode("utf-8"))


def notify_url_path() -> str:
    raw = (settings.wechat_pay_notify_url or "").strip()
    if not raw:
        return "/api/v1/wechat-pay/notify"
    return urlparse(raw).path or "/api/v1/wechat-pay/notify"
