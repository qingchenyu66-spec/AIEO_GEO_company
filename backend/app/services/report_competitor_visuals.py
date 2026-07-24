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
        summary = (
            f"{brand_name}当前综合平均排名约第{brand_rank:.1f}名。"
        )
        if head_competitor and gap_to_head is not None:
            summary += (
                f"头部竞品为{head_competitor['name']}（约第{head_competitor['avg_rank']:.1f}名），"
                f"品牌与其相差约{abs(gap_to_head):.1f}个位次。"
            )
        if nearest_competitor and nearest_competitor["name"] != (head_competitor or {}).get("name"):
            summary += f"近期直接对标对象为{nearest_competitor['name']}。"
        if brand_row.get("mention_rate") is not None:
            summary += f"品牌综合提及率约{float(brand_row['mention_rate']):.1f}%，需结合分平台与分语义词短板推进内容布局。"
    else:
        summary = f"{brand_name}当前缺少可核验的平均排名，建议先补齐有效样本后再判断竞争位次。"

    actions: list[str] = []
    platform_rows = platform_stats or []
    if platform_rows:
        ordered = sorted(
            platform_rows,
            key=lambda row: (_optional_float(row.get("mention_rate")) or 0.0, -(_optional_float(row.get("avg_rank")) or 0.0)),
        )
        weak = ordered[0]
        strong = ordered[-1]
        weak_name = str(weak.get("name") or weak.get("platform") or "短板平台")
        strong_name = str(strong.get("name") or strong.get("platform") or "优势平台")
        weak_rate = _optional_float(weak.get("mention_rate"))
        strong_rate = _optional_float(strong.get("mention_rate"))
        actions.append(
            f"短板平台攻坚：在「{weak_name}」系统补权威信源与结构化品牌口径"
            + (f"（当前提及率约 {weak_rate:.1f}%）" if weak_rate is not None else "")
            + "，优先产出低露出语义词对应的榜单、对比问答与可被模型摘录的结论段，而不是只发泛化通稿。"
        )
        if strong_name != weak_name:
            actions.append(
                f"优势平台复用：把「{strong_name}」上已验证有效的答法、证据链与标题结构迁移到短板平台"
                + (f"（优势侧提及率约 {strong_rate:.1f}%）" if strong_rate is not None else "")
                + "，形成跨平台统一口径，避免各平台内容各自为政导致模型采信不一致。"
            )
    else:
        actions.append(
            "平台诊断：补齐分平台明细后，按提及率与均位双指标锁定短板平台，"
            "再按平台内容形态安排榜单/问答/结构化介绍投放。"
        )

    prompt_rows = prompt_analytics or []
    if prompt_rows:
        weak_prompt = max(
            prompt_rows,
            key=lambda row: (
                _optional_float(row.get("brand_avg_rank")) or 999.0,
                -(_optional_float(row.get("brand_mention_rate")) or 0.0),
            ),
        )
        strong_prompt = min(
            prompt_rows,
            key=lambda row: (
                _optional_float(row.get("brand_avg_rank")) or 999.0,
                -(_optional_float(row.get("brand_mention_rate")) or 0.0),
            ),
        )
        weak_q = str(weak_prompt.get("prompt") or "重点问题")
        strong_q = str(strong_prompt.get("prompt") or "")
        weak_rate = _optional_float(weak_prompt.get("brand_mention_rate"))
        actions.append(
            f"语义词攻坚：围绕「{weak_q}」补场景案例、对比问答与可引用结论"
            + (f"（当前提及率约 {weak_rate:.1f}%）" if weak_rate is not None else "")
            + "，下一监测批次重点回看该问法位次与露出变化，形成「内容→复测」闭环。"
        )
        if strong_q and strong_q != weak_q:
            actions.append(
                f"优势问法巩固：保持「{strong_q}」相关内容的更新节奏与证据新鲜度，"
                f"防止优势问法被竞品用更新材料挤出推荐位。"
            )
    else:
        actions.append(
            "语义词诊断：结合问题明细锁定低提及、低排名问法，"
            "再补对比型问答与案例证据，避免只扩量不改问法结构。"
        )

    if chase_target:
        actions.append(
            f"追赶路径：以{chase_target['name']}为阶段标杆（约第{chase_target['avg_rank']:.1f}名），"
            f"优先缩小均位差距；内容侧聚焦其高露出场景词与高引用信源类型，做可落地的证据链仿制。"
        )
    if defend_target:
        actions.append(
            f"守位路径：持续领先{defend_target['name']}（约第{defend_target['avg_rank']:.1f}名），"
            f"在双方重叠的高流量问法上保持更新频率与权威信源覆盖，避免被反超。"
        )
    if head_competitor and (not chase_target or chase_target["name"] != head_competitor["name"]):
        actions.append(
            f"头部对标：拆解{head_competitor['name']}在高引用站点的内容形态（榜单/百科/问答），"
            f"按可落地优先级补齐同类证据，而不是只追求发稿量。"
        )
    actions.append(
        "信源协同：把垂直媒体、问答、百科三类信源打包进同一主题战役，"
        "确保模型在多平台回答时能交叉采信品牌相关材料，降低单站依赖。"
    )
    actions.append(
        "节奏管理：按周复盘「短板平台 × 短板语义词」组合，固定产出清单与外链投放，"
        "形成监测→内容→再监测的闭环，避免一次性投放后失联。"
    )
    actions.append(
        "资产分层：通稿只解决基础认知；对比表、案例数据、城市覆盖清单用于抬升可引用密度，"
        "两类资产分开生产、分开投放。"
    )
    # 去重保序
    deduped: list[str] = []
    for item in actions:
        if item not in deduped:
            deduped.append(item)
    actions = deduped[:7]

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
