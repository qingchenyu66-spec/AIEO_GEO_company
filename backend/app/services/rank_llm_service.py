"""DeepSeek fallback for ambiguous monitor answer rank extraction."""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from typing import Any

from app.core.config import settings
from app.models.monitor import GeoMonitorSubtask, GeoMonitorTask
from app.services.brand_service import BrandAsset, _is_industry_monitor_keyword, ranking_task_is_industry_scoped
from app.services.deepseek_client import DeepseekApiError, DeepseekClient
from app.services.monitor_service import (
    BrandRankResolution,
    _SECONDARY_MENTION_HEADING_RE,
    _answer_body_for_rank,
    _brand_appears_in_text,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LlmBrandRankResult:
    rank: int | float | None
    mentioned: bool
    category: str | None
    rank_basis: str | None
    confidence: float
    evidence: str | None
    overall_rank: int | float | None = None
    category_ranks: list | None = None


def _parse_rank_number(raw: Any) -> int | float | None:
    if raw is None or raw == "":
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value != value:  # NaN
        return None
    return int(value) if value.is_integer() else value


def _is_secondary_rank_category(name: str) -> bool:
    return bool(_SECONDARY_MENTION_HEADING_RE.search(str(name or "")))


def _select_llm_matrix_rank(
    category_ranks: list[dict[str, Any]],
    *,
    preferred_category: str | None,
) -> tuple[int | float | None, str | None]:
    """主表有 rank 就用主表；主表没有再用补充名单。禁止 min() 让「其他值得关注」盖掉主表。"""
    ranked = [row for row in category_ranks if row.get("rank") is not None]
    primary = [row for row in ranked if not _is_secondary_rank_category(str(row["category"]))]
    secondary = [row for row in ranked if _is_secondary_rank_category(str(row["category"]))]
    pool = primary or secondary
    if not pool:
        return None, preferred_category
    if preferred_category:
        named = next((row for row in pool if row["category"] == preferred_category), None)
        if named is not None:
            return named["rank"], named["category"]
    chosen = min(pool, key=lambda item: float(item["rank"]))
    return chosen["rank"], chosen["category"]


def parse_llm_rank_payload(payload: dict[str, Any]) -> LlmBrandRankResult:
    """LLM JSON → 结果。矩阵用分类排；总排只作附录。

    2026-08-19 - 总排会叠全球段，不能当 mention_position
    2026-08-19 - 主表与补充名单都有时取主表，禁止 min 到补充名单
    """
    mentioned = bool(payload.get("brand_mentioned"))
    overall = _parse_rank_number(payload.get("overall_rank"))
    category_ranks: list[dict[str, Any]] = []
    raw_cats = payload.get("category_ranks")
    if isinstance(raw_cats, list):
        for item in raw_cats:
            if not isinstance(item, dict):
                continue
            name = str(item.get("category") or item.get("name") or "").strip()
            if not name:
                continue
            category_ranks.append(
                {"category": name, "rank": _parse_rank_number(item.get("rank"))}
            )

    category = str(payload.get("category") or "").strip() or None
    category_rank = _parse_rank_number(payload.get("category_rank"))
    selected_rank, selected_category = _select_llm_matrix_rank(
        category_ranks,
        preferred_category=category,
    )
    if selected_rank is not None:
        category_rank = selected_rank
        if selected_category:
            category = selected_category
    elif category_rank is None and category:
        named = next(
            (row["rank"] for row in category_ranks if row["category"] == category),
            None,
        )
        if named is not None:
            category_rank = named
    if category_rank is None:
        category_rank = _parse_rank_number(payload.get("rank"))

    if not category and category_ranks:
        matched = next(
            (row["category"] for row in category_ranks if row.get("rank") == category_rank),
            None,
        )
        category = matched or str(category_ranks[0]["category"])

    confidence_raw = payload.get("confidence")
    try:
        confidence = float(confidence_raw)
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    return LlmBrandRankResult(
        rank=category_rank if mentioned else None,
        mentioned=mentioned,
        category=category,
        rank_basis=str(payload.get("rank_basis") or "").strip() or None,
        confidence=confidence,
        evidence=str(payload.get("evidence") or "").strip() or None,
        overall_rank=overall if mentioned else None,
        category_ranks=category_ranks or None,
    )


def should_trigger_llm_fallback(
    resolution: BrandRankResolution,
    *,
    is_industry_task: bool,
) -> bool:
    """Only call LLM for ranking prompts where rules are low-confidence."""
    if resolution.source in {"manual", "llm", "exposure"}:
        return False
    if not resolution.mentioned:
        return False
    if resolution.rank is None:
        return True
    if is_industry_task and resolution.rank > 10:
        return True
    if resolution.source == "appearance":
        return True
    if is_industry_task and resolution.source == "api":
        return True
    return False


def _truncate_answer(text: str, limit: int) -> tuple[str, bool]:
    cleaned = (text or "").strip()
    if len(cleaned) <= limit:
        return cleaned, False
    return cleaned[:limit], True


def rank_engine_is_llm() -> bool:
    return str(getattr(settings, "rank_engine", "llm") or "llm").strip().lower() == "llm"


def extract_brand_rank_with_llm(
    *,
    brand_terms: list[str],
    monitor_keyword: str,
    prompt: str,
    answer_text: str,
    force: bool = False,
) -> LlmBrandRankResult | None:
    client = DeepseekClient()
    # 2026-08-19 - rank_engine=llm 时不看 fallback 开关，有 key 就抽分类排
    if not client.api_key:
        return None
    if not force and not rank_engine_is_llm() and not client.rank_fallback_enabled:
        return None

    body, truncated = _truncate_answer(answer_text, settings.deepseek_rank_parse_max_chars)
    if not body:
        return None

    try:
        payload = client.extract_brand_rank_from_answer(
            brand_terms=brand_terms,
            monitor_keyword=monitor_keyword,
            prompt=prompt,
            answer_text=body,
            truncated=truncated,
        )
    except DeepseekApiError as exc:
        logger.warning("[rank_llm] deepseek failed monitor_keyword=%r: %s", monitor_keyword, exc)
        return None

    return parse_llm_rank_payload(payload)


def apply_llm_rank_fallback(
    resolution: BrandRankResolution,
    llm_result: LlmBrandRankResult | None,
    *,
    min_confidence: float = 0.65,
) -> BrandRankResolution:
    """合并规则结果与 LLM：有多个位次时取最靠前（数字最小）。

    2026-07-29 - 任何情况取最优 - LLM 不再无条件覆盖 appearance；与规则比 min
    """
    if llm_result is None or llm_result.confidence < min_confidence:
        return resolution
    if not llm_result.mentioned:
        if resolution.rank is None:
            return replace(resolution, mentioned=False, source="none", confidence=llm_result.confidence)
        return resolution

    llm_resolution = BrandRankResolution(
        rank=llm_result.rank,
        mentioned=True,
        source="llm",
        confidence=llm_result.confidence,
        category=llm_result.category,
        rank_basis=llm_result.rank_basis,
        evidence=llm_result.evidence,
        overall_rank=llm_result.overall_rank,
        category_ranks=llm_result.category_ranks,
    )
    if resolution.rank is None:
        return llm_resolution

    # 两边都有位次：取更靠前的一条（与方案 X 规则池一致）
    try:
        rule_key = float(resolution.rank)
        llm_key = float(llm_result.rank) if llm_result.rank is not None else float("inf")
    except (TypeError, ValueError):
        return llm_resolution
    return resolution if rule_key <= llm_key else llm_resolution


def rank_resolution_to_json(resolution: BrandRankResolution) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "source": resolution.source,
        "rank": resolution.rank,
        "mentioned": resolution.mentioned,
        "confidence": resolution.confidence,
    }
    if resolution.category:
        payload["category"] = resolution.category
    if resolution.rank_basis:
        payload["rank_basis"] = resolution.rank_basis
    if resolution.evidence:
        payload["evidence"] = resolution.evidence
    if resolution.overall_rank is not None:
        payload["overall_rank"] = resolution.overall_rank
    if resolution.category_ranks:
        payload["category_ranks"] = resolution.category_ranks
    return payload


def persist_rank_resolution(subtask: GeoMonitorSubtask, resolution: BrandRankResolution) -> None:
    from datetime import datetime

    raw = dict(subtask.raw_result_json or {})
    payload = rank_resolution_to_json(resolution)
    # 2026-08-14 - 落库权威元数据带解析时间，补跑/详情可审计
    payload["parsed_at"] = datetime.now().isoformat(timespec="seconds")
    raw["rank_resolution"] = payload
    subtask.raw_result_json = raw


def _llm_resolution_from_result(llm_result: LlmBrandRankResult) -> BrandRankResolution:
    return BrandRankResolution(
        rank=llm_result.rank,
        mentioned=True,
        source="llm",
        confidence=llm_result.confidence,
        category=llm_result.category,
        rank_basis=llm_result.rank_basis or "category_local",
        evidence=llm_result.evidence,
        overall_rank=llm_result.overall_rank,
        category_ranks=llm_result.category_ranks,
    )


def resolve_rank_with_optional_llm(
    *,
    subtask: GeoMonitorSubtask,
    task: GeoMonitorTask,
    resolution: BrandRankResolution,
    brand_terms: list[str],
    asset: BrandAsset | None,
) -> BrandRankResolution:
    monitor_keyword = str(task.monitor_keywords or "").strip()
    answer_text = _answer_body_for_rank(subtask)
    if not _brand_appears_in_text(answer_text, brand_terms):
        return resolution

    def _run_llm() -> LlmBrandRankResult | None:
        result = extract_brand_rank_with_llm(
            brand_terms=brand_terms,
            monitor_keyword=monitor_keyword,
            prompt=str(subtask.prompt or ""),
            answer_text=answer_text,
            force=rank_engine_is_llm(),
        )
        if result is not None and result.mentioned and result.evidence:
            if result.evidence not in answer_text:
                # 2026-08-11 - LLM evidence 不在正文 - 丢弃，防 context 串味
                return None
        return result

    # 2026-08-19 - 规则计位先停：矩阵只用 LLM 分类排，不再和规则取 min
    if rank_engine_is_llm():
        llm_result = _run_llm()
        if llm_result is None or not llm_result.mentioned or llm_result.rank is None:
            return BrandRankResolution(
                rank=None,
                mentioned=True,
                source="none",
                confidence=0.4,
                rank_basis="llm_miss",
            )
        if llm_result.confidence < 0.65:
            return BrandRankResolution(
                rank=None,
                mentioned=True,
                source="none",
                confidence=llm_result.confidence,
                rank_basis="llm_low_conf",
                category=llm_result.category,
                evidence=llm_result.evidence,
                overall_rank=llm_result.overall_rank,
                category_ranks=llm_result.category_ranks,
            )
        return _llm_resolution_from_result(llm_result)

    is_industry_task = ranking_task_is_industry_scoped(monitor_keyword, subtask.prompt, asset)
    if not should_trigger_llm_fallback(resolution, is_industry_task=is_industry_task):
        return resolution
    return apply_llm_rank_fallback(resolution, _run_llm())
