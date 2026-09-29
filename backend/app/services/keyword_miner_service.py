"""GEO 选词历史与范例库: 平台运营落主库."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentSession, require_platform
from app.models.keyword_miner import GeoKeywordMinerExample, GeoKeywordMinerJob
from app.schemas.keyword_miner import (
    KeywordMinerExampleBatchRequest,
    KeywordMinerExampleUpdateRequest,
    KeywordMinerJobEditRequest,
    KeywordMinerJobUpsertRequest,
)
from app.services.menu_permission_service import has_any_identity_menu_permission
from app.services.operation_log_service import write_operation_log

MENU_CODE = "platform.keyword_miner"
WORKBENCH_MENU = "platform.keyword_miner.workbench"
EXAMPLES_MENU = "platform.keyword_miner.examples"
HISTORY_KEEP = 200
# 挖词进程重启或浏览器离开后, 主库可能残留 queued/running
STALE_JOB_SECONDS = 2 * 3600
AUDIT_MODULE = "GEO选词"


def _audit(
    db: Session,
    current: CurrentSession,
    action_type: str,
    description: str,
    *,
    target_id: int | None = None,
) -> None:
    write_operation_log(
        db,
        current,
        action_type,
        description,
        target_module=AUDIT_MODULE,
        target_id=target_id,
        risk_level="普通",
    )


def _summarize_edit_notes(notes: list[dict] | None, *, limit: int = 6) -> str:
    rows: list[str] = []
    for note in notes or []:
        if not isinstance(note, dict):
            continue
        old_word = str(note.get("old_word") or "").strip()
        new_word = str(note.get("word") or "").strip()
        reason = str(note.get("reason") or "").strip()
        kind = str(note.get("kind") or "").strip()
        stage = str(note.get("stage") or "").strip()
        if not (old_word or new_word):
            continue
        if old_word and new_word and old_word != new_word:
            piece = f"「{old_word}」→「{new_word}」"
        else:
            piece = f"「{new_word or old_word}」"
        if kind == "expand" and stage:
            piece = f"{stage}/{piece}"
        if reason:
            piece = f"{piece}（{reason}）"
        rows.append(piece)
        if len(rows) >= limit:
            break
    if not rows:
        return "保存修订"
    extra = max(0, len(notes or []) - len(rows))
    text = "；".join(rows)
    if extra:
        text = f"{text} 等共 {len(notes or [])} 条"
    return text


def _require_workbench(db: Session, current: CurrentSession) -> None:
    require_platform(current)
    ok = has_any_identity_menu_permission(
        db, current.identity.id, MENU_CODE, ("can_export", "can_create", "can_update")
    ) or has_any_identity_menu_permission(
        db, current.identity.id, WORKBENCH_MENU, ("can_export", "can_create", "can_update")
    )
    if not ok:
        raise PermissionError("当前账号无权使用 GEO选词台")


def _require_examples(db: Session, current: CurrentSession, *, need_update: bool = False) -> None:
    require_platform(current)
    # 读: 打开/导出即可; 写: 必须 can_update 或 can_create (不再与读权限集合相同)
    actions = ("can_update", "can_create") if need_update else ("can_export", "can_create", "can_update")
    if not has_any_identity_menu_permission(db, current.identity.id, EXAMPLES_MENU, actions):
        # 兼容: 旧账号仅有父菜单时也能进范例库(迁移后会拷贝授权)
        if not has_any_identity_menu_permission(db, current.identity.id, MENU_CODE, actions):
            raise PermissionError("当前账号无权使用 GEO选词范例库")


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
        "has_edited_result": bool(row.edited_result_json),
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
    if row.edited_result_json is not None:
        out["edited_result"] = row.edited_result_json
    if row.edit_notes_json is not None:
        out["edit_notes"] = row.edit_notes_json
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


def finalize_stale_jobs(db: Session, *, older_than_seconds: int = STALE_JOB_SECONDS) -> int:
    """把超时仍停在 queued/running 的主库任务收成 error, 避免历史列表僵尸."""
    cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=max(60, int(older_than_seconds)))
    rows = list(
        db.scalars(
            select(GeoKeywordMinerJob).where(
                GeoKeywordMinerJob.status.in_(("queued", "running")),
                or_(
                    and_(
                        GeoKeywordMinerJob.job_updated_at.is_not(None),
                        GeoKeywordMinerJob.job_updated_at < cutoff,
                    ),
                    and_(
                        GeoKeywordMinerJob.job_updated_at.is_(None),
                        GeoKeywordMinerJob.updated_at < cutoff,
                    ),
                ),
            )
        ).all()
    )
    now = datetime.now(UTC).replace(tzinfo=None)
    for row in rows:
        row.status = "error"
        row.error = row.error or "任务超时未完成 (可能挖词服务重启或浏览器中断), 请重新生成"
        row.job_updated_at = now
    return len(rows)


def list_jobs(db: Session, current: CurrentSession, *, limit: int = 50) -> list[dict]:
    _require_workbench(db, current)
    if finalize_stale_jobs(db):
        db.flush()
    limit = max(1, min(int(limit or 50), 200))
    rows = db.scalars(
        select(GeoKeywordMinerJob)
        .order_by(GeoKeywordMinerJob.job_updated_at.desc(), GeoKeywordMinerJob.id.desc())
        .limit(limit)
    ).all()
    return [_serialize_list_item(r) for r in rows]


def get_job(db: Session, current: CurrentSession, job_id: str) -> dict:
    _require_workbench(db, current)
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
    _require_workbench(db, current)
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
            edited_result_json=payload.edited_result,
            edit_notes_json=payload.edit_notes,
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
        if payload.edited_result is not None:
            row.edited_result_json = payload.edited_result
        if payload.edit_notes is not None:
            row.edit_notes_json = payload.edit_notes
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

    finalize_stale_jobs(db)
    _prune_old(db)
    db.flush()
    return _serialize_detail(row)


def save_job_edits(
    db: Session,
    current: CurrentSession,
    job_id: str,
    payload: KeywordMinerJobEditRequest,
) -> dict:
    """另存修订结果与改因, 不覆盖原始 result_json."""
    _require_workbench(db, current)
    if not has_any_identity_menu_permission(
        db, current.identity.id, WORKBENCH_MENU, ("can_update",)
    ) and not has_any_identity_menu_permission(
        db, current.identity.id, MENU_CODE, ("can_update",)
    ):
        raise PermissionError("当前账号无权保存修订")
    row = db.scalar(select(GeoKeywordMinerJob).where(GeoKeywordMinerJob.job_id == job_id))
    if row is None:
        raise LookupError("记录不存在")
    if not isinstance(payload.edited_result, dict):
        raise ValueError("edited_result 无效")
    row.edited_result_json = payload.edited_result
    row.edit_notes_json = list(payload.edit_notes or [])
    row.job_updated_at = datetime.now(UTC).replace(tzinfo=None)
    company = (row.company or "").strip() or "未命名企业"
    detail = _summarize_edit_notes(list(payload.edit_notes or []))
    _audit(
        db,
        current,
        "修订选词",
        f"修订选词任务 {job_id}（{company}）：{detail}",
        target_id=row.id,
    )
    db.flush()
    return _serialize_detail(row)


def _example_hash(*, kind: str, industry: str, stage: str, word: str) -> str:
    raw = f"{kind}|{industry.strip().lower()}|{stage.strip()}|{word.strip()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _serialize_example(row: GeoKeywordMinerExample) -> dict:
    return {
        "id": row.id,
        "kind": row.kind,
        "industry": row.industry or "",
        "product_tags": row.product_tags if isinstance(row.product_tags, list) else [],
        "stage": row.stage or "",
        "word": row.word or "",
        "answer": row.answer or "",
        "intent": row.intent or "",
        "heat": row.heat,
        "note": row.note or "",
        "edit_reason": row.edit_reason or "",
        "status": row.status,
        "source_job_id": row.source_job_id,
        "source_company": row.source_company or "",
        "source_product": row.source_product or "",
        "use_count": int(row.use_count or 0),
        "created_at": _dt_to_ts(row.created_at),
        "updated_at": _dt_to_ts(row.updated_at),
    }


def list_examples(
    db: Session,
    current: CurrentSession,
    *,
    kind: str | None = None,
    industry: str | None = None,
    status: str | None = "active",
    q: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict:
    _require_examples(db, current)
    stmt = select(GeoKeywordMinerExample).order_by(
        GeoKeywordMinerExample.updated_at.desc(), GeoKeywordMinerExample.id.desc()
    )
    if kind:
        stmt = stmt.where(GeoKeywordMinerExample.kind == kind.strip())
    if industry:
        stmt = stmt.where(GeoKeywordMinerExample.industry == industry.strip())
    if status:
        stmt = stmt.where(GeoKeywordMinerExample.status == status.strip())
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                GeoKeywordMinerExample.word.like(like),
                GeoKeywordMinerExample.answer.like(like),
                GeoKeywordMinerExample.edit_reason.like(like),
            )
        )
    page_limit = max(1, min(int(limit or 100), 500))
    page_offset = max(0, int(offset or 0))
    id_stmt = stmt.with_only_columns(GeoKeywordMinerExample.id).order_by(None)
    total = int(db.scalar(select(func.count()).select_from(id_stmt.subquery())) or 0)
    rows = db.scalars(stmt.offset(page_offset).limit(page_limit)).all()
    return {
        "items": [_serialize_example(r) for r in rows],
        "total": total,
        "limit": page_limit,
        "offset": page_offset,
    }


def match_examples(
    db: Session,
    current: CurrentSession,
    *,
    industry: str = "",
    product: str = "",
    kind: str | None = None,
    limit: int = 6,
) -> dict:
    """生成前检索范例 + 改因提醒. 工作台或范例库权限均可调用."""
    try:
        _require_workbench(db, current)
    except PermissionError:
        _require_examples(db, current)

    limit = max(1, min(int(limit or 6), 20))
    industry = (industry or "").strip()
    product = (product or "").strip()
    stmt = select(GeoKeywordMinerExample).where(GeoKeywordMinerExample.status == "active")
    if kind:
        stmt = stmt.where(GeoKeywordMinerExample.kind == kind.strip())
    if industry:
        stmt = stmt.where(
            or_(
                GeoKeywordMinerExample.industry == industry,
                GeoKeywordMinerExample.industry == "",
            )
        )
    rows = list(
        db.scalars(
            stmt.order_by(
                GeoKeywordMinerExample.use_count.desc(),
                GeoKeywordMinerExample.updated_at.desc(),
            ).limit(80)
        ).all()
    )

    def _score(row: GeoKeywordMinerExample) -> int:
        score = 0
        if industry and row.industry == industry:
            score += 100
        tags = row.product_tags if isinstance(row.product_tags, list) else []
        if product and any(product in str(t) or str(t) in product for t in tags):
            score += 40
        if product and product in (row.source_product or ""):
            score += 20
        score += min(int(row.use_count or 0), 30)
        return score

    rows.sort(key=_score, reverse=True)
    picked = rows[:limit]
    # match 只检索, 不改 use_count (避免 GET 非幂等虚增)

    lessons: list[str] = []
    for row in picked:
        reason = (row.edit_reason or "").strip()
        if reason and reason not in lessons:
            lessons.append(reason)
        if len(lessons) >= 8:
            break

    return {
        "items": [_serialize_example(r) for r in picked],
        "edit_lessons": lessons,
    }


def touch_examples(db: Session, current: CurrentSession, ids: list[int]) -> dict:
    """生成时真正注入范例后 +1 use_count."""
    _require_workbench(db, current)
    cleaned: list[int] = []
    for raw in ids or []:
        try:
            n = int(raw)
        except (TypeError, ValueError):
            continue
        if n > 0:
            cleaned.append(n)
    cleaned = list(dict.fromkeys(cleaned))[:50]
    if not cleaned:
        return {"updated": 0, "ids": []}
    rows = list(
        db.scalars(
            select(GeoKeywordMinerExample).where(
                GeoKeywordMinerExample.id.in_(cleaned),
                GeoKeywordMinerExample.status == "active",
            )
        ).all()
    )
    for row in rows:
        row.use_count = int(row.use_count or 0) + 1
    db.flush()
    return {"updated": len(rows), "ids": [r.id for r in rows]}


def batch_create_examples(
    db: Session,
    current: CurrentSession,
    payload: KeywordMinerExampleBatchRequest,
) -> dict:
    _require_examples(db, current, need_update=True)
    if not payload.items:
        raise ValueError("items 不能为空")
    if len(payload.items) > 200:
        raise ValueError("单次最多入库 200 条")
    industry = (payload.industry or "").strip()[:80]
    created = 0
    skipped = 0
    out_ids: list[int] = []
    for item in payload.items:
        kind = (item.kind or "").strip().lower()
        if kind not in {"select", "expand"}:
            skipped += 1
            continue
        word = (item.word or "").strip()
        if not word:
            skipped += 1
            continue
        stage = (item.stage or item.intent or "")[:40]
        digest = _example_hash(kind=kind, industry=industry, stage=stage, word=word)
        exists = db.scalar(
            select(GeoKeywordMinerExample).where(GeoKeywordMinerExample.content_hash == digest)
        )
        if exists is not None:
            skipped += 1
            out_ids.append(exists.id)
            continue
        row = GeoKeywordMinerExample(
            kind=kind,
            industry=industry,
            product_tags=list(item.product_tags or []),
            stage=stage,
            word=word[:255],
            answer=(item.answer or "")[:4000] or None,
            intent=(item.intent or None),
            heat=item.heat,
            note=(item.note or None),
            edit_reason=(item.edit_reason or None),
            status="active",
            source_job_id=(payload.source_job_id or None),
            source_company=(payload.source_company or "")[:200] or None,
            source_product=(payload.source_product or "")[:200] or None,
            content_hash=digest,
            use_count=0,
            created_by_user_id=current.user.id,
            created_by_identity_id=current.identity.id,
        )
        db.add(row)
        db.flush()
        created += 1
        out_ids.append(row.id)
    if created:
        sample = "、".join(
            (item.word or "").strip()
            for item in payload.items
            if (item.word or "").strip()
        )[:180]
        company = (payload.source_company or "").strip()
        prefix = f"入库范例 {created} 条"
        if company:
            prefix = f"{prefix}（来源 {company}）"
        _audit(db, current, "入库范例", f"{prefix}：{sample}" if sample else prefix)
    return {"created": created, "skipped": skipped, "ids": out_ids}


def _require_examples_actions(
    db: Session,
    current: CurrentSession,
    actions: tuple[str, ...],
) -> None:
    require_platform(current)
    if not has_any_identity_menu_permission(db, current.identity.id, EXAMPLES_MENU, actions):
        if not has_any_identity_menu_permission(db, current.identity.id, MENU_CODE, actions):
            raise PermissionError("当前账号无权维护 GEO选词范例库")


def update_example(
    db: Session,
    current: CurrentSession,
    example_id: int,
    payload: KeywordMinerExampleUpdateRequest,
) -> dict:
    # 停用/启用走 can_delete (兼容仅有 can_update 的旧授权)
    if payload.status is not None:
        _require_examples_actions(db, current, ("can_delete", "can_update"))
    else:
        _require_examples(db, current, need_update=True)
    row = db.get(GeoKeywordMinerExample, int(example_id))
    if row is None:
        raise LookupError("范例不存在")
    before_word = (row.word or "").strip()
    before_status = row.status
    if payload.industry is not None:
        row.industry = payload.industry.strip()[:80]
    if payload.stage is not None:
        row.stage = payload.stage.strip()[:40]
    if payload.word is not None:
        word = payload.word.strip()
        if not word:
            raise ValueError("word 不能为空")
        row.word = word[:255]
    if payload.answer is not None:
        row.answer = payload.answer
    if payload.intent is not None:
        row.intent = payload.intent
    if payload.heat is not None:
        row.heat = payload.heat
    if payload.note is not None:
        row.note = payload.note
    if payload.edit_reason is not None:
        row.edit_reason = payload.edit_reason[:500]
    if payload.status is not None:
        st = payload.status.strip().lower()
        if st not in {"active", "disabled"}:
            raise ValueError("status 无效")
        row.status = st
    if payload.product_tags is not None:
        row.product_tags = list(payload.product_tags)
    row.content_hash = _example_hash(
        kind=row.kind, industry=row.industry or "", stage=row.stage or "", word=row.word or ""
    )
    after_word = (row.word or "").strip()
    if payload.status is not None and row.status != before_status:
        label = "启用" if row.status == "active" else "停用"
        _audit(
            db,
            current,
            f"{label}范例",
            f"{label}范例「{after_word or before_word}」(id={row.id})",
            target_id=row.id,
        )
    elif after_word and after_word != before_word:
        _audit(
            db,
            current,
            "维护范例",
            f"修改范例词「{before_word}」→「{after_word}」(id={row.id})",
            target_id=row.id,
        )
    else:
        _audit(
            db,
            current,
            "维护范例",
            f"更新范例「{after_word or before_word}」(id={row.id})",
            target_id=row.id,
        )
    db.flush()
    return _serialize_example(row)


def format_examples_for_prompt(items: list[dict], *, kind: str) -> str:
    """给选词服务注入的文本块."""
    if not items:
        return ""
    if kind == "expand":
        by_stage: dict[str, list[dict]] = {}
        for it in items:
            stage = str(it.get("stage") or "通用")
            by_stage.setdefault(stage, []).append(
                {
                    "word": it.get("word"),
                    "heat": it.get("heat") or 80,
                    "answer": it.get("answer") or "",
                }
            )
        blob = json.dumps({"expansion": by_stage}, ensure_ascii=False)
        return f"【运营范例库样本】\n{blob}"
    rows = [
        {
            "word": it.get("word"),
            "category": it.get("stage") or "长尾词",
            "intent": it.get("intent") or "信息型",
            "score": 85,
            "reason": it.get("note") or it.get("edit_reason") or "",
        }
        for it in items
    ]
    blob = json.dumps({"selection": rows}, ensure_ascii=False)
    return f"【运营范例库样本】\n{blob}"
