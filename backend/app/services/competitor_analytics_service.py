"""Aggregate competitor mention/rank stats from synced monitor subtasks."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, load_only

from app.api.dependencies import CurrentSession
from app.models.brand import BrandAsset
from app.models.monitor import GeoMonitorSubtask, GeoMonitorTask
from app.services.brand_service import get_brand_asset, list_competitors
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


def _tracked_entities(asset: BrandAsset | None, competitors: list[Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(name: str | None, *, is_brand: bool) -> None:
        text = str(name or "").strip()
        key = _normalize_name_key(text)
        if not text or key in seen:
            return
        seen.add(key)
        rows.append({"name": text, "is_brand": is_brand})

    if asset is not None:
        add(asset.brand_name, is_brand=True)
        add(asset.brand_short_name, is_brand=False)
        add(asset.company_full_name, is_brand=False)
    for item in competitors:
        add(getattr(item, "name", None) or item.get("name"), is_brand=False)
        for alias in getattr(item, "aliases_json", None) or item.get("aliases") or []:
            add(str(alias or ""), is_brand=False)
    return rows


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


def _resolve_tenant_id(current: CurrentSession, tenant_id: int | None) -> int | None:
    if current.identity.identity_type == "CUSTOMER":
        return current.identity.tenant_id
    return tenant_id


def _parse_platform_filters(platform: str | None, platforms: str | None = None) -> list[str]:
    raw = str(platforms or platform or "").strip()
    if not raw or raw.lower() == "all":
        return []
    parts = re.split(r"[,，\s]+", raw)
    return [item for item in parts if item and item.lower() != "all"]


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
    resolved_tenant_id = _resolve_tenant_id(current, tenant_id)
    if resolved_tenant_id is None:
        return {
            "brand_name": None,
            "competitor_count": 0,
            "sample_total": 0,
            "rows": [],
            "platform_rows": [],
            "mention_trends": {"labels": [], "series": []},
            "sentiment_trends": {"labels": [], "positive": [], "neutral": [], "negative": []},
            "sentiment_rows": [],
            "trend_day_keys": [],
        }

    asset = get_brand_asset(db, resolved_tenant_id)
    competitors = list_competitors(db, resolved_tenant_id)
    entities = _tracked_entities(asset, competitors)
    brand_display = (asset.brand_name if asset else None) or "本品牌"
    brand_keys = {row["name"] for row in entities if row["is_brand"]}
    if not brand_keys and asset and asset.brand_name:
        brand_keys = {asset.brand_name}

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

    display_names: dict[str, str] = {}
    canonical_by_key: dict[str, str] = {}
    for competitor in competitors:
        canonical_by_key[_normalize_name_key(competitor.name)] = competitor.name
        for alias in competitor.aliases_json or []:
            canonical_by_key[_normalize_name_key(str(alias))] = competitor.name
    if asset and asset.brand_name:
        canonical_by_key[_normalize_name_key(asset.brand_name)] = brand_display

    for entity in entities:
        key = _normalize_name_key(entity["name"])
        if entity["is_brand"]:
            display_names[key] = brand_display
        elif key in canonical_by_key:
            display_names[key] = canonical_by_key[key]
        elif key not in display_names:
            display_names[key] = entity["name"]

    def entity_display(entity: dict[str, Any]) -> str:
        if entity["is_brand"]:
            return brand_display
        key = _normalize_name_key(entity["name"])
        return display_names.get(key, entity["name"])

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
            name = entity["name"]
            is_brand = entity["is_brand"]
            rank = _find_entity_rank(entries, name)
            mentioned = _entity_mentioned_in_entries(entries, name)
            if is_brand and rank is None and item.mention_position is not None:
                rank = float(item.mention_position)
                mentioned = True

            if not mentioned and rank is None:
                continue

            if is_brand:
                if rank is not None and rank <= 1:
                    bucket_for(None, name, is_brand)["first_mention_count"] += 1
                    bucket_for(item.platform, name, is_brand)["first_mention_count"] += 1
            elif rank is not None and rank <= 1:
                bucket_for(None, name, is_brand)["first_mention_count"] += 1
                bucket_for(item.platform, name, is_brand)["first_mention_count"] += 1

            if day_key:
                display_key = entity_display(entity)
                day_map = daily_mentions.setdefault(day_key, {})
                day_map[display_key] = day_map.get(display_key, 0) + 1

            global_bucket = bucket_for(None, name, is_brand)
            platform_bucket = bucket_for(item.platform, name, is_brand)
            for bucket in (global_bucket, platform_bucket):
                bucket["mention_count"] += 1
                if rank is not None:
                    bucket["rank_total"] += rank
                    bucket["rank_count"] += 1

            if sentiment_label:
                global_bucket["sentiment_sample"] += 1
                if sentiment_label == "positive":
                    global_bucket["sentiment_positive"] += 1
                elif sentiment_label == "negative":
                    global_bucket["sentiment_negative"] += 1
                else:
                    global_bucket["sentiment_neutral"] += 1

    merged_global: dict[str, dict[str, Any]] = {}
    for bucket in global_buckets.values():
        key = _normalize_name_key(bucket["name"])
        display = display_names.get(key, bucket["name"])
        target = merged_global.setdefault(
            display,
            _init_bucket(display, is_brand=any(_names_match(display, b) for b in brand_keys)),
        )
        target["mention_count"] += bucket["mention_count"]
        target["first_mention_count"] += bucket["first_mention_count"]
        target["rank_total"] += bucket["rank_total"]
        target["rank_count"] += bucket["rank_count"]
        target["sentiment_positive"] += bucket["sentiment_positive"]
        target["sentiment_neutral"] += bucket["sentiment_neutral"]
        target["sentiment_negative"] += bucket["sentiment_negative"]
        target["sentiment_sample"] += bucket["sentiment_sample"]

    if brand_display not in merged_global:
        merged_global[brand_display] = _init_bucket(brand_display, is_brand=True)
    for competitor in competitors:
        if competitor.name not in merged_global:
            merged_global[competitor.name] = _init_bucket(competitor.name, is_brand=False)

    rows = [
        _finalize_bucket(bucket, sample_total)
        for bucket in sorted(
            merged_global.values(),
            key=lambda row: (-int(row["is_brand"]), -row["mention_count"], row["name"]),
        )
    ]
    rows.sort(key=lambda row: (-row["mention_rate"], row["avg_rank"] if row["avg_rank"] is not None else 999))

    platform_rows = []
    for platform_code, entity_map in sorted(platform_buckets.items()):
        platform_sample = sum(
            1 for item in subtasks if item.platform == platform_code
        )
        merged_platform: dict[str, dict[str, Any]] = {}
        for bucket in entity_map.values():
            key = _normalize_name_key(bucket["name"])
            display = display_names.get(key, bucket["name"])
            target = merged_platform.setdefault(
                display,
                _init_bucket(display, is_brand=any(_names_match(display, b) for b in brand_keys)),
            )
            target["mention_count"] += bucket["mention_count"]
            target["first_mention_count"] += bucket["first_mention_count"]
            target["rank_total"] += bucket["rank_total"]
            target["rank_count"] += bucket["rank_count"]
        platform_rows.append({
            "platform": platform_code,
            "sample_count": platform_sample,
            "rows": [
                _finalize_bucket(bucket, platform_sample)
                for bucket in sorted(
                    merged_platform.values(),
                    key=lambda row: (-int(row["is_brand"]), -row["mention_count"], row["name"]),
                )
            ],
        })

    sorted_days = sorted(daily_samples.keys())
    trend_labels = [
        datetime.fromisoformat(day).strftime("%m-%d")
        for day in sorted_days
    ]
    trend_entities = sorted(
        merged_global.values(),
        key=lambda row: (-int(row["is_brand"]), -row["mention_count"], row["name"]),
    )[:4]
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
            if row["is_brand"] or row["sentiment_sample"] > 0
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
