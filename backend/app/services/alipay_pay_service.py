"""支付宝：手机网站支付（WAP）+ 当面付预下单（扫码）。"""

from __future__ import annotations

import base64
import json
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus, urlencode, urlparse

import httpx
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from app.core.config import settings

_ALIPAY_GATEWAY = "https://openapi.alipay.com/gateway.do"


class AlipayPayError(RuntimeError):
    pass


def alipay_configured() -> bool:
    return bool(
        settings.alipay_app_id
        and (settings.alipay_private_key_path or settings.alipay_private_key)
        and (settings.alipay_public_key_path or settings.alipay_public_key)
        and settings.alipay_notify_url
    )


def _read_key_text(path: str, inline: str) -> str:
    raw = (inline or "").strip()
    if raw:
        return raw
    key_path = (path or "").strip()
    if not key_path:
        return ""
    return Path(key_path).read_text(encoding="utf-8").strip()


def _normalize_pem(raw: str, *, kind: str) -> bytes:
    text = raw.strip().replace("\r", "").replace("\n", "")
    if "BEGIN" in raw:
        return raw.strip().encode("utf-8")
    # 密钥工具导出常为裸 Base64，需包 PEM
    if kind == "private":
        header, footer = "-----BEGIN PRIVATE KEY-----", "-----END PRIVATE KEY-----"
    else:
        header, footer = "-----BEGIN PUBLIC KEY-----", "-----END PUBLIC KEY-----"
    lines = [text[i : i + 64] for i in range(0, len(text), 64)]
    return ("\n".join([header, *lines, footer]) + "\n").encode("utf-8")


@lru_cache(maxsize=1)
def _app_private_key():
    raw = _read_key_text(settings.alipay_private_key_path, settings.alipay_private_key)
    if not raw:
        raise AlipayPayError("未配置 ALIPAY_PRIVATE_KEY / ALIPAY_PRIVATE_KEY_PATH")
    return serialization.load_pem_private_key(
        _normalize_pem(raw, kind="private"),
        password=None,
        backend=default_backend(),
    )


@lru_cache(maxsize=1)
def _alipay_public_key():
    raw = _read_key_text(settings.alipay_public_key_path, settings.alipay_public_key)
    if not raw:
        raise AlipayPayError("未配置 ALIPAY_PUBLIC_KEY / ALIPAY_PUBLIC_KEY_PATH")
    return serialization.load_pem_public_key(
        _normalize_pem(raw, kind="public"),
        backend=default_backend(),
    )


def _sign_content(content: str) -> str:
    signature = _app_private_key().sign(
        content.encode("utf-8"),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    return base64.b64encode(signature).decode("ascii")


def verify_notify_signature(params: dict[str, Any]) -> bool:
    """验支付宝异步/同步通知签名（RSA2）。"""
    sign = str(params.get("sign") or "").strip()
    if not sign:
        return False
    items = []
    for key in sorted(params.keys()):
        if key in {"sign", "sign_type"}:
            continue
        value = params.get(key)
        if value is None or value == "":
            continue
        items.append(f"{key}={value}")
    content = "&".join(items)
    try:
        _alipay_public_key().verify(
            base64.b64decode(sign),
            content.encode("utf-8"),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        return True
    except Exception:
        return False


def _ordered_sign_content(params: dict[str, str]) -> str:
    return "&".join(f"{k}={params[k]}" for k in sorted(params.keys()) if params[k] != "")


def create_wap_pay_url(
    *,
    out_trade_no: str,
    amount_fen: int,
    subject: str,
    return_url: str | None = None,
    notify_url: str | None = None,
    quit_url: str | None = None,
) -> str:
    """手机网站支付：返回可浏览器跳转的 gateway URL。"""
    # 2026-09-01 - H5 手机非微信：走 alipay.trade.wap.pay
    if settings.alipay_dev_mode:
        base = (return_url or settings.alipay_return_url or "").strip() or "https://www.aieokj.com/h5/diagnosis/apply"
        sep = "&" if "?" in base else "?"
        return f"{base}{sep}out_trade_no={quote_plus(out_trade_no)}&alipay_dev=1"

    if not alipay_configured():
        raise AlipayPayError("支付宝支付尚未配置完整")

    total = f"{int(amount_fen) / 100:.2f}"
    biz: dict[str, Any] = {
        "out_trade_no": out_trade_no,
        "total_amount": total,
        "subject": (subject or "GEO售前诊断")[:256],
        "product_code": "QUICK_WAP_WAY",
    }
    quit = (quit_url or settings.alipay_quit_url or return_url or settings.alipay_return_url or "").strip()
    if quit:
        biz["quit_url"] = quit

    params: dict[str, str] = {
        "app_id": settings.alipay_app_id.strip(),
        "method": "alipay.trade.wap.pay",
        "format": "JSON",
        "charset": "utf-8",
        "sign_type": "RSA2",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "version": "1.0",
        "notify_url": (notify_url or settings.alipay_notify_url).strip(),
        "biz_content": json.dumps(biz, ensure_ascii=False, separators=(",", ":")),
    }
    ret = (return_url or settings.alipay_return_url or "").strip()
    if ret:
        params["return_url"] = ret

    params["sign"] = _sign_content(_ordered_sign_content(params))
    return f"{_ALIPAY_GATEWAY}?{urlencode(params)}"


def create_precreate_qr_code(
    *,
    out_trade_no: str,
    amount_fen: int,
    subject: str,
    notify_url: str | None = None,
) -> str:
    """当面付预下单：返回 qr_code，前端生成二维码供手机支付宝扫。"""
    # 2026-09-01 - PC 选支付宝：alipay.trade.precreate 出码（需商户开通当面付）
    if settings.alipay_dev_mode:
        return f"https://qr.alipay.com/dev/{quote_plus(out_trade_no)}"

    if not alipay_configured():
        raise AlipayPayError("支付宝支付尚未配置完整")

    total = f"{int(amount_fen) / 100:.2f}"
    biz: dict[str, Any] = {
        "out_trade_no": out_trade_no,
        "total_amount": total,
        "subject": (subject or "GEO售前诊断")[:256],
        "product_code": "FACE_TO_FACE_PAYMENT",
    }
    params: dict[str, str] = {
        "app_id": settings.alipay_app_id.strip(),
        "method": "alipay.trade.precreate",
        "format": "JSON",
        "charset": "utf-8",
        "sign_type": "RSA2",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "version": "1.0",
        "notify_url": (notify_url or settings.alipay_notify_url).strip(),
        "biz_content": json.dumps(biz, ensure_ascii=False, separators=(",", ":")),
    }
    params["sign"] = _sign_content(_ordered_sign_content(params))
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(_ALIPAY_GATEWAY, data=params)
    try:
        data = resp.json()
    except Exception as exc:
        raise AlipayPayError(f"支付宝当面付响应异常: {resp.status_code} {resp.text[:200]}") from exc
    inner = data.get("alipay_trade_precreate_response") or {}
    if str(inner.get("code") or "") != "10000":
        raise AlipayPayError(
            f"支付宝当面付下单失败: {inner.get('sub_msg') or inner.get('msg') or inner}"
        )
    qr_code = str(inner.get("qr_code") or "").strip()
    if not qr_code:
        raise AlipayPayError("支付宝当面付未返回收款码")
    return qr_code


def notify_url_path() -> str:
    raw = (settings.alipay_notify_url or "").strip()
    if not raw:
        return "/api/v1/alipay/notify"
    return urlparse(raw).path or "/api/v1/alipay/notify"
