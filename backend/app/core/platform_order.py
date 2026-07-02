"""Market-usage ranking for AI platforms (display order only)."""

from __future__ import annotations

from typing import Any

# Comprehensive market ranking (Dec 2025): doubao > baiduai > deepseek > weibo > yuanbao > qianwen > quark > kimi
PLATFORM_MARKET_RANK: dict[str, int] = {
    "doubao": 10,
    "doubao_mobile": 11,
    "baiduai": 20,
    "deepseek": 30,
    "deepseek_mobile": 31,
    "weibo_zhisou": 40,
    "yuanbao": 50,
    "qianwen": 60,
    "quark": 70,
    "kimi": 80,
    "wenxinyiyan": 90,
}


def platform_market_rank(code: str | None) -> int:
    text = str(code or "").strip()
    if not text:
        return 999
    if text in PLATFORM_MARKET_RANK:
        return PLATFORM_MARKET_RANK[text]
    base = text.removesuffix("_mobile")
    return PLATFORM_MARKET_RANK.get(base, 999)


def sort_platform_codes(codes: list[str] | None) -> list[str]:
    return sorted([str(code).strip() for code in (codes or []) if str(code or "").strip()], key=lambda code: (platform_market_rank(code), code))


def sort_platform_items(items: list[Any], *, key: str = "platform") -> list[Any]:
    def resolve(item: Any) -> str:
        if isinstance(item, dict):
            return str(item.get(key) or "")
        return str(getattr(item, key, "") or "")

    return sorted(items, key=lambda item: (platform_market_rank(resolve(item)), resolve(item)))


def sort_catalog_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sort_platform_items(items, key="code")
    for index, item in enumerate(ordered):
        item["sort_order"] = platform_market_rank(item.get("code"))
        if item["sort_order"] >= 999:
            item["sort_order"] = (index + 1) * 10
    return ordered
