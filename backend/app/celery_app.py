"""Celery application for GEO monitor scheduling and sync workers."""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery_app = Celery("geo_monitor")

# 2026-09-02 - 本地无 requirepass 时勿带着密码连 broker（否则 delay 报 Client sent AUTH）
try:
    from app.core.redis_client import redis_url_without_auth
    from redis import Redis
    from redis.exceptions import RedisError

    _broker = settings.celery_broker_url
    _backend = settings.celery_result_backend
    try:
        _probe = Redis.from_url(_broker, socket_connect_timeout=1.5, socket_timeout=1.5)
        _probe.ping()
        _probe.close()
    except RedisError as _exc:
        if "auth" in str(_exc).lower() or "no password is set" in str(_exc).lower():
            _broker = redis_url_without_auth(_broker)
            _backend = redis_url_without_auth(_backend)
except Exception:
    _broker = settings.celery_broker_url
    _backend = settings.celery_result_backend

celery_app.conf.update(
    broker_url=_broker,
    result_backend=_backend,
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
        "app.tasks.monitor.scan_stale_schedule_submits": {"queue": "submit"},
        "app.tasks.monitor.submit_lead_diagnosis_run": {"queue": "submit"},
        "app.tasks.monitor.finalize_lead_diagnoses": {"queue": "default"},
        "app.tasks.monitor.scan_pending_syncs": {"queue": "sync"},
        "app.tasks.monitor.sync_one_monitor_task": {"queue": "sync"},
        "app.tasks.monitor.process_molizhishu_callback_task": {"queue": "sync"},
        "app.tasks.monitor.build_ranking_matrix_job_task": {"queue": "default"},
        "app.tasks.monitoring.check_queue_backlog": {"queue": "sync"},
        "app.tasks.monitoring.warm_window_snapshots": {"queue": "default"},
        "app.tasks.monitor.scan_due_scheduled_reports": {"queue": "default"},
        "app.tasks.monitor.expire_overdue_tenant_services": {"queue": "default"},
        "app.tasks.monitor.activate_due_tenants_and_kick_brand_words": {"queue": "submit"},
        "app.tasks.monitor.kick_brand_word_service_start": {"queue": "submit"},
        "app.tasks.monitor.scan_tenant_expiry_notifications": {"queue": "default"},
        "app.tasks.monitor.sync_platform_catalog_daily": {"queue": "default"},
        "app.tasks.monitor.check_platform_availability_weekly": {"queue": "submit"},
        "app.tasks.monitor.finalize_platform_probes": {"queue": "sync"},
        "app.tasks.monitor.refresh_ops_overview_rollup": {"queue": "default"},
        "app.tasks.monitor.sync_announcement_lifecycle": {"queue": "default"},
        "app.tasks.monitor.scan_stale_credit_reserves": {"queue": "default"},
        "app.tasks.monitor.refresh_credit_window_estimate": {"queue": "default"},
        "app.tasks.monitor.apply_scheduled_billing_mode_changes": {"queue": "default"},
        "app.tasks.monitor.scan_credit_three_day_shortfall": {"queue": "default"},
        "app.tasks.knowledge.parse_knowledge_file_task": {"queue": "default"},
        "app.tasks.knowledge.fail_stale_knowledge_parses": {"queue": "default"},
        # 2026-09-02 - Playwright 解析/截图独立队列 - 勿与报表/知识库抢 default
        "app.tasks.snapshot_backfill.capture_backfill_screenshot_task": {"queue": "backfill"},
        "app.tasks.snapshot_backfill.parse_and_apply_backfill_task": {"queue": "backfill"},
        "app.tasks.snapshot_backfill.fail_stale_backfill_parses_task": {"queue": "default"},
        "app.tasks.snapshot_backfill.refresh_source_daily_after_backfill_task": {"queue": "default"},
        "app.tasks.report_source_value.pregenerate_source_value_task": {"queue": "default"},
        "app.tasks.report_source_value.scan_source_value_pregenerate": {"queue": "default"},
    },
    beat_schedule={
        "scan-due-schedules": {
            "task": "app.tasks.monitor.scan_due_schedules",
            # 7×24：按企业配置的任意 schedule_times 触发（含周末/凌晨）
            "schedule": crontab(minute="*/5"),
            "kwargs": {"max_prompts": settings.celery_scan_submit_max_prompts},
        },
        # 2026-09-07 - 死锁/异常留下的陈旧 running：窗口外也能补投或清尸
        "scan-stale-schedule-submits": {
            "task": "app.tasks.monitor.scan_stale_schedule_submits",
            "schedule": crontab(minute="*/5"),
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
        "warm-window-snapshots": {
            "task": "app.tasks.monitoring.warm_window_snapshots",
            # 2026-08-21 - 稳定性⑤：每小时预热近 7/30 日工作台快照
            "schedule": crontab(minute=20),
            "kwargs": {"limit": 80},
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
        "activate-due-tenants-and-kick-brand-words": {
            "task": "app.tasks.monitor.activate_due_tenants_and_kick_brand_words",
            # 2026-08-03 - 服务开始日 00:15 启用企业并开跑品牌词首轮
            "schedule": crontab(hour=0, minute=15),
        },
        "scan-tenant-expiry-notifications": {
            "task": "app.tasks.monitor.scan_tenant_expiry_notifications",
            "schedule": crontab(hour=0, minute=20),
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
        # 2026-09-02 - 补录解析 pending 硬杀/超时兜底
        "fail-stale-backfill-parses": {
            "task": "app.tasks.snapshot_backfill.fail_stale_backfill_parses_task",
            "schedule": crontab(minute="*/2"),
        },
        "scan-source-value-pregenerate": {
            "task": "app.tasks.report_source_value.scan_source_value_pregenerate",
            # 每日 22:00 预热，赶在 00:05 周期报生成前
            "schedule": crontab(hour=22, minute=0),
            "kwargs": {"max_tenants": 40},
        },
        "refresh-ops-overview-rollup": {
            "task": "app.tasks.monitor.refresh_ops_overview_rollup",
            "schedule": crontab(minute="*/5"),
        },
        "sync-announcement-lifecycle": {
            "task": "app.tasks.monitor.sync_announcement_lifecycle",
            "schedule": crontab(minute="*/1"),
        },
        # 2026-09-04 - 算力自助三定时 + 模式落地独立（A+C）- 此前只写了 task 未进 beat
        "scan-stale-credit-reserves": {
            "task": "app.tasks.monitor.scan_stale_credit_reserves",
            "schedule": crontab(minute="*/5"),
        },
        "refresh-credit-window-estimate": {
            "task": "app.tasks.monitor.refresh_credit_window_estimate",
            "schedule": crontab(minute="*/15"),
        },
        # 2026-09-09 - A甲：next_window 仅监测提交落地，不再每 5 分钟挂空跑 beat
        # （任务 apply_scheduled_billing_mode_changes 仍保留，供手工/兼容调用）
        # 2026-09-08 - 条款不硬确认，已移除 scan-credit-terms-reminders beat
        # 2026-09-08 - 方案甲：可用 < 日预估×3 通知企业（每日一次去重）
        "scan-credit-three-day-shortfall": {
            "task": "app.tasks.monitor.scan_credit_three_day_shortfall",
            "schedule": crontab(hour=9, minute=40),
        },
    },
)

celery_app.autodiscover_tasks(["app.tasks"])

import app.tasks.monitor  # noqa: E402, F401
import app.tasks.monitoring  # noqa: E402, F401
import app.tasks.knowledge  # noqa: E402, F401
import app.tasks.snapshot_backfill  # noqa: E402, F401
import app.tasks.report_source_value  # noqa: E402, F401

try:
    from celery.signals import worker_process_init, worker_ready
except Exception:  # pragma: no cover
    worker_process_init = None  # type: ignore[assignment]
    worker_ready = None  # type: ignore[assignment]


def _fix_windows_playwright_loop(**_kwargs) -> None:
    # 2026-09-02 - Worker 进程启动即切 Proactor，避免补录 Playwright NotImplementedError
    try:
        from app.services.share_page_fetch_service import _ensure_windows_playwright_event_loop

        _ensure_windows_playwright_event_loop()
    except Exception:
        pass


if worker_process_init is not None:
    worker_process_init.connect(_fix_windows_playwright_loop, weak=False)
if worker_ready is not None:
    worker_ready.connect(_fix_windows_playwright_loop, weak=False)
