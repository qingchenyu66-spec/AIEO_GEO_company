"""模力指数 Webhook 回调：鉴权、幂等、落库。"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
from datetime import datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.monitor import GeoMonitorCallbackEvent, GeoMonitorSubtask, GeoMonitorTask
from app.services.monitor_service import (
    _apply_remote_task_counts,
    _reconcile_task_progress,
    _upsert_subtask,
    fill_missing_subtask_ranks_for_task,
)

logger = logging.getLogger(__name__)


def expected_callback_token() -> str:
    """优先独立 token；否则从 MOLIZHISHU_CALLBACK_URL 的 ?token= 解析。"""
    direct = str(settings.molizhishu_callback_token or "").strip()
    if direct:
        return direct
    url = str(settings.molizhishu_callback_url or "").strip()
    if not url:
        return ""
    query = parse_qs(urlparse(url).query)
    values = query.get("token") or []
    return str(values[0] or "").strip() if values else ""


def verify_callback_token(provided: str | None) -> bool:
    expected = expected_callback_token()
    if not expected:
        return False
    return secrets.compare_digest(str(provided or "").strip(), expected)


def _payload_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _load_task(db: Session, task_id: str) -> GeoMonitorTask | None:
    return db.scalar(
        select(GeoMonitorTask).where(
            GeoMonitorTask.task_id == task_id,
            GeoMonitorTask.deleted.is_(False),
        )
    )


def _apply_callback_payload(db: Session, task: GeoMonitorTask, data: dict[str, Any]) -> None:
    """与 sync 同源：写主任务进度 + upsert 子任务 + 排名补算/重试/统计。"""
    task.status = data.get("status") or task.status
    _apply_remote_task_counts(task, data)
    if data.get("createdAt"):
        task.remote_created_at = data.get("createdAt")
    if data.get("completedAt"):
        task.remote_completed_at = data.get("completedAt")
    for item in data.get("subTaskList") or []:
        if isinstance(item, dict):
            _upsert_subtask(db, task.task_id, item)

    filled = fill_missing_subtask_ranks_for_task(db, task)
    if filled:
        logger.info("callback fill_missing_subtask_ranks task_id=%s filled=%s", task.task_id, filled)
    task.last_error = None
    task.subtasks = list(
        db.scalars(select(GeoMonitorSubtask).where(GeoMonitorSubtask.task_id == task.task_id))
    )
    _reconcile_task_progress(task)

    from app.services.monitor_auto_retry_service import apply_auto_retry_results, launch_auto_retries_for_task
    from app.services.snapshot_backfill_service import notify_failed_subtasks_for_task

    apply_auto_retry_results(db, task)
    task.subtasks = list(
        db.scalars(select(GeoMonitorSubtask).where(GeoMonitorSubtask.task_id == task.task_id))
    )
    launch_auto_retries_for_task(db, task)
    notify_failed_subtasks_for_task(db, task)


def _post_commit_side_effects(db: Session, task: GeoMonitorTask) -> None:
    try:
        from app.services.monitor_stats_service import refresh_stats_for_task

        refresh_stats_for_task(db, task.task_id)
        db.commit()
    except Exception as exc:
        logger.warning("callback refresh_stats failed task_id=%s error=%s", task.task_id, exc)
        db.rollback()

    from app.services.monitor_service import invalidate_monitor_summary_cache

    invalidate_monitor_summary_cache(task.tenant_id)
    try:
        from app.services.brand_analysis_service import parse_sentiments_after_brand_word_sync

        parse_sentiments_after_brand_word_sync(db, task)
    except Exception as exc:
        logger.warning("callback brand_word sentiment failed task_id=%s error=%s", task.task_id, exc)


def ingest_molizhishu_callback(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    """
    处理模力 Callback。
    2026-07-27 - 回调接收端未落地 - 幂等写 geo_monitor_callback_event + 复用 upsert/排名补算
    - 同 payload_hash 幂等：直接成功
    - 未知 taskId：记 ignored 并 2xx，避免对方无限重试
    """
    if not isinstance(payload, dict) or not payload:
        raise ValueError("回调体必须是非空 JSON 对象")

    task_id = str(payload.get("taskId") or "").strip()
    if not task_id:
        raise ValueError("回调缺少 taskId")

    digest = _payload_hash(payload)
    existing = db.scalar(
        select(GeoMonitorCallbackEvent).where(GeoMonitorCallbackEvent.payload_hash == digest)
    )
    if existing is not None:
        return {
            "task_id": task_id,
            "status": "duplicate",
            "process_status": existing.process_status,
            "event_id": existing.id,
        }

    event = GeoMonitorCallbackEvent(
        task_id=task_id,
        payload_hash=digest,
        process_status="received",
        payload_json=payload,
        received_at=datetime.now(),
    )
    db.add(event)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raced = db.scalar(
            select(GeoMonitorCallbackEvent).where(GeoMonitorCallbackEvent.payload_hash == digest)
        )
        if raced is not None:
            return {
                "task_id": task_id,
                "status": "duplicate",
                "process_status": raced.process_status,
                "event_id": raced.id,
            }
        raise

    task = _load_task(db, task_id)
    if task is None:
        event.process_status = "ignored"
        event.error_message = "本地无此任务"
        event.processed_at = datetime.now()
        db.commit()
        logger.warning("molizhishu callback ignored unknown task_id=%s", task_id)
        return {
            "task_id": task_id,
            "status": "ignored",
            "process_status": "ignored",
            "event_id": event.id,
        }

    try:
        _apply_callback_payload(db, task, payload)
        event.process_status = "processed"
        event.error_message = None
        event.processed_at = datetime.now()
        db.commit()
    except Exception as exc:
        db.rollback()
        # 重新附着事件行并标记失败；仍向上抛，由 endpoint 决定是否 5xx 触发对方重试
        event = db.scalar(
            select(GeoMonitorCallbackEvent).where(GeoMonitorCallbackEvent.payload_hash == digest)
        )
        if event is None:
            event = GeoMonitorCallbackEvent(
                task_id=task_id,
                payload_hash=digest,
                process_status="failed",
                payload_json=payload,
                error_message=str(exc)[:2000],
                received_at=datetime.now(),
                processed_at=datetime.now(),
            )
            db.add(event)
        else:
            event.process_status = "failed"
            event.error_message = str(exc)[:2000]
            event.processed_at = datetime.now()
        db.commit()
        raise

    _post_commit_side_effects(db, task)
    return {
        "task_id": task_id,
        "status": "processed",
        "process_status": "processed",
        "event_id": event.id,
        "task_status": task.status,
    }
