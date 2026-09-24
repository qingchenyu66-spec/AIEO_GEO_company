"""GEO 选词历史: 平台运营任务落主库."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentSession, require_platform
from app.models.keyword_miner import GeoKeywordMinerJob
from app.schemas.keyword_miner import KeywordMinerJobUpsertRequest
from app.services.menu_permission_service import has_any_identity_menu_permission

MENU_CODE = "platform.keyword_miner"
HISTORY_KEEP = 200


def _require_access(db: Session, current: CurrentSession) -> None:
    require_platform(current)
    if not has_any_identity_menu_permission(
        db,
        current.identity.id,
        MENU_CODE,
        ("can_export", "can_create", "can_update"),
    ):
        raise PermissionError("当前账号无权使用 GEO选词")


def _ts_to_dt(ts: float | None) -> datetime | None:
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(float(ts), UTC).replace(tzinfo=None)
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def _dt_to_ts(value: datetime | None) -> float | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.timestamp()


def _summary_from_result(result: dict | None) -> dict:
    if not isinstance(result, dict):
        return {
            "selection_count": 0,
            "expansion_count": 0,
            "task": "",
            "platforms": [],
            "source": "",
            "model": "",
            "top_words": [],
        }
    sel = result.get("selection") or []
    exp = result.get("expansion") or {}
    exp_n = sum(len(v or []) for v in exp.values()) if isinstance(exp, dict) else 0
    meta = result.get("meta") or {}
    tops = [
        str(x.get("word") or "")
        for x in sorted(sel, key=lambda z: -int(z.get("score") or 0))[:5]
        if isinstance(x, dict) and x.get("word")
    ]
    return {
        "selection_count": len(sel) if isinstance(sel, list) else 0,
        "expansion_count": exp_n,
        "task": str(meta.get("task") or ""),
        "platforms": list(meta.get("platforms") or []),
        "source": str(result.get("source") or ""),
        "model": str(result.get("model") or ""),
        "top_words": tops,
    }


def _serialize_list_item(row: GeoKeywordMinerJob) -> dict:
    platforms = row.platforms_json if isinstance(row.platforms_json, list) else []
    top_words = row.top_words_json if isinstance(row.top_words_json, list) else []
    return {
        "job_id": row.job_id,
        "status": row.status,
        "company": row.company or "",
        "product": row.product or "",
        "created_at": _dt_to_ts(row.job_created_at or row.created_at),
        "updated_at": _dt_to_ts(row.job_updated_at or row.updated_at),
        "error": row.error,
        "has_result": bool(row.result_json),
        "selection_count": int(row.selection_count or 0),
        "expansion_count": int(row.expansion_count or 0),
        "task": row.task or "",
        "platforms": platforms,
        "source": row.source or "",
        "model": row.model or "",
        "top_words": top_words,
    }


def _serialize_detail(row: GeoKeywordMinerJob) -> dict:
    out = _serialize_list_item(row)
    if row.payload_json is not None:
        out["payload"] = row.payload_json
    if row.status == "done" and row.result_json is not None:
        out["result"] = row.result_json
    return out


def _prune_old(db: Session) -> None:
    ids = list(
        db.scalars(
            select(GeoKeywordMinerJob.id)
            .order_by(GeoKeywordMinerJob.job_updated_at.desc(), GeoKeywordMinerJob.id.desc())
            .offset(HISTORY_KEEP)
        ).all()
    )
    if not ids:
        return
    for row in db.scalars(select(GeoKeywordMinerJob).where(GeoKeywordMinerJob.id.in_(ids))).all():
        db.delete(row)


def list_jobs(db: Session, current: CurrentSession, *, limit: int = 50) -> list[dict]:
    _require_access(db, current)
    limit = max(1, min(int(limit or 50), 200))
    rows = db.scalars(
        select(GeoKeywordMinerJob)
        .order_by(GeoKeywordMinerJob.job_updated_at.desc(), GeoKeywordMinerJob.id.desc())
        .limit(limit)
    ).all()
    return [_serialize_list_item(r) for r in rows]


def get_job(db: Session, current: CurrentSession, job_id: str) -> dict:
    _require_access(db, current)
    row = db.scalar(select(GeoKeywordMinerJob).where(GeoKeywordMinerJob.job_id == job_id))
    if row is None:
        raise LookupError("记录不存在")
    return _serialize_detail(row)


def upsert_job(
    db: Session,
    current: CurrentSession,
    job_id: str,
    payload: KeywordMinerJobUpsertRequest,
) -> dict:
    _require_access(db, current)
    job_id = (job_id or "").strip()
    if not job_id or len(job_id) > 64:
        raise ValueError("job_id 无效")
    status = (payload.status or "").strip().lower()
    if status not in {"queued", "running", "done", "error"}:
        raise ValueError("status 无效")

    summary = _summary_from_result(payload.result)
    if payload.selection_count is not None:
        summary["selection_count"] = int(payload.selection_count)
    if payload.expansion_count is not None:
        summary["expansion_count"] = int(payload.expansion_count)
    if payload.task is not None:
        summary["task"] = str(payload.task or "")
    if payload.platforms is not None:
        summary["platforms"] = list(payload.platforms)
    if payload.source is not None:
        summary["source"] = str(payload.source or "")
    if payload.model is not None:
        summary["model"] = str(payload.model or "")
    if payload.top_words is not None:
        summary["top_words"] = list(payload.top_words)

    if not summary.get("task") and isinstance(payload.payload, dict):
        summary["task"] = str(payload.payload.get("task") or "")
    if not summary.get("platforms") and isinstance(payload.payload, dict):
        plats = payload.payload.get("platforms")
        if isinstance(plats, list):
            summary["platforms"] = list(plats)

    row = db.scalar(select(GeoKeywordMinerJob).where(GeoKeywordMinerJob.job_id == job_id))
    now = datetime.now(UTC).replace(tzinfo=None)
    job_created = _ts_to_dt(payload.created_at) or now
    job_updated = _ts_to_dt(payload.updated_at) or now

    if row is None:
        row = GeoKeywordMinerJob(
            job_id=job_id,
            status=status,
            company=(payload.company or "")[:200],
            product=(payload.product or "")[:200],
            error=payload.error,
            payload_json=payload.payload,
            result_json=payload.result if payload.result is not None else None,
            selection_count=int(summary["selection_count"] or 0),
            expansion_count=int(summary["expansion_count"] or 0),
            task=str(summary.get("task") or "")[:40],
            platforms_json=summary.get("platforms") or [],
            source=str(summary.get("source") or "")[:40],
            model=str(summary.get("model") or "")[:80],
            top_words_json=summary.get("top_words") or [],
            created_by_user_id=current.user.id,
            created_by_identity_id=current.identity.id,
            job_created_at=job_created,
            job_updated_at=job_updated,
        )
        db.add(row)
    else:
        row.status = status
        row.company = (payload.company or row.company or "")[:200]
        row.product = (payload.product or row.product or "")[:200]
        row.error = payload.error
        if payload.payload is not None:
            row.payload_json = payload.payload
        if payload.result is not None:
            row.result_json = payload.result
        row.selection_count = int(summary["selection_count"] or 0)
        row.expansion_count = int(summary["expansion_count"] or 0)
        row.task = str(summary.get("task") or "")[:40]
        row.platforms_json = summary.get("platforms") or []
        row.source = str(summary.get("source") or "")[:40]
        row.model = str(summary.get("model") or "")[:80]
        row.top_words_json = summary.get("top_words") or []
        if row.job_created_at is None:
            row.job_created_at = job_created
        row.job_updated_at = job_updated

    _prune_old(db)
    db.flush()
    return _serialize_detail(row)
