"""Celery queue depth monitoring and backlog alerts."""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import Any

import httpx
from redis.exceptions import RedisError

from app.core.config import settings
from app.core.redis_client import get_json_cache, get_redis_client, prefixed_key, set_json_cache

logger = logging.getLogger(__name__)

# 2026-08-27 - 纳入 default（矩阵异步构建等），便于运营看积压
# 2026-09-02 - 纳入 backfill（Playwright 解析/截图）
QUEUE_NAMES = ("submit", "sync", "default", "backfill")
ALERT_LOG = "celery-alerts"
BEAT_HISTORY_KEY = "celery:beat:history"
BEAT_HISTORY_MAX = 15
SYNC_LIVE_KEY = "celery:sync:live"

TASK_LABELS: dict[str, str] = {
    "app.tasks.monitor.scan_due_schedules": "扫描到点监测计划",
    "app.tasks.monitor.scan_stale_schedule_submits": "回收陈旧调度提交",
    "app.tasks.monitor.submit_schedule_group": "提交监测词组",
    "app.tasks.monitor.scan_pending_syncs": "扫描待同步任务",
    "app.tasks.monitor.sync_one_monitor_task": "同步监测结果",
    "app.tasks.monitoring.check_queue_backlog": "检查队列积压",
    "app.tasks.monitor.build_ranking_matrix_job_task": "排名矩阵异步构建",
    "app.tasks.snapshot_backfill.parse_and_apply_backfill_task": "补录分享页解析",
    "app.tasks.snapshot_backfill.fail_stale_backfill_parses_task": "补录解析超时清理",
}

BEAT_TASK_KEYS = frozenset(TASK_LABELS.keys())

BUSINESS_METRIC_LABELS: dict[str, str] = {
    "ranking_drop": "排名下滑",
    "negative_rate": "负面占比",
    "task_failure_rate": "任务失败率",
    "molizhishu_balance": "账户余额",
}

TECHNICAL_METRIC_LABELS: dict[str, str] = {
    "celery_queue_submit": "提交队列积压",
    "celery_queue_sync": "同步队列积压",
    "celery_queue_default": "默认队列积压",
    "celery_queue_backfill": "补录解析队列积压",
}

QUEUE_METRIC_BY_NAME = {
    "submit": "celery_queue_submit",
    "sync": "celery_queue_sync",
    "default": "celery_queue_default",
    "backfill": "celery_queue_backfill",
}

_THRESHOLD_CACHE: dict[str, int] = {}
_THRESHOLD_CACHE_EXPIRES_AT = 0.0
_THRESHOLD_CACHE_TTL_SECONDS = 30

TECHNICAL_METRIC_PREFIXES = ("celery_",)


def _broker_client():
    if not settings.celery_enabled:
        return None
    try:
        from redis import Redis
        from redis.exceptions import RedisError

        from app.core.redis_client import _is_auth_redis_error, redis_url_without_auth

        url = settings.celery_broker_url
        client = Redis.from_url(
            url,
            decode_responses=True,
            socket_timeout=settings.redis_socket_timeout_seconds,
            socket_connect_timeout=settings.redis_socket_timeout_seconds,
        )
        try:
            client.ping()
        except RedisError as exc:
            if not _is_auth_redis_error(exc):
                raise
            client.close()
            client = Redis.from_url(
                redis_url_without_auth(url),
                decode_responses=True,
                socket_timeout=settings.redis_socket_timeout_seconds,
                socket_connect_timeout=settings.redis_socket_timeout_seconds,
            )
            client.ping()
        return client
    except Exception as exc:
        logger.warning("Celery broker client unavailable: %s", exc)
        return None


def _queue_length(client, queue_name: str) -> int:
    try:
        return int(client.llen(queue_name) or 0)
    except RedisError:
        return 0


_RUNTIME_INSPECT_CACHE: dict[str, Any] | None = None
_RUNTIME_INSPECT_CACHE_AT = 0.0
_RUNTIME_INSPECT_CACHE_TTL_SECONDS = 10.0


def _worker_role_from_name(worker_name: str) -> str:
    """Celery -n 形如 submit@HOST；取 @ 前缀比子串匹配更稳。"""
    prefix = str(worker_name or "").split("@", 1)[0].strip().lower()
    if prefix in {"submit", "sync", "default", "backfill", "beat"}:
        return prefix
    lowered = worker_name.lower()
    if "submit" in lowered:
        return "submit"
    if "sync" in lowered:
        return "sync"
    if "backfill" in lowered:
        return "backfill"
    return "default"


def _coverage_from_worker_names(worker_names: list[str]) -> dict[str, Any]:
    submit_workers = sum(1 for name in worker_names if _worker_role_from_name(name) == "submit")
    sync_workers = sum(1 for name in worker_names if _worker_role_from_name(name) == "sync")
    return {
        "submit_workers": submit_workers,
        "sync_workers": sync_workers,
        "has_submit_queue": submit_workers > 0,
        "has_sync_queue": sync_workers > 0,
    }


def _probe_celery_runtime() -> dict[str, Any]:
    """一次并行 inspect：ping + active_queues + active/reserved，减少 Windows 上重复超时。"""
    from concurrent.futures import ThreadPoolExecutor

    from app.celery_app import celery_app

    probe_timeout = max(2.0, float(settings.celery_inspect_timeout_seconds or 1.5))
    inspect = celery_app.control.inspect(timeout=probe_timeout)

    with ThreadPoolExecutor(max_workers=4) as pool:
        ping_future = pool.submit(lambda: celery_app.control.ping(timeout=probe_timeout) or [])
        queues_future = pool.submit(lambda: inspect.active_queues() or {})
        active_future = pool.submit(lambda: inspect.active() or {})
        reserved_future = pool.submit(lambda: inspect.reserved() or {})
        ping_rows = ping_future.result()
        active_queues = queues_future.result()
        active_map = active_future.result()
        reserved_map = reserved_future.result()

    ping_names = {
        name
        for item in ping_rows
        if isinstance(item, dict)
        for name in item
    }
    worker_names = sorted(set(active_queues.keys()) | ping_names)

    queue_names: set[str] = set()
    submit_workers = 0
    sync_workers = 0
    for worker, queues in active_queues.items():
        for queue in queues or []:
            if not isinstance(queue, dict):
                continue
            name = str(queue.get("name") or "").strip()
            if not name:
                continue
            queue_names.add(name)
            if name == "submit":
                submit_workers += 1
            elif name == "sync":
                sync_workers += 1

    name_coverage = _coverage_from_worker_names(worker_names)
    has_submit = "submit" in queue_names or name_coverage["has_submit_queue"]
    has_sync = "sync" in queue_names or name_coverage["has_sync_queue"]
    if submit_workers == 0 and name_coverage["submit_workers"] > 0:
        submit_workers = name_coverage["submit_workers"]
    if sync_workers == 0 and name_coverage["sync_workers"] > 0:
        sync_workers = name_coverage["sync_workers"]

    stats = {name: {} for name in ping_names}

    return {
        "active_map": active_map,
        "reserved_map": reserved_map,
        "stats": stats,
        "worker_names": worker_names,
        "workers_online": len(worker_names),
        "submit_workers": submit_workers,
        "sync_workers": sync_workers,
        "has_submit_queue": has_submit,
        "has_sync_queue": has_sync,
        "queue_names": sorted(queue_names),
        "inspect_queues_ok": bool(active_queues),
    }


def _inspect_snapshot() -> tuple[dict[str, list], dict[str, list], dict[str, Any]]:
    """兼容旧调用；内部走统一 probe。"""
    probe = _probe_celery_runtime()
    return probe["active_map"], probe["reserved_map"], probe["stats"]


def _inspect_worker_coverage(timeout: float | None = None) -> dict[str, Any]:
    """兼容旧调用；内部走统一 probe。"""
    del timeout
    probe = _probe_celery_runtime()
    return {
        "worker_names": probe["worker_names"],
        "workers_online": probe["workers_online"],
        "submit_workers": probe["submit_workers"],
        "sync_workers": probe["sync_workers"],
        "has_submit_queue": probe["has_submit_queue"],
        "has_sync_queue": probe["has_sync_queue"],
        "queue_names": probe["queue_names"],
        "inspect_queues_ok": probe["inspect_queues_ok"],
    }


def _scheduling_appears_healthy(beat_history: list[dict[str, Any]] | None) -> bool:
    """Beat 近期有成功扫描时，说明调度实际在跑（inspect 在 Windows 上可能误报）。"""
    if not beat_history:
        return False
    now = datetime.now(UTC)
    for item in beat_history[:12]:
        checked_raw = str(item.get("checked_at") or "")
        if not checked_raw:
            continue
        try:
            checked_at = datetime.fromisoformat(checked_raw.replace("Z", "+00:00"))
        except ValueError:
            continue
        if (now - checked_at).total_seconds() > 900:
            continue
        if item.get("task_key") not in BEAT_TASK_KEYS:
            continue
        if str(item.get("status") or "") in {"ok", "locked"}:
            return True
    return False


def _build_scheduler_insight(
    runtime: dict[str, Any],
    *,
    beat_history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    workers_online = int(runtime.get("workers_online") or 0)
    submit_workers = int(runtime.get("submit_workers") or 0)
    sync_workers = int(runtime.get("sync_workers") or 0)
    has_submit = bool(runtime.get("has_submit_queue"))
    has_sync = bool(runtime.get("has_sync_queue"))

    if not settings.celery_enabled:
        return {
            "scheduler_ok": None,
            "scheduler_status": "未启用",
            "scheduler_detail": "Celery 调度未开启",
            "workers_online": 0,
            "submit_workers": 0,
            "sync_workers": 0,
        }

    if workers_online == 0:
        return {
            "scheduler_ok": False,
            "scheduler_status": "离线",
            "scheduler_detail": "未检测到 Worker，请运行 backend\\scripts\\start_celery.ps1 -Role all",
            "workers_online": 0,
            "submit_workers": 0,
            "sync_workers": 0,
        }

    if has_submit and has_sync:
        return {
            "scheduler_ok": True,
            "scheduler_status": "正常",
            "scheduler_detail": f"{workers_online} 个进程在线 · 提交/同步已就绪",
            "workers_online": workers_online,
            "submit_workers": submit_workers,
            "sync_workers": sync_workers,
        }

    if workers_online > 0 and _scheduling_appears_healthy(beat_history):
        missing: list[str] = []
        if not has_submit:
            missing.append("提交")
        if not has_sync:
            missing.append("同步")
        hint = f"（探测未确认{'/'.join(missing)}进程，Beat 扫描正常）" if missing else ""
        return {
            "scheduler_ok": True,
            "scheduler_status": "正常",
            "scheduler_detail": f"调度运行中 · {workers_online} 进程在线{hint}",
            "workers_online": workers_online,
            "submit_workers": submit_workers,
            "sync_workers": sync_workers,
        }

    hints: list[str] = []
    if not has_submit:
        hints.append("未检测到提交进程")
    if not has_sync:
        hints.append("未检测到同步进程")
    return {
        "scheduler_ok": False,
        "scheduler_status": "需关注",
        "scheduler_detail": f"{' · '.join(hints)}（{workers_online} 进程在线）",
        "workers_online": workers_online,
        "submit_workers": submit_workers,
        "sync_workers": sync_workers,
    }


def _task_detail_text(name: str, kwargs: dict[str, Any]) -> str:
    if name == "app.tasks.monitor.submit_schedule_group":
        tenant_id = kwargs.get("tenant_id")
        keyword = kwargs.get("keyword") or kwargs.get("group_key")
        parts = [f"企业 #{tenant_id}" if tenant_id else None, str(keyword) if keyword else None]
        return " · ".join(item for item in parts if item) or "提交词组任务"
    if name == "app.tasks.monitor.sync_one_monitor_task":
        task_id = kwargs.get("task_id")
        if task_id:
            text = str(task_id)
            return f"监测任务 {text[:8]}…{text[-4:]}" if len(text) > 16 else f"监测任务 {text}"
        return "同步监测主任务"
    if name == "app.tasks.monitor.scan_pending_syncs":
        live = get_sync_live()
        if live:
            tenant = live.get("tenant_name") or (f"企业 #{live.get('tenant_id')}" if live.get("tenant_id") else None)
            keywords = live.get("monitor_keywords")
            pending = live.get("pending_platforms") or []
            parts = [part for part in (tenant, keywords) if part]
            if pending:
                parts.append(f"待完成平台：{'、'.join(pending[:4])}")
            return " · ".join(parts) if parts else "正在批量同步监测结果"
        return "批量同步待完成监测任务"
    if name == "app.tasks.monitor.scan_due_schedules":
        return "Beat 调度扫描"
    if name == "app.tasks.monitoring.check_queue_backlog":
        return "队列健康检查"
    return TASK_LABELS.get(name, name.rsplit(".", 1)[-1])


def _format_runtime_task(task: dict[str, Any], worker: str, phase: str) -> dict[str, Any]:
    name = str(task.get("name") or task.get("type") or "")
    kwargs = task.get("kwargs") or {}
    if not isinstance(kwargs, dict):
        kwargs = {}
    time_start = task.get("time_start")
    started_at = None
    if isinstance(time_start, (int, float)) and time_start > 0:
        started_at = datetime.fromtimestamp(time_start, tz=UTC).isoformat()
    return {
        "task_id": task.get("id"),
        "task_key": name,
        "label": TASK_LABELS.get(name, name.rsplit(".", 1)[-1] if name else "未知任务"),
        "detail": _task_detail_text(name, kwargs),
        "worker": worker,
        "worker_role": _worker_role_label(worker),
        "phase": phase,
        "phase_label": "执行中" if phase == "active" else "已预取待执行",
        "started_at": started_at,
    }


def _collect_runtime_tasks() -> dict[str, Any]:
    global _RUNTIME_INSPECT_CACHE, _RUNTIME_INSPECT_CACHE_AT

    if not settings.celery_enabled:
        return {
            "active": [],
            "reserved": [],
            "active_count": 0,
            "reserved_count": 0,
            "workers_online": 0,
            "worker_names": [],
        }

    now = time.time()
    if (
        _RUNTIME_INSPECT_CACHE is not None
        and now - _RUNTIME_INSPECT_CACHE_AT < _RUNTIME_INSPECT_CACHE_TTL_SECONDS
    ):
        return _RUNTIME_INSPECT_CACHE

    try:
        probe = _probe_celery_runtime()
    except Exception as exc:
        logger.debug("Celery inspect unavailable: %s", exc)
        return {
            "active": [],
            "reserved": [],
            "active_count": 0,
            "reserved_count": 0,
            "workers_online": 0,
            "worker_names": [],
            "submit_workers": 0,
            "sync_workers": 0,
            "has_submit_queue": False,
            "has_sync_queue": False,
            "queue_names": [],
        }

    active_map = probe["active_map"]
    reserved_map = probe["reserved_map"]
    stats = probe["stats"]

    active_rows: list[dict[str, Any]] = []
    reserved_rows: list[dict[str, Any]] = []
    for worker, items in active_map.items():
        for item in items or []:
            active_rows.append(_format_runtime_task(item, worker, "active"))
    for worker, items in reserved_map.items():
        for item in items or []:
            reserved_rows.append(_format_runtime_task(item, worker, "reserved"))

    active_rows.sort(key=lambda row: row.get("started_at") or "", reverse=True)
    reserved_rows.sort(key=lambda row: (row.get("label") or "", row.get("worker") or ""))
    result = {
        "active": active_rows[:20],
        "reserved": reserved_rows[:20],
        "active_count": len(active_rows),
        "reserved_count": len(reserved_rows),
        "workers_online": probe["workers_online"] or len(stats),
        "worker_names": probe["worker_names"] or sorted(stats.keys()),
        "submit_workers": probe["submit_workers"],
        "sync_workers": probe["sync_workers"],
        "has_submit_queue": probe["has_submit_queue"],
        "has_sync_queue": probe["has_sync_queue"],
        "queue_names": probe["queue_names"],
    }
    _RUNTIME_INSPECT_CACHE = result
    _RUNTIME_INSPECT_CACHE_AT = now
    return result


def _worker_stats_from_runtime(runtime: dict[str, Any]) -> dict[str, Any]:
    return {
        "workers_online": runtime.get("workers_online", 0),
        "active_tasks": runtime.get("active_count", 0),
        "reserved_tasks": runtime.get("reserved_count", 0),
        "worker_names": runtime.get("worker_names", []),
    }


def _worker_stats() -> dict[str, Any]:
    return _worker_stats_from_runtime(_collect_runtime_tasks())


def record_beat_scan(task_key: str, result: dict[str, Any]) -> None:
    """Append a Beat/scan task summary for the operations dashboard."""
    if task_key not in BEAT_TASK_KEYS:
        return
    status = str(result.get("status") or "unknown")
    entry: dict[str, Any] = {
        "task_key": task_key,
        "label": TASK_LABELS.get(task_key, task_key),
        "status": status,
        "status_label": _beat_status_label(status),
        "checked_at": datetime.now(UTC).isoformat(),
        "enqueued": int(result.get("enqueued") or 0),
        "skipped": int(result.get("skipped") or 0),
        "alert_count": int(result.get("alert_count") or 0),
        "workers_online": result.get("workers_online"),
        "queues": result.get("queues"),
        "message": result.get("message"),
    }
    if task_key == "app.tasks.monitoring.check_queue_backlog":
        queues = result.get("queues") or {}
        submit_q = int((queues.get("submit") or {}).get("queued") or 0)
        sync_q = int((queues.get("sync") or {}).get("queued") or 0)
        entry["summary"] = f"提交队列 {submit_q} · 同步队列 {sync_q} · 告警 {entry['alert_count']} 条"
    elif task_key == "app.tasks.monitor.scan_due_schedules":
        entry["summary"] = f"入队 {entry['enqueued']} · 跳过 {entry['skipped']}"
    elif task_key == "app.tasks.monitor.scan_pending_syncs":
        synced = int(result.get("synced") or result.get("enqueued") or 0)
        failed = int(result.get("failed") or result.get("skipped") or 0)
        sync_details = result.get("sync_details") or []
        pending_platform_total = sum(len(item.get("pending_platforms") or []) for item in sync_details if isinstance(item, dict))
        entry["sync_details"] = sync_details[:8] if isinstance(sync_details, list) else []
        entry["summary"] = f"已同步 {synced} 个主任务" + (f"，失败 {failed}" if failed else "")
        if pending_platform_total:
            entry["summary"] += f" · 仍有 {pending_platform_total} 个平台排队"
    else:
        entry["summary"] = entry.get("message") or entry["status_label"]

    history = get_json_cache(BEAT_HISTORY_KEY) or []
    if not isinstance(history, list):
        history = []
    history.insert(0, entry)
    set_json_cache(BEAT_HISTORY_KEY, history[:BEAT_HISTORY_MAX], ttl_seconds=86400)


def _beat_status_label(status: str) -> str:
    mapping = {
        "ok": "成功",
        "locked": "跳过（已有扫描）",
        "disabled": "已禁用",
        "unknown": "未知",
    }
    return mapping.get(status, status)


def _get_beat_history() -> list[dict[str, Any]]:
    history = get_json_cache(BEAT_HISTORY_KEY) or []
    if not isinstance(history, list):
        return []
    return history[:BEAT_HISTORY_MAX]


def set_sync_live(payload: dict[str, Any] | None) -> None:
    """Publish the monitor task currently being synced (for live dashboard)."""
    if not payload:
        clear_sync_live()
        return
    set_json_cache(SYNC_LIVE_KEY, payload, ttl_seconds=120)


def clear_sync_live() -> None:
    set_json_cache(SYNC_LIVE_KEY, None, ttl_seconds=1)


def get_sync_live() -> dict[str, Any] | None:
    payload = get_json_cache(SYNC_LIVE_KEY)
    return payload if isinstance(payload, dict) else None


def _collect_pending_sync_details(limit: int = 12) -> list[dict[str, Any]]:
    from app.core.database import SessionLocal
    from app.services.monitor_service import summarize_monitor_tasks_for_ops

    db = SessionLocal()
    try:
        return summarize_monitor_tasks_for_ops(db, limit=limit, terminal_grace_hours=24)
    finally:
        db.close()


def _collect_ops_insights(beat_history: list[dict[str, Any]], runtime: dict[str, Any]) -> dict[str, Any]:
    """运营向调度摘要，放在上方调度监控区。"""
    from app.core.database import SessionLocal
    from app.services.monitor_service import list_pending_monitor_task_ids

    pending_sync_count = 0
    db = SessionLocal()
    try:
        pending_sync_count = len(
            list_pending_monitor_task_ids(db, limit=500, terminal_grace_hours=24)
        )
    finally:
        db.close()

    today_prefix = datetime.now(UTC).astimezone().date().isoformat()
    today_scans = 0
    today_enqueued = 0
    last_due_scan: dict[str, Any] | None = None
    for item in beat_history:
        checked_at = str(item.get("checked_at") or "")
        if checked_at.startswith(today_prefix):
            today_scans += 1
            today_enqueued += int(item.get("enqueued") or 0)
        if item.get("task_key") == "app.tasks.monitor.scan_due_schedules" and last_due_scan is None:
            last_due_scan = item

    scheduler = _build_scheduler_insight(runtime, beat_history=beat_history)

    return {
        **scheduler,
        "pending_sync_tasks": pending_sync_count,
        "today_scan_count": today_scans,
        "today_enqueued_tasks": today_enqueued,
        "last_due_scan": {
            "at": last_due_scan.get("checked_at") if last_due_scan else None,
            "status_label": last_due_scan.get("status_label") if last_due_scan else None,
            "summary": last_due_scan.get("summary") if last_due_scan else None,
        }
        if last_due_scan
        else None,
    }


def is_business_metric_type(metric_type: str) -> bool:
    return not str(metric_type or "").startswith(TECHNICAL_METRIC_PREFIXES)


def threshold_display_name(metric_type: str, threshold_name: str | None) -> str:
    name = str(threshold_name or "").strip()
    if metric_type == "molizhishu_balance":
        return name.replace("模力账户余额", "账户余额")
    return name


def business_metric_label(metric_type: str) -> str:
    return BUSINESS_METRIC_LABELS.get(metric_type, metric_type)


def metric_label(metric_type: str) -> str:
    return BUSINESS_METRIC_LABELS.get(metric_type) or TECHNICAL_METRIC_LABELS.get(metric_type, metric_type)


def invalidate_queue_threshold_cache() -> None:
    global _THRESHOLD_CACHE_EXPIRES_AT
    _THRESHOLD_CACHE.clear()
    _THRESHOLD_CACHE_EXPIRES_AT = 0.0


def _refresh_queue_threshold_cache() -> None:
    global _THRESHOLD_CACHE_EXPIRES_AT
    now = time.time()
    if now < _THRESHOLD_CACHE_EXPIRES_AT:
        return
    _THRESHOLD_CACHE.clear()
    try:
        from sqlalchemy import select

        from app.core.database import SessionLocal
        from app.models.platform import AlertThreshold

        with SessionLocal() as db:
            rows = db.scalars(
                select(AlertThreshold).where(
                    AlertThreshold.deleted.is_(False),
                    AlertThreshold.tenant_id.is_(None),
                    AlertThreshold.enabled.is_(True),
                    AlertThreshold.metric_type.in_(tuple(QUEUE_METRIC_BY_NAME.values())),
                )
            ).all()
            for row in rows:
                warning = int(str(row.warning_value or "0"))
                critical = int(str(row.critical_value or "0"))
                _THRESHOLD_CACHE[f"{row.metric_type}:warning"] = warning
                _THRESHOLD_CACHE[f"{row.metric_type}:critical"] = critical
    except Exception:
        logger.exception("Failed to load queue thresholds from database")
    _THRESHOLD_CACHE_EXPIRES_AT = now + _THRESHOLD_CACHE_TTL_SECONDS


def collect_queue_stats() -> dict[str, Any]:
    """Collect queue backlog and worker runtime stats."""
    queues: dict[str, dict[str, int]] = {}
    client = _broker_client()
    if client is None:
        for name in QUEUE_NAMES:
            queues[name] = {"queued": 0, "warning_threshold": _threshold(name, "warning"), "critical_threshold": _threshold(name, "critical")}
    else:
        for name in QUEUE_NAMES:
            queues[name] = {
                "queued": _queue_length(client, name),
                "warning_threshold": _threshold(name, "warning"),
                "critical_threshold": _threshold(name, "critical"),
            }

    runtime = _collect_runtime_tasks()
    worker_stats = _worker_stats_from_runtime(runtime)
    snapshot = {
        "checked_at": datetime.now(UTC).isoformat(),
        "queues": queues,
        "workers": worker_stats,
        "runtime": runtime,
        "flower_url": settings.flower_url if settings.flower_enabled else None,
    }
    snapshot["alerts"] = evaluate_queue_alerts(snapshot, persist=False)
    return snapshot


def _threshold(queue_name: str, level: str) -> int:
    _refresh_queue_threshold_cache()
    metric_type = QUEUE_METRIC_BY_NAME.get(queue_name)
    if metric_type:
        cached = _THRESHOLD_CACHE.get(f"{metric_type}:{level}")
        if cached is not None:
            return cached
    if queue_name == "submit":
        return settings.celery_queue_submit_warning if level == "warning" else settings.celery_queue_submit_critical
    if queue_name == "default":
        return settings.celery_queue_default_warning if level == "warning" else settings.celery_queue_default_critical
    if queue_name == "backfill":
        return settings.celery_queue_backfill_warning if level == "warning" else settings.celery_queue_backfill_critical
    return settings.celery_queue_sync_warning if level == "warning" else settings.celery_queue_sync_critical


def evaluate_queue_alerts(snapshot: dict[str, Any] | None = None, *, persist: bool = True) -> list[dict[str, Any]]:
    """Evaluate queue depth against thresholds and optionally emit alerts."""
    snapshot = snapshot or collect_queue_stats()
    alerts: list[dict[str, Any]] = []

    for queue_name, queue_data in snapshot.get("queues", {}).items():
        queued = int(queue_data.get("queued") or 0)
        warning = int(queue_data.get("warning_threshold") or 0)
        critical = int(queue_data.get("critical_threshold") or 0)
        if queued >= critical:
            alerts.append(_build_alert(queue_name, queued, critical, "critical"))
        elif queued >= warning:
            alerts.append(_build_alert(queue_name, queued, warning, "warning"))

    workers_online = int(snapshot.get("workers", {}).get("workers_online") or 0)
    if settings.celery_enabled and workers_online == 0:
        alerts.append(
            {
                "queue": "workers",
                "level": "critical",
                "title": "Celery Worker 离线",
                "message": "未检测到在线 Worker，队列任务将无法消费",
                "queued": 0,
                "threshold": 0,
            }
        )

    if settings.celery_enabled:
        from app.core.database import SessionLocal
        from app.services.monitor_service import list_pending_monitor_task_ids

        db = SessionLocal()
        try:
            pending_sync_tasks = len(
                list_pending_monitor_task_ids(db, limit=500, terminal_grace_hours=24)
            )
        finally:
            db.close()
        if pending_sync_tasks >= settings.celery_pending_sync_task_critical:
            alerts.append(
                {
                    "queue": "pending_sync",
                    "level": "critical",
                    "title": "待同步监测任务积压严重",
                    "message": f"仍有 {pending_sync_tasks} 个监测任务等待同步，客户侧进度可能长时间不更新",
                    "queued": pending_sync_tasks,
                    "threshold": settings.celery_pending_sync_task_critical,
                }
            )
        elif pending_sync_tasks >= settings.celery_pending_sync_task_warning:
            alerts.append(
                {
                    "queue": "pending_sync",
                    "level": "warning",
                    "title": "待同步监测任务积压预警",
                    "message": f"仍有 {pending_sync_tasks} 个监测任务等待同步",
                    "queued": pending_sync_tasks,
                    "threshold": settings.celery_pending_sync_task_warning,
                }
            )

    # 2026-08-21 - 稳定性⑥：并入 API P95 / 回调失败率 / 矩阵耗时
    try:
        from app.services.stability_metrics_service import (
            collect_stability_metrics,
            evaluate_stability_alerts,
        )

        alerts.extend(evaluate_stability_alerts(collect_stability_metrics()))
    except Exception:
        logger.exception("Failed to evaluate stability alerts")

    if persist:
        _persist_alert_snapshot(snapshot, alerts)
        for alert in alerts:
            _emit_alert(alert)
        from app.core.database import SessionLocal
        from app.services.system_notification_service import resolve_stale_monitor_alert_notifications

        db = SessionLocal()
        try:
            resolve_stale_monitor_alert_notifications(db, alerts)
        except Exception:
            logger.exception("Failed to resolve stale monitor alert notifications")
        finally:
            db.close()
    return alerts


def _build_alert(queue_name: str, queued: int, threshold: int, level: str) -> dict[str, Any]:
    label = "提交队列" if queue_name == "submit" else "同步队列"
    return {
        "queue": queue_name,
        "level": level,
        "title": f"{label}积压{'严重' if level == 'critical' else '预警'}",
        "message": f"{label}待处理 {queued} 条，阈值 {threshold}",
        "queued": queued,
        "threshold": threshold,
    }


def _persist_alert_snapshot(snapshot: dict[str, Any], alerts: list[dict[str, Any]]) -> None:
    payload = {
        **snapshot,
        "alerts": alerts,
        "alert_count": len(alerts),
        "has_critical": any(item["level"] == "critical" for item in alerts),
    }
    set_json_cache("celery:queue:snapshot", payload, ttl_seconds=300)


def get_queue_monitor_snapshot() -> dict[str, Any]:
    cached = get_json_cache("celery:queue:snapshot")
    if cached:
        return cached
    snapshot = collect_queue_stats()
    _persist_alert_snapshot(snapshot, snapshot.get("alerts") or evaluate_queue_alerts(snapshot, persist=False))
    return snapshot


def format_celery_monitor_zh(snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    """Format queue monitor data for the Chinese operations dashboard."""
    snapshot = snapshot or get_queue_monitor_snapshot()
    queue_labels = {
        "submit": "提交队列",
        "sync": "同步队列",
        "default": "默认队列（矩阵/知识库）",
        "backfill": "补录解析队列（Playwright）",
    }
    status_labels = {
        "normal": "正常",
        "warning": "预警",
        "critical": "严重",
    }

    queues: list[dict[str, Any]] = []
    for key, data in (snapshot.get("queues") or {}).items():
        pending = int(data.get("queued") or 0)
        warning = int(data.get("warning_threshold") or 0)
        critical = int(data.get("critical_threshold") or 0)
        if pending >= critical:
            level = "critical"
        elif pending >= warning:
            level = "warning"
        else:
            level = "normal"
        queues.append(
            {
                "key": key,
                "name": queue_labels.get(key, key),
                "pending": pending,
                "warning_threshold": warning,
                "critical_threshold": critical,
                "status": status_labels[level],
                "status_level": level,
                "usage_percent": round(min(100, pending / max(1, critical) * 100), 1),
            }
        )

    workers = snapshot.get("workers") or {}
    runtime = _collect_runtime_tasks()
    beat_history = _get_beat_history()
    runtime_rows = [
        *(runtime.get("active") or []),
        *(runtime.get("reserved") or []),
    ]
    online_count = int(runtime.get("workers_online") or workers.get("workers_online") or 0)
    worker_names = runtime.get("worker_names") or workers.get("worker_names") or []
    worker_rows = [
        {"name": name, "role": _worker_role_label(name)}
        for name in worker_names
    ]

    return {
        "checked_at": snapshot.get("checked_at"),
        "queues": queues,
        "workers": {
            "online_count": online_count,
            "active_tasks": int(runtime.get("active_count") or 0),
            "reserved_tasks": int(runtime.get("reserved_count") or 0),
            "status": "在线" if online_count > 0 else "离线",
            "items": worker_rows,
        },
        "runtime_tasks": {
            "active": runtime.get("active") or [],
            "reserved": runtime.get("reserved") or [],
            "total": len(runtime_rows),
        },
        "beat_history": beat_history,
        "alerts": snapshot.get("alerts") or [],
        "alert_count": len(snapshot.get("alerts") or []),
        "flower_url": snapshot.get("flower_url"),
        "tips": [
            "提交队列：负责把到点监测任务提交抓取",
            "同步队列：负责拉取监测任务结果",
            "待同步监测任务：已提交抓取、尚未全部拉回结果的主任务数量",
        ],
        "scheduler": {
            "submit_scan": "每 5 分钟扫描到点任务（09:00-21:00）",
            "sync_scan": "每 1 分钟同步待完成监测任务",
            "backlog_check": "每 5 分钟检查队列积压并告警",
        },
        "ops_insights": _collect_ops_insights(beat_history, runtime),
        "pending_sync_details": _collect_pending_sync_details(limit=12),
        "sync_live": get_sync_live(),
    }


def _worker_role_label(worker_name: str) -> str:
    role = _worker_role_from_name(worker_name)
    if role == "submit":
        return "提交进程"
    if role == "sync":
        return "同步进程"
    if role == "default":
        return "默认进程（矩阵等）"
    return "调度进程"


def _emit_alert(alert: dict[str, Any]) -> None:
    level = alert.get("level", "warning")
    message = f"[{level}] {alert.get('title')}: {alert.get('message')}"
    log_fn = logger.error if level == "critical" else logger.warning
    log_fn(message)

    if _in_alert_cooldown(alert):
        return

    _set_alert_cooldown(alert)
    try:
        from app.services.system_notification_service import push_monitor_alert_notification

        push_monitor_alert_notification(alert)
    except Exception:
        logger.exception("Failed to push in-app monitor notification")
    if settings.monitor_webhook_url.strip():
        _post_webhook(alert)


def _cooldown_key(alert: dict[str, Any]) -> str:
    return prefixed_key(f"alert:cooldown:{alert.get('queue')}:{alert.get('level')}")


def _in_alert_cooldown(alert: dict[str, Any]) -> bool:
    client = get_redis_client()
    if client is None:
        return False
    try:
        return bool(client.exists(_cooldown_key(alert)))
    except RedisError:
        return False


def _set_alert_cooldown(alert: dict[str, Any]) -> None:
    client = get_redis_client()
    if client is None:
        return
    ttl = max(60, settings.monitor_alert_cooldown_seconds)
    try:
        client.setex(_cooldown_key(alert), ttl, "1")
    except RedisError as exc:
        logger.warning("Set alert cooldown failed: %s", exc)


def _post_webhook(alert: dict[str, Any]) -> None:
    url = settings.monitor_webhook_url.strip()
    if not url:
        return
    payload = {
        "source": "geo_monitor",
        "type": "celery_queue_backlog",
        "level": alert.get("level"),
        "title": alert.get("title"),
        "message": alert.get("message"),
        "queue": alert.get("queue"),
        "queued": alert.get("queued"),
        "threshold": alert.get("threshold"),
        "timestamp": datetime.now(UTC).isoformat(),
    }
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(url, json=payload)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("Monitor webhook failed: %s", exc)
