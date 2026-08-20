"""监测日维度预聚合统计：减轻首页/工作台明细扫描。"""

from __future__ import annotations

import logging
import time as time_mod
from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.exc import IntegrityError, OperationalError, PendingRollbackError
from sqlalchemy.orm import Session, joinedload

from app.models.brand import BrandAsset
from app.models.lead_diagnosis import LeadDiagnosisRun
from app.models.monitor import (
    GeoMonitorCompetitorDailyStat,
    GeoMonitorDailyStat,
    GeoMonitorScheduleRun,
    GeoMonitorSubtask,
    GeoMonitorTask,
)
from app.services.brand_service import get_brand_asset
from app.services.schedule_context import (
    lead_diagnosis_runs_for_tasks,
    resolve_task_schedule_context,
    schedule_runs_for_tasks,
)

from app.services.monitor_sample_metrics import SUCCESS_STATUSES as TERMINAL_STATUSES
logger = logging.getLogger(__name__)

# 2026-08-10 - 周末 sync 并发写 daily_stat 死锁致 PendingRollback - 先算后写 + 按 key commit 重试
_DAILY_STAT_WRITE_RETRIES = 3


def _is_transient_daily_stat_conflict(exc: BaseException) -> bool:
    """MySQL 死锁/锁等待/唯一键竞态（可安全重试重建）。"""
    cur: BaseException | None = exc
    seen: set[int] = set()
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        args = getattr(cur, "args", ()) or ()
        code = args[0] if args else None
        if code in (1213, 1205, 1062):
            return True
        msg = str(cur).lower()
        if (
            "deadlock" in msg
            or "lock wait timeout" in msg
            or "duplicate entry" in msg
            or "unique constraint" in msg
        ):
            return True
        nxt = cur.__cause__
        if nxt is None:
            orig = getattr(cur, "orig", None)
            nxt = orig if isinstance(orig, BaseException) else None
        cur = nxt
    return False


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


def load_subtasks_for_business_date_range(
    db: Session,
    tenant_id: int,
    *,
    start_date: date,
    end_date: date,
    asset: BrandAsset | None = None,
    statuses: set[str] | None = None,
    limit: int | None = None,
    only_with_refs: bool = False,
) -> tuple[list[GeoMonitorSubtask], list[GeoMonitorTask], dict[int, date]]:
    """按业务检测日（非裸 updated_at）拉取区间内子任务，供报告/分析复用。

    返回 (subtasks, tasks, {subtask.id: business_date}).
    only_with_refs：信源聚合用，跳过无 reference_list 的行，减冷路径 IO。
    """
    start_dt = datetime.combine(start_date, time.min)
    end_dt = datetime.combine(end_date, time.max)

    status_filter = statuses or TERMINAL_STATUSES
    stmt = (
        select(GeoMonitorSubtask)
        .join(GeoMonitorTask, GeoMonitorTask.task_id == GeoMonitorSubtask.task_id)
        .options(joinedload(GeoMonitorSubtask.task))
        .where(
            GeoMonitorTask.deleted.is_(False),
            GeoMonitorTask.tenant_id == tenant_id,
            GeoMonitorTask.purpose == "geo",
            or_(
                and_(GeoMonitorTask.created_at >= start_dt, GeoMonitorTask.created_at <= end_dt),
                and_(GeoMonitorSubtask.updated_at >= start_dt, GeoMonitorSubtask.updated_at <= end_dt),
            ),
            GeoMonitorSubtask.status.in_(tuple(status_filter)),
        )
    )
    if limit is not None:
        stmt = stmt.limit(max(1, limit))

    fetched = list(db.scalars(stmt).unique())
    if only_with_refs:
        fetched = [item for item in fetched if item.reference_list_json]
    if not fetched:
        return [], [], {}

    resolved_asset = asset if asset is not None else get_brand_asset(db, tenant_id)
    task_ids = list({item.task_id for item in fetched if item.task_id})
    schedule_runs_map = schedule_runs_for_tasks(db, task_ids)
    lead_runs_map = lead_diagnosis_runs_for_tasks(db, task_ids)

    matched: list[GeoMonitorSubtask] = []
    task_by_id: dict[str, GeoMonitorTask] = {}
    day_by_id: dict[int, date] = {}
    for item in fetched:
        task = item.task
        if task is None:
            continue
        detect_day = _detect_stat_date(
            item,
            task,
            schedule_run=schedule_runs_map.get(item.task_id),
            lead_run=lead_runs_map.get(item.task_id),
            asset=resolved_asset,
        )
        if detect_day is None or detect_day < start_date or detect_day > end_date:
            continue
        matched.append(item)
        task_by_id[task.task_id] = task
        day_by_id[item.id] = detect_day
    return matched, list(task_by_id.values()), day_by_id


def upsert_daily_stat_row(
    db: Session,
    *,
    tenant_id: int,
    stat_date: date,
    platform: str,
    completed_delta: int = 0,
    mentioned_delta: int = 0,
    top3_delta: int = 0,
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
    row.top3_count = max(0, (row.top3_count or 0) + top3_delta)
    row.rank_sum = max(0, (row.rank_sum or 0) + rank_sum_delta)
    row.rank_count = max(0, (row.rank_count or 0) + rank_count_delta)
    row.citation_count = max(0, (row.citation_count or 0) + citation_delta)


def _write_daily_stat_row(
    db: Session,
    *,
    tenant_id: int,
    stat_date: date,
    platform: str,
    metrics: dict[str, int],
) -> None:
    """短临界区：DELETE 后按汇总结果写回（completed=0 则只删）。SAVEPOINT 内可重试。"""
    db.execute(
        delete(GeoMonitorDailyStat).where(
            GeoMonitorDailyStat.tenant_id == tenant_id,
            GeoMonitorDailyStat.stat_date == stat_date,
            GeoMonitorDailyStat.platform == platform,
        )
    )
    # ponytail: 同会话多次重建同一 key 时，先 flush 掉 DELETE，否则未落库的旧 INSERT 会撞唯一键
    db.flush()
    if int(metrics.get("completed") or 0) <= 0:
        return
    db.add(
        GeoMonitorDailyStat(
            tenant_id=tenant_id,
            stat_date=stat_date,
            platform=platform,
            completed_count=metrics["completed"],
            mentioned_count=metrics["mentioned"],
            top3_count=metrics["top3"],
            rank_sum=metrics["rank_sum"],
            rank_count=metrics["rank_count"],
            citation_count=metrics["citation"],
        )
    )
    db.flush()


def _write_competitor_daily_rows(
    db: Session,
    *,
    tenant_id: int,
    stat_date: date,
    platform: str,
    completed: int,
    competitor_metrics: dict[int, dict[str, Any]],
) -> None:
    """同平台日：删后写竞品日表；completed 与本品牌日表同分母。

    2026-08-17 - B3+ 竞品日物化
    """
    from app.services.entity_daily_kpi import KPI_RULE_VERSION

    db.execute(
        delete(GeoMonitorCompetitorDailyStat).where(
            GeoMonitorCompetitorDailyStat.tenant_id == tenant_id,
            GeoMonitorCompetitorDailyStat.stat_date == stat_date,
            GeoMonitorCompetitorDailyStat.platform == platform,
        )
    )
    db.flush()
    if completed <= 0:
        return
    for competitor_id, payload in competitor_metrics.items():
        db.add(
            GeoMonitorCompetitorDailyStat(
                tenant_id=tenant_id,
                competitor_id=int(competitor_id),
                competitor_name=str(payload.get("name") or "")[:100],
                stat_date=stat_date,
                platform=platform,
                completed_count=completed,
                mentioned_count=int(payload.get("mentioned") or 0),
                top3_count=int(payload.get("top3") or 0),
                rank_sum=int(payload.get("rank_sum") or 0),
                rank_count=int(payload.get("rank_count") or 0),
                rule_version=KPI_RULE_VERSION,
            )
        )
    db.flush()


def _rebuild_daily_stat_for_platform_day(
    db: Session,
    *,
    tenant_id: int,
    stat_date: date,
    platform: str,
) -> None:
    """按企业+检测日+平台，汇总全部已返回子任务重建日统计（本品牌+竞品）。

    2026-08-17 - B3+：A2 仅 ranking 进对比分母；竞品同行写入
    """
    # 预筛 created_at/updated_at 邻近窗口，避免整表终态子任务进内存再滤业务日
    pad_start = datetime.combine(stat_date - timedelta(days=3), time.min)
    pad_end = datetime.combine(stat_date + timedelta(days=14), time.max)
    subtasks = list(
        db.scalars(
            select(GeoMonitorSubtask)
            .join(GeoMonitorTask, GeoMonitorTask.task_id == GeoMonitorSubtask.task_id)
            .options(joinedload(GeoMonitorSubtask.task))
            .where(
                GeoMonitorTask.deleted.is_(False),
                GeoMonitorTask.tenant_id == tenant_id,
                GeoMonitorTask.purpose == "geo",
                GeoMonitorSubtask.platform == platform,
                GeoMonitorSubtask.status.in_(TERMINAL_STATUSES),
                or_(
                    and_(GeoMonitorTask.created_at >= pad_start, GeoMonitorTask.created_at <= pad_end),
                    and_(GeoMonitorSubtask.updated_at >= pad_start, GeoMonitorSubtask.updated_at <= pad_end),
                ),
            )
        )
    )
    from app.services.entity_daily_kpi import (
        apply_rank_to_metrics,
        empty_kpi_metrics,
        is_kpi_ranking_prompt,
        resolve_entity_rank_for_kpi,
    )

    metrics = empty_kpi_metrics()
    competitor_metrics: dict[int, dict[str, Any]] = {}
    if subtasks:
        task_ids = list({item.task_id for item in subtasks if item.task_id})
        schedule_runs_map = schedule_runs_for_tasks(db, task_ids)
        lead_runs_map = lead_diagnosis_runs_for_tasks(db, task_ids)
        asset = get_brand_asset(db, tenant_id)

        from app.services.brand_service import (
            active_keyword_groups,
            brand_exposure_terms,
            list_competitors,
        )
        from app.services.competitor_analytics_service import _expand_entity_match_terms
        from app.services.monitor_service import _is_valid_citation_source, _ranking_match_terms

        try:
            groups = active_keyword_groups(db, tenant_id) if asset is not None else []
        except Exception:
            # ponytail: 单测/残缺库无词组表时退回资产别名，勿拖垮日统计重建
            groups = []
        tenant_terms = _ranking_match_terms(asset, groups) if asset is not None else []
        if asset is not None:
            for term in brand_exposure_terms(asset, groups):
                text = str(term or "").strip()
                if text and text not in tenant_terms:
                    tenant_terms.append(text)

        competitors = []
        try:
            competitors = list_competitors(db, tenant_id)
        except Exception:
            # ponytail: 单测无竞品表时跳过竞品日表写入
            competitors = []
        for comp in competitors:
            if not comp.status:
                continue
            name = str(comp.name or "").strip()
            if not name:
                continue
            competitor_metrics[int(comp.id)] = {
                "name": name,
                "terms": _expand_entity_match_terms(name, list(comp.aliases_json or [])),
                "mentioned": 0,
                "top3": 0,
                "rank_sum": 0,
                "rank_count": 0,
            }

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
            refs = item.reference_list_json or []
            if isinstance(refs, list):
                metrics["citation"] += sum(
                    1 for src in refs if isinstance(src, dict) and _is_valid_citation_source(src)
                )
            # 2026-08-17 - B3+ A2：非 ranking 不进对比 KPI 分母/分子（引文仍累计）
            if not is_kpi_ranking_prompt(item.prompt):
                continue
            metrics["completed"] += 1
            terms = list(tenant_terms)
            kw = str(task.monitor_keywords or "").strip()
            if kw and kw not in terms:
                terms.append(kw)
            brand_rank = resolve_entity_rank_for_kpi(
                item,
                terms,
                asset,
                is_brand=True,
                monitor_keywords=task.monitor_keywords,
            )
            apply_rank_to_metrics(metrics, brand_rank)
            for payload in competitor_metrics.values():
                comp_rank = resolve_entity_rank_for_kpi(
                    item,
                    list(payload["terms"]),
                    asset,
                    is_brand=False,
                )
                apply_rank_to_metrics(payload, comp_rank)

    # 先读后写缩短持锁；每 key 独立 commit，死锁/唯一键竞态时 rollback 后重试写段
    # ponytail: 调用方本就在 sync/补录 commit 之后刷日统计，单 key commit 不扩大事务边界
    last_exc: BaseException | None = None
    for attempt in range(_DAILY_STAT_WRITE_RETRIES):
        try:
            _write_daily_stat_row(
                db,
                tenant_id=tenant_id,
                stat_date=stat_date,
                platform=platform,
                metrics=metrics,
            )
            _write_competitor_daily_rows(
                db,
                tenant_id=tenant_id,
                stat_date=stat_date,
                platform=platform,
                completed=int(metrics.get("completed") or 0),
                competitor_metrics=competitor_metrics,
            )
            db.commit()
            return
        except (OperationalError, IntegrityError, PendingRollbackError) as exc:
            last_exc = exc
            try:
                db.rollback()
            except Exception:
                pass
            if not _is_transient_daily_stat_conflict(exc) or attempt + 1 >= _DAILY_STAT_WRITE_RETRIES:
                raise
            logger.warning(
                "daily_stat write conflict retry tenant=%s day=%s platform=%s attempt=%s err=%s",
                tenant_id,
                stat_date,
                platform,
                attempt + 1,
                exc,
            )
            time_mod.sleep(0.05 * (2**attempt))
    if last_exc is not None:
        raise last_exc


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
    # 品牌词不进 GEO 日预聚合
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
    try:
        from app.services.monitor_source_rollup_service import refresh_source_daily_for_task

        refresh_source_daily_for_task(db, task_id)
    except Exception as exc:
        logger.warning("refresh_source_daily_for_task failed task_id=%s error=%s", task_id, exc)


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
    if str(getattr(task, "purpose", "geo") or "geo") == "brand_word":
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
    # 2026-08-12 - 重算/补录后矩阵仍读 Redis 旧格（如 5）- 清 dashboard 含 ranking-matrix
    try:
        from app.services.monitor_service import invalidate_monitor_summary_cache

        invalidate_monitor_summary_cache(int(task.tenant_id), bust_overview=True)
    except Exception as exc:
        logger.warning(
            "invalidate_monitor_summary_cache after backfill failed tenant_id=%s error=%s",
            task.tenant_id,
            exc,
        )
    # 2026-08-17 - 补录 HTTP 30s 超时：艾迪亚信源日表同步重刷可达 8–12s+，改异步（日表仍同步）
    try:
        from app.services.monitor_source_rollup_service import enqueue_source_daily_after_backfill

        enqueue_source_daily_after_backfill(
            tenant_id=int(task.tenant_id),
            task_id=str(task.task_id),
            previous_stat_date=previous_stat_date.isoformat() if previous_stat_date else None,
            new_stat_date=new_day.isoformat() if new_day else None,
        )
    except Exception as exc:
        logger.warning(
            "enqueue_source_daily_after_backfill failed task_id=%s error=%s",
            task.task_id,
            exc,
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
    until: date | None = None,
) -> list[dict]:
    stmt = select(GeoMonitorDailyStat)
    if tenant_ids is not None:
        if not tenant_ids:
            return []
        stmt = stmt.where(GeoMonitorDailyStat.tenant_id.in_(tenant_ids))
    if since is not None:
        stmt = stmt.where(GeoMonitorDailyStat.stat_date >= since)
    # 2026-08-14 - 信源页平台表现与工作台同窗：支持截止日，勿默认含今日全历史近30天
    if until is not None:
        stmt = stmt.where(GeoMonitorDailyStat.stat_date <= until)
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


def list_competitor_daily_stats_for_tenant(
    db: Session,
    tenant_id: int,
    *,
    since: date | None = None,
    until: date | None = None,
) -> list[GeoMonitorCompetitorDailyStat]:
    """2026-08-17 - B3+ 竞品日表读取."""
    stmt = select(GeoMonitorCompetitorDailyStat).where(
        GeoMonitorCompetitorDailyStat.tenant_id == tenant_id
    )
    if since is not None:
        stmt = stmt.where(GeoMonitorCompetitorDailyStat.stat_date >= since)
    if until is not None:
        stmt = stmt.where(GeoMonitorCompetitorDailyStat.stat_date <= until)
    return list(db.scalars(stmt.order_by(GeoMonitorCompetitorDailyStat.stat_date.asc())))


def has_competitor_daily_stats(db: Session, tenant_ids: list[int] | None) -> bool:
    stmt = select(func.count()).select_from(GeoMonitorCompetitorDailyStat)
    if tenant_ids is not None:
        if not tenant_ids:
            return False
        stmt = stmt.where(GeoMonitorCompetitorDailyStat.tenant_id.in_(tenant_ids))
    return int(db.scalar(stmt) or 0) > 0


def competitor_period_rows_from_daily_stats(
    db: Session,
    tenant_id: int,
    *,
    range_start: date | datetime,
    range_end: date | datetime,
    platforms: list[str] | set[str] | frozenset[str] | None = None,
) -> list[dict[str, Any]] | None:
    """区间竞品 KPI（与本品牌日表同分母加权）。无竞品日表时返回 None。"""
    since = range_start.date() if isinstance(range_start, datetime) else range_start
    until = range_end.date() if isinstance(range_end, datetime) else range_end
    rows = list_competitor_daily_stats_for_tenant(db, tenant_id, since=since, until=until)
    if platforms:
        allow = {str(code).strip() for code in platforms if str(code).strip()}
        if allow:
            rows = [row for row in rows if str(row.platform or "").strip() in allow]
    if not rows:
        return None
    bucket: dict[int, dict[str, Any]] = {}
    for row in rows:
        cid = int(row.competitor_id)
        item = bucket.setdefault(
            cid,
            {
                "competitor_id": cid,
                "name": str(row.competitor_name or ""),
                "completed": 0,
                "mentioned": 0,
                "rank_sum": 0,
                "rank_count": 0,
            },
        )
        item["name"] = str(row.competitor_name or item["name"])
        item["completed"] += int(row.completed_count or 0)
        item["mentioned"] += int(row.mentioned_count or 0)
        item["rank_sum"] += int(row.rank_sum or 0)
        item["rank_count"] += int(row.rank_count or 0)
    out: list[dict[str, Any]] = []
    for item in bucket.values():
        completed = int(item["completed"] or 0)
        mentioned = int(item["mentioned"] or 0)
        rank_count = int(item["rank_count"] or 0)
        out.append(
            {
                "competitor_id": item["competitor_id"],
                "name": item["name"],
                "is_brand": False,
                "mention_count": mentioned,
                "mention_rate": round(mentioned / completed * 100, 1) if completed else 0.0,
                "avg_rank": round(item["rank_sum"] / rank_count, 1) if rank_count else None,
                "sample_count": completed,
                "kpi_basis": "daily_stat",
            }
        )
    return out


def competitor_kpi_trends_from_stats(
    db: Session,
    tenant_id: int,
    range_start: datetime,
    range_end: datetime,
    *,
    platforms: list[str] | set[str] | frozenset[str] | None = None,
) -> dict[str, list[float]]:
    """竞品名 → 与工作台同日序列的提及率。"""
    since = range_start.date()
    until = range_end.date()
    rows = list_competitor_daily_stats_for_tenant(db, tenant_id, since=since, until=until)
    if platforms:
        allow = {str(code).strip() for code in platforms if str(code).strip()}
        if allow:
            rows = [row for row in rows if str(row.platform or "").strip() in allow]
    # day -> name -> {m, c}
    by_day: dict[str, dict[str, dict[str, int]]] = {}
    names: set[str] = set()
    for row in rows:
        day = row.stat_date.isoformat()
        name = str(row.competitor_name or "").strip()
        if not name:
            continue
        names.add(name)
        cell = by_day.setdefault(day, {}).setdefault(name, {"m": 0, "c": 0})
        cell["m"] += int(row.mentioned_count or 0)
        cell["c"] += int(row.completed_count or 0)
    sorted_days: list[str] = []
    cursor = since
    while cursor <= until:
        sorted_days.append(cursor.isoformat())
        cursor += timedelta(days=1)
    series: dict[str, list[float]] = {name: [] for name in names}
    for day in sorted_days:
        day_map = by_day.get(day) or {}
        for name in names:
            cell = day_map.get(name) or {"m": 0, "c": 0}
            c = int(cell["c"] or 0)
            series[name].append(round(cell["m"] / c * 100, 1) if c else 0.0)
    return series


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
    """从日统计行聚合工作台 KPI。

    Top3 口径与 monitor_sample_metrics.compute_brand_rank_rates 一致：
    top3_count / completed_count（成功样本分母）。负面仍需子任务补充。
    """
    completed = sum(int(row.completed_count or 0) for row in rows)
    mentioned = sum(int(row.mentioned_count or 0) for row in rows)
    top3 = sum(int(getattr(row, "top3_count", 0) or 0) for row in rows)
    rank_sum = sum(int(row.rank_sum or 0) for row in rows)
    rank_count = sum(int(row.rank_count or 0) for row in rows)
    mention_rate = round(mentioned / max(1, completed) * 100, 1) if completed else 0.0
    top3_rate = round(top3 / max(1, completed) * 100, 1) if completed else 0.0
    avg_rank = round(rank_sum / rank_count, 1) if rank_count else None
    return {
        "ranking_sample_count": completed,
        # 2026-08-13 - 竞品/工作台对齐展示 N/M，需透出提及分子
        "mentioned_count": mentioned,
        "brand_mention_rate": mention_rate,
        "avg_brand_rank": avg_rank,
        "top3_rate": top3_rate,
        "top3_count": top3,
        "exposure_sample_count": 0,
        "negative_count": 0,
        "negative_rate": 0.0,
    }


def brand_period_metrics_from_daily_stats(
    db: Session,
    tenant_id: int,
    *,
    range_start: date | datetime,
    range_end: date | datetime,
    platforms: list[str] | set[str] | frozenset[str] | None = None,
) -> dict[str, int | float | None] | None:
    """区间本品牌 KPI：与工作台「本期结论」同一日表样本加权。

    2026-08-13 - 竞品页本品牌提及率曾走实时子任务+mention_position，与工作台日表漂移
    """
    if not has_daily_stats(db, [tenant_id]):
        return None
    since = range_start.date() if isinstance(range_start, datetime) else range_start
    until = range_end.date() if isinstance(range_end, datetime) else range_end
    rows = filter_daily_stat_rows_by_platforms(
        list_daily_stats_for_tenant(db, tenant_id, since=since, until=until),
        platforms,
    )
    metrics = workspace_metrics_from_stat_rows(rows)
    if int(metrics.get("ranking_sample_count") or 0) <= 0:
        return None
    return metrics


def filter_daily_stat_rows_by_platforms(
    rows: list[GeoMonitorDailyStat],
    platforms: list[str] | set[str] | frozenset[str] | None,
) -> list[GeoMonitorDailyStat]:
    """按平台白名单过滤日统计行；platforms 空/None 表示不过滤。"""
    if not platforms:
        return list(rows)
    allow = {str(code).strip() for code in platforms if str(code).strip()}
    if not allow:
        return list(rows)
    return [row for row in rows if str(row.platform or "").strip() in allow]


def period_bucket_from_stat_rows(rows: list[GeoMonitorDailyStat]) -> dict[str, int | float | None]:
    """周期报告趋势桶：与 _aggregate_bucket 字段对齐；无样本时率类为 None。"""
    metrics = workspace_metrics_from_stat_rows(rows)
    completed = int(metrics["ranking_sample_count"] or 0)
    if completed <= 0:
        return {
            "completed": 0,
            "mention_rate": None,
            "avg_rank": None,
            "top3_rate": None,
        }
    return {
        "completed": completed,
        "mention_rate": metrics["brand_mention_rate"],
        "avg_rank": metrics["avg_brand_rank"],
        "top3_rate": metrics["top3_rate"],
    }


def workspace_kpi_trends_from_stats(
    db: Session,
    tenant_id: int,
    range_start: datetime,
    range_end: datetime,
    *,
    platforms: list[str] | set[str] | frozenset[str] | None = None,
) -> list[dict[str, int | str | float | None]]:
    rows = list_daily_stats_for_tenant(
        db,
        tenant_id,
        since=range_start.date(),
        until=range_end.date(),
    )
    # 2026-08-07 - 观察号趋势按已授权平台重算，勿用全平台日表
    rows = filter_daily_stat_rows_by_platforms(rows, platforms)
    by_day: dict[str, list[GeoMonitorDailyStat]] = {}
    for row in rows:
        by_day.setdefault(row.stat_date.isoformat(), []).append(row)
    points: list[dict[str, int | str | float | None]] = []
    cursor = range_start.date()
    end = range_end.date()
    while cursor <= end:
        day_key = cursor.isoformat()
        metrics = workspace_metrics_from_stat_rows(by_day.get(day_key, []))
        # 2026-08-20 - 趋势图无样本日误画成 0% - 透出 sample_count 供前端断点/灰点
        points.append({
            "label": cursor.strftime("%m-%d"),
            "mention_rate": metrics["brand_mention_rate"],
            "avg_brand_rank": metrics["avg_brand_rank"],
            "top3_rate": metrics["top3_rate"],
            "negative_rate": metrics["negative_rate"],
            "sample_count": int(metrics.get("ranking_sample_count") or 0),
        })
        cursor += timedelta(days=1)
    return points
