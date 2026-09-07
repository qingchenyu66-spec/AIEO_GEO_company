"""快照图代理：对外只暴露自家 /media/shot/{token}，上游域名不进地址栏。

ponytail: token 为 HMAC 密封的相对能力 URL（无需再查 Redis）；
仅允许白名单 host，避免 SSRF。
# 2026-09-07 - 导出/转发 HTML 无 Cookie：endpoint 凭 token 即可读，登录不是第二道闸
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

# 模力快照 CDN；扩容时只加明确域名，勿用通配
ALLOWED_SHOT_HOSTS = frozenset({
    "img.molizhishu.com",
})

SHOT_TOKEN_SCOPE = "media_shot"
SHOT_TOKEN_TTL_DAYS = 90
SHOT_PATH_PREFIX = "/api/v1/media/shot/"
_MAX_BYTES = 25 * 1024 * 1024
_FETCH_TIMEOUT = httpx.Timeout(30.0, connect=10.0)


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64url_decode(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def _signing_key() -> bytes:
    return hashlib.sha256(f"geo-media-shot|{settings.secret_key}".encode()).digest()


def _obfuscate(raw: bytes) -> bytes:
    # ponytail: XOR 混淆即可，目标是地址栏/复制链接看不到供应商域名；非强加密
    key = _signing_key()
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(raw))


def is_allowed_shot_url(url: str | None) -> bool:
    text = str(url or "").strip()
    if not text:
        return False
    try:
        parsed = urlparse(text)
    except Exception:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    host = (parsed.hostname or "").lower()
    return host in ALLOWED_SHOT_HOSTS


def seal_shot_url(url: str, *, ttl_days: int = SHOT_TOKEN_TTL_DAYS) -> str:
    """密封上游 URL → 不透明 token（地址栏看不到供应商域名）。"""
    exp = int((datetime.now(UTC) + timedelta(days=ttl_days)).timestamp())
    body = f"{SHOT_TOKEN_SCOPE}|{exp}|{url}".encode()
    payload = _b64url_encode(_obfuscate(body))
    sig = hmac.new(_signing_key(), payload.encode("ascii"), hashlib.sha256).hexdigest()[:32]
    return f"{payload}.{sig}"


def unseal_shot_token(token: str) -> str:
    """校验 token 并还原上游 URL；失败抛 ValueError。"""
    text = str(token or "").strip()
    if not text or "." not in text:
        raise ValueError("无效的快照凭证")
    payload, sig = text.rsplit(".", 1)
    expect = hmac.new(_signing_key(), payload.encode("ascii"), hashlib.sha256).hexdigest()[:32]
    if not hmac.compare_digest(expect, sig):
        raise ValueError("快照凭证校验失败")
    try:
        body = _obfuscate(_b64url_decode(payload)).decode("utf-8")
    except Exception as exc:
        raise ValueError("快照凭证无法解析") from exc
    parts = body.split("|", 2)
    if len(parts) != 3 or parts[0] != SHOT_TOKEN_SCOPE:
        raise ValueError("快照凭证格式错误")
    try:
        exp = int(parts[1])
    except ValueError as exc:
        raise ValueError("快照凭证已损坏") from exc
    if exp < int(datetime.now(UTC).timestamp()):
        raise ValueError("快照凭证已过期")
    url = parts[2].strip()
    if not is_allowed_shot_url(url):
        raise ValueError("快照地址不在允许范围")
    return url


def public_screenshot_url(raw: str | None) -> str | None:
    """API 对外展示用：白名单上游 → 代理路径；其它原样返回。"""
    text = str(raw or "").strip() or None
    if not text:
        return None
    if text.startswith(SHOT_PATH_PREFIX) or "/media/shot/" in text:
        return text
    if not is_allowed_shot_url(text):
        return text
    return f"{SHOT_PATH_PREFIX}{seal_shot_url(text)}"


def public_site_origin() -> str:
    """导出 HTML 离线打开时需要绝对地址；从 H5 基址推导站点源。"""
    from urllib.parse import urlparse

    base = str(getattr(settings, "wechat_h5_base_url", None) or "https://www.aieokj.com/").strip()
    parsed = urlparse(base)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    return "https://www.aieokj.com"


def public_screenshot_url_absolute(raw: str | None) -> str | None:
    """诊断报告 HTML 导出：代理路径补全域名，源码不出现供应商 host。"""
    path = public_screenshot_url(raw)
    if not path:
        return None
    if path.startswith("http://") or path.startswith("https://"):
        return path
    if not path.startswith("/"):
        path = f"/{path}"
    return f"{public_site_origin()}{path}"


def is_proxied_shot_url(raw: str | None) -> bool:
    text = str(raw or "").strip()
    return bool(text) and (text.startswith(SHOT_PATH_PREFIX) or "/api/v1/media/shot/" in text)


def fetch_shot_response(url: str) -> tuple[bytes, str]:
    """拉取白名单图片；返回 (body, content_type)。"""
    if not is_allowed_shot_url(url):
        raise ValueError("快照地址不在允许范围")
    # 禁止跟随跳转，避免白名单 URL 302 到内网造成 SSRF
    with httpx.Client(timeout=_FETCH_TIMEOUT, follow_redirects=False) as client:
        response = client.get(url)
        if response.is_redirect:
            raise ValueError("上游快照发生跳转，已拒绝")
        if response.status_code >= 400:
            raise ValueError(f"上游快照不可用（{response.status_code}）")
        content_type = (response.headers.get("content-type") or "image/png").split(";")[0].strip()
        if not content_type.startswith("image/"):
            raise ValueError("上游返回非图片内容")
        body = response.content
        if len(body) > _MAX_BYTES:
            raise ValueError("快照过大")
        return body, content_type


def shot_meta_for_tests(url: str) -> dict[str, Any]:
    """单测辅助：密封再解封。"""
    token = seal_shot_url(url)
    return {"token": token, "url": unseal_shot_token(token), "public": public_screenshot_url(url)}
