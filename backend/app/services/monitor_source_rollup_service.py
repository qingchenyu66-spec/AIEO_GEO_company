"""信源日级物化：监测完成后按业务日重建，读路径按日合并。"""

from __future__ import annotations

import logging
from datetime import date, datetime, time
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.read_cache import source_stats_config_fingerprint
from app.models.monitor import GeoMonitorDailyStat, GeoMonitorSourceDaily, GeoMonitorSubtask, GeoMonitorTask
from app.services.brand_service import (
    active_keyword_groups,
    brand_exposure_terms,
    get_brand_asset,
    tenant_purchased_platforms,
)
from app.services.monitor_sample_metrics import SUCCESS_STATUSES as TERMINAL_STATUSES
from app.services.schedule_context import lead_diagnosis_runs_for_tasks, schedule_runs_for_tasks

logger = logging.getLogger(__name__)


def _merge_url_maps(chunks: list[dict[str, dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for chunk in chunks:
        if not isinstance(chunk, dict):
            continue
        for key, row in chunk.items():
            if not isinstance(row, dict):
                continue
            dest = out.get(key)
            if dest is None:
                out[key] = {
                    "title": row.get("title"),
                    "url": row.get("url"),
                    "site": row.get("site"),
                    "count": int(row.get("count") or 0),
                    "platforms": list(row.get("platforms") or []),
                    "exposure_terms": list(row.get("exposure_terms") or []),
                    "questions": list(row.get("questions") or []),
                    "latest_time": row.get("latest_time"),
                }
                continue
            dest["count"] = int(dest.get("count") or 0) + int(row.get("count") or 0)
            if not dest.get("site") and row.get("site"):
                dest["site"] = row.get("site")
            for platform in row.get("platforms") or []:
                if platform and platform not in dest["platforms"]:
                    dest["platforms"].append(platform)
            for term in row.get("exposure_terms") or []:
                if term and term not in dest["exposure_terms"]:
                    dest["exposure_terms"].append(term)
            for question in row.get("questions") or []:
                if question and question not in dest["questions"]:
                    dest["questions"].append(question)
            candidate = row.get("latest_time")
            if candidate and (dest.get("latest_time") is None or candidate > dest["latest_time"]):
                dest["latest_time"] = candidate
    return out


def _tenant_source_config(db: Session, tenant_id: int) -> tuple[set[str], list[str], str]:
    asset = get_brand_asset(db, tenant_id)
    purchased = set(tenant_purchased_platforms(db, tenant_id, asset) if asset else [])
    exposure = brand_exposure_terms(asset, active_keyword_groups(db, tenant_id)) if asset else []
    config_fp = source_stats_config_fingerprint(exposure, purchased)
    return purchased, exposure, config_fp


def rebuild_source_daily_for_day(
    db: Session,
    *,
    tenant_id: int,
    stat_date: date,
    purchased_platforms: set[str],
    exposure_terms: list[str],
    config_fp: str,
) -> GeoMonitorSourceDaily:
    """按企业+监测日从子任务重建信源日物化（幂等 upsert）。"""
    from app.services.monitor_service import _aggregate_source_stats_pair_maps
    from app.services.monitor_stats_service import load_subtasks_for_business_date_range

    hist_rows, hist_tasks, hist_days = load_subtasks_for_business_date_range(
        db,
        tenant_id,
        start_date=stat_date,
        end_date=stat_date,
        only_with_refs=True,
    )
    source_items: list[GeoMonitorSubtask] = []
    source_day_by_id: dict[int, date] = {}
    source_tenant_map: dict[int, int] = {}
    task_tenant = {t.task_id: t.tenant_id for t in hist_tasks if t.task_id}
    for item in hist_rows:
        biz = hist_days.get(item.id)
        if biz is None or biz != stat_date:
            continue
        source_items.append(item)
        source_day_by_id[item.id] = biz
        tid = task_tenant.get(item.task_id) or tenant_id
        if tid:
            source_tenant_map[item.id] = int(tid)

    branded_map, all_map, daily_counts, daily_by_platform = _aggregate_source_stats_pair_maps(
        source_items,
        business_day_by_id=source_day_by_id,
        subtask_tenant_map=source_tenant_map,
        purchased_platforms_by_tenant={tenant_id: purchased_platforms},
        exposure_terms_by_tenant={tenant_id: exposure_terms},
    )
    day_key = stat_date.isoformat()
    branded_day_count = int(daily_counts.get(day_key) or 0)
    platform_day: dict[str, int] = {
        platform: int((bucket or {}).get(day_key) or 0)
        for platform, bucket in daily_by_platform.items()
        if int((bucket or {}).get(day_key) or 0) > 0
    }

    row = db.scalar(
        select(GeoMonitorSourceDaily).where(
            GeoMonitorSourceDaily.tenant_id == tenant_id,
            GeoMonitorSourceDaily.stat_date == stat_date,
        )
    )
    if row is None:
        row = GeoMonitorSourceDaily(
            tenant_id=tenant_id,
            stat_date=stat_date,
            branded_json={},
            all_json={},
            daily_by_platform_json={},
        )
        db.add(row)
    row.config_fp = config_fp
    row.branded_json = branded_map
    row.all_json = all_map
    row.daily_branded_count = branded_day_count
    row.daily_by_platform_json = platform_day
    db.flush()
    return row


def refresh_source_daily_for_task(db: Session, task_id: str) -> None:
    """同步完成后，按任务涉及监测日重建信源日物化。"""
    from app.services.monitor_stats_service import _detect_stat_date

    task = db.scalar(
        select(GeoMonitorTask).where(
            GeoMonitorTask.task_id == task_id,
            GeoMonitorTask.deleted.is_(False),
        )
    )
    if task is None or task.tenant_id is None:
        return
    if str(getattr(task, "purpose", "geo") or "geo") == "brand_word":
        return
    subtasks = list(
        db.scalars(
            select(GeoMonitorSubtask).where(
                GeoMonitorSubtask.task_id == task_id,
                GeoMonitorSubtask.status.in_(TERMINAL_STATUSES),
            )
        )
    )
    if not subtasks:
        return
    schedule_run = schedule_runs_for_tasks(db, [task_id]).get(task_id)
    lead_run = lead_diagnosis_runs_for_tasks(db, [task_id]).get(task_id)
    asset = get_brand_asset(db, task.tenant_id)
    days: set[date] = set()
    for item in subtasks:
        detect_day = _detect_stat_date(
            item,
            task,
            schedule_run=schedule_run,
            lead_run=lead_run,
            asset=asset,
        )
        if detect_day is not None:
            days.add(detect_day)
    if not days:
        return
    purchased, exposure, config_fp = _tenant_source_config(db, task.tenant_id)
    for day in sorted(days):
        rebuild_source_daily_for_day(
            db,
            tenant_id=task.tenant_id,
            stat_date=day,
            purchased_platforms=purchased,
            exposure_terms=exposure,
            config_fp=config_fp,
        )


def refresh_source_daily_after_subtask_backfill(
    db: Session,
    *,
    task: GeoMonitorTask,
    previous_stat_date: date | None,
    new_stat_date: date | None,
) -> None:
    """补录后重建旧/新监测日信源物化。"""
    if task.tenant_id is None:
        return
    if str(getattr(task, "purpose", "geo") or "geo") == "brand_word":
        return
    days: set[date] = set()
    if previous_stat_date:
        days.add(previous_stat_date)
    if new_stat_date:
        days.add(new_stat_date)
    if not days:
        return
    purchased, exposure, config_fp = _tenant_source_config(db, task.tenant_id)
    for day in sorted(days):
        rebuild_source_daily_for_day(
            db,
            tenant_id=task.tenant_id,
            stat_date=day,
            purchased_platforms=purchased,
            exposure_terms=exposure,
            config_fp=config_fp,
        )


def _candidate_source_days(db: Session, tenant_id: int, cutoff_day: date) -> list[date]:
    from_stat = list(
        db.scalars(
            select(GeoMonitorDailyStat.stat_date)
            .where(
                GeoMonitorDailyStat.tenant_id == tenant_id,
                GeoMonitorDailyStat.stat_date <= cutoff_day,
                GeoMonitorDailyStat.citation_count > 0,
            )
            .distinct()
        )
    )
    from_rollup = list(
        db.scalars(
            select(GeoMonitorSourceDaily.stat_date).where(
                GeoMonitorSourceDaily.tenant_id == tenant_id,
                GeoMonitorSourceDaily.stat_date <= cutoff_day,
            )
        )
    )
    return sorted(set(from_stat) | set(from_rollup))


def _bundle_from_day_rows(
    day_rows: list[GeoMonitorSourceDaily],
    *,
    cutoff_day: date,
) -> dict[str, Any]:
    from app.services.monitor_service import (
        _build_source_citation_trend,
        _build_source_citation_trends_by_platform,
        _finalize_source_stat_rows,
        customer_display_cutoff,
    )

    branded_maps: list[dict[str, dict[str, Any]]] = []
    all_maps: list[dict[str, dict[str, Any]]] = []
    source_daily_counts: dict[str, int] = {}
    source_daily_by_platform: dict[str, dict[str, int]] = {}
    for row in day_rows:
        if row.stat_date > cutoff_day:
            continue
        day_key = row.stat_date.isoformat()
        branded_maps.append(row.branded_json if isinstance(row.branded_json, dict) else {})
        all_maps.append(row.all_json if isinstance(row.all_json, dict) else {})
        count = int(row.daily_branded_count or 0)
        if count > 0:
            source_daily_counts[day_key] = count
        plat_map = row.daily_by_platform_json if isinstance(row.daily_by_platform_json, dict) else {}
        for platform, plat_count in plat_map.items():
            n = int(plat_count or 0)
            if n <= 0:
                continue
            bucket = source_daily_by_platform.setdefault(str(platform), {})
            bucket[day_key] = n

    citation_range_end = customer_display_cutoff()
    positive_days = [date.fromisoformat(k) for k, v in source_daily_counts.items() if int(v or 0) > 0]
    citation_range_start = datetime.combine(
        min(positive_days) if positive_days else citation_range_end.date(),
        time.min,
    )
    return {
        "source_stats": _finalize_source_stat_rows(list(_merge_url_maps(branded_maps).values())),
        "source_stats_all": _finalize_source_stat_rows(list(_merge_url_maps(all_maps).values())),
        "source_citation_trend": _build_source_citation_trend(
            source_daily_counts,
            range_start=citation_range_start,
            range_end=citation_range_end,
            only_with_data=True,
        ),
        "source_citation_trend_by_platform": _build_source_citation_trends_by_platform(
            source_daily_by_platform,
            range_start=citation_range_start,
            range_end=citation_range_end,
            only_with_data=True,
        ),
    }


def _backfill_source_daily_from_history(
    db: Session,
    tenant_id: int,
    *,
    cutoff_day: date,
    purchased_platforms: set[str],
    exposure_terms: list[str],
    config_fp: str,
) -> list[GeoMonitorSourceDaily]:
    """冷启动：一次扫全历史引用，按日写入物化后返回行。"""
    from app.services.monitor_service import _aggregate_source_stats_pair_maps
    from app.services.monitor_stats_service import load_subtasks_for_business_date_range

    hist_rows, hist_tasks, hist_days = load_subtasks_for_business_date_range(
        db,
        tenant_id,
        start_date=date(2020, 1, 1),
        end_date=datetime.now().date(),
        only_with_refs=True,
    )
    by_day: dict[date, list[GeoMonitorSubtask]] = {}
    day_by_id: dict[int, date] = {}
    tenant_map: dict[int, int] = {}
    task_tenant = {t.task_id: t.tenant_id for t in hist_tasks if t.task_id}
    for item in hist_rows:
        biz = hist_days.get(item.id)
        if biz is None or biz > cutoff_day:
            continue
        by_day.setdefault(biz, []).append(item)
        day_by_id[item.id] = biz
        tid = task_tenant.get(item.task_id) or tenant_id
        if tid:
            tenant_map[item.id] = int(tid)

    written: list[GeoMonitorSourceDaily] = []
    for day, items in sorted(by_day.items()):
        branded_map, all_map, daily_counts, daily_by_platform = _aggregate_source_stats_pair_maps(
            items,
            business_day_by_id={i.id: day_by_id[i.id] for i in items},
            subtask_tenant_map={i.id: tenant_map[i.id] for i in items if i.id in tenant_map},
            purchased_platforms_by_tenant={tenant_id: purchased_platforms},
            exposure_terms_by_tenant={tenant_id: exposure_terms},
        )
        day_key = day.isoformat()
        platform_day = {
            platform: int((bucket or {}).get(day_key) or 0)
            for platform, bucket in daily_by_platform.items()
            if int((bucket or {}).get(day_key) or 0) > 0
        }
        row = db.scalar(
            select(GeoMonitorSourceDaily).where(
                GeoMonitorSourceDaily.tenant_id == tenant_id,
                GeoMonitorSourceDaily.stat_date == day,
            )
        )
        if row is None:
            row = GeoMonitorSourceDaily(
                tenant_id=tenant_id,
                stat_date=day,
                branded_json={},
                all_json={},
                daily_by_platform_json={},
            )
            db.add(row)
        row.config_fp = config_fp
        row.branded_json = branded_map
        row.all_json = all_map
        row.daily_branded_count = int(daily_counts.get(day_key) or 0)
        row.daily_by_platform_json = platform_day
        written.append(row)
    db.flush()
    return written


def build_customer_source_stats_from_daily(
    db: Session,
    tenant_id: int,
    *,
    purchased_platforms: set[str],
    exposure_terms: list[str],
) -> dict[str, Any]:
    """读路径：确保截止日前各监测日物化可用，再合并。"""
    from app.services.monitor_service import customer_display_cutoff

    cutoff_day = customer_display_cutoff().date()
    config_fp = source_stats_config_fingerprint(exposure_terms, purchased_platforms)
    candidate_days = _candidate_source_days(db, tenant_id, cutoff_day)

    if not candidate_days:
        day_rows = _backfill_source_daily_from_history(
            db,
            tenant_id,
            cutoff_day=cutoff_day,
            purchased_platforms=purchased_platforms,
            exposure_terms=exposure_terms,
            config_fp=config_fp,
        )
        return _bundle_from_day_rows(day_rows, cutoff_day=cutoff_day)

    existing = {
        row.stat_date: row
        for row in db.scalars(
            select(GeoMonitorSourceDaily).where(
                GeoMonitorSourceDaily.tenant_id == tenant_id,
                GeoMonitorSourceDaily.stat_date <= cutoff_day,
            )
        )
    }
    day_rows: list[GeoMonitorSourceDaily] = []
    for day in candidate_days:
        row = existing.get(day)
        if row is None or str(row.config_fp or "") != config_fp:
            row = rebuild_source_daily_for_day(
                db,
                tenant_id=tenant_id,
                stat_date=day,
                purchased_platforms=purchased_platforms,
                exposure_terms=exposure_terms,
                config_fp=config_fp,
            )
        day_rows.append(row)
    return _bundle_from_day_rows(day_rows, cutoff_day=cutoff_day)
