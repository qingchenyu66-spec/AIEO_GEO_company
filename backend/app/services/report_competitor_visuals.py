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


def _optional_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _risk_dict(rank: Any) -> dict[str, str]:
    risk = classify_rank_risk(rank)
    return {"level": risk.level, "label": risk.label, "color": risk.color}


def _analysis_row(row: dict[str, Any], *, brand_name: str) -> dict[str, Any]:
    name = str(row.get("name") or "").strip()
    rank = _optional_float(row.get("avg_rank"))
    mention_rate = _optional_float(row.get("mention_rate")) or 0.0
    style = entity_visual_style(name, brand_name=brand_name)
    return {
        "name": name,
        "avg_rank": rank,
        "mention_rate": round(mention_rate, 1),
        "is_brand": bool(row.get("is_brand")) or normalize_entity_name(name) == normalize_entity_name(brand_name),
        "risk": _risk_dict(rank),
        "style": {
            "color": style.color,
            "line_style": str(style.line_style),
            "marker": style.marker,
            "css_dash": style.css_dash,
        },
    }


def build_competitor_analysis(
    *,
    brand_name: str,
    rows: list[dict[str, Any]],
    platform_stats: list[dict[str, Any]] | None = None,
    prompt_analytics: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a deterministic, data-bound management and operations summary."""
    normalized_rows = [
        _analysis_row(row, brand_name=brand_name)
        for row in rows
        if str(row.get("name") or "").strip()
    ]
    brand_row = next((row for row in normalized_rows if row["is_brand"]), None)
    competitors = [row for row in normalized_rows if not row["is_brand"]]
    ranked_competitors = [row for row in competitors if row["avg_rank"] is not None]
    ranked_competitors.sort(key=lambda row: (row["avg_rank"], row["name"]))
    brand_rank = brand_row["avg_rank"] if brand_row else None
    head_competitor = ranked_competitors[0] if ranked_competitors else None
    nearest_competitor = None
    if brand_rank is not None and ranked_competitors:
        nearest_competitor = min(
            ranked_competitors,
            key=lambda row: (abs(row["avg_rank"] - brand_rank), row["avg_rank"], row["name"]),
        )
    gap_to_head = None
    if brand_rank is not None and head_competitor is not None:
        gap_to_head = round(brand_rank - head_competitor["avg_rank"], 1)

    chase_candidates = [row for row in ranked_competitors if brand_rank is not None and row["avg_rank"] < brand_rank]
    defend_candidates = [row for row in ranked_competitors if brand_rank is not None and row["avg_rank"] > brand_rank]
    chase_target = chase_candidates[0] if chase_candidates else None
    defend_target = min(
        defend_candidates,
        key=lambda row: (row["avg_rank"] - brand_rank, row["name"]),
        default=None,
    )

    tiers = {
        "head": [row for row in normalized_rows if row["avg_rank"] is not None and row["avg_rank"] <= 3],
        "middle": [row for row in normalized_rows if row["avg_rank"] is not None and 3 < row["avg_rank"] <= 5],
        "chasing": [row for row in normalized_rows if row["avg_rank"] is not None and row["avg_rank"] > 5],
        "insufficient": [row for row in normalized_rows if row["avg_rank"] is None],
    }

    if brand_row and brand_rank is not None:
        summary = f"{brand_name}当前平均排名为第{brand_rank:.1f}名，{brand_row['risk']['label']}。"
        if head_competitor and gap_to_head is not None:
            summary += f"头部竞品为{head_competitor['name']}，品牌与其相差{abs(gap_to_head):.1f}个位次。"
        if nearest_competitor:
            summary += f"最近的直接对标对象为{nearest_competitor['name']}。"
    else:
        summary = f"{brand_name}当前缺少可核验的平均排名，暂不判断竞争位次。"

    actions: list[str] = []
    platform_rows = platform_stats or []
    if platform_rows:
        weak_platform = min(
            platform_rows,
            key=lambda row: (_optional_float(row.get("mention_rate")) or 0.0, -(_optional_float(row.get("avg_rank")) or 0.0)),
        )
        platform_name = str(weak_platform.get("name") or weak_platform.get("platform") or "该平台")
        actions.append(
            f"平台动作：优先复盘{platform_name}，围绕当前提及率和排名短板补充权威信源与结构化品牌内容。"
        )
    else:
        actions.append("平台动作：需结合平台明细确认短板平台，再安排权威信源和品牌内容补强。")

    prompt_rows = prompt_analytics or []
    if prompt_rows:
        weak_prompt = max(
            prompt_rows,
            key=lambda row: (
                _optional_float(row.get("brand_avg_rank")) or 999.0,
                -(_optional_float(row.get("brand_mention_rate")) or 0.0),
            ),
        )
        prompt = str(weak_prompt.get("prompt") or "重点问题")
        actions.append(f"问题动作：针对“{prompt}”补充对比型问答、案例证据和可引用结论，并在下一执行批次复测。")
    else:
        actions.append("问题动作：需结合问题明细确认低提及、低排名语义词，再补充对比型问答和案例证据。")

    if chase_target:
        actions.append(f"追赶目标：以{chase_target['name']}为阶段标杆，优先缩小平均排名差距。")
    if defend_target:
        actions.append(f"守位目标：持续领先{defend_target['name']}，避免现有排名优势被反超。")

    return {
        "rows": normalized_rows,
        "tiers": tiers,
        "brand_position": brand_row,
        "head_competitor": head_competitor,
        "nearest_competitor": nearest_competitor,
        "gap_to_head": gap_to_head,
        "defend_target": defend_target,
        "chase_target": chase_target,
        "management_summary": summary,
        "actions": actions,
    }
