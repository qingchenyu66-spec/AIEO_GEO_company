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


def platform_code_family(code: str | None) -> set[str]:
    """桌面/移动端成对映射：deepseek ↔ deepseek_mobile。"""
    text = str(code or "").strip()
    if not text:
        return set()
    base = text.removesuffix("_mobile") or text
    return {base, f"{base}_mobile"}


def expand_platform_codes(codes: list[str] | set[str] | None) -> set[str]:
    """购买/筛选码扩展为含移动端家族，避免一端漏数。"""
    out: set[str] = set()
    for code in codes or []:
        out |= platform_code_family(code)
    return out


def platforms_compatible(left: str | None, right: str | None) -> bool:
    a = platform_code_family(left)
    b = platform_code_family(right)
    return bool(a and b and (a & b))


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


def ranking_matrix_row_sort_key(
    *,
    day_key: str | None,
    keyword_group: str | None = None,
    platform: str | None = None,
) -> tuple[str, str, int, str]:
    """Newest day first; platforms follow market rank ascending within a day."""
    return (
        day_key or "",
        keyword_group or "",
        -platform_market_rank(platform),
        platform or "",
    )
