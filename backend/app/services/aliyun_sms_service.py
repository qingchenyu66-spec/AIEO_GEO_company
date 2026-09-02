"""阿里云短信（RPC SendSms），无额外 SDK 依赖。

2026-09-01 - H5 诊断 ready 通知；AccessKey/签名/模板走环境变量
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote, urlencode

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

_ENDPOINT = "https://dysmsapi.aliyuncs.com/"


def _percent_encode(value: str) -> str:
    return quote(str(value), safe="~")


def _sign(secret: str, string_to_sign: str) -> str:
    import base64

    digest = hmac.new(
        (secret + "&").encode("utf-8"),
        string_to_sign.encode("utf-8"),
        hashlib.sha1,
    ).digest()
    return base64.b64encode(digest).decode("utf-8")


def send_sms(
    *,
    phone: str,
    template_code: str,
    template_param: dict[str, Any],
    sign_name: str | None = None,
) -> dict[str, Any]:
    """发送短信；失败抛 ValueError。"""
    import json

    access_key = str(settings.aliyun_sms_access_key_id or "").strip()
    secret = str(settings.aliyun_sms_access_key_secret or "").strip()
    sign = str(sign_name or settings.aliyun_sms_sign_name or "").strip()
    if not settings.aliyun_sms_enabled:
        raise ValueError("短信未启用（aliyun_sms_enabled=false）")
    if not access_key or not secret or not sign or not template_code:
        raise ValueError("短信配置不完整（AccessKey/签名/模板）")
    phone_text = str(phone or "").strip()
    if not phone_text:
        raise ValueError("手机号为空")

    params: dict[str, str] = {
        "AccessKeyId": access_key,
        "Action": "SendSms",
        "Format": "JSON",
        "PhoneNumbers": phone_text,
        "RegionId": str(settings.aliyun_sms_region_id or "cn-hangzhou"),
        "SignName": sign,
        "SignatureMethod": "HMAC-SHA1",
        "SignatureNonce": uuid.uuid4().hex,
        "SignatureVersion": "1.0",
        "TemplateCode": template_code,
        "TemplateParam": json.dumps(template_param, ensure_ascii=False, separators=(",", ":")),
        "Timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "Version": "2017-05-25",
    }
    sorted_query = "&".join(
        f"{_percent_encode(k)}={_percent_encode(v)}" for k, v in sorted(params.items())
    )
    string_to_sign = f"GET&{_percent_encode('/')}&{_percent_encode(sorted_query)}"
    params["Signature"] = _sign(secret, string_to_sign)
    url = f"{_ENDPOINT}?{urlencode(params)}"
    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(url)
            data = resp.json()
    except Exception as exc:
        logger.warning("aliyun sms request failed phone=%s err=%s", phone_text[-4:], exc)
        raise ValueError(f"短信请求失败：{exc}") from exc

    code = str(data.get("Code") or "")
    if code != "OK":
        msg = str(data.get("Message") or code or "unknown")
        logger.warning("aliyun sms rejected phone=%s code=%s msg=%s", phone_text[-4:], code, msg)
        raise ValueError(f"短信发送失败：{msg}")
    return {"biz_id": data.get("BizId"), "request_id": data.get("RequestId")}
