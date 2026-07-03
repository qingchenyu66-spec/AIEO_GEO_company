"""Aggregate competitor mention/rank stats from synced monitor subtasks."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, time
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, load_only

from app.api.dependencies import CurrentSession
from app.models.brand import BrandAsset
from app.models.monitor import GeoMonitorSubtask, GeoMonitorTask
from app.services.brand_service import get_brand_asset, list_competitors
from app.services.monitor_service import customer_display_cutoff
from app.services.tenant_scope import resolve_and_guard_analytics_tenant
from app.core.platform_order import sort_platform_items
from app.services.ranking_parser import (
    normalize_structured_rankings,
    ranking_entry_explicit_rank,
    ranking_entry_name,
)


def _normalize_name_key(name: str | None) -> str:
    text = str(name or "").strip().lower()
    return re.sub(r"\s+", "", text)


def _names_match(left: str | None, right: str | None) -> bool:
    a = _normalize_name_key(left)
    b = _normalize_name_key(right)
    if not a or not b:
        return False
    if a == b or a in b or b in a:
        return True
    if len(a) >= 2 and len(b) >= 2 and (a[:2] in b or b[:2] in a):
        return True
    return False


def _find_entity_rank(entries: list[dict[str, Any]], entity_name: str) -> float | None:
    for entry in entries:
        if _names_match(ranking_entry_name(entry), entity_name):
            rank = ranking_entry_explicit_rank(entry)
            if rank is not None:
                return float(rank)
    return None


def _entity_mentioned_in_entries(entries: list[dict[str, Any]], entity_name: str) -> bool:
    return any(_names_match(ranking_entry_name(entry), entity_name) for entry in entries)


def _competitor_field(item: Any, attr: str, dict_key: str) -> Any:
    if isinstance(item, dict):
        return item.get(dict_key)
    return getattr(item, attr, None)


def _competitor_aliases(item: Any) -> list[Any]:
    if isinstance(item, dict):
        raw = item.get("aliases")
    else:
        raw = getattr(item, "aliases_json", None)
    return list(raw or [])


def _brand_match_terms(asset: BrandAsset | None) -> list[str]:
    if asset is None:
        return []
    terms: list[str] = []
    for value in (asset.brand_name, asset.brand_short_name, asset.company_full_name):
        text = str(value or "").strip()
        if text and text not in terms:
            terms.append(text)
    return terms


def _tracked_entities(asset: BrandAsset | None, competitors: list[Any]) -> list[dict[str, Any]]:
    """仅返回本品牌与各竞品主名称；别名仅用于匹配推荐列表，不单独成系列。"""
    rows: list[dict[str, Any]] = []
    brand_terms = _brand_match_terms(asset)
    if brand_terms:
        rows.append({
            "name": brand_terms[0],
            "is_brand": True,
            "match_terms": brand_terms,
        })
    for item in competitors:
        name = str(_competitor_field(item, "name", "name") or "").strip()
        if not name:
            continue
        terms = [name]
        for alias in _competitor_aliases(item):
            text = str(alias or "").strip()
            if text and text not in terms:
                terms.append(text)
        rows.append({"name": name, "is_brand": False, "match_terms": terms})
    return rows


def _entity_match_stats(
    entries: list[dict[str, Any]],
    match_terms: list[str],
    *,
    mention_position: int | None = None,
    is_brand: bool = False,
) -> tuple[bool, float | None]:
    rank: float | None = None
    mentioned = False
    for term in match_terms:
        term_rank = _find_entity_rank(entries, term)
        if term_rank is not None and (rank is None or term_rank < rank):
            rank = term_rank
        if _entity_mentioned_in_entries(entries, term):
            mentioned = True
    if is_brand and rank is None and mention_position is not None:
        rank = float(mention_position)
        mentioned = True
    return mentioned, rank


def _init_bucket(name: str, *, is_brand: bool) -> dict[str, Any]:
    return {
        "name": name,
        "is_brand": is_brand,
        "mention_count": 0,
        "first_mention_count": 0,
        "rank_total": 0.0,
        "rank_count": 0,
        "sentiment_positive": 0,
        "sentiment_neutral": 0,
        "sentiment_negative": 0,
        "sentiment_sample": 0,
    }


def _normalize_sentiment_label(value: str | None) -> str | None:
    text = str(value or "").strip().lower()
    mapping = {
        "positive": "positive",
        "negative": "negative",
        "neutral": "neutral",
        "正向": "positive",
        "负向": "negative",
        "中立": "neutral",
        "正面": "positive",
        "负面": "negative",
        "中性": "neutral",
    }
    return mapping.get(text)


def _finalize_bucket(bucket: dict[str, Any], sample_total: int) -> dict[str, Any]:
    mention_count = int(bucket["mention_count"])
    rank_count = int(bucket["rank_count"])
    first_mention_count = int(bucket["first_mention_count"])
    avg_rank = round(bucket["rank_total"] / rank_count, 1) if rank_count else None
    mention_rate = round(mention_count / sample_total * 100, 1) if sample_total else 0.0
    first_mention_rate = round(first_mention_count / sample_total * 100, 1) if sample_total else 0.0
    sentiment_sample = int(bucket["sentiment_sample"])
    positive_rate = round(bucket["sentiment_positive"] / sentiment_sample * 100, 1) if sentiment_sample else 0.0
    negative_rate = round(bucket["sentiment_negative"] / sentiment_sample * 100, 1) if sentiment_sample else 0.0
    return {
        "name": bucket["name"],
        "is_brand": bucket["is_brand"],
        "mention_count": mention_count,
        "mention_rate": mention_rate,
        "first_mention_count": first_mention_count,
        "first_mention_rate": first_mention_rate,
        "avg_rank": avg_rank,
        "rank_sample_count": rank_count,
        "positive_rate": positive_rate,
        "negative_rate": negative_rate,
        "sentiment_sample": sentiment_sample,
        "source_count": 0,
        "gap_summary": None,
    }


def _parse_platform_filters(platform: str | None, platforms: str | None = None) -> list[str]:
    raw = str(platforms or platform or "").strip()
    if not raw or raw.lower() == "all":
        return []
    parts = re.split(r"[,，\s]+", raw)
    return [item for item in parts if item and item.lower() != "all"]


def _dedupe_preserve_order(names: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for name in names:
        if name in seen:
            continue
        seen.add(name)
        result.append(name)
    return result


def _include_in_sentiment_leaderboard(row: dict[str, Any]) -> bool:
    """情绪榜需有情绪样本；竞品若正负面均为 0%（全中立）则不展示。"""
    if row["sentiment_sample"] <= 0:
        return False
    if row["is_brand"]:
        return True
    return row["positive_rate"] > 0 or row["negative_rate"] > 0


def build_competitor_compare_summary(
    db: Session,
    current: CurrentSession,
    *,
    tenant_id: int | None = None,
    platform: str | None = None,
    platforms: str | None = None,
    days: int = 30,
    prompt: str | None = None,
) -> dict[str, Any]:
    resolved_tenant_id = resolve_and_guard_analytics_tenant(db, current, tenant_id)

    asset = get_brand_asset(db, resolved_tenant_id)
    competitors = list_competitors(db, resolved_tenant_id)
    entities = _tracked_entities(asset, competitors)
    brand_display = (asset.brand_name if asset else None) or "本品牌"

    if current.identity.identity_type == "CUSTOMER":
        range_end = customer_display_cutoff()
        range_start = datetime.combine(
            range_end.date() - timedelta(days=max(1, min(days, 365)) - 1),
            time.min,
        )
    else:
        range_end = datetime.now()
        range_start = range_end - timedelta(days=max(1, min(days, 365)))
    platform_filters = _parse_platform_filters(platform, platforms)
    prompt_filter = str(prompt or "").strip()

    stmt = (
        select(GeoMonitorSubtask)
        .join(GeoMonitorTask, GeoMonitorTask.task_id == GeoMonitorSubtask.task_id)
        .options(
            load_only(
                GeoMonitorSubtask.platform,
                GeoMonitorSubtask.prompt,
                GeoMonitorSubtask.mention_position,
                GeoMonitorSubtask.competitor_rankings_json,
                GeoMonitorSubtask.all_rankings_json,
                GeoMonitorSubtask.sentiment,
                GeoMonitorSubtask.updated_at,
            )
        )
        .where(
            GeoMonitorTask.deleted.is_(False),
            GeoMonitorTask.tenant_id == resolved_tenant_id,
            GeoMonitorSubtask.updated_at >= range_start,
            GeoMonitorSubtask.updated_at <= range_end,
            GeoMonitorSubtask.status.in_(("completed", "partial_completed")),
        )
    )
    if platform_filters:
        stmt = stmt.where(GeoMonitorSubtask.platform.in_(platform_filters))
    if prompt_filter:
        stmt = stmt.where(GeoMonitorSubtask.prompt == prompt_filter)

    subtasks = list(db.scalars(stmt.limit(5000)))
    sample_total = len(subtasks)
    prompt_options = sorted({str(item.prompt or "").strip() for item in subtasks if str(item.prompt or "").strip()})

    global_buckets: dict[str, dict[str, Any]] = {}
    platform_buckets: dict[str, dict[str, dict[str, Any]]] = {}
    daily_samples: dict[str, int] = {}
    daily_mentions: dict[str, dict[str, int]] = {}
    daily_sentiment: dict[str, dict[str, int]] = {}

    def bucket_for(platform_code: str | None, entity_name: str, is_brand: bool) -> dict[str, Any]:
        if platform_code:
            platform_map = platform_buckets.setdefault(platform_code, {})
            if entity_name not in platform_map:
                platform_map[entity_name] = _init_bucket(entity_name, is_brand=is_brand)
            return platform_map[entity_name]
        if entity_name not in global_buckets:
            global_buckets[entity_name] = _init_bucket(entity_name, is_brand=is_brand)
        return global_buckets[entity_name]

    for item in subtasks:
        entries = normalize_structured_rankings(item.all_rankings_json or [])
        day_key = item.updated_at.date().isoformat() if item.updated_at else None
        if day_key:
            daily_samples[day_key] = daily_samples.get(day_key, 0) + 1
            sentiment_label = _normalize_sentiment_label(item.sentiment)
            if sentiment_label:
                day_sentiment = daily_sentiment.setdefault(day_key, {"positive": 0, "neutral": 0, "negative": 0})
                day_sentiment[sentiment_label] += 1

        sentiment_label = _normalize_sentiment_label(item.sentiment)

        for entity in entities:
            is_brand = entity["is_brand"]
            display_name = brand_display if is_brand else entity["name"]
            match_terms = entity.get("match_terms") or [entity["name"]]
            mentioned, rank = _entity_match_stats(
                entries,
                match_terms,
                mention_position=item.mention_position,
                is_brand=is_brand,
            )

            if not mentioned and rank is None:
                continue

            if is_brand:
                if rank is not None and rank <= 1:
                    bucket_for(None, display_name, is_brand)["first_mention_count"] += 1
                    bucket_for(item.platform, display_name, is_brand)["first_mention_count"] += 1
            elif rank is not None and rank <= 1:
                bucket_for(None, display_name, is_brand)["first_mention_count"] += 1
                bucket_for(item.platform, display_name, is_brand)["first_mention_count"] += 1

            if day_key:
                day_map = daily_mentions.setdefault(day_key, {})
                day_map[display_name] = day_map.get(display_name, 0) + 1

            global_bucket = bucket_for(None, display_name, is_brand)
            platform_bucket = bucket_for(item.platform, display_name, is_brand)
            for bucket in (global_bucket, platform_bucket):
                bucket["mention_count"] += 1
                if rank is not None:
                    bucket["rank_total"] += rank
                    bucket["rank_count"] += 1

            if sentiment_label and mentioned:
                global_bucket["sentiment_sample"] += 1
                if sentiment_label == "positive":
                    global_bucket["sentiment_positive"] += 1
                elif sentiment_label == "negative":
                    global_bucket["sentiment_negative"] += 1
                else:
                    global_bucket["sentiment_neutral"] += 1

    configured_names = _dedupe_preserve_order(
        [brand_display] + [competitor.name for competitor in competitors],
    )
    merged_global: dict[str, dict[str, Any]] = {}
    for bucket in global_buckets.values():
        display = bucket["name"]
        if display not in configured_names:
            continue
        target = merged_global.setdefault(
            display,
            _init_bucket(display, is_brand=display == brand_display),
        )
        target["mention_count"] += bucket["mention_count"]
        target["first_mention_count"] += bucket["first_mention_count"]
        target["rank_total"] += bucket["rank_total"]
        target["rank_count"] += bucket["rank_count"]
        target["sentiment_positive"] += bucket["sentiment_positive"]
        target["sentiment_neutral"] += bucket["sentiment_neutral"]
        target["sentiment_negative"] += bucket["sentiment_negative"]
        target["sentiment_sample"] += bucket["sentiment_sample"]

    for name in configured_names:
        if name not in merged_global:
            merged_global[name] = _init_bucket(name, is_brand=name == brand_display)

    rows = [
        _finalize_bucket(merged_global[name], sample_total)
        for name in configured_names
    ]
    rows.sort(key=lambda row: (-row["mention_rate"], row["avg_rank"] if row["avg_rank"] is not None else 999))

    platform_rows = []
    for item in sort_platform_items(
        [{"platform": code, "entity_map": entity_map} for code, entity_map in platform_buckets.items()],
        key="platform",
    ):
        platform_code = item["platform"]
        entity_map = item["entity_map"]
        platform_sample = sum(
            1 for item in subtasks if item.platform == platform_code
        )
        merged_platform: dict[str, dict[str, Any]] = {}
        for bucket in entity_map.values():
            display = bucket["name"]
            if display not in configured_names:
                continue
            target = merged_platform.setdefault(
                display,
                _init_bucket(display, is_brand=display == brand_display),
            )
            target["mention_count"] += bucket["mention_count"]
            target["first_mention_count"] += bucket["first_mention_count"]
            target["rank_total"] += bucket["rank_total"]
            target["rank_count"] += bucket["rank_count"]
        for name in configured_names:
            if name not in merged_platform:
                merged_platform[name] = _init_bucket(name, is_brand=name == brand_display)
        platform_rows.append({
            "platform": platform_code,
            "sample_count": platform_sample,
            "rows": [
                _finalize_bucket(merged_platform[name], platform_sample)
                for name in configured_names
            ],
        })

    sorted_days = sorted(daily_samples.keys())
    trend_labels = [
        datetime.fromisoformat(day).strftime("%m-%d")
        for day in sorted_days
    ]
    trend_entities = [merged_global[name] for name in configured_names]
    mention_trend_series = []
    for bucket in trend_entities:
        name = bucket["name"]
        values: list[float] = []
        for day in sorted_days:
            day_total = daily_samples.get(day, 0)
            if not day_total:
                values.append(0.0)
                continue
            day_count = daily_mentions.get(day, {}).get(name, 0)
            values.append(round(day_count / day_total * 100, 1))
        mention_trend_series.append({
            "name": name,
            "is_brand": bucket["is_brand"],
            "values": values,
        })

    sentiment_positive: list[float] = []
    sentiment_neutral: list[float] = []
    sentiment_negative: list[float] = []
    for day in sorted_days:
        day_total = daily_samples.get(day, 0)
        counts = daily_sentiment.get(day, {})
        if not day_total:
            sentiment_positive.append(0.0)
            sentiment_neutral.append(0.0)
            sentiment_negative.append(0.0)
            continue
        sentiment_positive.append(round(counts.get("positive", 0) / day_total * 100, 1))
        sentiment_neutral.append(round(counts.get("neutral", 0) / day_total * 100, 1))
        sentiment_negative.append(round(counts.get("negative", 0) / day_total * 100, 1))

    sentiment_rows = sorted(
        [
            {
                "name": row["name"],
                "is_brand": row["is_brand"],
                "positive_rate": row["positive_rate"],
                "negative_rate": row["negative_rate"],
                "sentiment_sample": row["sentiment_sample"],
            }
            for row in rows
            if _include_in_sentiment_leaderboard(row)
        ],
        key=lambda item: (-item["positive_rate"], -int(item["is_brand"])),
    )
    if not sentiment_rows and brand_display:
        brand_row = next((row for row in rows if row["is_brand"]), None)
        if brand_row:
            sentiment_rows = [{
                "name": brand_row["name"],
                "is_brand": True,
                "positive_rate": brand_row["positive_rate"],
                "negative_rate": brand_row["negative_rate"],
                "sentiment_sample": brand_row["sentiment_sample"],
            }]

    return {
        "brand_name": brand_display,
        "competitor_count": len(competitors),
        "sample_total": sample_total,
        "start_at": range_start.isoformat(),
        "end_at": range_end.isoformat(),
        "prompt_options": prompt_options,
        "trend_day_keys": sorted_days,
        "rows": rows,
        "platform_rows": platform_rows,
        "mention_trends": {
            "labels": trend_labels,
            "series": mention_trend_series,
        },
        "sentiment_trends": {
            "labels": trend_labels,
            "positive": sentiment_positive,
            "neutral": sentiment_neutral,
            "negative": sentiment_negative,
        },
        "sentiment_rows": sentiment_rows,
    }
