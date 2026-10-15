"""缓存 snapshot 仍报 Worker 离线时, 仪表盘须按实时探测对齐告警."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from app.core.celery_queue_monitor import format_celery_monitor_zh


def _live_runtime(*, workers_online: int) -> dict[str, Any]:
    names = [f"submit@host", f"sync@host", f"default@host", f"backfill@host"][:workers_online]
    return {
        "active": [],
        "reserved": [],
        "active_count": 0,
        "reserved_count": 0,
        "workers_online": workers_online,
        "worker_names": names,
        "submit_workers": 1 if workers_online else 0,
        "sync_workers": 1 if workers_online else 0,
        "has_submit_queue": workers_online > 0,
        "has_sync_queue": workers_online > 0,
        "queue_names": ["submit", "sync"] if workers_online else [],
    }


def test_format_drops_stale_worker_offline_alert_when_workers_online() -> None:
    stale_snapshot = {
        "checked_at": "2026-10-15T01:00:00+00:00",
        "queues": {
            "submit": {"queued": 0, "warning_threshold": 20, "critical_threshold": 50},
            "sync": {"queued": 0, "warning_threshold": 20, "critical_threshold": 50},
        },
        "workers": {"workers_online": 0, "worker_names": []},
        "alerts": [
            {
                "queue": "workers",
                "level": "critical",
                "title": "Celery Worker 离线",
                "message": "未检测到在线 Worker，队列任务将无法消费",
                "queued": 0,
                "threshold": 0,
            }
        ],
        "flower_url": None,
    }

    with (
        patch("app.core.celery_queue_monitor.settings.celery_enabled", True),
        patch(
            "app.core.celery_queue_monitor._collect_runtime_tasks",
            return_value=_live_runtime(workers_online=4),
        ),
        patch("app.core.celery_queue_monitor._get_beat_history", return_value=[]),
        patch("app.core.celery_queue_monitor._collect_pending_sync_details", return_value=[]),
        patch("app.core.celery_queue_monitor.get_sync_live", return_value=None),
        patch(
            "app.core.celery_queue_monitor._collect_ops_insights",
            return_value={
                "scheduler_ok": True,
                "scheduler_status": "正常",
                "scheduler_detail": "4 个进程在线 · 提交/同步已就绪",
                "workers_online": 4,
                "pending_sync_tasks": 0,
                "today_scan_count": 0,
                "today_enqueued_tasks": 0,
                "last_due_scan": None,
            },
        ),
    ):
        payload = format_celery_monitor_zh(stale_snapshot)

    assert payload["workers"]["online_count"] == 4
    assert payload["workers"]["status"] == "在线"
    assert not any(item.get("queue") == "workers" for item in payload["alerts"])
    assert payload["alert_count"] == 0


def test_format_keeps_worker_offline_alert_when_still_offline() -> None:
    stale_snapshot = {
        "checked_at": "2026-10-15T01:00:00+00:00",
        "queues": {
            "submit": {"queued": 0, "warning_threshold": 20, "critical_threshold": 50},
        },
        "workers": {"workers_online": 0, "worker_names": []},
        "alerts": [],
        "flower_url": None,
    }

    with (
        patch("app.core.celery_queue_monitor.settings.celery_enabled", True),
        patch(
            "app.core.celery_queue_monitor._collect_runtime_tasks",
            return_value=_live_runtime(workers_online=0),
        ),
        patch("app.core.celery_queue_monitor._get_beat_history", return_value=[]),
        patch("app.core.celery_queue_monitor._collect_pending_sync_details", return_value=[]),
        patch("app.core.celery_queue_monitor.get_sync_live", return_value=None),
        patch(
            "app.core.celery_queue_monitor._collect_ops_insights",
            return_value={
                "scheduler_ok": False,
                "scheduler_status": "离线",
                "scheduler_detail": "未检测到 Worker",
                "workers_online": 0,
                "pending_sync_tasks": 0,
                "today_scan_count": 0,
                "today_enqueued_tasks": 0,
                "last_due_scan": None,
            },
        ),
    ):
        payload = format_celery_monitor_zh(stale_snapshot)

    assert payload["workers"]["status"] == "离线"
    assert any(item.get("queue") == "workers" for item in payload["alerts"])
