"""DeepSeek fallback for ambiguous monitor answer rank extraction."""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from typing import Any

from app.core.config import settings
from app.models.monitor import GeoMonitorSubtask, GeoMonitorTask
from app.services.brand_service import BrandAsset, _is_industry_monitor_keyword
from app.services.deepseek_client import DeepseekApiError, DeepseekClient
from app.services.monitor_service import BrandRankResolution, _subtask_answer_plaintext

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LlmBrandRankResult:
    rank: int | float | None
    mentioned: bool
    category: str | None
    rank_basis: str | None
    confidence: float
    evidence: str | None


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
    return False


def _truncate_answer(text: str, limit: int) -> tuple[str, bool]:
    cleaned = (text or "").strip()
    if len(cleaned) <= limit:
        return cleaned, False
    return cleaned[:limit], True


def extract_brand_rank_with_llm(
    *,
    brand_terms: list[str],
    monitor_keyword: str,
    prompt: str,
    answer_text: str,
) -> LlmBrandRankResult | None:
    client = DeepseekClient()
    if not client.rank_fallback_enabled:
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

    mentioned = bool(payload.get("brand_mentioned"))
    rank_raw = payload.get("rank")
    rank: int | float | None
    if rank_raw is None:
        rank = None
    else:
        try:
            rank_value = float(rank_raw)
            rank = int(rank_value) if rank_value.is_integer() else rank_value
        except (TypeError, ValueError):
            rank = None

    confidence_raw = payload.get("confidence")
    try:
        confidence = float(confidence_raw)
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    return LlmBrandRankResult(
        rank=rank if mentioned else None,
        mentioned=mentioned,
        category=str(payload.get("category") or "").strip() or None,
        rank_basis=str(payload.get("rank_basis") or "").strip() or None,
        confidence=confidence,
        evidence=str(payload.get("evidence") or "").strip() or None,
    )


def apply_llm_rank_fallback(
    resolution: BrandRankResolution,
    llm_result: LlmBrandRankResult | None,
    *,
    min_confidence: float = 0.65,
) -> BrandRankResolution:
    if llm_result is None or llm_result.confidence < min_confidence:
        return resolution
    if not llm_result.mentioned:
        if resolution.rank is None:
            return replace(resolution, mentioned=False, source="none", confidence=llm_result.confidence)
        return resolution

    if resolution.rank is None:
        return BrandRankResolution(
            rank=llm_result.rank,
            mentioned=True,
            source="llm",
            confidence=llm_result.confidence,
            category=llm_result.category,
            rank_basis=llm_result.rank_basis,
            evidence=llm_result.evidence,
        )

    if resolution.source == "appearance" or (resolution.rank is not None and resolution.rank > 10):
        return BrandRankResolution(
            rank=llm_result.rank,
            mentioned=True,
            source="llm",
            confidence=llm_result.confidence,
            category=llm_result.category,
            rank_basis=llm_result.rank_basis,
            evidence=llm_result.evidence,
        )
    return resolution


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
    return payload


def persist_rank_resolution(subtask: GeoMonitorSubtask, resolution: BrandRankResolution) -> None:
    raw = dict(subtask.raw_result_json or {})
    raw["rank_resolution"] = rank_resolution_to_json(resolution)
    subtask.raw_result_json = raw


def resolve_rank_with_optional_llm(
    *,
    subtask: GeoMonitorSubtask,
    task: GeoMonitorTask,
    resolution: BrandRankResolution,
    brand_terms: list[str],
    asset: BrandAsset | None,
) -> BrandRankResolution:
    monitor_keyword = str(task.monitor_keywords or "").strip()
    is_industry_task = asset is not None and _is_industry_monitor_keyword(monitor_keyword, asset)
    if not should_trigger_llm_fallback(resolution, is_industry_task=is_industry_task):
        return resolution

    llm_result = extract_brand_rank_with_llm(
        brand_terms=brand_terms,
        monitor_keyword=monitor_keyword,
        prompt=str(subtask.prompt or ""),
        answer_text=_subtask_answer_plaintext(subtask),
    )
    return apply_llm_rank_fallback(resolution, llm_result)
