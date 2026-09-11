"""公用观察账号范围。

2026-08-07 - 艾迪亚观察号：同租户只读(+知识库上传)；平台白名单可配。
2026-09-11 - 平台列表走 settings / sys_config（observer_platforms），默认千问+百度 AI+。
"""

from __future__ import annotations

from typing import Iterable

from sqlalchemy.orm import Session

from app.api.dependencies import CurrentSession
from app.core.config import settings
from app.models.user import User

# 登录名写死为中文「艾迪亚」；平台不含 mobile。
OBSERVER_USERNAME = "艾迪亚"
OBSERVER_TENANT_NAME = "艾迪亚控股集团有限公司"
# 2026-08-07 - 观察号侧栏不开放空壳菜单
OBSERVER_HIDDEN_MENU_CODES: frozenset[str] = frozenset({
    "customer.links",
    "customer.diagnosis",
})

_DEFAULT_OBSERVER_PLATFORMS = frozenset({"qianwen", "baiduai"})


def parse_observer_platforms(raw: str | None) -> frozenset[str]:
    codes = {str(part or "").strip() for part in str(raw or "").split(",") if str(part or "").strip()}
    return frozenset(codes) if codes else frozenset(_DEFAULT_OBSERVER_PLATFORMS)


def get_observer_platforms(db: Session | None = None) -> frozenset[str]:
    """观察号平台白名单：优先 sys_config，其次 .env/settings。"""
    try:
        from app.services.system_config_service import get_runtime_config

        raw = get_runtime_config("observer_platforms", db)
    except Exception:
        raw = getattr(settings, "observer_platforms", None)
    return parse_observer_platforms(str(raw) if raw is not None else None)


# 兼容旧引用：进程启动时的默认快照（测试/脚本仍可用；运行时请用 get_observer_platforms）
OBSERVER_PLATFORMS: frozenset[str] = get_observer_platforms()


def is_observer_username(username: str | None) -> bool:
    return str(username or "").strip() == OBSERVER_USERNAME


def is_observer_user(user: User | None) -> bool:
    return bool(user is not None and is_observer_username(user.username))


def is_observer_session(current: CurrentSession | None) -> bool:
    return bool(current is not None and is_observer_user(getattr(current, "user", None)))


def observer_platforms_for_session(current: CurrentSession | None) -> frozenset[str] | None:
    if not is_observer_session(current):
        return None
    return get_observer_platforms()


def observer_platforms_for_user_id(db: Session, user_id: int | None) -> frozenset[str] | None:
    if not user_id:
        return None
    user = db.get(User, user_id)
    if not is_observer_user(user):
        return None
    return get_observer_platforms(db)


def narrow_platform_codes(
    codes: Iterable[str] | None,
    allow: frozenset[str] | None,
) -> list[str]:
    """allow 为 None 表示不限制；空 allow 表示全挡。"""
    from app.core.platform_order import sort_platform_codes

    raw = [str(c or "").strip() for c in (codes or []) if str(c or "").strip()]
    if allow is None:
        return sort_platform_codes(raw)
    return sort_platform_codes([c for c in raw if c in allow])


def clamp_platform_query(
    current: CurrentSession | None,
    platform: str | None = None,
    platforms: str | None = None,
) -> tuple[str | None, str | None]:
    """观察号：未指定平台时强制白名单；指定了则与白名单求交，交空则用白名单。"""
    allow = observer_platforms_for_session(current)
    if allow is None:
        return platform, platforms

    single = str(platform or "").strip()
    if single and single.lower() != "all":
        if single in allow:
            return single, None
        # 点名非授权平台 → 落到白名单全集，避免误用全库
        return None, ",".join(sorted(allow))

    multi = [p.strip() for p in str(platforms or "").split(",") if p.strip()]
    if multi:
        kept = [p for p in multi if p in allow]
        if kept:
            return None, ",".join(kept)
    return None, ",".join(sorted(allow))


def observer_cache_suffix(current: CurrentSession | None) -> str:
    allow = observer_platforms_for_session(current)
    if allow is None:
        return ""
    return "|obs=" + ",".join(sorted(allow))


def scope_asset_platforms_dict(data: dict | None, allow: frozenset[str] | None) -> dict | None:
    """收窄 brand asset 序列化里的 monitored_platforms / 词组 platforms（不改库）。"""
    if data is None or allow is None:
        return data
    out = dict(data)
    out["monitored_platforms"] = narrow_platform_codes(out.get("monitored_platforms") or [], allow)
    groups = []
    for group in out.get("keyword_groups") or []:
        row = dict(group)
        if row.get("platforms"):
            row["platforms"] = narrow_platform_codes(row.get("platforms") or [], allow)
        groups.append(row)
    out["keyword_groups"] = groups
    bw_groups = []
    for group in out.get("brand_word_groups") or []:
        row = dict(group)
        if row.get("platforms"):
            row["platforms"] = narrow_platform_codes(row.get("platforms") or [], allow)
        bw_groups.append(row)
    out["brand_word_groups"] = bw_groups
    return out
