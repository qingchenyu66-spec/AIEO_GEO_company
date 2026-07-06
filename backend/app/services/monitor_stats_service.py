"""监测日维度预聚合统计：减轻首页/工作台明细扫描。"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, joinedload

from app.models.brand import BrandAsset
from app.models.lead_diagnosis import LeadDiagnosisRun
from app.models.monitor import GeoMonitorDailyStat, GeoMonitorScheduleRun, GeoMonitorSubtask, GeoMonitorTask
from app.services.brand_service import get_brand_asset
from app.services.schedule_context import (
    lead_diagnosis_runs_for_tasks,
    resolve_task_schedule_context,
    schedule_runs_for_tasks,
)

TERMINAL_STATUSES = {"completed", "partial_completed"}
logger = logging.getLogger(__name__)


def _schedule_window_date(schedule_ctx: dict[str, Any] | None) -> date | None:
    window_key = str((schedule_ctx or {}).get("schedule_window_key") or "").strip()
    if len(window_key) >= 8 and window_key[:8].isdigit():
        try:
            return datetime.strptime(window_key[:8], "%Y%m%d").date()
        except ValueError:
            pass
    schedule_label = str((schedule_ctx or {}).get("schedule_label") or "").strip()
    if len(schedule_label) >= 10:
        try:
            return datetime.strptime(schedule_label[:10], "%Y-%m-%d").date()
        except ValueError:
            pass
    return None


def _detect_stat_date(
    subtask: GeoMonitorSubtask,
    task: GeoMonitorTask,
    *,
    schedule_run: GeoMonitorScheduleRun | None,
    lead_run: LeadDiagnosisRun | None,
    asset: BrandAsset | None,
) -> date | None:
    """与工作台一致：优先调度批次日期，避免补录改 updated_at 后统计错位。"""
    ctx = resolve_task_schedule_context(task, schedule_run, asset, lead_run)
    detect_date = _schedule_window_date(ctx)
    if detect_date is not None:
        return detect_date
    if task.created_at:
        return task.created_at.date()
    if subtask.updated_at:
        return subtask.updated_at.date()
    return None


def upsert_daily_stat_row(
    db: Session,
    *,
    tenant_id: int,
    stat_date: date,
    platform: str,
    completed_delta: int = 0,
    mentioned_delta: int = 0,
    rank_sum_delta: int = 0,
    rank_count_delta: int = 0,
    citation_delta: int = 0,
) -> None:
    row = db.scalar(
        select(GeoMonitorDailyStat).where(
            GeoMonitorDailyStat.tenant_id == tenant_id,
            GeoMonitorDailyStat.stat_date == stat_date,
            GeoMonitorDailyStat.platform == platform,
        )
    )
    if row is None:
        row = GeoMonitorDailyStat(
            tenant_id=tenant_id,
            stat_date=stat_date,
            platform=platform,
        )
        db.add(row)
    row.completed_count = max(0, (row.completed_count or 0) + completed_delta)
    row.mentioned_count = max(0, (row.mentioned_count or 0) + mentioned_delta)
    row.rank_sum = max(0, (row.rank_sum or 0) + rank_sum_delta)
    row.rank_count = max(0, (row.rank_count or 0) + rank_count_delta)
    row.citation_count = max(0, (row.citation_count or 0) + citation_delta)


def _rebuild_daily_stat_for_platform_day(
    db: Session,
    *,
    tenant_id: int,
    stat_date: date,
    platform: str,
) -> None:
    """按企业+检测日+平台，汇总全部已返回子任务重建日统计。"""
    db.execute(
        delete(GeoMonitorDailyStat).where(
            GeoMonitorDailyStat.tenant_id == tenant_id,
            GeoMonitorDailyStat.stat_date == stat_date,
            GeoMonitorDailyStat.platform == platform,
        )
    )
    subtasks = list(
        db.scalars(
            select(GeoMonitorSubtask)
            .join(GeoMonitorTask, GeoMonitorTask.task_id == GeoMonitorSubtask.task_id)
            .options(joinedload(GeoMonitorSubtask.task))
            .where(
                GeoMonitorTask.deleted.is_(False),
                GeoMonitorTask.tenant_id == tenant_id,
                GeoMonitorSubtask.platform == platform,
                GeoMonitorSubtask.status.in_(TERMINAL_STATUSES),
            )
        )
    )
    if not subtasks:
        return
    task_ids = list({item.task_id for item in subtasks if item.task_id})
    schedule_runs_map = schedule_runs_for_tasks(db, task_ids)
    lead_runs_map = lead_diagnosis_runs_for_tasks(db, task_ids)
    asset = get_brand_asset(db, tenant_id)

    metrics = {"completed": 0, "mentioned": 0, "rank_sum": 0, "rank_count": 0, "citation": 0}
    for item in subtasks:
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
        if detect_day != stat_date:
            continue
        metrics["completed"] += 1
        if item.mention_position is not None:
            metrics["mentioned"] += 1
            metrics["rank_sum"] += int(item.mention_position)
            metrics["rank_count"] += 1
        refs = item.reference_list_json or []
        metrics["citation"] += len(refs) if isinstance(refs, list) else 0
    if metrics["completed"] == 0:
        return
    db.add(
        GeoMonitorDailyStat(
            tenant_id=tenant_id,
            stat_date=stat_date,
            platform=platform,
            completed_count=metrics["completed"],
            mentioned_count=metrics["mentioned"],
            rank_sum=metrics["rank_sum"],
            rank_count=metrics["rank_count"],
            citation_count=metrics["citation"],
        )
    )


def refresh_stats_for_task(db: Session, task_id: str) -> None:
    """同步完成后，按任务子项刷新日统计（幂等重建该任务涉及检测日）。"""
    task = db.scalar(
        select(GeoMonitorTask).where(
            GeoMonitorTask.task_id == task_id,
            GeoMonitorTask.deleted.is_(False),
        )
    )
    if task is None or task.tenant_id is None:
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
    day_platform_keys: set[tuple[date, str]] = set()
    for item in subtasks:
        detect_day = _detect_stat_date(
            item,
            task,
            schedule_run=schedule_run,
            lead_run=lead_run,
            asset=asset,
        )
        if detect_day is None:
            continue
        day_platform_keys.add((detect_day, item.platform))
    for day, platform in day_platform_keys:
        _rebuild_daily_stat_for_platform_day(
            db,
            tenant_id=task.tenant_id,
            stat_date=day,
            platform=platform,
        )


def refresh_stats_after_subtask_backfill(
    db: Session,
    *,
    task: GeoMonitorTask,
    subtask: GeoMonitorSubtask,
    previous_stat_date: date | None,
) -> None:
    """补录/覆盖后重建旧检测日与新检测日的日统计。"""
    if task.tenant_id is None:
        return
    schedule_run = schedule_runs_for_tasks(db, [task.task_id]).get(task.task_id)
    lead_run = lead_diagnosis_runs_for_tasks(db, [task.task_id]).get(task.task_id)
    asset = get_brand_asset(db, task.tenant_id)
    keys: set[tuple[date, str]] = set()
    if previous_stat_date:
        keys.add((previous_stat_date, subtask.platform))
    new_day = _detect_stat_date(
        subtask,
        task,
        schedule_run=schedule_run,
        lead_run=lead_run,
        asset=asset,
    )
    if new_day:
        keys.add((new_day, subtask.platform))
    for day, platform in keys:
        _rebuild_daily_stat_for_platform_day(
            db,
            tenant_id=task.tenant_id,
            stat_date=day,
            platform=platform,
        )


def aggregate_daily_mention_trend(
    db: Session,
    *,
    tenant_ids: list[int] | None,
    days: int = 7,
    end_day: date | None = None,
) -> list[dict[str, int | str]]:
    end = end_day or date.today()
    start = end - timedelta(days=max(1, days) - 1)
    stmt = select(GeoMonitorDailyStat).where(
        GeoMonitorDailyStat.stat_date >= start,
        GeoMonitorDailyStat.stat_date <= end,
    )
    if tenant_ids is not None:
        if not tenant_ids:
            return []
        stmt = stmt.where(GeoMonitorDailyStat.tenant_id.in_(tenant_ids))
    rows = list(db.scalars(stmt))
    by_day: dict[str, int] = {}
    for row in rows:
        key = row.stat_date.isoformat()
        by_day[key] = by_day.get(key, 0) + int(row.mentioned_count or 0)
    points: list[dict[str, int | str]] = []
    cursor = start
    while cursor <= end:
        key = cursor.isoformat()
        points.append({
            "label": cursor.strftime("%m-%d"),
            "day_key": key,
            "value": by_day.get(key, 0),
        })
        cursor += timedelta(days=1)
    return points


def aggregate_platform_stats(
    db: Session,
    *,
    tenant_ids: list[int] | None,
    since: date | None = None,
) -> list[dict]:
    stmt = select(GeoMonitorDailyStat)
    if tenant_ids is not None:
        if not tenant_ids:
            return []
        stmt = stmt.where(GeoMonitorDailyStat.tenant_id.in_(tenant_ids))
    if since is not None:
        stmt = stmt.where(GeoMonitorDailyStat.stat_date >= since)
    rows = list(db.scalars(stmt))
    bucket: dict[str, dict[str, int]] = {}
    for row in rows:
        pb = bucket.setdefault(
            row.platform,
            {"total": 0, "completed": 0, "mentioned": 0, "rank_sum": 0, "rank_count": 0},
        )
        pb["total"] += int(row.completed_count or 0)
        pb["completed"] += int(row.completed_count or 0)
        pb["mentioned"] += int(row.mentioned_count or 0)
        pb["rank_sum"] += int(row.rank_sum or 0)
        pb["rank_count"] += int(row.rank_count or 0)
    stats: list[dict] = []
    for platform, pb in bucket.items():
        total = pb["total"] or 1
        stats.append({
            "platform": platform,
            "total": pb["total"],
            "completed": pb["completed"],
            "mention_rate": round(pb["mentioned"] / total * 100, 1),
            "avg_rank": round(pb["rank_sum"] / pb["rank_count"], 1) if pb["rank_count"] else None,
        })
    return stats


def has_daily_stats(db: Session, tenant_ids: list[int] | None) -> bool:
    stmt = select(func.count()).select_from(GeoMonitorDailyStat)
    if tenant_ids is not None:
        if not tenant_ids:
            return False
        stmt = stmt.where(GeoMonitorDailyStat.tenant_id.in_(tenant_ids))
    return int(db.scalar(stmt) or 0) > 0


def list_daily_stats_for_tenant(
    db: Session,
    tenant_id: int,
    *,
    since: date | None = None,
    until: date | None = None,
) -> list[GeoMonitorDailyStat]:
    stmt = select(GeoMonitorDailyStat).where(GeoMonitorDailyStat.tenant_id == tenant_id)
    if since is not None:
        stmt = stmt.where(GeoMonitorDailyStat.stat_date >= since)
    if until is not None:
        stmt = stmt.where(GeoMonitorDailyStat.stat_date <= until)
    return list(db.scalars(stmt.order_by(GeoMonitorDailyStat.stat_date.asc())))


def platform_bucket_from_stat_rows(rows: list[GeoMonitorDailyStat]) -> dict[str, dict[str, int | float]]:
    """转换为 workspace 平台高亮所需的 bucket 结构。"""
    bucket: dict[str, dict[str, int | float]] = {}
    for row in rows:
        pb = bucket.setdefault(
            row.platform,
            {"total": 0, "mentioned": 0, "rank_total": 0.0, "rank_count": 0},
        )
        pb["total"] += int(row.completed_count or 0)
        pb["mentioned"] += int(row.mentioned_count or 0)
        pb["rank_total"] += float(row.rank_sum or 0)
        pb["rank_count"] += int(row.rank_count or 0)
    return bucket


def workspace_metrics_from_stat_rows(rows: list[GeoMonitorDailyStat]) -> dict[str, int | float | None]:
    """从日统计行聚合工作台 KPI（不含 top3/负面，需子任务补充）。"""
    completed = sum(int(row.completed_count or 0) for row in rows)
    mentioned = sum(int(row.mentioned_count or 0) for row in rows)
    rank_sum = sum(int(row.rank_sum or 0) for row in rows)
    rank_count = sum(int(row.rank_count or 0) for row in rows)
    mention_rate = round(mentioned / max(1, completed) * 100, 1) if completed else 0.0
    avg_rank = round(rank_sum / rank_count, 1) if rank_count else None
    return {
        "ranking_sample_count": completed,
        "brand_mention_rate": mention_rate,
        "avg_brand_rank": avg_rank,
        "top3_rate": 0.0,
        "exposure_sample_count": 0,
        "negative_count": 0,
        "negative_rate": 0.0,
    }


def workspace_kpi_trends_from_stats(
    db: Session,
    tenant_id: int,
    range_start: datetime,
    range_end: datetime,
) -> list[dict[str, int | str | float | None]]:
    rows = list_daily_stats_for_tenant(
        db,
        tenant_id,
        since=range_start.date(),
        until=range_end.date(),
    )
    by_day: dict[str, list[GeoMonitorDailyStat]] = {}
    for row in rows:
        by_day.setdefault(row.stat_date.isoformat(), []).append(row)
    points: list[dict[str, int | str | float | None]] = []
    cursor = range_start.date()
    end = range_end.date()
    while cursor <= end:
        day_key = cursor.isoformat()
        metrics = workspace_metrics_from_stat_rows(by_day.get(day_key, []))
        points.append({
            "label": cursor.strftime("%m-%d"),
            "mention_rate": metrics["brand_mention_rate"],
            "avg_brand_rank": metrics["avg_brand_rank"],
            "top3_rate": metrics["top3_rate"],
            "negative_rate": metrics["negative_rate"],
        })
        cursor += timedelta(days=1)
    return points
