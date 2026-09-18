"""信源日级物化：监测完成后按业务日重建，读路径按日合并。"""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, PendingRollbackError
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
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

# 2026-09-18 - 同企业同日多任务并发回调会撞 uk；MySQL 下 savepoint 有时毒化整段事务，改 rollback 整段重试
_SOURCE_DAILY_WRITE_RETRIES = 3


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


def _upsert_source_daily_row(
    db: Session,
    *,
    tenant_id: int,
    stat_date: date,
    config_fp: str,
    branded_map: dict[str, Any],
    all_map: dict[str, Any],
    branded_day_count: int,
    platform_day: dict[str, int],
) -> GeoMonitorSourceDaily:
    """写入或更新一日物化行；撞 uk 时由调用方 rollback 后重试。"""
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
        try:
            # 同企业同日多任务并发双插：savepoint 收回后读已有行
            with db.begin_nested():
                db.flush()
        except IntegrityError:
            # savepoint 已回滚；须甩掉本地 pending，否则二次 flush 会再撞 uk
            try:
                db.expunge(row)
            except Exception:
                pass
            row = db.scalar(
                select(GeoMonitorSourceDaily).where(
                    GeoMonitorSourceDaily.tenant_id == tenant_id,
                    GeoMonitorSourceDaily.stat_date == stat_date,
                )
            )
            if row is None:
                raise
    row.config_fp = config_fp
    row.branded_json = branded_map
    row.all_json = all_map
    row.daily_branded_count = branded_day_count
    row.daily_by_platform_json = platform_day
    db.flush()
    return row


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

    # 2026-08-13 - 方案 A：日物化开启抓网页补露出词（读路径聚合仍默认不抓）
    branded_map, all_map, daily_counts, daily_by_platform = _aggregate_source_stats_pair_maps(
        source_items,
        business_day_by_id=source_day_by_id,
        subtask_tenant_map=source_tenant_map,
        purchased_platforms_by_tenant={tenant_id: purchased_platforms},
        exposure_terms_by_tenant={tenant_id: exposure_terms},
        allow_page_fetch=True,
        page_fetch_budget=40,
    )
    day_key = stat_date.isoformat()
    branded_day_count = int(daily_counts.get(day_key) or 0)
    platform_day: dict[str, int] = {
        platform: int((bucket or {}).get(day_key) or 0)
        for platform, bucket in daily_by_platform.items()
        if int((bucket or {}).get(day_key) or 0) > 0
    }

    last_exc: BaseException | None = None
    for attempt in range(_SOURCE_DAILY_WRITE_RETRIES):
        try:
            return _upsert_source_daily_row(
                db,
                tenant_id=tenant_id,
                stat_date=stat_date,
                config_fp=config_fp,
                branded_map=branded_map,
                all_map=all_map,
                branded_day_count=branded_day_count,
                platform_day=platform_day,
            )
        except (IntegrityError, PendingRollbackError) as exc:
            last_exc = exc
            try:
                db.rollback()
            except Exception:
                pass
            if attempt + 1 >= _SOURCE_DAILY_WRITE_RETRIES:
                break
            logger.warning(
                "source_daily upsert conflict retry tenant=%s day=%s attempt=%s err=%s",
                tenant_id,
                stat_date,
                attempt + 1,
                exc,
            )
    assert last_exc is not None
    raise last_exc


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


def enqueue_source_daily_after_backfill(
    *,
    tenant_id: int,
    task_id: str,
    previous_stat_date: str | None,
    new_stat_date: str | None,
) -> str:
    """补录后信源日表重刷改异步，避免 HTTP 被艾迪亚级租户拖过 30s。

    2026-08-17 - 快照补录 timeout of 30000ms：同步 source rollup 8–12s+
    """
    from app.core.config import settings

    if settings.celery_enabled:
        try:
            from app.tasks.snapshot_backfill import refresh_source_daily_after_backfill_task

            refresh_source_daily_after_backfill_task.delay(
                int(tenant_id),
                str(task_id),
                previous_stat_date,
                new_stat_date,
            )
            return "queued"
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "source daily after backfill enqueue failed task_id=%s err=%s; thread fallback",
                task_id,
                exc,
            )

    import threading

    def _run() -> None:
        db = SessionLocal()
        try:
            _run_source_daily_after_backfill(
                db,
                tenant_id=int(tenant_id),
                task_id=str(task_id),
                previous_stat_date=previous_stat_date,
                new_stat_date=new_stat_date,
            )
            db.commit()
        except Exception:  # noqa: BLE001
            db.rollback()
            logger.exception("source daily after backfill thread failed task_id=%s", task_id)
        finally:
            db.close()

    threading.Thread(target=_run, name=f"src-daily-bf-{task_id[:12]}", daemon=True).start()
    return "thread_fallback"


def _run_source_daily_after_backfill(
    db: Session,
    *,
    tenant_id: int,
    task_id: str,
    previous_stat_date: str | None,
    new_stat_date: str | None,
) -> None:
    task = db.scalar(select(GeoMonitorTask).where(GeoMonitorTask.task_id == task_id))
    if task is None or task.tenant_id is None:
        return
    if int(task.tenant_id) != int(tenant_id):
        logger.warning(
            "source daily after backfill tenant mismatch task_id=%s expected=%s actual=%s",
            task_id,
            tenant_id,
            task.tenant_id,
        )
        return
    prev = date.fromisoformat(previous_stat_date) if previous_stat_date else None
    new = date.fromisoformat(new_stat_date) if new_stat_date else None
    refresh_source_daily_after_subtask_backfill(
        db,
        task=task,
        previous_stat_date=prev,
        new_stat_date=new,
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
    range_start_day: date | None = None,
) -> dict[str, Any]:
    from app.services.monitor_service import (
        _build_source_citation_trend,
        _build_source_citation_trends_by_platform,
        _finalize_source_stat_rows,
        _is_valid_citation_source,
    )

    def _filter_url_map(raw: Any) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        if not isinstance(raw, dict):
            return out
        for key, row in raw.items():
            if isinstance(row, dict) and _is_valid_citation_source(row):
                out[str(key)] = row
        return out

    branded_maps: list[dict[str, dict[str, Any]]] = []
    all_maps: list[dict[str, dict[str, Any]]] = []
    source_daily_counts: dict[str, int] = {}
    source_daily_by_platform: dict[str, dict[str, int]] = {}
    for row in day_rows:
        if row.stat_date > cutoff_day:
            continue
        # 2026-08-14 - 按区间合并日物化，count/趋势与「近7天」一致
        if range_start_day is not None and row.stat_date < range_start_day:
            continue
        day_key = row.stat_date.isoformat()
        filtered_branded = _filter_url_map(row.branded_json)
        filtered_all = _filter_url_map(row.all_json)
        branded_maps.append(filtered_branded)
        all_maps.append(filtered_all)
        count = sum(int(item.get("count") or 0) for item in filtered_branded.values())
        if count > 0:
            source_daily_counts[day_key] = count
        plat_map = row.daily_by_platform_json if isinstance(row.daily_by_platform_json, dict) else {}
        for platform, plat_count in plat_map.items():
            n = int(plat_count or 0)
            if n <= 0:
                continue
            bucket = source_daily_by_platform.setdefault(str(platform), {})
            bucket[day_key] = n

    citation_range_end = datetime.combine(cutoff_day, time.max)
    if range_start_day is not None:
        citation_range_start = datetime.combine(range_start_day, time.min)
    else:
        positive_days = [date.fromisoformat(k) for k, v in source_daily_counts.items() if int(v or 0) > 0]
        citation_range_start = datetime.combine(
            min(positive_days) if positive_days else cutoff_day,
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
            allow_page_fetch=True,
            page_fetch_budget=40,
        )
        day_key = day.isoformat()
        platform_day = {
            platform: int((bucket or {}).get(day_key) or 0)
            for platform, bucket in daily_by_platform.items()
            if int((bucket or {}).get(day_key) or 0) > 0
        }
        last_exc: BaseException | None = None
        row: GeoMonitorSourceDaily | None = None
        for attempt in range(_SOURCE_DAILY_WRITE_RETRIES):
            try:
                row = _upsert_source_daily_row(
                    db,
                    tenant_id=tenant_id,
                    stat_date=day,
                    config_fp=config_fp,
                    branded_map=branded_map,
                    all_map=all_map,
                    branded_day_count=int(daily_counts.get(day_key) or 0),
                    platform_day=platform_day,
                )
                break
            except (IntegrityError, PendingRollbackError) as exc:
                last_exc = exc
                try:
                    db.rollback()
                except Exception:
                    pass
                if attempt + 1 >= _SOURCE_DAILY_WRITE_RETRIES:
                    break
                logger.warning(
                    "source_daily history upsert conflict retry tenant=%s day=%s attempt=%s err=%s",
                    tenant_id,
                    day,
                    attempt + 1,
                    exc,
                )
        if row is None:
            assert last_exc is not None
            raise last_exc
        written.append(row)
    return written


def build_customer_source_stats_from_daily(
    db: Session,
    tenant_id: int,
    *,
    purchased_platforms: set[str],
    exposure_terms: list[str],
) -> dict[str, Any]:
    """读路径：确保截止日前各监测日物化可用，再合并。

    缺日/指纹失效超过 1 天时优先异步全历史回填（避免 GET 堵死）；
    写完显式 commit（GET 会话默认不 commit，否则物化会被回滚）。
    """
    from app.services.monitor_service import customer_display_cutoff

    cutoff_day = customer_display_cutoff().date()
    config_fp = source_stats_config_fingerprint(exposure_terms, purchased_platforms)
    candidate_days = _candidate_source_days(db, tenant_id, cutoff_day)

    existing = {
        row.stat_date: row
        for row in db.scalars(
            select(GeoMonitorSourceDaily).where(
                GeoMonitorSourceDaily.tenant_id == tenant_id,
                GeoMonitorSourceDaily.stat_date <= cutoff_day,
            )
        )
    }
    stale_days = [
        day
        for day in candidate_days
        if day not in existing or str(existing[day].config_fp or "") != config_fp
    ]

    wrote = False
    if not candidate_days or len(stale_days) > 1:
        # ponytail: 多日冷填改异步，GET 先回已有物化；Celery 不可用时仍同步回填
        if _try_enqueue_source_daily_warm(tenant_id):
            day_rows = [
                existing[day]
                for day in candidate_days
                if day in existing and str(existing[day].config_fp or "") == config_fp
            ]
            return _bundle_from_day_rows(day_rows, cutoff_day=cutoff_day)
        day_rows = _backfill_source_daily_from_history(
            db,
            tenant_id,
            cutoff_day=cutoff_day,
            purchased_platforms=purchased_platforms,
            exposure_terms=exposure_terms,
            config_fp=config_fp,
        )
        wrote = True
    else:
        day_rows = []
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
                wrote = True
            day_rows.append(row)

    if wrote:
        try:
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("commit source daily rollup failed tenant_id=%s", tenant_id)
            raise

    return _bundle_from_day_rows(day_rows, cutoff_day=cutoff_day)


def ensure_source_daily_range(
    db: Session,
    tenant_id: int,
    *,
    start_day: date | None,
    end_day: date,
    purchased_platforms: set[str],
    exposure_terms: list[str],
) -> list[GeoMonitorSourceDaily]:
    """只保证查询区间内日物化可用，不先算全历史。"""
    cutoff = end_day
    start = start_day or cutoff
    if start > cutoff:
        start = cutoff
    config_fp = source_stats_config_fingerprint(exposure_terms, purchased_platforms)
    existing = {
        row.stat_date: row
        for row in db.scalars(
            select(GeoMonitorSourceDaily).where(
                GeoMonitorSourceDaily.tenant_id == tenant_id,
                GeoMonitorSourceDaily.stat_date >= start,
                GeoMonitorSourceDaily.stat_date <= cutoff,
            )
        )
    }
    days: list[date] = []
    cursor = start
    while cursor <= cutoff:
        days.append(cursor)
        cursor += timedelta(days=1)
    stale = [
        day
        for day in days
        if day not in existing or str(existing[day].config_fp or "") != config_fp
    ]
    if len(stale) > 3 and _try_enqueue_source_daily_warm(tenant_id):
        return [
            existing[day]
            for day in days
            if day in existing and str(existing[day].config_fp or "") == config_fp
        ]
    wrote = False
    out: list[GeoMonitorSourceDaily] = []
    for day in days:
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
            wrote = True
        out.append(row)
    if wrote:
        try:
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("commit source daily range failed tenant_id=%s", tenant_id)
            raise
    return out


def _try_enqueue_source_daily_warm(tenant_id: int) -> bool:
    """投递信源日物化预热；成功或已在队列中返回 True。"""
    from app.core.config import settings
    from app.core.redis_client import delete_cache, get_redis_client, prefixed_key
    from redis.exceptions import RedisError

    if not settings.celery_enabled:
        return False
    client = get_redis_client()
    dedupe_key = f"celery:enqueued:source-daily-warm:{tenant_id}"
    if client is not None:
        try:
            if not client.set(prefixed_key(dedupe_key), "1", ex=900, nx=True):
                return True
        except RedisError as exc:
            logger.warning("source daily warm dedupe failed tenant_id=%s error=%s", tenant_id, exc)
            return False
    try:
        from app.tasks.monitor import warm_customer_source_daily

        warm_customer_source_daily.delay(int(tenant_id))
        return True
    except Exception as exc:
        logger.warning("enqueue source daily warm failed tenant_id=%s error=%s", tenant_id, exc)
        delete_cache(dedupe_key)
        return False


def warm_source_daily_for_tenant(db: Session, tenant_id: int) -> int:
    """同步执行全历史信源日物化，返回写入天数。供 Celery 预热调用。"""
    from app.services.brand_service import (
        active_keyword_groups,
        brand_exposure_terms,
        get_brand_asset,
        tenant_purchased_platforms,
    )
    from app.services.monitor_service import customer_display_cutoff, invalidate_monitor_summary_cache

    asset = get_brand_asset(db, tenant_id)
    purchased = set(tenant_purchased_platforms(db, tenant_id, asset))
    exposure = brand_exposure_terms(asset, active_keyword_groups(db, tenant_id)) if asset else []
    cutoff_day = customer_display_cutoff().date()
    config_fp = source_stats_config_fingerprint(exposure, purchased)
    rows = _backfill_source_daily_from_history(
        db,
        tenant_id,
        cutoff_day=cutoff_day,
        purchased_platforms=purchased,
        exposure_terms=exposure,
        config_fp=config_fp,
    )
    db.commit()
    invalidate_monitor_summary_cache(tenant_id)
    return len(rows)
