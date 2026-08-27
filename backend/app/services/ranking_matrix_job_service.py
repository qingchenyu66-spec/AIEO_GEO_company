"""排名矩阵异步构建：缓存优先，未命中入队，同条件单飞。

2026-08-21 - 稳定性桌面方案③：miss 不占 HTTP 线程同步重算
"""

from __future__ import annotations

import hashlib
import logging
import time
from datetime import date, datetime, time as dt_time
from typing import Any

from sqlalchemy.orm import Session, joinedload

from app.api.dependencies import CurrentSession
from app.core.config import settings
from app.core.read_cache import RANKING_MATRIX_CACHE_TTL, get_or_build_json_cache
from app.core.redis_client import (
    delete_cache,
    get_json_cache,
    redis_enabled,
    redis_lock,
    set_json_cache,
)
from app.models.user_identity import UserIdentity

logger = logging.getLogger(__name__)

MATRIX_JOB_TTL_SECONDS = 900
MATRIX_JOB_LOCK_TTL = 120
# 2026-08-27 - pending 25s 无 worker 接管；processing 拉长避免与大矩阵 worker 双算
MATRIX_JOB_PENDING_STALE_SECONDS = 25
MATRIX_JOB_PROCESSING_STALE_SECONDS = 150


def _matrix_job_is_stale(meta: dict[str, Any]) -> bool:
    updated = int(meta.get("updated_at") or 0)
    if updated <= 0:
        return True
    status = str(meta.get("status") or "pending")
    threshold = (
        MATRIX_JOB_PROCESSING_STALE_SECONDS
        if status == "processing"
        else MATRIX_JOB_PENDING_STALE_SECONDS
    )
    return (time.time() - updated) > threshold


def _sync_build_matrix_response(cache_key: str, builder) -> dict[str, Any]:
    data = get_or_build_json_cache(
        cache_key,
        builder,
        ttl_seconds=RANKING_MATRIX_CACHE_TTL,
        lock_ttl_seconds=60,
        wait_seconds=2.0,
    )
    out = dict(data) if isinstance(data, dict) else {"data": data}
    out["matrix_status"] = "ready"
    return out


def _matrix_job_public_status(job_id: str, meta: dict[str, Any]) -> dict[str, Any]:
    status = str(meta.get("status") or "pending")
    if status == "ready":
        return get_matrix_job_status(job_id)
    out = {
        "matrix_status": status if status in {"pending", "processing", "failed"} else "processing",
        "job_id": job_id,
        "status": status,
    }
    if meta.get("error"):
        out["error"] = meta["error"]
    return out


def matrix_job_redis_key(job_id: str) -> str:
    return f"monitor:ranking-matrix:job:v1:{job_id}"


def matrix_job_id_for_cache_key(cache_key: str) -> str:
    digest = hashlib.sha1(cache_key.encode("utf-8")).hexdigest()[:24]
    return f"mx-{digest}"


def read_matrix_job(job_id: str) -> dict[str, Any] | None:
    data = get_json_cache(matrix_job_redis_key(job_id))
    return data if isinstance(data, dict) else None


def write_matrix_job(job_id: str, payload: dict[str, Any], *, ttl: int = MATRIX_JOB_TTL_SECONDS) -> None:
    set_json_cache(matrix_job_redis_key(job_id), payload, ttl_seconds=ttl)


def mark_matrix_job(
    job_id: str,
    *,
    status: str,
    cache_key: str,
    build_params: dict[str, Any] | None = None,
    error: str | None = None,
    result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    prev = read_matrix_job(job_id) or {}
    payload: dict[str, Any] = {
        "job_id": job_id,
        "status": status,
        "cache_key": cache_key,
        "updated_at": int(time.time()),
        "build_params": build_params if build_params is not None else prev.get("build_params"),
    }
    if error:
        payload["error"] = error[:500]
    payload["has_result"] = result is not None
    write_matrix_job(job_id, payload)
    if result is not None:
        set_json_cache(
            f"{matrix_job_redis_key(job_id)}:result",
            result,
            ttl_seconds=MATRIX_JOB_TTL_SECONDS,
        )
    return payload


def read_matrix_job_result(job_id: str) -> dict[str, Any] | None:
    data = get_json_cache(f"{matrix_job_redis_key(job_id)}:result")
    return data if isinstance(data, dict) else None


def enqueue_or_reuse_matrix_job(cache_key: str, build_params: dict[str, Any]) -> dict[str, Any]:
    """同 cache_key 只保留一个 job；返回 pending/processing 态。"""
    job_id = matrix_job_id_for_cache_key(cache_key)
    existing = read_matrix_job(job_id)
    if existing and existing.get("status") in {"pending", "processing"}:
        if not _matrix_job_is_stale(existing):
            return {
                "matrix_status": "processing",
                "job_id": job_id,
                "status": existing.get("status") or "processing",
            }
        logger.warning("stale matrix job re-enqueue job_id=%s status=%s", job_id, existing.get("status"))
    if existing and existing.get("status") == "ready":
        cached = get_json_cache(cache_key)
        if isinstance(cached, dict):
            out = dict(cached)
            out["matrix_status"] = "ready"
            out["job_id"] = job_id
            return out

    mark_matrix_job(job_id, status="pending", cache_key=cache_key, build_params=build_params)

    from app.tasks.monitor import build_ranking_matrix_job_task

    try:
        build_ranking_matrix_job_task.apply_async(
            kwargs={"job_id": job_id},
            task_id=f"ranking-matrix-job-{job_id}",
        )
    except Exception as exc:
        message = str(exc).lower()
        if "already exists" not in message and "duplicate" not in message:
            logger.warning("enqueue ranking matrix job failed job_id=%s error=%s", job_id, exc)
            mark_matrix_job(job_id, status="failed", cache_key=cache_key, error=str(exc))
            return {
                "matrix_status": "failed",
                "job_id": job_id,
                "status": "failed",
                "error": str(exc)[:240],
            }

    return {
        "matrix_status": "processing",
        "job_id": job_id,
        "status": "pending",
    }


def refresh_matrix_job(db: Session, job_id: str) -> dict[str, Any]:
    """轮询态失败/超时/卡 pending 时在 API 线程同步重建（与生产同逻辑，降级不丢页面）。"""
    meta = read_matrix_job(job_id)
    if meta is None:
        return {"matrix_status": "missing", "job_id": job_id, "status": "missing"}
    status = str(meta.get("status") or "pending")
    if status == "ready":
        return get_matrix_job_status(job_id)
    if status in {"pending", "processing"} and not _matrix_job_is_stale(meta):
        return _matrix_job_public_status(job_id, meta)
    cached_key = str(meta.get("cache_key") or "")
    cached = get_json_cache(cached_key) if cached_key else None
    if isinstance(cached, dict):
        mark_matrix_job(job_id, status="ready", cache_key=cached_key, result=cached)
        out = dict(cached)
        out["matrix_status"] = "ready"
        out["job_id"] = job_id
        return out
    logger.warning("matrix job sync refresh job_id=%s prev_status=%s", job_id, status)
    result = run_matrix_job(db, job_id)
    if str(result.get("status")) == "ready":
        return get_matrix_job_status(job_id)
    err = str(result.get("error") or meta.get("error") or "排名矩阵计算失败")
    return {
        "matrix_status": "failed",
        "job_id": job_id,
        "status": "failed",
        "error": err[:240],
    }


def get_matrix_job_status(job_id: str) -> dict[str, Any]:
    meta = read_matrix_job(job_id)
    if meta is None:
        return {"matrix_status": "missing", "job_id": job_id, "status": "missing"}
    status = str(meta.get("status") or "pending")
    if status == "ready":
        result = read_matrix_job_result(job_id)
        if result is None:
            cache_key = str(meta.get("cache_key") or "")
            cached = get_json_cache(cache_key) if cache_key else None
            if isinstance(cached, dict):
                result = cached
        if isinstance(result, dict):
            out = dict(result)
            out["matrix_status"] = "ready"
            out["job_id"] = job_id
            return out
        return {"matrix_status": "ready", "job_id": job_id, "status": "ready"}
    out = {
        "matrix_status": status if status in {"pending", "processing", "failed"} else "processing",
        "job_id": job_id,
        "status": status,
    }
    if meta.get("error"):
        out["error"] = meta["error"]
    return out


def _session_from_identity_id(db: Session, identity_id: int) -> CurrentSession:
    from sqlalchemy import select

    identity = db.scalar(
        select(UserIdentity)
        .options(joinedload(UserIdentity.user), joinedload(UserIdentity.tenant))
        .where(
            UserIdentity.id == int(identity_id),
            UserIdentity.status.is_(True),
            UserIdentity.deleted.is_(False),
        )
    )
    if identity is None or identity.user is None or not identity.user.status:
        raise RuntimeError(f"矩阵任务身份不可用 identity_id={identity_id}")
    return CurrentSession(user=identity.user, identity=identity)


def run_matrix_job(db: Session, job_id: str) -> dict[str, Any]:
    """Worker：按 job 内 build_params 重建并写缓存。"""
    started = time.perf_counter()
    meta = read_matrix_job(job_id)
    if meta is None:
        return {"status": "missing", "job_id": job_id}
    cache_key = str(meta.get("cache_key") or "")
    params = meta.get("build_params") if isinstance(meta.get("build_params"), dict) else {}
    if not cache_key or not params:
        mark_matrix_job(job_id, status="failed", cache_key=cache_key or "-", error="缺少构建参数")
        return {"status": "failed", "job_id": job_id}

    mark_matrix_job(job_id, status="processing", cache_key=cache_key, build_params=params)
    lock_key = f"matrix-job-build:{job_id}"
    with redis_lock(lock_key, ttl_seconds=MATRIX_JOB_LOCK_TTL) as acquired:
        cached = get_json_cache(cache_key)
        if isinstance(cached, dict):
            mark_matrix_job(job_id, status="ready", cache_key=cache_key, result=cached)
            _record_matrix_elapsed(job_id, started, "ready")
            return {"status": "ready", "job_id": job_id, "cache_hit": True}
        if not acquired:
            # 2026-08-27 - 拿不到锁仍构建，避免 Redis 抖动留 processing 永动机
            logger.warning("matrix job lock busy job_id=%s, continue build", job_id)

        from app.services.monitor_service import ranking_matrix

        try:
            current = _session_from_identity_id(db, int(params["identity_id"]))
            start_date = params.get("start_date")
            end_date = params.get("end_date")
            start_at = datetime.combine(date.fromisoformat(start_date), dt_time.min) if start_date else None
            end_at = datetime.combine(date.fromisoformat(end_date), dt_time.max) if end_date else None
            data = ranking_matrix(
                db,
                current,
                platform=params.get("platform"),
                start_at=start_at,
                end_at=end_at,
                keyword=params.get("keyword"),
                monitor_group=params.get("monitor_group"),
                keyword_group=params.get("keyword_group"),
                monitor_keyword=params.get("monitor_keyword"),
                exposure_term=params.get("exposure_term"),
                limit_rows=int(params.get("limit_rows") or 120),
                tenant_id=params.get("tenant_id"),
            )
            set_json_cache(cache_key, data, ttl_seconds=RANKING_MATRIX_CACHE_TTL)
            mark_matrix_job(job_id, status="ready", cache_key=cache_key, result=data)
            _record_matrix_elapsed(job_id, started, "ready")
            return {"status": "ready", "job_id": job_id}
        except Exception as exc:
            logger.exception("ranking matrix job failed job_id=%s", job_id)
            mark_matrix_job(job_id, status="failed", cache_key=cache_key, error=str(exc))
            _record_matrix_elapsed(job_id, started, "failed")
            return {"status": "failed", "job_id": job_id, "error": str(exc)[:240]}


def _record_matrix_elapsed(job_id: str, started: float, status: str) -> None:
    try:
        from app.services.stability_metrics_service import record_matrix_job_duration

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        record_matrix_job_duration(job_id, elapsed_ms, status)
    except Exception:
        pass


def resolve_ranking_matrix_response(
    *,
    cache_key: str | None,
    builder,
    build_params: dict[str, Any] | None,
    prefer_async: bool,
) -> dict[str, Any]:
    """缓存命中直接返回；miss 时按 prefer_async 入队或同步构建。"""
    if cache_key:
        cached = get_json_cache(cache_key)
        if isinstance(cached, dict):
            out = dict(cached)
            out["matrix_status"] = "ready"
            return out

    if (
        prefer_async
        and settings.celery_enabled
        and redis_enabled()
        and cache_key
        and build_params
    ):
        async_out = enqueue_or_reuse_matrix_job(cache_key, build_params)
        if async_out.get("matrix_status") == "failed":
            # 2026-08-27 - 入队失败（本地 Celery/Redis）降级同步，与生产同代码路径
            logger.warning("matrix async enqueue failed, sync fallback cache_key=%s", cache_key)
            return _sync_build_matrix_response(cache_key, builder)
        return async_out

    if cache_key:
        return _sync_build_matrix_response(cache_key, builder)
    data = builder()
    out = dict(data) if isinstance(data, dict) else {"data": data}
    out["matrix_status"] = "ready"
    return out


def clear_matrix_job_markers(cache_key: str) -> None:
    if not redis_enabled():
        return
    job_id = matrix_job_id_for_cache_key(cache_key)
    delete_cache(matrix_job_redis_key(job_id))
    delete_cache(f"{matrix_job_redis_key(job_id)}:result")
