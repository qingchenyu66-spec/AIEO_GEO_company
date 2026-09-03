"""售前品牌露出：共用匹配词与子任务位次解析。

2026-08-21 - 格级/样本两套算法不一致 - 统一弱别名门槛与位次解析入口
"""

from __future__ import annotations

import re
from typing import Any, Iterable


def is_weak_brand_alias(term: str | None) -> bool:
    """短别名默认不进自动匹配：纯拉丁/数字 ≤3，或其它长度 <3。

    强别名需入口显式配置（当前无单独开关时一律按弱别名过滤）。
    """
    text = str(term or "").strip()
    if not text:
        return True
    if re.fullmatch(r"[A-Za-z0-9]+", text) and len(text) <= 3:
        return True
    return len(text) < 3


def matchable_brand_terms(brand: str | None, aliases: Iterable[str] | None = None) -> list[str]:
    """可参与露出匹配的词：品牌全称强制保留，弱别名剔除。"""
    out: list[str] = []
    seen: set[str] = set()

    def _add(value: str | None, *, force: bool = False) -> None:
        text = str(value or "").strip()
        if not text or text in seen:
            return
        if not force and is_weak_brand_alias(text):
            return
        seen.add(text)
        out.append(text)

    _add(brand, force=True)
    for alias in aliases or []:
        _add(alias, force=False)
    return out


def _normalize_match_text(text: str) -> str:
    """统一全半角括号/空白，便于门店名对上。"""
    return (
        str(text or "")
        .replace("（", "(")
        .replace("）", ")")
        .replace("【", "(")
        .replace("】", ")")
        .casefold()
    )


# 2026-09-03 - 仅配置词自带「店名(门店)」时启用双钥，勿全局切片公司名
_VENUE_PAREN_TERM_RE = re.compile(
    r"^(?P<head>.+?)\s*[\(（]\s*(?P<venue>[^）\)]+?)\s*[\)）]\s*$"
)


def _head_match_variants(head: str) -> list[str]:
    """店名前半变体：原文、去店后缀、以及开头品牌核（须与门店钥同在一行）。"""
    raw = str(head or "").strip()
    if not raw:
        return []
    out: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        token = value.strip()
        if len(token) < 2 or token in seen:
            return
        seen.add(token)
        out.append(token)

    add(raw)
    stripped = re.sub(r"(?:分店|总店|一部|二部|店面|门店|店)$", "", raw).strip()
    add(stripped)
    # 2026-09-03 - 「千里马泥炉烤肉店」正文常写成「千里马（市妇婴店）」；门店钥已锚定，允许品牌核
    stop = re.match(
        r"^(.+?)(?=泥炉|烧烤|烤肉|烤串|火锅|餐饮|酒店|面馆|餐厅|饭店|公司|集团|控股|有限|店面|门店)",
        raw,
    )
    if stop and len(stop.group(1).strip()) >= 2:
        add(stop.group(1).strip())
    else:
        core = re.match(r"^([\u4e00-\u9fff]{2,4}|[A-Za-z][A-Za-z0-9&\-]{1,20})", raw)
        if core:
            add(core.group(1))
    return out


def _venue_match_variants(venue: str) -> list[str]:
    """门店括号内变体：市妇婴总店 ↔ 市妇婴店。"""
    raw = str(venue or "").strip()
    if not raw:
        return []
    out: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        token = value.strip()
        if len(token) < 2 or token in seen:
            return
        seen.add(token)
        out.append(token)

    add(raw)
    add(re.sub(r"总店$", "店", raw))
    core = re.sub(r"(?:总|分)?店$", "", raw).strip()
    if len(core) >= 2:
        add(core)
    return out


def parse_venue_paren_term(term: str | None) -> tuple[str, str] | None:
    """配置露出词是否为「品牌头(门店)」形态。"""
    text = str(term or "").strip()
    if not text:
        return None
    match = _VENUE_PAREN_TERM_RE.match(text)
    if not match:
        return None
    head = match.group("head").strip()
    venue = match.group("venue").strip()
    if len(head) < 2 or len(venue) < 2:
        return None
    # 括号里必须像门店/地点，避免误伤「爱格(奥地利)」国别
    if not re.search(r"店|街|路|广场|商场|市场|中心|站|城", venue):
        return None
    # 2026-09-03 - 「(总店)」过泛，不允许靠双钥；须有具体地名核
    venue_core = re.sub(r"(?:总|分)?店$", "", venue).strip()
    if len(venue_core) < 2:
        return None
    return head, venue


def venue_paren_dual_key_in_text(haystack: str | None, term: str | None) -> bool:
    """品牌头 + 门店括号双钥：同一行同时出现才算命中。

    2026-09-03 - 千里马泥炉烤肉店(市妇婴店) ↔ 千里马（市妇婴店）/泥炉烤肉(市妇婴店)
    仅配置词自带门店括号时生效；南市场店行不会因只有「千里马」误中。
    """
    parsed = parse_venue_paren_term(term)
    if not parsed or not haystack:
        return False
    head, venue = parsed
    heads = _head_match_variants(head)
    venues = _venue_match_variants(venue)
    if not heads or not venues:
        return False
    for raw_line in str(haystack).splitlines() or [str(haystack)]:
        line = _normalize_match_text(raw_line)
        if not line.strip():
            continue
        if any(_normalize_match_text(h) in line for h in heads) and any(
            _normalize_match_text(v) in line for v in venues
        ):
            return True
    return False


def exact_configured_term_in_text(haystack: str | None, needle: str | None) -> bool:
    """配置露出词/别名须在文本中整段出现（casefold 子串，不做 fragment 切片）。

    2026-09-03 - 词表仅含品牌全称+入口别名；禁止再自动切广东菜/核心词干
    2026-09-03 - 带门店括号的配置词额外走双钥（头+店），其余仍整段 exact
    """
    if not haystack or not needle:
        return False
    n = str(needle).strip()
    if not n:
        return False
    hay = _normalize_match_text(haystack)
    needle_norm = _normalize_match_text(n)
    if needle_norm in hay:
        return True
    # 2026-09-03 - 仅门店括号形态放宽，其它品牌逻辑不变
    return venue_paren_dual_key_in_text(haystack, n)


def text_has_configured_brand_term(text: str | None, brand_terms: list[str]) -> bool:
    """正文/榜单是否出现任一配置词整段（全称或露出词/别名）。"""
    for term in brand_terms:
        token = str(term or "").strip()
        if token and exact_configured_term_in_text(text, token):
            return True
    return False


def ranking_entry_matches_brand(name: str, brand_terms: list[str]) -> bool:
    """榜单项：仅配置词整段命中；整项相等优先。"""
    normalized = str(name or "").strip()
    if not normalized:
        return False
    for term in brand_terms:
        token = str(term or "").strip()
        if not token:
            continue
        if _normalize_match_text(normalized) == _normalize_match_text(token):
            return True
        if exact_configured_term_in_text(normalized, token):
            return True
    return False


def resolve_subtask_brand_rank(
    item: Any,
    brand: str,
    brand_terms: list[str],
) -> float | None:
    """子任务品牌位次：信任已写 mention_position，否则按匹配词解析榜单。

    与热力格/样本表共用，避免各算各的。
    """
    if getattr(item, "mention_position", None) is not None:
        try:
            return float(item.mention_position)
        except (TypeError, ValueError):
            pass
    from app.services.monitor_service import _resolve_brand_rank

    terms = matchable_brand_terms(brand, brand_terms)
    if not terms:
        return None
    rank, mentioned = _resolve_brand_rank(item, "", terms, None)
    if mentioned and rank is not None:
        try:
            return float(rank)
        except (TypeError, ValueError):
            return None
    return None
