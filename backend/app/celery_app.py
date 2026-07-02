"""Celery application for GEO monitor scheduling and sync workers."""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery_app = Celery("geo_monitor")

celery_app.conf.update(
    broker_url=settings.celery_broker_url,
    result_backend=settings.celery_result_backend,
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Shanghai",
    enable_utc=False,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_track_started=True,
    broker_connection_retry_on_startup=True,
    task_default_queue="default",
    task_routes={
        "app.tasks.monitor.scan_due_schedules": {"queue": "submit"},
        "app.tasks.monitor.submit_lead_diagnosis_run": {"queue": "submit"},
        "app.tasks.monitor.finalize_lead_diagnoses": {"queue": "default"},
        "app.tasks.monitor.scan_pending_syncs": {"queue": "sync"},
        "app.tasks.monitor.sync_one_monitor_task": {"queue": "sync"},
        "app.tasks.monitoring.check_queue_backlog": {"queue": "sync"},
        "app.tasks.knowledge.parse_knowledge_file_task": {"queue": "default"},
    },
    beat_schedule={
        "scan-due-schedules": {
            "task": "app.tasks.monitor.scan_due_schedules",
            "schedule": crontab(minute="*/5", hour="9-20"),
            "kwargs": {"max_prompts": settings.celery_scan_submit_max_prompts},
        },
        "scan-pending-syncs": {
            "task": "app.tasks.monitor.scan_pending_syncs",
            "schedule": crontab(minute="*"),
            "kwargs": {
                "limit": settings.celery_sync_batch_limit,
                "terminal_grace_hours": settings.celery_sync_terminal_grace_hours,
            },
        },
        "check-queue-backlog": {
            "task": "app.tasks.monitoring.check_queue_backlog",
            "schedule": crontab(minute="*/5"),
        },
        "scan-due-lead-diagnosis": {
            "task": "app.tasks.monitor.scan_due_lead_diagnosis",
            "schedule": crontab(minute="*/5", hour="9-21"),
        },
        "finalize-lead-diagnoses": {
            "task": "app.tasks.monitor.finalize_lead_diagnoses",
            "schedule": crontab(minute="*/10", hour="9-22"),
        },
    },
)

celery_app.autodiscover_tasks(["app.tasks"])

import app.tasks.monitor  # noqa: E402, F401
import app.tasks.monitoring  # noqa: E402, F401
import app.tasks.knowledge  # noqa: E402, F401
