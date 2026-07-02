"""Operational monitoring tasks."""

from __future__ import annotations

import logging
from typing import Any

from app.celery_app import celery_app
from app.core.celery_queue_monitor import collect_queue_stats, evaluate_queue_alerts, record_beat_scan

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
