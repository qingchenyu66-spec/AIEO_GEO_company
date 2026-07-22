"""Aggregate competitor mention/rank stats from synced monitor subtasks."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, time
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, joinedload, load_only

from app.api.dependencies import CurrentSession
from app.models.brand import BrandAsset
from app.models.monitor import GeoMonitorScheduleRun, GeoMonitorSubtask, GeoMonitorTask
from app.services.brand_service import (
    active_keyword_groups,
    get_brand_asset,
    keyword_group_monitor_keywords,
    list_competitors,
)
from app.services.lead_diagnosis_analytics import names_match as _strict_entity_names_match
from app.services.monitor_service import customer_display_cutoff, customer_display_date_range
from app.services.monitor_stats_service import _detect_stat_date
from app.services.schedule_context import lead_diagnosis_runs_for_tasks, schedule_runs_for_tasks
from app.services.tenant_scope import resolve_and_guard_analytics_tenant
from app.core.platform_order import sort_platform_items
from app.services.ranking_parser import (
    normalize_structured_rankings,
    ranking_entry_explicit_rank,
    ranking_entry_name,
)


def _names_match(left: str | None, right: str | None) -> bool:
    """与售前诊断同一套严格实体匹配：禁止「保研*」两字前缀互撞导致全员同分。"""
    return _strict_entity_names_match(left, right)


def _schedule_task_day_map(
    db: Session,
    tenant_id: int,
    *,
    range_start_day: date,
    range_end_day: date,
) -> dict[str, date]:
    """业务检测日 → task_id：用 schedule_key 前缀，避免宽窗扫 updated_at。"""
    start_key = range_start_day.strftime("%Y%m%d")
    end_key_exclusive = (range_end_day + timedelta(days=1)).strftime("%Y%m%d")
    rows = db.execute(
        select(GeoMonitorScheduleRun.task_id, GeoMonitorScheduleRun.schedule_key).where(
            GeoMonitorScheduleRun.tenant_id == tenant_id,
            GeoMonitorScheduleRun.task_id.isnot(None),
            GeoMonitorScheduleRun.schedule_key >= start_key,
            GeoMonitorScheduleRun.schedule_key < end_key_exclusive,
        )
    ).all()
    out: dict[str, date] = {}
    for task_id, schedule_key in rows:
        tid = str(task_id or "").strip()
        key = str(schedule_key or "").strip()
        if not tid or len(key) < 8:
            continue
        try:
            day = datetime.strptime(key[:8], "%Y%m%d").date()
        except ValueError:
            continue
        if range_start_day <= day <= range_end_day:
            out[tid] = day
    return out


_SUBTASK_LIGHT_COLS = (
    GeoMonitorSubtask.task_id,
    GeoMonitorSubtask.platform,
    GeoMonitorSubtask.prompt,
    GeoMonitorSubtask.mention_position,
    GeoMonitorSubtask.all_rankings_json,
    GeoMonitorSubtask.sentiment,
    GeoMonitorSubtask.updated_at,
)
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


def _entity_match_stats_from_names(
    named_entries: list[tuple[str, float | None]],
    match_terms: list[str],
    *,
    mention_position: int | None = None,
    is_brand: bool = False,
) -> tuple[bool, float | None]:
    """named_entries: (entry_name, explicit_rank)；每条子任务只解析一次推荐列表。"""
    rank: float | None = None
    mentioned = False
    for term in match_terms:
        for entry_name, entry_rank in named_entries:
            if not _names_match(entry_name, term):
                continue
            mentioned = True
            if entry_rank is not None and (rank is None or entry_rank < rank):
                rank = float(entry_rank)
    if is_brand and rank is None and mention_position is not None:
        rank = float(mention_position)
        mentioned = True
    return mentioned, rank


def _entity_match_stats(
    entries: list[dict[str, Any]],
    match_terms: list[str],
    *,
    mention_position: int | None = None,
    is_brand: bool = False,
) -> tuple[bool, float | None]:
    named = [
        (ranking_entry_name(entry), ranking_entry_explicit_rank(entry))
        for entry in entries
    ]
    return _entity_match_stats_from_names(
        named,
        match_terms,
        mention_position=mention_position,
        is_brand=is_brand,
    )

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


def resolve_analytics_date_range(
    current: CurrentSession,
    *,
    days: int = 30,
    start_date: date | None = None,
    end_date: date | None = None,
) -> tuple[datetime, datetime]:
    if current.identity.identity_type == "CUSTOMER":
        start_at = datetime.combine(start_date, time.min) if start_date else None
        end_at = datetime.combine(end_date, time.max) if end_date else None
        if start_at is not None or end_at is not None:
            return customer_display_date_range(
                start_at=start_at,
                end_at=end_at,
                default_lookback_days=30,
            )
        range_end = customer_display_cutoff()
        range_start = datetime.combine(
            range_end.date() - timedelta(days=max(1, min(days, 365)) - 1),
            time.min,
        )
        return range_start, range_end
    if start_date is not None and end_date is not None:
        return datetime.combine(start_date, time.min), datetime.combine(end_date, time.max)
    range_end = datetime.now()
    range_start = range_end - timedelta(days=max(1, min(days, 365)))
    return range_start, range_end


def _configured_prompt_options(db: Session, tenant_id: int) -> list[str]:
    """竞品页问题筛选：与当前启用的监测词组配置同步，而非历史子任务残留。"""
    seen: set[str] = set()
    options: list[str] = []
    for group in active_keyword_groups(db, tenant_id):
        for prompt in keyword_group_monitor_keywords(group):
            text = str(prompt or "").strip()
            if text and text not in seen:
                seen.add(text)
                options.append(text)
    return options


def _inclusive_day_keys(range_start: datetime, range_end: datetime) -> list[str]:
    """Return every ISO day in [range_start.date(), range_end.date()] for continuous trends."""
    start = range_start.date()
    end = range_end.date()
    if end < start:
        return []
    days: list[str] = []
    cursor = start
    while cursor <= end:
        days.append(cursor.isoformat())
        cursor += timedelta(days=1)
    return days


def build_competitor_compare_summary(
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
    subtask_limit: int = 5000,
) -> dict[str, Any]:
    resolved_tenant_id = resolve_and_guard_analytics_tenant(db, current, tenant_id)

    range_start, range_end = resolve_analytics_date_range(
        current,
        days=days,
        start_date=start_date,
        end_date=end_date,
    )
    platform_filters = _parse_platform_filters(platform, platforms)
    prompt_filter = str(prompt or "").strip()

    payload = _aggregate_competitor_stats(
        db,
        resolved_tenant_id,
        range_start=range_start,
        range_end=range_end,
        platform_filters=platform_filters,
        prompt_filter=prompt_filter,
        subtask_limit=subtask_limit,
    )
    payload["prompt_options"] = _configured_prompt_options(db, resolved_tenant_id)
    return payload


def aggregate_competitor_period_stats(
    db: Session,
    tenant_id: int,
    *,
    start_date: date,
    end_date: date,
    subtask_limit: int = 5000,
) -> dict[str, Any]:
    """Period-bound competitor stats for report export (no auth session)."""
    range_start = datetime.combine(start_date, time.min)
    range_end = datetime.combine(end_date, time.max)
    return _aggregate_competitor_stats(
        db,
        tenant_id,
        range_start=range_start,
        range_end=range_end,
        platform_filters=[],
        prompt_filter="",
        subtask_limit=subtask_limit,
    )


def _aggregate_competitor_stats(
    db: Session,
    tenant_id: int,
    *,
    range_start: datetime,
    range_end: datetime,
    platform_filters: list[str],
    prompt_filter: str,
    subtask_limit: int,
) -> dict[str, Any]:
    asset = get_brand_asset(db, tenant_id)
    competitors = list_competitors(db, tenant_id)
    entities = _tracked_entities(asset, competitors)
    brand_display = (asset.brand_name if asset else None) or "本品牌"
    range_start_day = range_start.date()
    range_end_day = range_end.date()
    row_cap = max(1, min(subtask_limit, 5000))

    # 快路径：按 schedule_key 业务日取 task，再按 task_id 拉轻字段（与工作台热力同源）。
    # 无调度记录时回退宽窗 + _detect_stat_date，保证手工/补录任务不丢。
    task_day_map = _schedule_task_day_map(
        db,
        tenant_id,
        range_start_day=range_start_day,
        range_end_day=range_end_day,
    )
    subtasks: list[GeoMonitorSubtask] = []
    subtask_day_keys: dict[int, str] = {}

    if task_day_map:
        stmt = (
            select(GeoMonitorSubtask)
            .options(load_only(*_SUBTASK_LIGHT_COLS))
            .where(
                GeoMonitorSubtask.task_id.in_(list(task_day_map.keys())),
                GeoMonitorSubtask.status.in_(("completed", "partial_completed")),
            )
        )
        if platform_filters:
            stmt = stmt.where(GeoMonitorSubtask.platform.in_(platform_filters))
        if prompt_filter:
            stmt = stmt.where(GeoMonitorSubtask.prompt == prompt_filter)
        for item in db.scalars(stmt.limit(row_cap)):
            day = task_day_map.get(str(item.task_id or ""))
            if day is None:
                continue
            subtasks.append(item)
            subtask_day_keys[id(item)] = day.isoformat()
    else:
        stmt = (
            select(GeoMonitorSubtask)
            .join(GeoMonitorTask, GeoMonitorTask.task_id == GeoMonitorSubtask.task_id)
            .options(
                load_only(*_SUBTASK_LIGHT_COLS),
                joinedload(GeoMonitorSubtask.task),
            )
            .where(
                GeoMonitorTask.deleted.is_(False),
                GeoMonitorTask.tenant_id == tenant_id,
                GeoMonitorTask.purpose == "geo",
                or_(
                    and_(
                        GeoMonitorTask.created_at >= range_start,
                        GeoMonitorTask.created_at <= range_end,
                    ),
                    and_(
                        GeoMonitorSubtask.updated_at >= range_start,
                        GeoMonitorSubtask.updated_at <= range_end,
                    ),
                ),
                GeoMonitorSubtask.status.in_(("completed", "partial_completed")),
            )
        )
        if platform_filters:
            stmt = stmt.where(GeoMonitorSubtask.platform.in_(platform_filters))
        if prompt_filter:
            stmt = stmt.where(GeoMonitorSubtask.prompt == prompt_filter)

        fetched = list(db.scalars(stmt.limit(row_cap)).unique())
        task_ids = list({item.task_id for item in fetched if item.task_id})
        schedule_runs_map = schedule_runs_for_tasks(db, task_ids) if task_ids else {}
        lead_runs_map = lead_diagnosis_runs_for_tasks(db, task_ids) if task_ids else {}
        for item in fetched:
            task = item.task
            if task is None:
                continue
            detect_day = _detect_stat_date(
                item,
                task,
                schedule_run=schedule_runs_map.get(item.task_id),
                lead_run=lead_runs_map.get(item.task_id),
                asset=asset,
            )
            if detect_day is None or detect_day < range_start_day or detect_day > range_end_day:
                continue
            subtasks.append(item)
            subtask_day_keys[id(item)] = detect_day.isoformat()

    sample_total = len(subtasks)

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
        named_entries = [
            (ranking_entry_name(entry), ranking_entry_explicit_rank(entry))
            for entry in entries
        ]
        day_key = subtask_day_keys.get(id(item))
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
            mentioned, rank = _entity_match_stats_from_names(
                named_entries,
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

    sorted_days = _inclusive_day_keys(range_start, range_end)
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
