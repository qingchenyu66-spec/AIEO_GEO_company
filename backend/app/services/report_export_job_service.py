"""异步导出任务：立刻返回 job_id，后台生成，支持指纹命中复用。

不依赖 Celery（本地常停）；ThreadPool + 落盘文件。Redis 可用时同步一份 meta。
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Literal

from app.core.database import SessionLocal
from app.core.redis_client import get_json_cache, set_json_cache

logger = logging.getLogger(__name__)

ExportKind = Literal["lead_diagnosis", "report"]
ExportFormat = Literal["pdf", "docx", "html"]

_JOB_DIR = Path(__file__).resolve().parents[2] / "storage" / "export_jobs"
_JOB_TTL_SECONDS = 3600
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="export-job")
_lock = threading.Lock()
_jobs: dict[str, dict[str, Any]] = {}


def _ensure_dir() -> Path:
    _JOB_DIR.mkdir(parents=True, exist_ok=True)
    return _JOB_DIR


def _meta_path(job_id: str) -> Path:
    return _ensure_dir() / f"{job_id}.json"


def _bin_path(job_id: str) -> Path:
    return _ensure_dir() / f"{job_id}.bin"


def _fingerprint_key(fingerprint: str) -> str:
    return f"export_job_fp:{fingerprint}"


def _fp_index_path(fingerprint: str) -> Path:
    return _ensure_dir() / f"fp-{fingerprint}.json"


def _molizhishu_asset_stamp() -> str:
    """母版图变更时失效导出缓存。"""
    assets = Path(__file__).resolve().parents[1] / "templates" / "report_molizhishu" / "assets"
    parts: list[str] = []
    for name in ("idea-light.png", "idea-dark.jpg", "idea-cover.jpg"):
        path = assets / name
        try:
            st = path.stat()
            parts.append(f"{name}:{st.st_mtime_ns}:{st.st_size}")
        except OSError:
            parts.append(f"{name}:0")
    # 与 PDF 导出链路版本对齐，避免旧 Chromium-pdf 缓存
    try:
        from app.services.report_molizhishu_pdf_service import _PDF_PIPELINE

        parts.append(f"pipeline:{_PDF_PIPELINE}")
    except Exception:
        parts.append("pipeline:unknown")
    return "|".join(parts)


def _save_meta(meta: dict[str, Any]) -> None:
    job_id = str(meta["job_id"])
    with _lock:
        _jobs[job_id] = dict(meta)
    _meta_path(job_id).write_text(json.dumps(meta, ensure_ascii=False, default=str), encoding="utf-8")
    set_json_cache(f"export_job:{job_id}", meta, ttl_seconds=_JOB_TTL_SECONDS)
    fp = meta.get("fingerprint")
    if fp and meta.get("status") == "ready":
        set_json_cache(_fingerprint_key(str(fp)), {"job_id": job_id}, ttl_seconds=_JOB_TTL_SECONDS)
        try:
            _fp_index_path(str(fp)).write_text(
                json.dumps({"job_id": job_id}, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError:
            logger.warning("write export fingerprint index failed fp=%s", fp)


def _load_meta(job_id: str) -> dict[str, Any] | None:
    with _lock:
        cached = _jobs.get(job_id)
        if cached:
            return dict(cached)
    redis_meta = get_json_cache(f"export_job:{job_id}")
    if isinstance(redis_meta, dict) and redis_meta.get("job_id"):
        with _lock:
            _jobs[job_id] = dict(redis_meta)
        return dict(redis_meta)
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
        "kind": meta.get("kind"),
        "ref_id": meta.get("ref_id"),
        "format": meta.get("format"),
        "filename": meta.get("filename"),
        "mime": meta.get("mime"),
        "error": meta.get("error"),
        "cached": bool(meta.get("cached")),
        "progress": meta.get("progress") or "",
        "progress_pct": meta.get("progress_pct"),
        "created_at": meta.get("created_at"),
        "finished_at": meta.get("finished_at"),
    }


_progress_tls = threading.local()


def report_export_progress(label: str, pct: int | None = None) -> None:
    """供 PDF/导出链路上报阶段文案（同线程内有效）。"""
    fn = getattr(_progress_tls, "fn", None)
    if callable(fn):
        fn(label, pct)


def _lead_fingerprint(db, lead_id: int, export_format: str, theme: str) -> str:
    from app.models.lead_diagnosis import LeadDiagnosis

    row = db.get(LeadDiagnosis, lead_id)
    stamp = ""
    if row is not None:
        stamp = f"{row.updated_at}|{row.status}|{bool(row.diagnosis_result_json)}"
    asset = _molizhishu_asset_stamp() if export_format == "pdf" else ""
    raw = f"lead|{lead_id}|{export_format}|{theme}|{stamp}|{asset}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:40]


def _report_fingerprint(db, report_id: int, export_format: str, theme: str) -> str:
    from app.models.report import GeoReport

    row = db.get(GeoReport, report_id)
    stamp = ""
    if row is not None:
        stamp = f"{row.updated_at}|{row.status}|{row.report_type}"
    asset = _molizhishu_asset_stamp() if export_format == "pdf" else ""
    raw = f"report|{report_id}|{export_format}|{theme}|{stamp}|{asset}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:40]


def _load_report_payload(db, report_id: int) -> dict[str, Any]:
    from sqlalchemy import select

    from app.models.report import GeoReport
    from app.models.tenant import Tenant
    from app.services.report_service import (
        _sanitize_report_content,
        _serialize_report_row,
        _tenant_brand_name,
    )

    report = db.scalar(select(GeoReport).where(GeoReport.id == report_id, GeoReport.deleted.is_(False)))
    if report is None:
        raise ValueError("报告不存在")
    tenant = db.scalar(select(Tenant).where(Tenant.id == report.tenant_id, Tenant.deleted.is_(False)))
    payload = _serialize_report_row(report, tenant.name if tenant else None)
    brand_name = str((report.report_content_json or {}).get("brand_name") or _tenant_brand_name(db, report.tenant_id))
    payload["report_content"] = _sanitize_report_content(
        report.report_content_json,
        brand_name=brand_name,
        report_type=report.report_type,
    )
    return payload


def _reuse_ready_job(fingerprint: str, owner_user_id: int | None) -> dict[str, Any] | None:
    hit = get_json_cache(_fingerprint_key(fingerprint))
    job_id = hit.get("job_id") if isinstance(hit, dict) else None
    if not job_id:
        # 磁盘指纹索引（重启后仍可用）
        idx = _fp_index_path(fingerprint)
        if idx.is_file():
            try:
                payload = json.loads(idx.read_text(encoding="utf-8"))
                job_id = payload.get("job_id") if isinstance(payload, dict) else None
            except (OSError, json.JSONDecodeError):
                job_id = None
    if not job_id:
        with _lock:
            for meta in _jobs.values():
                if meta.get("fingerprint") == fingerprint and meta.get("status") == "ready":
                    job_id = meta.get("job_id")
                    break
    if not job_id:
        # 兼容旧缓存：扫 meta 落盘（仅少量文件）
        try:
            for path in _ensure_dir().glob("*.json"):
                if path.name.startswith("fp-"):
                    continue
                try:
                    meta = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                if (
                    isinstance(meta, dict)
                    and meta.get("fingerprint") == fingerprint
                    and meta.get("status") == "ready"
                ):
                    job_id = meta.get("job_id")
                    break
        except OSError:
            pass
    if not job_id:
        return None
    meta = _load_meta(str(job_id))
    if not meta or meta.get("status") != "ready":
        return None
    if not _bin_path(str(job_id)).is_file():
        return None
    del owner_user_id  # 同指纹文件可跨账号只读复用
    out = dict(meta)
    out["cached"] = True
    return out


def _run_job(job_id: str) -> None:
    meta = _load_meta(job_id)
    if not meta:
        return
    meta["status"] = "running"
    meta["error"] = None
    meta["progress"] = "内容写入中…"
    meta["progress_pct"] = 5
    _save_meta(meta)

    def _on_progress(label: str, pct: int | None = None) -> None:
        cur = _load_meta(job_id) or meta
        cur["progress"] = label
        if pct is not None:
            cur["progress_pct"] = int(pct)
        cur["status"] = "running"
        _save_meta(cur)

    _progress_tls.fn = _on_progress
    db = SessionLocal()
    try:
        kind = meta["kind"]
        export_format = meta["format"]
        theme = meta.get("theme") or "b"
        ref_id = int(meta["ref_id"])
        _on_progress("内容写入中…", 10)
        if kind == "lead_diagnosis":
            from app.services.lead_diagnosis_service import build_lead_diagnosis_export

            content, filename, mime = build_lead_diagnosis_export(
                db, ref_id, export_format=export_format, current=None
            )
        elif kind == "report":
            from app.services.report_export_service import build_report_export

            detail = _load_report_payload(db, ref_id)
            _on_progress("内容写入中…", 25)
            content, filename, mime = build_report_export(detail, export_format, db=db, theme=theme)
        else:
            raise ValueError(f"unknown export kind: {kind}")

        if export_format == "pdf":
            _on_progress("PDF生成中…", 95)
        else:
            _on_progress("生成中…", 95)
        payload = content.encode("utf-8") if isinstance(content, str) else content
        _bin_path(job_id).write_bytes(payload)
        meta = _load_meta(job_id) or meta
        meta["status"] = "ready"
        meta["filename"] = filename
        meta["mime"] = mime
        meta["finished_at"] = time.time()
        meta["bytes"] = len(payload)
        meta["progress"] = "完成"
        meta["progress_pct"] = 100
        _save_meta(meta)
        logger.info("export job ready job_id=%s kind=%s ref=%s bytes=%s", job_id, kind, ref_id, len(payload))
    except Exception as exc:
        logger.exception("export job failed job_id=%s", job_id)
        meta = _load_meta(job_id) or meta
        meta["status"] = "failed"
        meta["error"] = str(exc)
        meta["finished_at"] = time.time()
        meta["progress"] = "失败"
        _save_meta(meta)
    finally:
        _progress_tls.fn = None
        db.close()


def start_export_job(
    *,
    kind: ExportKind,
    ref_id: int,
    export_format: ExportFormat,
    owner_user_id: int | None,
    theme: str = "b",
) -> dict[str, Any]:
    db = SessionLocal()
    try:
        if kind == "lead_diagnosis":
            fingerprint = _lead_fingerprint(db, ref_id, export_format, theme)
        else:
            fingerprint = _report_fingerprint(db, ref_id, export_format, theme)
    finally:
        db.close()

    reused = _reuse_ready_job(fingerprint, owner_user_id)
    if reused:
        return _public_meta(reused)

    job_id = uuid.uuid4().hex
    meta = {
        "job_id": job_id,
        "status": "queued",
        "kind": kind,
        "ref_id": ref_id,
        "format": export_format,
        "theme": theme,
        "fingerprint": fingerprint,
        "owner_user_id": owner_user_id,
        "filename": None,
        "mime": None,
        "error": None,
        "cached": False,
        "progress": "内容写入中…",
        "progress_pct": 0,
        "created_at": time.time(),
        "finished_at": None,
    }
    _save_meta(meta)
    _executor.submit(_run_job, job_id)
    return _public_meta(meta)


def get_export_job(job_id: str) -> dict[str, Any] | None:
    meta = _load_meta(job_id)
    return _public_meta(meta) if meta else None


def read_export_job_file(job_id: str) -> tuple[bytes, str, str]:
    meta = _load_meta(job_id)
    if not meta:
        raise FileNotFoundError("导出任务不存在")
    if meta.get("status") != "ready":
        raise ValueError(f"导出尚未完成：{meta.get('status')}")
    path = _bin_path(job_id)
    if not path.is_file():
        raise FileNotFoundError("导出文件已过期或不存在")
    filename = str(meta.get("filename") or f"export-{job_id}.bin")
    mime = str(meta.get("mime") or "application/octet-stream")
    return path.read_bytes(), filename, mime
