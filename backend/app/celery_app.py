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
        "app.tasks.monitor.scan_due_brand_word_weekly": {"queue": "submit"},
        "app.tasks.monitor.submit_lead_diagnosis_run": {"queue": "submit"},
        "app.tasks.monitor.finalize_lead_diagnoses": {"queue": "default"},
        "app.tasks.monitor.scan_pending_syncs": {"queue": "sync"},
        "app.tasks.monitor.sync_one_monitor_task": {"queue": "sync"},
        "app.tasks.monitoring.check_queue_backlog": {"queue": "sync"},
        "app.tasks.monitor.scan_due_scheduled_reports": {"queue": "default"},
        "app.tasks.monitor.expire_overdue_tenant_services": {"queue": "default"},
        "app.tasks.monitor.sync_platform_catalog_daily": {"queue": "default"},
        "app.tasks.monitor.check_platform_availability_weekly": {"queue": "submit"},
        "app.tasks.monitor.finalize_platform_probes": {"queue": "sync"},
        "app.tasks.knowledge.parse_knowledge_file_task": {"queue": "default"},
        "app.tasks.knowledge.fail_stale_knowledge_parses": {"queue": "default"},
    },
    beat_schedule={
        "scan-due-schedules": {
            "task": "app.tasks.monitor.scan_due_schedules",
            "schedule": crontab(minute="*/5", hour="9-20"),
            "kwargs": {"max_prompts": settings.celery_scan_submit_max_prompts},
        },
        "scan-due-brand-word-weekly": {
            "task": "app.tasks.monitor.scan_due_brand_word_weekly",
            "schedule": crontab(hour=9, minute=0, day_of_week="1"),
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
        "scan-due-scheduled-reports": {
            "task": "app.tasks.monitor.scan_due_scheduled_reports",
            "schedule": crontab(hour=0, minute=5),
        },
        "expire-overdue-tenant-services": {
            "task": "app.tasks.monitor.expire_overdue_tenant_services",
            "schedule": crontab(hour=0, minute=10),
        },
        "sync-platform-catalog-daily": {
            "task": "app.tasks.monitor.sync_platform_catalog_daily",
            "schedule": crontab(hour=3, minute=15),
        },
        "check-platform-availability-weekly": {
            "task": "app.tasks.monitor.check_platform_availability_weekly",
            "schedule": crontab(hour=4, minute=30, day_of_week="1"),
        },
        "finalize-platform-probes": {
            "task": "app.tasks.monitor.finalize_platform_probes",
            "schedule": crontab(minute="*/20"),
        },
        "fail-stale-knowledge-parses": {
            "task": "app.tasks.knowledge.fail_stale_knowledge_parses",
            "schedule": crontab(minute="*/5"),
        },
        "refresh-ops-overview-rollup": {
            "task": "app.tasks.monitor.refresh_ops_overview_rollup",
            "schedule": crontab(minute="*/5"),
        },
    },
)

celery_app.autodiscover_tasks(["app.tasks"])

import app.tasks.monitor  # noqa: E402, F401
import app.tasks.monitoring  # noqa: E402, F401
import app.tasks.knowledge  # noqa: E402, F401
