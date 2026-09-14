"""报告重算异步任务：立刻返回 job_id，后台 ThreadPool 执行。

与导出任务同款：不依赖 Celery（本地常停）；落盘 + Redis meta，切页不断。
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from app.core.database import SessionLocal
from app.core.redis_client import delete_cache, get_json_cache, set_json_cache

logger = logging.getLogger(__name__)

_JOB_DIR = Path(__file__).resolve().parents[2] / "storage" / "report_refresh_jobs"
_JOB_TTL_SECONDS = 3600
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="report-refresh")
_lock = threading.Lock()
_jobs: dict[str, dict[str, Any]] = {}
_active_by_report: dict[int, str] = {}


def _ensure_dir() -> Path:
    _JOB_DIR.mkdir(parents=True, exist_ok=True)
    return _JOB_DIR


def _meta_path(job_id: str) -> Path:
    return _ensure_dir() / f"{job_id}.json"


def _active_key(report_id: int) -> str:
    return f"report_refresh_active:{int(report_id)}"


def _save_meta(meta: dict[str, Any]) -> None:
    job_id = str(meta["job_id"])
    with _lock:
        _jobs[job_id] = dict(meta)
        report_id = meta.get("report_id")
        status = str(meta.get("status") or "")
        if report_id is not None and status in {"queued", "running"}:
            _active_by_report[int(report_id)] = job_id
        elif report_id is not None and _active_by_report.get(int(report_id)) == job_id:
            _active_by_report.pop(int(report_id), None)
    _meta_path(job_id).write_text(json.dumps(meta, ensure_ascii=False, default=str), encoding="utf-8")
    set_json_cache(f"report_refresh_job:{job_id}", meta, ttl_seconds=_JOB_TTL_SECONDS)
    report_id = meta.get("report_id")
    status = str(meta.get("status") or "")
    if report_id is not None:
        if status in {"queued", "running"}:
            set_json_cache(_active_key(int(report_id)), {"job_id": job_id}, ttl_seconds=_JOB_TTL_SECONDS)
        else:
            delete_cache(_active_key(int(report_id)))


def _load_meta(job_id: str) -> dict[str, Any] | None:
    redis_meta = get_json_cache(f"report_refresh_job:{job_id}")
    if isinstance(redis_meta, dict) and redis_meta.get("job_id"):
        with _lock:
            _jobs[job_id] = dict(redis_meta)
        return dict(redis_meta)
    with _lock:
        cached = _jobs.get(job_id)
        if cached:
            return dict(cached)
    path = _meta_path(job_id)
    if not path.is_file():
        return None
    try:
        meta = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(meta, dict):
        return None
    with _lock:
        _jobs[job_id] = dict(meta)
    return dict(meta)


def _public_meta(meta: dict[str, Any]) -> dict[str, Any]:
    return {
        "job_id": meta.get("job_id"),
        "status": meta.get("status"),
        "report_id": meta.get("report_id"),
        "tenant_id": meta.get("tenant_id"),
        "report_title": meta.get("report_title"),
        "progress": meta.get("progress") or "",
        "error": meta.get("error"),
        "result": meta.get("result"),
        "created_at": meta.get("created_at"),
        "finished_at": meta.get("finished_at"),
    }


def find_active_refresh_job(report_id: int) -> dict[str, Any] | None:
    hit = get_json_cache(_active_key(report_id))
    job_id = hit.get("job_id") if isinstance(hit, dict) else None
    if not job_id:
        with _lock:
            job_id = _active_by_report.get(int(report_id))
    if not job_id:
        return None
    meta = _load_meta(str(job_id))
    if not meta:
        return None
    if str(meta.get("status") or "") not in {"queued", "running"}:
        return None
    return _public_meta(meta)


def _run_refresh_job(job_id: str) -> None:
    meta = _load_meta(job_id)
    if not meta:
        return
    meta["status"] = "running"
    meta["progress"] = "正在重新计算…"
    _save_meta(meta)

    report_id = int(meta["report_id"])
    db = SessionLocal()
    try:
        from app.services.report_service import refresh_report_content

        meta["progress"] = "汇总监测数据…"
        _save_meta(meta)
        row = refresh_report_content(db, report_id)
        meta["status"] = "ready"
        meta["progress"] = "重算完成"
        meta["result"] = row
        meta["report_title"] = row.get("report_title") or meta.get("report_title")
        meta["finished_at"] = time.time()
        meta["error"] = None
        _save_meta(meta)
    except Exception as exc:  # noqa: BLE001
        logger.exception("report refresh job failed job_id=%s report_id=%s", job_id, report_id)
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass
        meta = _load_meta(job_id) or meta
        meta["status"] = "failed"
        meta["progress"] = "重算失败"
        meta["error"] = str(exc) or "报告重算失败"
        meta["finished_at"] = time.time()
        _save_meta(meta)
    finally:
        db.close()


def start_report_refresh_job(
    *,
    report_id: int,
    tenant_id: int | None,
    report_title: str | None,
    owner_user_id: int | None,
) -> dict[str, Any]:
    active = find_active_refresh_job(report_id)
    if active:
        return active

    job_id = uuid.uuid4().hex
    meta = {
        "job_id": job_id,
        "status": "queued",
        "report_id": int(report_id),
        "tenant_id": tenant_id,
        "report_title": report_title,
        "owner_user_id": owner_user_id,
        "progress": "已排队…",
        "error": None,
        "result": None,
        "created_at": time.time(),
        "finished_at": None,
    }
    _save_meta(meta)
    _executor.submit(_run_refresh_job, job_id)
    return _public_meta(meta)


def get_report_refresh_job(job_id: str) -> dict[str, Any] | None:
    meta = _load_meta(job_id)
    return _public_meta(meta) if meta else None
