"""Celery tasks for monitor submission, result sync, and lead diagnosis."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from celery.exceptions import Ignore, Retry
from kombu.exceptions import OperationalError
from redis.exceptions import RedisError
from sqlalchemy import select

from app.celery_app import celery_app
from app.core.celery_queue_monitor import clear_sync_live, record_beat_scan, set_sync_live
from app.core.config import settings
from app.core.database import SessionLocal
from app.core.redis_client import delete_cache, get_redis_client, prefixed_key, redis_lock
from app.models.lead_diagnosis import LeadDiagnosisRun
from app.services.lead_diagnosis_service import (
    enumerate_due_lead_runs,
    finalize_due_lead_diagnoses,
    persist_lead_run_failure,
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
    enumerate_due_brand_word_weekly_groups,
    enumerate_due_schedule_groups,
    get_schedule_run,
    persist_schedule_group_failure,
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
    """用 Redis 短期标记防止同一业务任务被重复塞进队列。

    Redis 不可用时 fail-closed（本轮跳过），避免多 Beat 重复投递；
    Celery broker 本身也依赖 Redis，长期不可用时任务本就不会跑。
    """
    client = get_redis_client()
    if client is None:
        logger.warning("enqueue dedupe skipped (redis unavailable), key=%s", key)
        return False
    try:
        return bool(client.set(prefixed_key(f"celery:enqueued:{key}"), "1", ex=ttl_seconds, nx=True))
    except RedisError as exc:
        logger.warning("mark celery enqueue key failed, key=%s, error=%s", key, exc)
        return False


def _clear_enqueued_mark(key: str) -> None:
    delete_cache(f"celery:enqueued:{key}")


def _schedule_submit_task_id(group_key: str, *, is_retry: bool) -> str:
    if not is_retry:
        return f"submit-{group_key}"
    bucket = datetime.now().strftime("%Y%m%d%H") + str(datetime.now().minute // 5)
    return f"submit-{group_key}-r{bucket}"


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
                existing = get_schedule_run(db, item.tenant_id, item.group_key)
                is_retry = existing is not None and existing.status == "failed"
                if _enqueue_task(
                    submit_schedule_group_task,
                    task_id=_schedule_submit_task_id(item.group_key, is_retry=is_retry),
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


@celery_app.task(name="app.tasks.monitor.scan_due_brand_word_weekly", ignore_result=True)
def scan_due_brand_word_weekly(max_prompts: int | None = None) -> dict[str, Any]:
    """每周一约 09:00 扫描品牌词（run_mode=weekly）并入队提交。"""
    if not settings.celery_enabled:
        return {"status": "disabled"}

    max_prompts = max_prompts or settings.celery_scan_submit_max_prompts
    lock_key = _scan_lock_key("scan-bw-weekly", bucket_minutes=5)
    with redis_lock(lock_key, ttl_seconds=300) as acquired:
        if not acquired:
            result = {"status": "locked", "message": "已有其他进程正在扫描品牌词周调度"}
            record_beat_scan("app.tasks.monitor.scan_due_brand_word_weekly", result)
            return result

        db = SessionLocal()
        enqueued = 0
        skipped = 0
        try:
            for item in enumerate_due_brand_word_weekly_groups(db, max_prompts=max_prompts):
                existing = get_schedule_run(db, item.tenant_id, item.group_key)
                is_retry = existing is not None and existing.status == "failed"
                if _enqueue_task(
                    submit_schedule_group_task,
                    task_id=_schedule_submit_task_id(item.group_key, is_retry=is_retry),
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
    logger.info("scan_due_brand_word_weekly enqueued=%s skipped=%s", enqueued, skipped)
    record_beat_scan("app.tasks.monitor.scan_due_brand_word_weekly", result)
    return result


@celery_app.task(
    name="app.tasks.monitor.submit_schedule_group",
    bind=True,
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
    current = None
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
    except RuntimeError as exc:
        logger.warning("submit_schedule_group skipped tenant=%s key=%s error=%s", tenant_id, group_key, exc)
        return {"status": "skipped", "message": str(exc)}
    except (MolizhishuApiError, OperationalError, TimeoutError) as exc:
        logger.warning(
            "submit_schedule_group retry tenant=%s key=%s attempt=%s/%s error=%s",
            tenant_id,
            group_key,
            self.request.retries,
            self.max_retries,
            exc,
        )
        if self.request.retries >= self.max_retries:
            created_by = current.user.id if current else None
            persist_schedule_group_failure(
                db,
                tenant_id=tenant_id,
                group_key=group_key,
                error_message=str(exc),
                created_by=created_by,
            )
            return {
                "tenant_id": tenant_id,
                "schedule_key": group_key,
                "status": "failed",
                "keyword": keyword,
                "message": str(exc),
            }
        raise self.retry(exc=exc)
    finally:
        db.close()


def _lead_submit_task_id(lead_id: int, schedule_key: str, *, is_retry: bool) -> str:
    if not is_retry:
        return f"lead-submit-{lead_id}-{schedule_key}"
    bucket = datetime.now().strftime("%Y%m%d%H") + str(datetime.now().minute // 5)
    return f"lead-submit-{lead_id}-{schedule_key}-r{bucket}"


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
                existing = db.scalar(
                    select(LeadDiagnosisRun).where(
                        LeadDiagnosisRun.lead_diagnosis_id == item.lead_id,
                        LeadDiagnosisRun.schedule_key == item.schedule_key,
                    )
                )
                is_retry = existing is not None and existing.status == "failed"
                if _enqueue_task(
                    submit_lead_diagnosis_run_task,
                    task_id=_lead_submit_task_id(item.lead_id, item.schedule_key, is_retry=is_retry),
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
        logger.warning(
            "submit_lead_diagnosis_run retry lead=%s key=%s attempt=%s/%s error=%s",
            lead_id,
            schedule_key,
            self.request.retries,
            self.max_retries,
            exc,
        )
        if self.request.retries >= self.max_retries:
            persist_lead_run_failure(
                db,
                lead_id=lead_id,
                schedule_key=schedule_key,
                error_message=str(exc),
            )
            return {
                "status": "failed",
                "lead_id": lead_id,
                "schedule_key": schedule_key,
                "message": str(exc),
            }
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
                if not _mark_enqueued_once(f"sync:{task_id}", ttl_seconds=300):
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
    name="app.tasks.monitor.process_molizhishu_callback_task",
    bind=True,
    max_retries=8,
    default_retry_delay=30,
    queue="sync",
    # 2026-08-21 - 回调重活出 HTTP：与 sync 同队列、同任务锁
    soft_time_limit=540,
    time_limit=600,
)
def process_molizhishu_callback_task(self, event_id: int) -> dict[str, Any]:
    """处理已入队的模力回调事件（排名补算 / 日统计等）。"""
    if not settings.celery_enabled:
        return {"status": "disabled", "event_id": event_id}

    from app.models.monitor import GeoMonitorCallbackEvent
    from app.services.molizhishu_callback_service import process_molizhishu_callback_event

    db = SessionLocal()
    try:
        event = db.get(GeoMonitorCallbackEvent, int(event_id))
        if event is None:
            return {"status": "missing", "event_id": event_id}
        if event.process_status in {"processed", "ignored"}:
            return {
                "status": event.process_status,
                "event_id": event_id,
                "task_id": event.task_id,
            }
        task_id = str(event.task_id or "").strip() or "unknown-callback"
        with redis_lock(f"sync-task:{task_id}", ttl_seconds=600) as acquired:
            if not acquired:
                raise self.retry(countdown=30)
            return process_molizhishu_callback_event(db, int(event_id))
    except Retry:
        raise
    except Exception as exc:
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=min(120, 15 * (self.request.retries + 1)))
        logger.exception("process_molizhishu_callback failed event_id=%s", event_id)
        return {"status": "failed", "event_id": event_id, "message": str(exc)[:240]}
    finally:
        db.close()


@celery_app.task(
    name="app.tasks.monitor.build_ranking_matrix_job_task",
    bind=True,
    max_retries=3,
    default_retry_delay=20,
    queue="default",
    # 2026-08-21 - 矩阵异步构建走 default，避免堵 sync 回调
    soft_time_limit=240,
    time_limit=300,
)
def build_ranking_matrix_job_task(self, job_id: str) -> dict[str, Any]:
    if not settings.celery_enabled:
        return {"status": "disabled", "job_id": job_id}

    from app.services.ranking_matrix_job_service import run_matrix_job

    db = SessionLocal()
    try:
        return run_matrix_job(db, str(job_id))
    except Retry:
        raise
    except Exception as exc:
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=20)
        logger.exception("build_ranking_matrix_job failed job_id=%s", job_id)
        return {"status": "failed", "job_id": job_id, "message": str(exc)[:240]}
    finally:
        db.close()


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
        except RuntimeError as exc:
            logger.warning("sync_one_monitor_task skipped task_id=%s error=%s", task_id, exc)
            return {"task_id": task_id, "status": "skipped", "message": str(exc)}
        except (MolizhishuApiError, OperationalError, TimeoutError) as exc:
            logger.warning("sync_one_monitor_task retry task_id=%s error=%s", task_id, exc)
            raise self.retry(exc=exc)
        finally:
            clear_sync_live()
            _clear_enqueued_mark(f"sync:{task_id}")
            db.close()


@celery_app.task(name="app.tasks.monitor.scan_due_scheduled_reports", ignore_result=True)
def scan_due_scheduled_reports() -> dict[str, Any]:
    """每日扫描：周/月/季/年报（按日历）+ 服务到期结项报告，直接发布。"""
    if not settings.celery_enabled:
        return {"status": "disabled"}

    lock_key = _scan_lock_key("scan-scheduled-reports", bucket_minutes=60)
    with redis_lock(lock_key, ttl_seconds=3600) as acquired:
        if not acquired:
            return {"status": "locked", "message": "已有其他进程正在生成周期报告"}

        from app.services.report_schedule_service import run_due_scheduled_reports

        db = SessionLocal()
        try:
            result = run_due_scheduled_reports(db)
        finally:
            db.close()

    record_beat_scan("app.tasks.monitor.scan_due_scheduled_reports", result)
    logger.info(
        "scan_due_scheduled_reports due=%s generated=%s skipped=%s errors=%s completion=%s",
        result.get("due_types"),
        result.get("generated"),
        result.get("skipped"),
        len(result.get("errors") or []),
        (result.get("completion") or {}).get("generated"),
    )
    return result


@celery_app.task(name="app.tasks.monitor.expire_overdue_tenant_services", ignore_result=True)
def expire_overdue_tenant_services_task() -> dict[str, Any]:
    """每日扫描合同到期企业，标记 expired 并禁用关联客户账号。"""
    if not settings.celery_enabled:
        return {"status": "disabled"}

    lock_key = _scan_lock_key("expire-tenant-services", bucket_minutes=60)
    with redis_lock(lock_key, ttl_seconds=3600) as acquired:
        if not acquired:
            return {"status": "locked"}

        from app.services.tenant_account_service import expire_overdue_tenant_services

        db = SessionLocal()
        try:
            handled = expire_overdue_tenant_services(db)
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    record_beat_scan("app.tasks.monitor.expire_overdue_tenant_services", {"handled": handled})
    logger.info("expire_overdue_tenant_services handled=%s", handled)
    return {"status": "ok", "handled": handled}


@celery_app.task(name="app.tasks.monitor.activate_due_tenants_and_kick_brand_words", ignore_result=True)
def activate_due_tenants_and_kick_brand_words_task() -> dict[str, Any]:
    """每日：服务开始日到达则启用企业，并开跑一轮品牌词（once/weekly 都跑这一枪）。"""
    if not settings.celery_enabled:
        return {"status": "disabled"}

    lock_key = _scan_lock_key("activate-tenants-bw-start", bucket_minutes=30)
    with redis_lock(lock_key, ttl_seconds=1800) as acquired:
        if not acquired:
            result = {"status": "locked"}
            record_beat_scan("app.tasks.monitor.activate_due_tenants_and_kick_brand_words", result)
            return result

        from app.services.schedule_service import kick_brand_word_service_start_for_tenant
        from app.services.tenant_account_service import activate_due_tenant_services

        db = SessionLocal()
        activated_ids: list[int] = []
        kicks: list[dict[str, Any]] = []
        try:
            activated = activate_due_tenant_services(db)
            db.commit()
            activated_ids = [item.id for item in activated]
            for tenant_id in activated_ids:
                kicks.append(kick_brand_word_service_start_for_tenant(db, tenant_id))
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    result = {
        "status": "ok",
        "activated": len(activated_ids),
        "tenant_ids": activated_ids,
        "kicks": kicks,
    }
    record_beat_scan("app.tasks.monitor.activate_due_tenants_and_kick_brand_words", result)
    logger.info("activate_due_tenants_and_kick_brand_words activated=%s", len(activated_ids))
    return result


@celery_app.task(name="app.tasks.monitor.kick_brand_word_service_start", ignore_result=True)
def kick_brand_word_service_start_task(tenant_id: int) -> dict[str, Any]:
    """单企业服务开始首跑品牌词（管理端改期/恢复后触发）。"""
    if not settings.celery_enabled:
        db = SessionLocal()
        try:
            from app.services.schedule_service import kick_brand_word_service_start_for_tenant

            return kick_brand_word_service_start_for_tenant(db, int(tenant_id))
        finally:
            db.close()

    db = SessionLocal()
    try:
        from app.services.schedule_service import kick_brand_word_service_start_for_tenant

        return kick_brand_word_service_start_for_tenant(db, int(tenant_id))
    finally:
        db.close()


@celery_app.task(name="app.tasks.monitor.scan_tenant_expiry_notifications", ignore_result=True)
def scan_tenant_expiry_notifications_task() -> dict[str, Any]:
    """每日按通知规则推送客户即将到期站内铃铛。"""
    if not settings.celery_enabled:
        return {"status": "disabled"}

    lock_key = _scan_lock_key("tenant-expiry-notify", bucket_minutes=60)
    with redis_lock(lock_key, ttl_seconds=3600) as acquired:
        if not acquired:
            return {"status": "locked"}

        from app.services.tenant_expiry_notify_service import sync_tenant_expiry_notifications

        db = SessionLocal()
        try:
            result = sync_tenant_expiry_notifications(db)
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    record_beat_scan("app.tasks.monitor.scan_tenant_expiry_notifications", result)
    logger.info("scan_tenant_expiry_notifications %s", result)
    return {"status": "ok", **result}


@celery_app.task(name="app.tasks.monitor.sync_platform_catalog_daily", ignore_result=True)
def sync_platform_catalog_daily_task() -> dict[str, Any]:
    """每日同步模力支持平台目录：上下架 + 取消已下架勾选 + 铃铛。"""
    if not settings.celery_enabled:
        return {"status": "disabled"}
    lock_key = _scan_lock_key("platform-catalog-daily", bucket_minutes=60)
    with redis_lock(lock_key, ttl_seconds=3600) as acquired:
        if not acquired:
            return {"status": "locked"}
        from app.services.platform_catalog_lifecycle_service import sync_platform_catalog_lifecycle

        db = SessionLocal()
        try:
            result = sync_platform_catalog_lifecycle(db, force_refresh=True)
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
    record_beat_scan("app.tasks.monitor.sync_platform_catalog_daily", result)
    return {"status": "ok", **result}


@celery_app.task(name="app.tasks.monitor.check_platform_availability_weekly", ignore_result=True)
def check_platform_availability_weekly_task() -> dict[str, Any]:
    """每周混合探测平台可用性；冷门平台提交探针任务。"""
    if not settings.celery_enabled:
        return {"status": "disabled"}
    lock_key = _scan_lock_key("platform-availability-weekly", bucket_minutes=60)
    with redis_lock(lock_key, ttl_seconds=7200) as acquired:
        if not acquired:
            return {"status": "locked"}
        from app.core.redis_client import set_json_cache
        from app.services.monitor_service import submit_standalone_monitor_task
        from app.services.platform_availability_service import (
            build_cold_probe_request,
            run_weekly_availability_check,
        )

        db = SessionLocal()
        result: dict[str, Any] = {}
        try:
            result = run_weekly_availability_check(db)
            cold = list(result.get("cold") or [])
            if cold:
                payload = build_cold_probe_request(cold)
                if payload is not None:
                    task = submit_standalone_monitor_task(db, payload=payload, tenant_id=None, auto_commit=True)
                    set_json_cache(f"platform:probe:{task.task_id}", {"codes": cold}, ttl_seconds=7 * 24 * 3600)
                    result["probe_task_id"] = task.task_id
                    result["probe_codes"] = cold
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
    record_beat_scan("app.tasks.monitor.check_platform_availability_weekly", result)
    return {"status": "ok", **result}


@celery_app.task(name="app.tasks.monitor.finalize_platform_probes", ignore_result=True)
def finalize_platform_probes_task() -> dict[str, Any]:
    """回收冷门探针子任务结果，写回 service_available。"""
    if not settings.celery_enabled:
        return {"status": "disabled"}
    from app.core.redis_client import delete_cache, get_redis_client, prefixed_key
    from app.models.monitor import GeoMonitorSubtask, GeoMonitorTask
    from app.services.platform_availability_service import (
        SUCCESS_STATUSES,
        TERMINAL_STATUSES,
        apply_probe_results,
        notify_availability_flips,
    )

    client = get_redis_client()
    if client is None:
        return {"status": "no_redis"}
    try:
        keys = list(client.scan_iter(match=prefixed_key("platform:probe:*"), count=50))
    except Exception:
        keys = []
    finalized = 0
    flipped_down: list[str] = []
    flipped_up: list[str] = []
    marker = "platform:probe:"
    db = SessionLocal()
    try:
        for key in keys:
            key_text = key.decode() if isinstance(key, bytes) else str(key)
            idx = key_text.find(marker)
            if idx < 0:
                continue
            task_id = key_text[idx + len(marker) :]
            cache_key = f"platform:probe:{task_id}"
            task = db.scalar(select(GeoMonitorTask).where(GeoMonitorTask.task_id == task_id))
            if task is None:
                continue
            if task.status not in ("completed", "partial_completed", "failed", "stopped"):
                continue
            subtasks = list(db.scalars(select(GeoMonitorSubtask).where(GeoMonitorSubtask.task_id == task_id)))
            if not subtasks:
                continue
            if any(item.status not in TERMINAL_STATUSES for item in subtasks):
                continue
            results: dict[str, bool] = {}
            for item in subtasks:
                code = (item.platform or "").strip()
                if not code:
                    continue
                results[code] = item.status in SUCCESS_STATUSES
            flip = apply_probe_results(db, results)
            flipped_down.extend(flip.get("flipped_down") or [])
            flipped_up.extend(flip.get("flipped_up") or [])
            delete_cache(cache_key)
            finalized += 1
        if flipped_down or flipped_up:
            notify_availability_flips(db, flipped_down=list(set(flipped_down)), flipped_up=list(set(flipped_up)))
    finally:
        db.close()
    return {"status": "ok", "finalized": finalized}


@celery_app.task(name="app.tasks.monitor.refresh_ops_overview_rollup", bind=True, ignore_result=True)
def refresh_ops_overview_rollup(self) -> dict[str, Any]:
    """预热运营总览物理预聚合（全平台 scope）。"""
    from app.services.ops_overview_rollup_service import refresh_platform_overview_rollup

    db = SessionLocal()
    try:
        payload = refresh_platform_overview_rollup(db)
        return {
            "status": "ok",
            "pending_backfill": int((payload or {}).get("pending_backfill") or 0),
            "platform_stats": len((payload or {}).get("platform_stats") or []),
        }
    except Exception as exc:
        logger.exception("refresh_ops_overview_rollup failed")
        return {"status": "error", "error": str(exc)}
    finally:
        db.close()


@celery_app.task(name="app.tasks.monitor.sync_announcement_lifecycle", ignore_result=True)
def sync_announcement_lifecycle() -> dict[str, Any]:
    """定时上线 scheduled 公告，并将已过 expire_at 的 published 下线。"""
    if not settings.celery_enabled:
        return {"status": "disabled"}

    from app.services.announcement_service import expire_published_announcements, promote_scheduled_announcements

    db = SessionLocal()
    try:
        promoted = promote_scheduled_announcements(db)
        expired = expire_published_announcements(db)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    return {"status": "ok", "promoted": promoted, "expired": expired}


@celery_app.task(
    name="app.tasks.monitor.warm_customer_source_daily",
    ignore_result=True,
    queue="sync",
)
def warm_customer_source_daily(tenant_id: int) -> dict[str, Any]:
    """异步预热客户信源日物化，避免 GET 冷路径全历史扫描。"""
    if not settings.celery_enabled:
        return {"status": "disabled", "tenant_id": tenant_id}

    with redis_lock(f"source-daily-warm:{tenant_id}", ttl_seconds=1800) as acquired:
        if not acquired:
            return {"status": "locked", "tenant_id": tenant_id}
        db = SessionLocal()
        try:
            from app.services.monitor_source_rollup_service import warm_source_daily_for_tenant

            days = warm_source_daily_for_tenant(db, int(tenant_id))
            return {"status": "ok", "tenant_id": tenant_id, "days": days}
        except Exception as exc:
            logger.exception("warm_customer_source_daily failed tenant_id=%s", tenant_id)
            db.rollback()
            return {"status": "error", "tenant_id": tenant_id, "error": str(exc)}
        finally:
            _clear_enqueued_mark(f"source-daily-warm:{tenant_id}")
            db.close()


@celery_app.task(
    name="app.tasks.monitor.label_unknown_source_categories",
    ignore_result=True,
    queue="default",
)
def label_unknown_source_categories(items: list[dict[str, Any]]) -> dict[str, Any]:
    """离线 LLM 标注未知信源域名类型，结果写入全局缓存。"""
    if not settings.celery_enabled:
        return {"status": "disabled", "count": 0}
    try:
        from app.services.source_category_service import resolve_source_categories_with_llm

        resolved = resolve_source_categories_with_llm(items or [])
        return {"status": "ok", "count": len(resolved)}
    except Exception as exc:
        logger.exception("label_unknown_source_categories failed")
        return {"status": "error", "error": str(exc)}
