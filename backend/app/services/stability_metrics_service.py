"""稳定性护栏指标：快 API 延迟、回调失败率、矩阵 job 耗时。

2026-08-21 - 稳定性桌面方案⑥：进 Redis 环 + ops/告警，不另起监控栈
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.redis_client import get_redis_client, prefixed_key, redis_enabled

logger = logging.getLogger(__name__)

LATENCY_RING_KEY = "stability:api_latency:v1"
LATENCY_RING_MAX = 400
MATRIX_DURATION_RING_KEY = "stability:matrix_job_ms:v1"
MATRIX_DURATION_RING_MAX = 100

# 路径粗分：快 / 重 / 回调（与 Nginx 分流口径对齐）
CALLBACK_PREFIX = "/api/v1/monitor/molizhishu/callback"
HEAVY_MARKERS = (
    "/api/v1/monitor/ranking-matrix",
    "/api/v1/monitor/workspace-brief",
    "/api/v1/monitor/summary",
    "/api/v1/monitor/source-stats",
    "/api/v1/analytics/",
)

CALLBACK_FAIL_RATE_WARN = 0.05
CALLBACK_FAIL_RATE_CRIT = 0.15
MATRIX_JOB_WARN_MS = 60000


def classify_api_lane(path: str) -> str:
    p = str(path or "")
    if p.startswith(CALLBACK_PREFIX) or p == CALLBACK_PREFIX:
        return "callback"
    for marker in HEAVY_MARKERS:
        if p.startswith(marker):
            return "heavy"
    if p.startswith("/api/"):
        return "fast"
    return "other"


def _push_ring(key: str, sample: dict[str, Any], *, maxlen: int) -> None:
    if not redis_enabled():
        return
    client = get_redis_client()
    if client is None:
        return
    try:
        full = prefixed_key(key)
        import json

        client.lpush(full, json.dumps(sample, ensure_ascii=False, default=str))
        client.ltrim(full, 0, maxlen - 1)
        client.expire(full, 3600)
    except Exception as exc:
        logger.debug("stability ring push failed key=%s error=%s", key, exc)


def record_request_latency(path: str, duration_ms: int, status_code: int) -> None:
    lane = classify_api_lane(path)
    if lane == "other":
        return
    _push_ring(
        LATENCY_RING_KEY,
        {
            "lane": lane,
            "ms": int(duration_ms),
            "status": int(status_code),
            "path": str(path)[:160],
            "ts": int(time.time()),
        },
        maxlen=LATENCY_RING_MAX,
    )


def record_matrix_job_duration(job_id: str, elapsed_ms: int, status: str) -> None:
    _push_ring(
        MATRIX_DURATION_RING_KEY,
        {
            "job_id": str(job_id)[:64],
            "ms": int(elapsed_ms),
            "status": str(status),
            "ts": int(time.time()),
        },
        maxlen=MATRIX_DURATION_RING_MAX,
    )


def _read_ring(key: str) -> list[dict[str, Any]]:
    client = get_redis_client() if redis_enabled() else None
    if client is None:
        return []
    try:
        import json

        raw = client.lrange(prefixed_key(key), 0, -1) or []
        out: list[dict[str, Any]] = []
        for item in raw:
            try:
                parsed = json.loads(item)
            except Exception:
                continue
            if isinstance(parsed, dict):
                out.append(parsed)
        return out
    except Exception:
        return []


def _percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    idx = min(len(ordered) - 1, max(0, int(round((p / 100.0) * (len(ordered) - 1)))))
    return float(ordered[idx])


def latency_snapshot() -> dict[str, Any]:
    samples = _read_ring(LATENCY_RING_KEY)
    by_lane: dict[str, list[float]] = {"fast": [], "heavy": [], "callback": []}
    for item in samples:
        lane = str(item.get("lane") or "")
        if lane not in by_lane:
            continue
        try:
            by_lane[lane].append(float(item.get("ms") or 0))
        except (TypeError, ValueError):
            continue
    result: dict[str, Any] = {"sample_count": len(samples), "lanes": {}}
    for lane, values in by_lane.items():
        result["lanes"][lane] = {
            "count": len(values),
            "p50_ms": _percentile(values, 50),
            "p95_ms": _percentile(values, 95),
            "p99_ms": _percentile(values, 99),
        }
    return result


def matrix_job_duration_snapshot() -> dict[str, Any]:
    samples = _read_ring(MATRIX_DURATION_RING_KEY)
    values = []
    for item in samples:
        try:
            values.append(float(item.get("ms") or 0))
        except (TypeError, ValueError):
            continue
    return {
        "sample_count": len(values),
        "p50_ms": _percentile(values, 50),
        "p95_ms": _percentile(values, 95),
        "max_ms": max(values) if values else None,
    }


def callback_failure_rate(db: Session, *, hours: int = 24) -> dict[str, Any]:
    from app.models.monitor import GeoMonitorCallbackEvent

    since = datetime.now() - timedelta(hours=max(1, int(hours)))
    total = int(
        db.scalar(
            select(func.count())
            .select_from(GeoMonitorCallbackEvent)
            .where(GeoMonitorCallbackEvent.received_at >= since)
        )
        or 0
    )
    failed = int(
        db.scalar(
            select(func.count())
            .select_from(GeoMonitorCallbackEvent)
            .where(
                GeoMonitorCallbackEvent.received_at >= since,
                GeoMonitorCallbackEvent.process_status == "failed",
            )
        )
        or 0
    )
    rate = (failed / total) if total > 0 else 0.0
    return {
        "hours": int(hours),
        "total": total,
        "failed": failed,
        "failure_rate": round(rate, 4),
    }


def collect_stability_metrics(db: Session | None = None) -> dict[str, Any]:
    close = False
    if db is None:
        from app.core.database import SessionLocal

        db = SessionLocal()
        close = True
    try:
        return {
            "latency": latency_snapshot(),
            "callback": callback_failure_rate(db),
            "matrix_jobs": matrix_job_duration_snapshot(),
            "checked_at": datetime.now().isoformat(timespec="seconds"),
        }
    finally:
        if close:
            db.close()


def evaluate_stability_alerts(metrics: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    metrics = metrics or collect_stability_metrics()
    alerts: list[dict[str, Any]] = []
    # 2026-08-24 - 重 API P95 误报多且规则页不可配 - 停站内通知，指标仍采样
    # 2026-08-27 - 快 API P95 同理（补录/队列监控等拖慢仍进 fast 环）- 停站内通知

    cb = metrics.get("callback") or {}
    rate = float(cb.get("failure_rate") or 0.0)
    total = int(cb.get("total") or 0)
    if total >= 10 and rate >= CALLBACK_FAIL_RATE_CRIT:
        alerts.append(
            {
                "queue": "callback_fail_rate",
                "level": "critical",
                "title": "模力回调失败率过高",
                "message": f"近 {cb.get('hours')}h 失败率 {rate:.1%}（{cb.get('failed')}/{total}）",
                "queued": int(rate * 1000),
                "threshold": int(CALLBACK_FAIL_RATE_CRIT * 1000),
            }
        )
    elif total >= 10 and rate >= CALLBACK_FAIL_RATE_WARN:
        alerts.append(
            {
                "queue": "callback_fail_rate",
                "level": "warning",
                "title": "模力回调失败率预警",
                "message": f"近 {cb.get('hours')}h 失败率 {rate:.1%}（{cb.get('failed')}/{total}）",
                "queued": int(rate * 1000),
                "threshold": int(CALLBACK_FAIL_RATE_WARN * 1000),
            }
        )

    matrix = metrics.get("matrix_jobs") or {}
    max_ms = matrix.get("max_ms")
    if max_ms is not None and float(max_ms) >= MATRIX_JOB_WARN_MS:
        alerts.append(
            {
                "queue": "matrix_job_duration",
                "level": "warning",
                "title": "矩阵任务耗时过长",
                "message": f"近期矩阵 job 最大 {int(max_ms)}ms，阈值 {MATRIX_JOB_WARN_MS}ms",
                "queued": int(max_ms),
                "threshold": MATRIX_JOB_WARN_MS,
            }
        )
    return alerts
