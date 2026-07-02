"""Celery tasks for monitor submission, result sync, and lead diagnosis."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from celery.exceptions import Ignore
from kombu.exceptions import OperationalError
from redis.exceptions import RedisError

from app.celery_app import celery_app
from app.core.celery_queue_monitor import clear_sync_live, record_beat_scan, set_sync_live
from app.core.config import settings
from app.core.database import SessionLocal
from app.core.redis_client import delete_cache, get_redis_client, prefixed_key, redis_lock
from app.services.lead_diagnosis_service import (
    enumerate_due_lead_runs,
    finalize_due_lead_diagnoses,
    submit_due_lead_run,
)
from app.services.molizhishu_client import MolizhishuApiError
from app.services.monitor_service import (
    list_pending_monitor_task_ids,
    summarize_monitor_task_for_ops,
    summarize_monitor_tasks_for_ops,
    sync_monitor_task,
)
from app.services.platform_session import load_platform_session
from app.services.schedule_service import (
    DueScheduleGroup,
    enumerate_due_schedule_groups,
    submit_schedule_group as execute_schedule_group,
)

logger = logging.getLogger(__name__)


def _scan_lock_key(prefix: str, *, bucket_minutes: int) -> str:
    now = datetime.now()
    bucket = now.strftime("%Y%m%d%H") + str(now.minute // bucket_minutes)
    return f"celery:{prefix}:{bucket}"


def _enqueue_task(task, *, task_id: str, kwargs: dict[str, Any]) -> bool:
    try:
        task.apply_async(kwargs=kwargs, task_id=task_id)
        return True
    except Exception as exc:
        message = str(exc).lower()
        if "already exists" in message or "duplicate" in message:
            return False
        raise


def _mark_enqueued_once(key: str, *, ttl_seconds: int = 600) -> bool:
    """用 Redis 短期标记防止同一业务任务被重复塞进队列。"""
    client = get_redis_client()
    if client is None:
        return True
    try:
        return bool(client.set(prefixed_key(f"celery:enqueued:{key}"), "1", ex=ttl_seconds, nx=True))
    except RedisError as exc:
        logger.warning("mark celery enqueue key failed, key=%s, error=%s", key, exc)
        return True


def _clear_enqueued_mark(key: str) -> None:
    delete_cache(f"celery:enqueued:{key}")


@celery_app.task(name="app.tasks.monitor.scan_due_schedules", ignore_result=True)
def scan_due_schedules(max_prompts: int | None = None) -> dict[str, Any]:
    """Scan tenant schedules and enqueue one submit task per due keyword group."""
    if not settings.celery_enabled:
        return {"status": "disabled"}

    max_prompts = max_prompts or settings.celery_scan_submit_max_prompts
    lock_key = _scan_lock_key("scan-due", bucket_minutes=5)
    with redis_lock(lock_key, ttl_seconds=300) as acquired:
        if not acquired:
            result = {"status": "locked", "message": "已有其他进程正在扫描到点调度"}
            record_beat_scan("app.tasks.monitor.scan_due_schedules", result)
            return result

        db = SessionLocal()
        enqueued = 0
        skipped = 0
        try:
            for item in enumerate_due_schedule_groups(db, max_prompts=max_prompts):
                if _enqueue_task(
                    submit_schedule_group_task,
                    task_id=f"submit-{item.group_key}",
                    kwargs={
                        "tenant_id": item.tenant_id,
                        "group_key": item.group_key,
                        "max_prompts": item.max_prompts,
                        "keyword": item.keyword,
                    },
                ):
                    enqueued += 1
                else:
                    skipped += 1
        finally:
            db.close()

    result = {"status": "ok", "enqueued": enqueued, "skipped": skipped}
    logger.info("scan_due_schedules enqueued=%s skipped=%s", enqueued, skipped)
    record_beat_scan("app.tasks.monitor.scan_due_schedules", result)
    return result


@celery_app.task(
    name="app.tasks.monitor.submit_schedule_group",
    bind=True,
    autoretry_for=(MolizhishuApiError, OperationalError, TimeoutError),
    retry_backoff=True,
    retry_backoff_max=600,
    max_retries=3,
    queue="submit",
)
def submit_schedule_group_task(
    self,
    tenant_id: int,
    group_key: str,
    max_prompts: int = 50,
    keyword: str | None = None,
) -> dict[str, Any]:
    """Submit one tenant keyword group to Molizhishu."""
    if not settings.celery_enabled:
        return {"status": "disabled", "schedule_key": group_key}

    db = SessionLocal()
    try:
        current = load_platform_session(db)
        item = DueScheduleGroup(
            tenant_id=tenant_id,
            schedule_key=group_key.split("-kw", 1)[0],
            group_key=group_key,
            max_prompts=max_prompts,
            keyword=keyword,
        )
        result = execute_schedule_group(db, current, item)
        if result.get("status") == "skipped":
            raise Ignore()
        return result
    except Ignore:
        raise
    except (MolizhishuApiError, OperationalError, TimeoutError) as exc:
        logger.warning("submit_schedule_group retry tenant=%s key=%s error=%s", tenant_id, group_key, exc)
        raise self.retry(exc=exc)
    finally:
        db.close()


@celery_app.task(name="app.tasks.monitor.scan_due_lead_diagnosis", ignore_result=True)
def scan_due_lead_diagnosis() -> dict[str, Any]:
    """Scan active lead diagnoses and enqueue due schedule runs."""
    if not settings.celery_enabled:
        return {"status": "disabled"}

    lock_key = _scan_lock_key("scan-lead-diag", bucket_minutes=5)
    with redis_lock(lock_key, ttl_seconds=300) as acquired:
        if not acquired:
            return {"status": "locked", "message": "已有其他进程正在扫描售前诊断调度"}

        db = SessionLocal()
        enqueued = 0
        skipped = 0
        try:
            for item in enumerate_due_lead_runs(db):
                if _enqueue_task(
                    submit_lead_diagnosis_run_task,
                    task_id=f"lead-submit-{item.lead_id}-{item.schedule_key}",
                    kwargs={"lead_id": item.lead_id, "schedule_key": item.schedule_key},
                ):
                    enqueued += 1
                else:
                    skipped += 1
        finally:
            db.close()

    result = {"status": "ok", "enqueued": enqueued, "skipped": skipped}
    record_beat_scan("app.tasks.monitor.scan_due_lead_diagnosis", result)
    return result


@celery_app.task(
    name="app.tasks.monitor.submit_lead_diagnosis_run",
    bind=True,
    autoretry_for=(MolizhishuApiError, OperationalError, TimeoutError),
    retry_backoff=True,
    retry_backoff_max=600,
    max_retries=3,
    queue="submit",
)
def submit_lead_diagnosis_run_task(self, lead_id: int, schedule_key: str) -> dict[str, Any]:
    if not settings.celery_enabled:
        return {"status": "disabled", "lead_id": lead_id}

    db = SessionLocal()
    try:
        current = load_platform_session(db)
        result = submit_due_lead_run(db, current, lead_id, schedule_key=schedule_key, force=False)
        if result.get("status") == "skipped":
            raise Ignore()
        return result
    except Ignore:
        raise
    except (MolizhishuApiError, OperationalError, TimeoutError) as exc:
        logger.warning("submit_lead_diagnosis_run retry lead=%s key=%s error=%s", lead_id, schedule_key, exc)
        raise self.retry(exc=exc)
    except PermissionError:
        logger.warning("submit_lead_diagnosis_run skipped lead=%s no platform session", lead_id)
        return {"status": "skipped", "message": "无可用平台运营身份"}
    finally:
        db.close()


@celery_app.task(name="app.tasks.monitor.finalize_lead_diagnoses", ignore_result=True)
def finalize_lead_diagnoses() -> dict[str, Any]:
    if not settings.celery_enabled:
        return {"status": "disabled"}

    db = SessionLocal()
    try:
        result = finalize_due_lead_diagnoses(db)
    finally:
        db.close()
    record_beat_scan("app.tasks.monitor.finalize_lead_diagnoses", result)
    return result


@celery_app.task(name="app.tasks.monitor.scan_pending_syncs", ignore_result=True)
def scan_pending_syncs(
    limit: int | None = None,
    terminal_grace_hours: int | None = None,
) -> dict[str, Any]:
    """Scan pending monitor tasks and dispatch each sync as an independent task."""
    if not settings.celery_enabled:
        return {"status": "disabled"}

    limit = limit or settings.celery_sync_batch_limit
    terminal_grace_hours = terminal_grace_hours or settings.celery_sync_terminal_grace_hours
    lock_key = _scan_lock_key("scan-sync", bucket_minutes=1)
    with redis_lock(lock_key, ttl_seconds=90) as acquired:
        if not acquired:
            result = {"status": "locked", "message": "已有其他进程正在扫描待同步监测结果"}
            record_beat_scan("app.tasks.monitor.scan_pending_syncs", result)
            return result

        db = SessionLocal()
        enqueued = 0
        skipped = 0
        sync_details: list[dict[str, Any]] = []
        try:
            task_ids = list_pending_monitor_task_ids(
                db,
                limit=limit,
                terminal_grace_hours=terminal_grace_hours,
            )
            preview_map = {
                item["task_id"]: item
                for item in summarize_monitor_tasks_for_ops(
                    db,
                    task_ids=task_ids,
                    limit=limit,
                    terminal_grace_hours=terminal_grace_hours,
                )
            }
            for task_id in task_ids:
                live_payload = preview_map.get(task_id)
                if live_payload:
                    sync_details.append({**live_payload, "phase": "queued"})
                if not _mark_enqueued_once(f"sync:{task_id}", ttl_seconds=600):
                    skipped += 1
                    continue
                if _enqueue_task(
                    sync_one_monitor_task,
                    task_id=f"sync-{task_id}",
                    kwargs={"task_id": task_id},
                ):
                    enqueued += 1
                else:
                    _clear_enqueued_mark(f"sync:{task_id}")
                    skipped += 1
        finally:
            db.close()

    result = {
        "status": "ok",
        "enqueued": enqueued,
        "skipped": skipped,
        "synced": 0,
        "failed": 0,
        "sync_details": sync_details[:10],
    }
    logger.info("scan_pending_syncs enqueued=%s skipped=%s", enqueued, skipped)
    record_beat_scan("app.tasks.monitor.scan_pending_syncs", result)
    return result


@celery_app.task(
    name="app.tasks.monitor.sync_one_monitor_task",
    bind=True,
    autoretry_for=(MolizhishuApiError, OperationalError, TimeoutError),
    retry_backoff=True,
    retry_backoff_max=300,
    max_retries=5,
    queue="sync",
)
def sync_one_monitor_task(self, task_id: str) -> dict[str, Any]:
    """Sync one monitor task status and results from Molizhishu."""
    if not settings.celery_enabled:
        return {"status": "disabled", "task_id": task_id}

    with redis_lock(f"sync-task:{task_id}", ttl_seconds=600) as acquired:
        if not acquired:
            return {"task_id": task_id, "status": "locked", "message": "已有其他 Worker 正在同步该任务"}

        db = SessionLocal()
        try:
            current = load_platform_session(db)
            preview = summarize_monitor_tasks_for_ops(db, task_ids=[task_id], limit=1)
            if preview:
                set_sync_live({**preview[0], "phase": "syncing"})
            task = sync_monitor_task(db, task_id, current)
            detail = summarize_monitor_task_for_ops(
                task,
                tenant_name=preview[0].get("tenant_name") if preview else None,
            )
            finalize_due_lead_diagnoses(db)
            return {"task_id": task_id, "status": "synced", "task_status": task.status, "detail": detail}
        except (MolizhishuApiError, OperationalError, TimeoutError) as exc:
            logger.warning("sync_one_monitor_task retry task_id=%s error=%s", task_id, exc)
            raise self.retry(exc=exc)
        finally:
            clear_sync_live()
            _clear_enqueued_mark(f"sync:{task_id}")
            db.close()
