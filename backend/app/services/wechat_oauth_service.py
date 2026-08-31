"""微信服务号 OAuth（snsapi_base 静默拿 openid）。"""

from __future__ import annotations

from urllib.parse import quote

import httpx

from app.core.config import settings

_WECHAT_OAUTH_BASE = "https://open.weixin.qq.com/connect/oauth2/authorize"
_WECHAT_TOKEN_URL = "https://api.weixin.qq.com/sns/oauth2/access_token"


class WechatOAuthError(RuntimeError):
    pass


def oauth_configured() -> bool:
    return bool(settings.wechat_pay_app_id and settings.wechat_app_secret)


def build_oauth_redirect_url(*, redirect_uri: str, state: str) -> str:
    encoded = quote(redirect_uri, safe="")
    return (
        f"{_WECHAT_OAUTH_BASE}?appid={settings.wechat_pay_app_id}"
        f"&redirect_uri={encoded}&response_type=code&scope=snsapi_base&state={quote(state, safe='')}#wechat_redirect"
    )


def exchange_code_for_openid(code: str) -> str:
    if settings.wechat_pay_dev_mode and not settings.wechat_app_secret:
        return settings.wechat_pay_dev_openid or "dev-openid-h5-diagnosis"
    if not oauth_configured():
        raise WechatOAuthError("未配置 WECHAT_APP_SECRET，无法换取 openid")
    params = {
        "appid": settings.wechat_pay_app_id,
        "secret": settings.wechat_app_secret,
        "code": code,
        "grant_type": "authorization_code",
    }
    with httpx.Client(timeout=20.0) as client:
        resp = client.get(_WECHAT_TOKEN_URL, params=params)
    data = resp.json()
    openid = str(data.get("openid") or "").strip()
    if not openid:
        err = data.get("errmsg") or resp.text
        raise WechatOAuthError(f"微信 OAuth 失败: {err}")
    return openid
