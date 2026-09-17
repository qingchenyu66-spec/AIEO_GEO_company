"""微信支付 APIv3（JSAPI / Native）最小封装。"""

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


def _notify_url(notify_url: str | None = None) -> str:
    notify = (notify_url or settings.wechat_pay_notify_url or "").strip()
    if not notify:
        raise WechatPayError("未配置 WECHAT_PAY_NOTIFY_URL")
    return notify


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

    payload = {
        "appid": settings.wechat_pay_app_id,
        "mchid": settings.wechat_pay_mch_id,
        "description": description[:127],
        "out_trade_no": out_trade_no,
        "notify_url": _notify_url(notify_url),
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


def create_native_code_url(
    *,
    out_trade_no: str,
    amount_fen: int,
    description: str,
    notify_url: str | None = None,
) -> str:
    """Native 扫码：返回 code_url，前端生成二维码供手机微信扫。"""
    # 2026-08-31 - B3 PC 扫码付：与 JSAPI 共用回调，不依赖 openid
    if settings.wechat_pay_dev_mode:
        return f"weixin://wxpay/bizpayurl?pr=DEV{out_trade_no[-8:]}"

    if not wechat_pay_configured():
        raise WechatPayError("微信支付尚未配置完整")

    payload = {
        "appid": settings.wechat_pay_app_id,
        "mchid": settings.wechat_pay_mch_id,
        "description": description[:127],
        "out_trade_no": out_trade_no,
        "notify_url": _notify_url(notify_url),
        "amount": {"total": int(amount_fen), "currency": "CNY"},
    }
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    path = "/v3/pay/transactions/native"
    headers = _auth_headers("POST", path, body)
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(f"{_WECHAT_PAY_HOST}{path}", content=body.encode("utf-8"), headers=headers)
    if resp.status_code >= 400:
        raise WechatPayError(f"微信扫码下单失败: {resp.status_code} {resp.text}")
    data = resp.json()
    code_url = str(data.get("code_url") or "").strip()
    if not code_url:
        raise WechatPayError("微信扫码下单未返回 code_url")
    return code_url


def decrypt_notify_resource(resource: dict[str, Any]) -> dict[str, Any]:
    key = settings.wechat_pay_api_v3_key.encode("utf-8")
    nonce = str(resource.get("nonce") or "").encode("utf-8")
    associated_data = str(resource.get("associated_data") or "").encode("utf-8")
    ciphertext = base64.b64decode(str(resource.get("ciphertext") or ""))
    plaintext = AESGCM(key).decrypt(nonce, ciphertext, associated_data)
    return json.loads(plaintext.decode("utf-8"))


def _header_value(headers: Any, name: str) -> str:
    if headers is None:
        return ""
    getter = getattr(headers, "get", None)
    if callable(getter):
        for key in (name, name.lower(), name.upper(), name.title()):
            value = getter(key)
            if value:
                return str(value).strip()
        return ""
    if isinstance(headers, dict):
        lowered = {str(k).lower(): v for k, v in headers.items()}
        return str(lowered.get(name.lower()) or "").strip()
    return ""


def _parse_serial_material_map(raw: str) -> dict[str, str]:
    text = (raw or "").strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise WechatPayError("平台证书/公钥映射不是合法 JSON") from exc
    if not isinstance(data, dict):
        raise WechatPayError("平台证书/公钥映射必须是 JSON 对象")
    out: dict[str, str] = {}
    for key, value in data.items():
        serial = str(key or "").strip()
        material = str(value or "").strip()
        if serial and material:
            out[serial] = material
    return out


def _load_pem_bytes(material: str) -> bytes:
    raw = material.strip()
    if "BEGIN" in raw:
        return raw.encode("utf-8")
    path = Path(raw)
    if path.is_file():
        return path.read_bytes()
    raise WechatPayError("平台证书/公钥既不是 PEM 正文也不是可读文件路径")


def _platform_public_key_for_serial(serial: str):
    serial = str(serial or "").strip()
    if not serial:
        raise WechatPayError("缺少 Wechatpay-Serial")
    cert_map = _parse_serial_material_map(settings.wechat_pay_platform_cert_map)
    key_map = _parse_serial_material_map(settings.wechat_pay_platform_public_key_map)
    if serial in cert_map:
        cert = x509.load_pem_x509_certificate(_load_pem_bytes(cert_map[serial]), default_backend())
        return cert.public_key()
    if serial in key_map:
        return serialization.load_pem_public_key(_load_pem_bytes(key_map[serial]), backend=default_backend())
    if not cert_map and not key_map:
        raise WechatPayError("未配置 WECHAT_PAY_PLATFORM_CERT_MAP / WECHAT_PAY_PLATFORM_PUBLIC_KEY_MAP")
    raise WechatPayError("未知 Wechatpay-Serial，不在已配置平台证书/公钥列表中")


def verify_wechat_platform_notify(*, headers: Any, body: bytes) -> None:
    """验微信支付平台回调签名（必须用平台证书/公钥，不能用商户证书）。"""
    timestamp = _header_value(headers, "Wechatpay-Timestamp")
    nonce = _header_value(headers, "Wechatpay-Nonce")
    signature = _header_value(headers, "Wechatpay-Signature")
    serial = _header_value(headers, "Wechatpay-Serial")
    if not timestamp or not nonce or not signature or not serial:
        raise WechatPayError("缺少 Wechatpay-Timestamp/Nonce/Signature/Serial")
    try:
        ts = int(timestamp)
    except ValueError as exc:
        raise WechatPayError("Wechatpay-Timestamp 非法") from exc
    skew = max(0, int(settings.wechat_pay_notify_skew_seconds or 300))
    if abs(int(time.time()) - ts) > skew:
        raise WechatPayError("Wechatpay-Timestamp 超出允许时间窗")
    message = f"{timestamp}\n{nonce}\n{body.decode('utf-8')}\n".encode("utf-8")
    public_key = _platform_public_key_for_serial(serial)
    try:
        public_key.verify(base64.b64decode(signature), message, padding.PKCS1v15(), hashes.SHA256())
    except Exception as exc:
        raise WechatPayError("微信平台签名校验失败") from exc


def notify_url_path() -> str:
    raw = (settings.wechat_pay_notify_url or "").strip()
    if not raw:
        return "/api/v1/wechat-pay/notify"
    return urlparse(raw).path or "/api/v1/wechat-pay/notify"
