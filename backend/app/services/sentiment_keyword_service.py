"""Extract positive/negative keyword phrases from monitor answers for word cloud."""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, time
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, load_only

from app.api.dependencies import CurrentSession
from app.core.chinese_stop_words import SENTIMENT_NOISE_SUBSTRINGS, SENTIMENT_STOP_WORDS
from app.models.monitor import GeoMonitorSubtask, GeoMonitorTask
from app.services.brand_service import get_brand_asset, list_competitors
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
_LLM_MAX_SUBTASKS = 24
# 默认开启 DeepSeek 精修；规则路径作降级。快取子任务仍用 schedule_key。
_DEFAULT_USE_LLM = True
_FAST_SUBTASK_CAP = 800
_COMPANY_ENTITY_RE = re.compile(
    r"(传媒|广告|媒体|控股|集团|有限公司|股份|银行|保险|重工)$"
)
_CITY_PREFIX_RE = re.compile(
    r"^(北京|上海|广州|深圳|杭州|成都|重庆|天津|苏州|南京|武汉|西安|青岛|大连|厦门|"
    r"宁波|合肥|郑州|长沙|济南|中国|全国)"
)

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


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", (text or "").strip())


def _is_valid_phrase(phrase: str) -> bool:
    text = phrase.strip()
    if not text or _NOISE_RE.match(text):
        return False
    if len(text) < 4 or len(text) > 28:
        return False
    chinese_chars = re.findall(r"[\u4e00-\u9fff]", text)
    if len(chinese_chars) < 2:
        return False
    if text in SENTIMENT_STOP_WORDS or _compact(text) in SENTIMENT_STOP_WORDS:
        return False
    if re.fullmatch(r"[\d\sWw%+]+", text):
        return False
    return True


def _blocked_entity_names(asset, competitors) -> set[str]:
    """本品牌 + 配置竞品名/别名，避免词云被主体或竞品实体名刷屏。"""
    blocked = set(_brand_names(asset))
    for competitor in competitors or []:
        for value in (
            getattr(competitor, "name", None),
            getattr(competitor, "short_name", None),
            *(getattr(competitor, "aliases_json", None) or []),
        ):
            text = str(value or "").strip()
            if len(text) >= 2:
                blocked.add(text)
    return blocked


def _is_entity_like_phrase(text: str, blocked: set[str]) -> bool:
    compact = _compact(text)
    if not compact:
        return True
    for name in blocked:
        entity = _compact(name)
        if not entity:
            continue
        if compact == entity:
            return True
        # 「分众传媒」「艾迪亚控股集团」等实体名或仅加短缀
        if entity in compact and len(compact) <= len(entity) + 4:
            return True
        if compact in entity and len(entity) - len(compact) <= 4:
            return True
    if _COMPANY_ENTITY_RE.search(compact):
        return True
    # 短地名 / 行政区（上海浦东、中国平安类短实体另由公司后缀或 blocked 处理）
    if _CITY_PREFIX_RE.match(compact) and len(compact) <= 6:
        return True
    if compact.endswith("等") and len(compact) <= 8:
        return True
    return False


def _is_useful_sentiment_phrase(text: str, blocked: set[str]) -> bool:
    """正负面词云：只要评价向短语，丢掉实体名、套话、空泛营销词。"""
    if not _is_valid_phrase(text):
        return False
    compact = _compact(text)
    for noise in SENTIMENT_NOISE_SUBSTRINGS:
        if noise in compact:
            return False
    if _is_entity_like_phrase(text, blocked):
        return False
    return True


def _extract_phrases(text: str | None, *, blocked: set[str]) -> set[str]:
    if not text:
        return set()
    cleaned = _clean_text(text)
    if not cleaned:
        return set()

    phrases: set[str] = set()
    for clause in _CLAUSE_SPLIT.split(cleaned):
        clause = clause.strip()
        if _is_useful_sentiment_phrase(clause, blocked):
            phrases.add(clause)
        for part in _PHRASE_SPLIT.split(clause):
            part = part.strip()
            if _is_useful_sentiment_phrase(part, blocked):
                phrases.add(part)

    for word in re.findall(r"[\u4e00-\u9fff]{4,12}", cleaned):
        if _is_useful_sentiment_phrase(word, blocked):
            phrases.add(word)
    return phrases


def _brand_names(asset) -> set[str]:
    names: set[str] = set()
    if asset is None:
        return names
    for value in (
        asset.brand_name,
        asset.brand_short_name,
        asset.company_full_name,
        *(getattr(asset, "aliases_json", None) or []),
    ):
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
    blocked: set[str],
) -> dict[str, dict[str, Any]]:
    bucket: dict[str, dict[str, Any]] = defaultdict(lambda: {"count": 0, "subtask_ids": [], "task_ids": []})
    for item in items:
        phrases = _extract_phrases(item.mention_context, blocked=blocked)
        phrases.update(_extract_phrases(item.answer_content, blocked=blocked))
        for phrase in phrases:
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
    blocked: set[str],
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

    exclude_names = sorted(blocked, key=len, reverse=True)[:40]
    extracted_total = 0
    batches = [
        excerpts[start:start + _LLM_BATCH_SIZE]
        for start in range(0, len(excerpts), _LLM_BATCH_SIZE)
    ]
    try:
        workers = min(4, max(1, len(batches)))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(
                client.extract_sentiment_phrases,
                brand_name=brand_display,
                polarity=polarity,
                excerpts=batch,
                exclude_names=exclude_names,
            ) for batch in batches]
            for future in as_completed(futures):
                phrases = future.result()
                for row in phrases:
                    text = row["text"]
                    if not _is_useful_sentiment_phrase(text, blocked):
                        continue
                    entry = bucket[text]
                    entry["count"] += 1
                    entry["subtask_ids"].append(row["subtask_id"])
                    entry["task_ids"].append(row["task_id"])
                    extracted_total += 1
    except DeepseekApiError as exc:
        logger.warning("DeepSeek 情绪词提取失败：%s", exc)
        return None

    if extracted_total == 0:
        return None
    return bucket

def _brand_mentioned_light(item: GeoMonitorSubtask, brand_names: set[str]) -> bool:
    """词云快路径：位次命中或正文含品牌名即可，避免每条都 normalize 推荐 JSON。"""
    if item.mention_position is not None:
        return True
    if not brand_names:
        return True
    blob = f"{item.mention_context or ''}\n{item.answer_content or ''}"
    if not blob.strip():
        return False
    return any(name and name in blob for name in brand_names)


def _load_sentiment_subtasks_fast(
    db: Session,
    tenant_id: int,
    *,
    asset,
    range_start: datetime,
    range_end: datetime,
    platform_filters: list[str],
    prompt_filter: str,
) -> list[GeoMonitorSubtask]:
    """与竞品对比同源：schedule_key 业务日 + 轻字段；失败再回退宽扫。"""
    from app.services.competitor_analytics_service import _schedule_task_day_map

    range_start_day = range_start.date()
    range_end_day = range_end.date()
    task_day_map = _schedule_task_day_map(
        db,
        tenant_id,
        range_start_day=range_start_day,
        range_end_day=range_end_day,
    )
    light_cols = (
        GeoMonitorSubtask.subtask_id,
        GeoMonitorSubtask.task_id,
        GeoMonitorSubtask.platform,
        GeoMonitorSubtask.prompt,
        GeoMonitorSubtask.sentiment,
        GeoMonitorSubtask.mention_position,
        GeoMonitorSubtask.mention_context,
        GeoMonitorSubtask.answer_content,
    )
    if task_day_map:
        stmt = (
            select(GeoMonitorSubtask)
            .options(load_only(*light_cols))
            .where(
                GeoMonitorSubtask.task_id.in_(list(task_day_map.keys())),
                GeoMonitorSubtask.status.in_(("completed", "partial_completed")),
                GeoMonitorSubtask.sentiment.isnot(None),
            )
        )
        if platform_filters:
            stmt = stmt.where(GeoMonitorSubtask.platform.in_(platform_filters))
        if prompt_filter:
            stmt = stmt.where(GeoMonitorSubtask.prompt == prompt_filter)
        return list(db.scalars(stmt.limit(_FAST_SUBTASK_CAP)))

    from app.services.monitor_stats_service import load_subtasks_for_business_date_range

    fetched, _tasks, _day_by_id = load_subtasks_for_business_date_range(
        db,
        tenant_id,
        start_date=range_start_day,
        end_date=range_end_day,
        asset=asset,
        limit=_FAST_SUBTASK_CAP,
    )
    out: list[GeoMonitorSubtask] = []
    for item in fetched:
        if item.sentiment is None:
            continue
        if platform_filters and item.platform not in platform_filters:
            continue
        if prompt_filter and item.prompt != prompt_filter:
            continue
        out.append(item)
    return out


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
    use_llm: bool = _DEFAULT_USE_LLM,
) -> dict[str, Any]:
    resolved_tenant_id = resolve_and_guard_analytics_tenant(db, current, tenant_id)

    asset = get_brand_asset(db, resolved_tenant_id)
    brand_names = _brand_names(asset)
    competitors = list_competitors(db, resolved_tenant_id)
    blocked = _blocked_entity_names(asset, competitors)
    range_start, range_end = resolve_analytics_date_range(
        current,
        days=days,
        start_date=start_date,
        end_date=end_date,
    )
    platform_filters = _parse_platform_filters(platform, platforms)
    prompt_filter = str(prompt or "").strip()

    subtasks = _load_sentiment_subtasks_fast(
        db,
        resolved_tenant_id,
        asset=asset,
        range_start=range_start,
        range_end=range_end,
        platform_filters=platform_filters,
        prompt_filter=prompt_filter,
    )
    brand_display = (asset.brand_name if asset else None) or "本品牌"
    grouped: dict[str, list[GeoMonitorSubtask]] = {"positive": [], "negative": []}
    sample_counts = {"positive": 0, "negative": 0}

    for item in subtasks:
        polarity = _normalize_sentiment_label(item.sentiment)
        if polarity not in ("positive", "negative"):
            continue
        if not _brand_mentioned_light(item, brand_names):
            continue
        sample_counts[polarity] += 1
        grouped[polarity].append(item)

    buckets: dict[str, dict[str, dict[str, Any]]] = {"positive": {}, "negative": {}}
    used_llm = False

    def build_polarity_bucket(polarity: str) -> tuple[str, dict[str, dict[str, Any]], bool]:
        if use_llm:
            llm_bucket = _aggregate_with_deepseek(
                brand_display=brand_display,
                polarity=polarity,
                items=grouped[polarity],
                blocked=blocked,
            )
            if llm_bucket:
                return polarity, llm_bucket, True
        return polarity, _aggregate_rule_based(grouped[polarity], blocked), False
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {
            executor.submit(build_polarity_bucket, polarity): polarity
            for polarity in ("positive", "negative")
        }
        for future in as_completed(futures):
            polarity, bucket, llm_used = future.result()
            buckets[polarity] = bucket
            used_llm = used_llm or llm_used

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
