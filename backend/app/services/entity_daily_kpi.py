# -*- coding: utf-8 -*-
"""B3+ 实体日 KPI：本品牌与竞品共用写/读口径。

2026-08-17 - B3+：仅 ranking 进对比窗
2026-08-17 - 竞品提及与本品对称：榜空但正文点名仍计提及（均排仍要显式位次）
"""
from __future__ import annotations

from app.models.brand import BrandAsset
from app.models.monitor import GeoMonitorSubtask
from app.services.lead_diagnosis_analytics import names_match as _names_match
from app.services.ranking_parser import ranking_entry_explicit_rank, ranking_entry_name
from app.services.schedule_context import prompt_monitor_intent

# 写进竞品日表；规则升级时按日重刷
KPI_RULE_VERSION = "b3plus-a2-v2"

# 有提及无位次时的哨兵：只加 mentioned，不进均排
MENTION_WITHOUT_RANK = -1.0


def is_kpi_ranking_prompt(prompt: str | None) -> bool:
    return prompt_monitor_intent(prompt) == "ranking"


def _competitor_explicit_rank(
    subtask: GeoMonitorSubtask,
    match_terms: list[str],
) -> float | None:
    """只认原始榜里的显式位次；normalize 出场序不算。"""
    raw = subtask.all_rankings_json or []
    if not isinstance(raw, list):
        return None
    rank: float | None = None
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        name = ranking_entry_name(entry)
        if not name:
            continue
        if not any(_names_match(name, term) for term in match_terms):
            continue
        entry_rank = ranking_entry_explicit_rank(entry)
        if entry_rank is not None and (rank is None or entry_rank < rank):
            rank = float(entry_rank)
    return rank


def _competitor_mentioned_in_answer(
    subtask: GeoMonitorSubtask,
    match_terms: list[str],
) -> bool:
    """正文点名：与本品「有 mention_position / 正文露出」对称的提及门禁。"""
    answer = str(getattr(subtask, "answer_content", None) or "")
    context = str(getattr(subtask, "mention_context", None) or "")
    blob = f"{answer}\n{context}"
    if not blob.strip():
        return False
    for term in match_terms:
        text = str(term or "").strip()
        if len(text) < 2:
            continue
        if text in blob:
            return True
    return False


def resolve_entity_rank_for_kpi(
    subtask: GeoMonitorSubtask,
    match_terms: list[str],
    asset: BrandAsset | None,
    *,
    is_brand: bool,
    monitor_keywords: str | None = None,
) -> float | None:
    """对比用结果：None=未提及；>=0=有位次；MENTION_WITHOUT_RANK=有提及无位次。

    本品牌：ranking 题走 kpi_rank（可对账 mention_position）。
    竞品：显式位次优先；否则正文点名仍计提及（不借用品牌 mention_position 字段）。
    """
    if not is_kpi_ranking_prompt(getattr(subtask, "prompt", None)):
        return None
    terms = [str(t).strip() for t in (match_terms or []) if str(t).strip()]
    if is_brand:
        from app.services.monitor_service import kpi_rank_for_subtask

        # 本品牌允许 terms 为空：仍可读 mention_position / 库内权威位次
        rank = kpi_rank_for_subtask(subtask, monitor_keywords, terms, asset)
        return float(rank) if rank is not None else None
    if not terms:
        return None
    explicit = _competitor_explicit_rank(subtask, terms)
    if explicit is not None:
        return explicit
    # 2026-08-17 - 本品常靠 mention_position 而榜空；竞品同窗正文点名却不计 → 大厂虚低
    if _competitor_mentioned_in_answer(subtask, terms):
        return MENTION_WITHOUT_RANK
    return None


def empty_kpi_metrics() -> dict[str, int]:
    return {"completed": 0, "mentioned": 0, "top3": 0, "rank_sum": 0, "rank_count": 0, "citation": 0}


def apply_rank_to_metrics(metrics: dict[str, int], rank: float | None) -> None:
    if rank is None:
        return
    metrics["mentioned"] += 1
    if float(rank) < 0:
        # 有提及无位次：不进均排 / top3
        return
    metrics["rank_sum"] += int(rank)
    metrics["rank_count"] += 1
    if float(rank) <= 3:
        metrics["top3"] += 1
