"""Operational monitoring tasks."""

from __future__ import annotations

import logging
from typing import Any

from app.celery_app import celery_app
from app.core.celery_queue_monitor import collect_queue_stats, evaluate_queue_alerts, record_beat_scan
from app.core.config import settings
from app.core.database import SessionLocal

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.monitoring.check_queue_backlog", ignore_result=True)
def check_queue_backlog() -> dict[str, Any]:
    """Check Celery queue depth and emit backlog alerts."""
    snapshot = collect_queue_stats()
    alerts = evaluate_queue_alerts(snapshot, persist=True)
    logger.info(
        "check_queue_backlog submit=%s sync=%s workers=%s alerts=%s",
        snapshot["queues"]["submit"]["queued"],
        snapshot["queues"]["sync"]["queued"],
        snapshot["workers"]["workers_online"],
        len(alerts),
    )
    result = {
        "status": "ok",
        "alert_count": len(alerts),
        "queues": snapshot["queues"],
        "workers_online": snapshot["workers"]["workers_online"],
    }
    record_beat_scan("app.tasks.monitoring.check_queue_backlog", result)
    return result


@celery_app.task(name="app.tasks.monitoring.warm_window_snapshots", ignore_result=True)
def warm_window_snapshots(limit: int = 80) -> dict[str, Any]:
    """每小时预热活跃企业近 7/30 日工作台窗口快照。"""
    if not settings.celery_enabled:
        return {"status": "disabled"}

    from app.services.window_snapshot_service import (
        list_active_tenant_ids_for_warmup,
        warm_window_snapshots_for_tenant,
    )

    db = SessionLocal()
    warmed = 0
    failed = 0
    tenant_count = 0
    try:
        tenant_ids = list_active_tenant_ids_for_warmup(db, limit=limit)
        tenant_count = len(tenant_ids)
        for tenant_id in tenant_ids:
            out = warm_window_snapshots_for_tenant(db, tenant_id)
            warmed += int(out.get("warmed") or 0)
            failed += int(out.get("failed") or 0)
    finally:
        db.close()

    result = {
        "status": "ok",
        "tenants": tenant_count,
        "warmed": warmed,
        "failed": failed,
    }
    record_beat_scan("app.tasks.monitoring.warm_window_snapshots", result)
    return result
