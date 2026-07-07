"""Extract positive/negative keyword phrases from monitor answers for word cloud."""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from datetime import date, datetime, timedelta, time
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, load_only

from app.api.dependencies import CurrentSession
from app.core.chinese_stop_words import SENTIMENT_STOP_WORDS
from app.models.monitor import GeoMonitorSubtask, GeoMonitorTask
from app.services.brand_service import get_brand_asset
from app.services.competitor_analytics_service import (
    _entity_mentioned_in_entries,
    _normalize_sentiment_label,
    _parse_platform_filters,
    resolve_analytics_date_range,
)
from app.services.tenant_scope import resolve_and_guard_analytics_tenant
from app.services.deepseek_client import DeepseekApiError, DeepseekClient
from app.services.ranking_parser import normalize_structured_rankings

logger = logging.getLogger(__name__)

_LLM_BATCH_SIZE = 8
_LLM_MAX_SUBTASKS = 32

_CITATION_RE = re.compile(r"\[\s*citation\s*:\s*\d+\s*\]", re.I)
_MARKDOWN_RE = re.compile(r"\*\*|__|`")
_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_CLAUSE_SPLIT = re.compile(r"[。！？；\n\r|]+")
_PHRASE_SPLIT = re.compile(r"[；;，,、：:]+")
_NOISE_RE = re.compile(r"^[#\->\s|·•\d.]+$")


def _clean_text(text: str) -> str:
    cleaned = _CITATION_RE.sub("", text)
    cleaned = _LINK_RE.sub(r"\1", cleaned)
    cleaned = _MARKDOWN_RE.sub("", cleaned)
    cleaned = re.sub(r"^[*\-\s]+", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"[#\->\|]", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def _is_valid_phrase(phrase: str) -> bool:
    text = phrase.strip()
    if not text or _NOISE_RE.match(text):
        return False
    if len(text) < 4 or len(text) > 28:
        return False
    chinese_chars = re.findall(r"[\u4e00-\u9fff]", text)
    if len(chinese_chars) < 2:
        return False
    if text in SENTIMENT_STOP_WORDS:
        return False
    if re.fullmatch(r"[\d\sWw%+]+", text):
        return False
    return True


def _extract_phrases(text: str | None) -> set[str]:
    if not text:
        return set()
    cleaned = _clean_text(text)
    if not cleaned:
        return set()

    phrases: set[str] = set()
    for clause in _CLAUSE_SPLIT.split(cleaned):
        clause = clause.strip()
        if _is_valid_phrase(clause):
            phrases.add(clause)
        for part in _PHRASE_SPLIT.split(clause):
            part = part.strip()
            if _is_valid_phrase(part):
                phrases.add(part)

    for word in re.findall(r"[\u4e00-\u9fff]{4,12}", cleaned):
        if word not in SENTIMENT_STOP_WORDS:
            phrases.add(word)
    return phrases


def _brand_names(asset) -> set[str]:
    names: set[str] = set()
    if asset is None:
        return names
    for value in (asset.brand_name, asset.brand_short_name, asset.company_full_name):
        text = str(value or "").strip()
        if text:
            names.add(text)
    return names


def _brand_mentioned(item: GeoMonitorSubtask, brand_names: set[str]) -> bool:
    if item.mention_position is not None:
        return True
    if not brand_names:
        return True
    entries = normalize_structured_rankings(item.all_rankings_json or [])
    return any(_entity_mentioned_in_entries(entries, name) for name in brand_names)


def _snippet_for_subtask(item: GeoMonitorSubtask) -> str:
    context = _clean_text(item.mention_context or "")
    if context:
        return context[:420]
    answer = _clean_text(item.answer_content or "")
    return answer[:720]


def _aggregate_rule_based(
    items: list[GeoMonitorSubtask],
    brand_names: set[str],
) -> dict[str, dict[str, Any]]:
    bucket: dict[str, dict[str, Any]] = defaultdict(lambda: {"count": 0, "subtask_ids": [], "task_ids": []})
    for item in items:
        phrases = _extract_phrases(item.mention_context)
        phrases.update(_extract_phrases(item.answer_content))
        for phrase in phrases:
            if brand_names and phrase in brand_names:
                continue
            entry = bucket[phrase]
            entry["count"] += 1
            entry["subtask_ids"].append(item.subtask_id)
            entry["task_ids"].append(item.task_id)
    return bucket


def _aggregate_with_deepseek(
    *,
    brand_display: str,
    polarity: str,
    items: list[GeoMonitorSubtask],
    brand_names: set[str],
) -> dict[str, dict[str, Any]] | None:
    client = DeepseekClient()
    if not client.enabled or not items:
        return None

    bucket: dict[str, dict[str, Any]] = defaultdict(lambda: {"count": 0, "subtask_ids": [], "task_ids": []})
    sampled = items[:_LLM_MAX_SUBTASKS]
    excerpts = [
        {
            "subtask_id": item.subtask_id,
            "task_id": item.task_id,
            "text": _snippet_for_subtask(item),
        }
        for item in sampled
        if _snippet_for_subtask(item)
    ]
    if not excerpts:
        return None

    extracted_total = 0
    for start in range(0, len(excerpts), _LLM_BATCH_SIZE):
        batch = excerpts[start:start + _LLM_BATCH_SIZE]
        try:
            phrases = client.extract_sentiment_phrases(
                brand_name=brand_display,
                polarity=polarity,
                excerpts=batch,
            )
        except DeepseekApiError as exc:
            logger.warning("DeepSeek 情绪词提取失败：%s", exc)
            return None
        for row in phrases:
            text = row["text"]
            if brand_names and text in brand_names:
                continue
            entry = bucket[text]
            entry["count"] += 1
            entry["subtask_ids"].append(row["subtask_id"])
            entry["task_ids"].append(row["task_id"])
            extracted_total += 1

    if extracted_total == 0:
        return None
    return bucket


def build_sentiment_keywords(
    db: Session,
    current: CurrentSession,
    *,
    tenant_id: int | None = None,
    platform: str | None = None,
    platforms: str | None = None,
    days: int = 30,
    start_date: date | None = None,
    end_date: date | None = None,
    prompt: str | None = None,
    limit: int = 80,
) -> dict[str, Any]:
    resolved_tenant_id = resolve_and_guard_analytics_tenant(db, current, tenant_id)

    asset = get_brand_asset(db, resolved_tenant_id)
    brand_names = _brand_names(asset)
    range_start, range_end = resolve_analytics_date_range(
        current,
        days=days,
        start_date=start_date,
        end_date=end_date,
    )
    platform_filters = _parse_platform_filters(platform, platforms)
    prompt_filter = str(prompt or "").strip()

    stmt = (
        select(GeoMonitorSubtask)
        .join(GeoMonitorTask, GeoMonitorTask.task_id == GeoMonitorSubtask.task_id)
        .options(
            load_only(
                GeoMonitorSubtask.subtask_id,
                GeoMonitorSubtask.task_id,
                GeoMonitorSubtask.platform,
                GeoMonitorSubtask.prompt,
                GeoMonitorSubtask.mention_position,
                GeoMonitorSubtask.all_rankings_json,
                GeoMonitorSubtask.sentiment,
                GeoMonitorSubtask.answer_content,
                GeoMonitorSubtask.mention_context,
                GeoMonitorSubtask.updated_at,
            )
        )
        .where(
            GeoMonitorTask.deleted.is_(False),
            GeoMonitorTask.tenant_id == resolved_tenant_id,
            GeoMonitorSubtask.updated_at >= range_start,
            GeoMonitorSubtask.updated_at <= range_end,
            GeoMonitorSubtask.status.in_(("completed", "partial_completed")),
            GeoMonitorSubtask.sentiment.isnot(None),
        )
    )
    if platform_filters:
        stmt = stmt.where(GeoMonitorSubtask.platform.in_(platform_filters))
    if prompt_filter:
        stmt = stmt.where(GeoMonitorSubtask.prompt == prompt_filter)

    subtasks = list(db.scalars(stmt.limit(5000)))
    brand_display = (asset.brand_name if asset else None) or "本品牌"
    grouped: dict[str, list[GeoMonitorSubtask]] = {"positive": [], "negative": []}
    sample_counts = {"positive": 0, "negative": 0}

    for item in subtasks:
        polarity = _normalize_sentiment_label(item.sentiment)
        if polarity not in ("positive", "negative"):
            continue
        if not _brand_mentioned(item, brand_names):
            continue
        sample_counts[polarity] += 1
        grouped[polarity].append(item)

    buckets: dict[str, dict[str, dict[str, Any]]] = {"positive": {}, "negative": {}}
    used_llm = False
    for polarity in ("positive", "negative"):
        llm_bucket = _aggregate_with_deepseek(
            brand_display=brand_display,
            polarity=polarity,
            items=grouped[polarity],
            brand_names=brand_names,
        )
        if llm_bucket:
            buckets[polarity] = llm_bucket
            used_llm = True
        else:
            buckets[polarity] = _aggregate_rule_based(grouped[polarity], brand_names)

    def finalize(polarity: str) -> list[dict[str, Any]]:
        rows = []
        for text, stats in buckets[polarity].items():
            rows.append({
                "text": text,
                "count": int(stats["count"]),
                "subtask_id": stats["subtask_ids"][0],
                "task_id": stats["task_ids"][0],
                "subtask_ids": stats["subtask_ids"][:5],
            })
        rows.sort(key=lambda row: (-row["count"], row["text"]))
        return rows[: max(1, min(limit, 120))]

    return {
        "positive": finalize("positive"),
        "negative": finalize("negative"),
        "positive_sample": sample_counts["positive"],
        "negative_sample": sample_counts["negative"],
        "source": "deepseek" if used_llm else "rule",
    }
