"""Shared visual and risk semantics for competitor report sections."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from typing import Any, Literal


@dataclass(frozen=True)
class EntityVisualStyle:
    color: str
    line_style: str
    marker: str
    css_dash: str


@dataclass(frozen=True)
class RankRisk:
    level: Literal["good", "watch", "warning", "danger", "neutral"]
    label: str
    color: str


_BRAND_STYLE = EntityVisualStyle("#0057D9", "-", "o", "none")
_KNOWN_STYLES: tuple[tuple[tuple[str, ...], EntityVisualStyle], ...] = (
    (("分众传媒",), EntityVisualStyle("#F28E2B", "--", "s", "6 3")),
    (("白马户外媒体", "白马户外"), EntityVisualStyle("#009E73", "-.", "^", "8 3 2 3")),
    (("华铁传媒",), EntityVisualStyle("#C43C92", (0, (10, 4)), "D", "10 4")),
    (("北京优视传媒", "北京优视"), EntityVisualStyle("#7C3AED", (0, (3, 2)), "v", "3 2")),
    (("德高中国", "德高"), EntityVisualStyle("#008C95", ":", "p", "2 3")),
)
_FALLBACK_STYLES: tuple[EntityVisualStyle, ...] = (
    EntityVisualStyle("#D55E00", "--", "X", "6 3"),
    EntityVisualStyle("#0072B2", "-.", "P", "8 3 2 3"),
    EntityVisualStyle("#CC79A7", (0, (10, 4)), "h", "10 4"),
    EntityVisualStyle("#6B8E23", (0, (3, 2)), "*", "3 2"),
    EntityVisualStyle("#A65E2E", ":", "<", "2 3"),
    EntityVisualStyle("#5B5F97", "--", ">", "6 3"),
    EntityVisualStyle("#B23A48", "-.", "8", "8 3 2 3"),
    EntityVisualStyle("#2A9D8F", (0, (10, 4)), "d", "10 4"),
)
_RANK_RISKS: dict[str, RankRisk] = {
    "good": RankRisk("good", "达标（前三）", "#168A45"),
    "watch": RankRisk("watch", "关注（第4-5名）", "#B77900"),
    "warning": RankRisk("warning", "警告（第6-7名）", "#D55E00"),
    "danger": RankRisk("danger", "高风险（第8名以后）", "#C62828"),
    "neutral": RankRisk("neutral", "数据不足", "#6B7280"),
}


def normalize_entity_name(value: str | None) -> str:
    return re.sub(r"\s+", "", str(value or "")).casefold()


def entity_visual_style(
    entity_name: str,
    *,
    brand_name: str | None = None,
) -> EntityVisualStyle:
    normalized = normalize_entity_name(entity_name)
    if brand_name and normalized == normalize_entity_name(brand_name):
        return _BRAND_STYLE
    for aliases, style in _KNOWN_STYLES:
        if any(normalize_entity_name(alias) in normalized for alias in aliases):
            return style
    digest = hashlib.sha256(normalized.encode("utf-8")).digest()
    return _FALLBACK_STYLES[int.from_bytes(digest[:4], "big") % len(_FALLBACK_STYLES)]


def classify_rank_risk(rank: Any) -> RankRisk:
    try:
        if rank in (None, ""):
            return _RANK_RISKS["neutral"]
        value = float(rank)
    except (TypeError, ValueError):
        return _RANK_RISKS["neutral"]
    if value <= 3:
        return _RANK_RISKS["good"]
    if value <= 5:
        return _RANK_RISKS["watch"]
    if value <= 7:
        return _RANK_RISKS["warning"]
    return _RANK_RISKS["danger"]
