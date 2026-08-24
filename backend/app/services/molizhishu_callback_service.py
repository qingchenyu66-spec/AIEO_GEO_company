"""模力指数 Webhook 回调：鉴权、幂等、落库。

2026-08-21 - 稳定性桌面方案①：HTTP 只验签落事件+入队，重活进 Celery sync 队列
"""

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
    # 2026-08-21 - 稳定性④：回调后统一日统计+失效+作废窗口快照
    from app.services.monitor_mutation_service import after_monitor_data_change

    after_monitor_data_change(
        db,
        tenant_id=task.tenant_id,
        task_id=task.task_id,
        bust_overview=False,
    )
    try:
        from app.services.brand_analysis_service import parse_sentiments_after_brand_word_sync

        parse_sentiments_after_brand_word_sync(db, task)
    except Exception as exc:
        logger.warning("callback brand_word sentiment failed task_id=%s error=%s", task.task_id, exc)


def _duplicate_result(event: GeoMonitorCallbackEvent, task_id: str) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "status": "duplicate",
        "process_status": event.process_status,
        "event_id": event.id,
    }


def _create_or_get_callback_event(
    db: Session,
    *,
    task_id: str,
    digest: str,
    payload: dict[str, Any],
) -> tuple[GeoMonitorCallbackEvent, bool]:
    """返回 (event, created)。created=False 表示同 hash 已存在（幂等）。"""
    existing = db.scalar(
        select(GeoMonitorCallbackEvent).where(GeoMonitorCallbackEvent.payload_hash == digest)
    )
    if existing is not None:
        return existing, False

    event = GeoMonitorCallbackEvent(
        task_id=task_id,
        payload_hash=digest,
        process_status="queued",
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
            return raced, False
        raise
    return event, True


def process_molizhishu_callback_event(db: Session, event_id: int) -> dict[str, Any]:
    """按事件 ID 执行落库/排名/日统计（供 Celery 或同步兜底）。"""
    event = db.get(GeoMonitorCallbackEvent, event_id)
    if event is None:
        raise ValueError(f"回调事件不存在: {event_id}")

    task_id = str(event.task_id or "").strip()
    if event.process_status in {"processed", "ignored"}:
        return {
            "task_id": task_id,
            "status": event.process_status,
            "process_status": event.process_status,
            "event_id": event.id,
        }

    payload = event.payload_json if isinstance(event.payload_json, dict) else {}
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
        event = db.get(GeoMonitorCallbackEvent, event_id)
        if event is None:
            raise
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


def _enqueue_callback_event(event_id: int, task_id: str) -> bool:
    """投递 Celery；成功 True。失败由调用方同步兜底。"""
    from app.tasks.monitor import process_molizhishu_callback_task

    celery_task_id = f"molizhishu-callback-{event_id}"
    try:
        process_molizhishu_callback_task.apply_async(
            kwargs={"event_id": int(event_id)},
            task_id=celery_task_id,
        )
        return True
    except Exception as exc:
        message = str(exc).lower()
        if "already exists" in message or "duplicate" in message:
            return True
        logger.warning(
            "enqueue molizhishu callback failed event_id=%s task_id=%s error=%s",
            event_id,
            task_id,
            exc,
        )
        return False


def accept_molizhishu_callback(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    """HTTP 快路径：验过 token 后写事件并入队；Celery 关/入队失败则同步处理。"""
    if not isinstance(payload, dict) or not payload:
        raise ValueError("回调体必须是非空 JSON 对象")

    task_id = str(payload.get("taskId") or "").strip()
    if not task_id:
        raise ValueError("回调缺少 taskId")

    digest = _payload_hash(payload)
    event, created = _create_or_get_callback_event(
        db, task_id=task_id, digest=digest, payload=payload
    )
    if not created:
        db.commit()
        return _duplicate_result(event, task_id)

    # 未知任务：当场忽略，不占队列
    if _load_task(db, task_id) is None:
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

    db.commit()

    if settings.celery_enabled and _enqueue_callback_event(event.id, task_id):
        return {
            "task_id": task_id,
            "status": "accepted",
            "process_status": "queued",
            "event_id": event.id,
        }

    # Celery 关闭或入队失败：同步兜底，避免丢回调
    return process_molizhishu_callback_event(db, event.id)


def ingest_molizhishu_callback(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    """同步完整处理（单测/运维兜底）；生产 HTTP 走 accept_molizhishu_callback。"""
    if not isinstance(payload, dict) or not payload:
        raise ValueError("回调体必须是非空 JSON 对象")

    task_id = str(payload.get("taskId") or "").strip()
    if not task_id:
        raise ValueError("回调缺少 taskId")

    digest = _payload_hash(payload)
    event, created = _create_or_get_callback_event(
        db, task_id=task_id, digest=digest, payload=payload
    )
    if not created:
        return _duplicate_result(event, task_id)

    db.commit()
    return process_molizhishu_callback_event(db, event.id)
