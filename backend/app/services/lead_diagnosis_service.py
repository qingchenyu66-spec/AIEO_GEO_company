"""售前线索诊断：三时段抓取、汇总统计、PDF 导出。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any, Iterator

from sqlalchemy import desc, select
from sqlalchemy.orm import Session, selectinload

from app.api.dependencies import CurrentSession
from app.core.config import settings
from app.models.lead_diagnosis import DEFAULT_LEAD_SCHEDULE_TIMES, LeadDiagnosis, LeadDiagnosisRun
from app.models.monitor import GeoMonitorSubtask, GeoMonitorTask
from app.schemas.lead_diagnosis import LeadDiagnosisCreateRequest, LeadDiagnosisUpdateRequest
from app.schemas.monitor import CompetitorBrand, MonitorTaskCreateRequest, PlatformConfig
from app.services.deepseek_client import DeepseekApiError, DeepseekClient
from app.services.menu_permission_service import has_identity_menu_permission
from app.services.molizhishu_catalog_service import filter_submittable_platforms, get_supported_platform_catalog
from app.services.monitor_service import TERMINAL_STATUSES, submit_standalone_monitor_task
from app.services.report_export_service import build_report_export

ACTIVE_STATUSES = {"pending", "collecting"}
RUN_TERMINAL = {"completed", "failed", "skipped"}


@dataclass(frozen=True)
class DueLeadRun:
    lead_id: int
    schedule_key: str
    schedule_label: str


def require_lead_diagnosis_access(db: Session, current: CurrentSession, action: str = "can_export") -> None:
    if current.identity.identity_type != "PLATFORM":
        raise PermissionError("仅平台运营端可访问售前诊断")
    if not has_identity_menu_permission(db, current.identity.id, "platform.lead_diagnosis", action):
        raise PermissionError("当前身份无售前诊断权限")


def _schedule_slots(lead: LeadDiagnosis) -> list[str]:
    raw = lead.schedule_times_json or DEFAULT_LEAD_SCHEDULE_TIMES
    cleaned = [str(item).strip() for item in raw if str(item).strip()]
    return cleaned or list(DEFAULT_LEAD_SCHEDULE_TIMES)


def _slot_time(value: str) -> time | None:
    text = value.strip()
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).time()
        except ValueError:
            continue
    return None


def _build_schedule_key(diagnosis_date: date, slot: str) -> tuple[str, str]:
    slot_time = _slot_time(slot)
    if slot_time is None:
        raise ValueError(f"无效时段：{slot}")
    key = f"{diagnosis_date.strftime('%Y%m%d')}-{slot_time.strftime('%H%M')}"
    label = f"{diagnosis_date.isoformat()} {slot_time.strftime('%H:%M')}"
    return key, label


def _all_platform_configs() -> list[PlatformConfig]:
    codes = filter_submittable_platforms(
        [str(item.get("code") or "") for item in get_supported_platform_catalog()]
    )
    if not codes:
        raise ValueError("未配置可提交的 AI 监测平台")
    return [PlatformConfig(platform=code) for code in codes]


def _competitor_payload(names: list[str]) -> list[CompetitorBrand]:
    return [CompetitorBrand(name=name) for name in names if name.strip()]


def _serialize_run(run: LeadDiagnosisRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "schedule_key": run.schedule_key,
        "schedule_label": run.schedule_label,
        "task_id": run.task_id,
        "status": run.status,
        "prompt_count": run.prompt_count,
        "platform_count": run.platform_count,
        "error_message": run.error_message,
        "created_at": run.created_at.isoformat(),
        "updated_at": run.updated_at.isoformat(),
    }


def _serialize_lead(lead: LeadDiagnosis, *, include_result: bool = False) -> dict[str, Any]:
    result = lead.diagnosis_result_json or {}
    kpis = result.get("kpis") or {}
    payload: dict[str, Any] = {
        "id": lead.id,
        "brand_name": lead.brand_name,
        "contact_name": lead.contact_name,
        "contact_phone": lead.contact_phone,
        "contact_note": lead.contact_note,
        "prompts": lead.prompts_json or [],
        "competitors": lead.competitors_json or [],
        "schedule_times": _schedule_slots(lead),
        "diagnosis_date": lead.diagnosis_date.isoformat(),
        "status": lead.status,
        "health_score": lead.health_score,
        "converted_tenant_id": lead.converted_tenant_id,
        "created_by_user_id": lead.created_by_user_id,
        "created_at": lead.created_at.isoformat(),
        "updated_at": lead.updated_at.isoformat(),
        "run_count": len(lead.runs or []),
        "completed_run_count": sum(1 for item in (lead.runs or []) if item.status == "completed"),
        "mention_rate": kpis.get("mention_rate"),
        "avg_rank": kpis.get("avg_rank"),
    }
    if include_result:
        payload["diagnosis_result"] = result
        payload["runs"] = [_serialize_run(item) for item in sorted(lead.runs or [], key=lambda row: row.schedule_key)]
    return payload


def list_lead_diagnoses(db: Session, current: CurrentSession, *, keyword: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
    require_lead_diagnosis_access(db, current, "can_export")
    stmt = (
        select(LeadDiagnosis)
        .where(LeadDiagnosis.deleted.is_(False))
        .options(selectinload(LeadDiagnosis.runs))
        .order_by(desc(LeadDiagnosis.id))
    )
    if status:
        stmt = stmt.where(LeadDiagnosis.status == status)
    rows = list(db.scalars(stmt))
    if keyword:
        needle = keyword.strip().lower()
        rows = [
            row for row in rows
            if needle in (row.brand_name or "").lower()
            or needle in (row.contact_name or "").lower()
            or needle in (row.contact_phone or "").lower()
        ]
    return [_serialize_lead(row) for row in rows]


def get_lead_diagnosis(db: Session, lead_id: int) -> dict[str, Any]:
    lead = db.scalar(
        select(LeadDiagnosis)
        .where(LeadDiagnosis.id == lead_id, LeadDiagnosis.deleted.is_(False))
        .options(selectinload(LeadDiagnosis.runs))
    )
    if lead is None:
        raise ValueError("售前诊断不存在")
    return _serialize_lead(lead, include_result=True)


def create_lead_diagnosis(
    db: Session,
    current: CurrentSession,
    payload: LeadDiagnosisCreateRequest,
) -> dict[str, Any]:
    require_lead_diagnosis_access(db, current, "can_create")
    diagnosis_date = payload.diagnosis_date or date.today()
    lead = LeadDiagnosis(
        brand_name=payload.brand_name.strip(),
        contact_name=(payload.contact_name or "").strip() or None,
        contact_phone=(payload.contact_phone or "").strip() or None,
        contact_note=(payload.contact_note or "").strip() or None,
        prompts_json=payload.prompts,
        competitors_json=payload.competitors,
        schedule_times_json=list(DEFAULT_LEAD_SCHEDULE_TIMES),
        diagnosis_date=diagnosis_date,
        status="pending",
        created_by_user_id=current.user.id,
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    if payload.start_immediately:
        submit_due_lead_run(db, current, lead.id, force=True)

    return get_lead_diagnosis(db, lead.id)


def update_lead_diagnosis(
    db: Session,
    current: CurrentSession,
    lead_id: int,
    payload: LeadDiagnosisUpdateRequest,
) -> dict[str, Any]:
    require_lead_diagnosis_access(db, current, "can_create")
    lead = db.scalar(select(LeadDiagnosis).where(LeadDiagnosis.id == lead_id, LeadDiagnosis.deleted.is_(False)))
    if lead is None:
        raise ValueError("售前诊断不存在")
    if payload.contact_name is not None:
        lead.contact_name = payload.contact_name.strip() or None
    if payload.contact_phone is not None:
        lead.contact_phone = payload.contact_phone.strip() or None
    if payload.contact_note is not None:
        lead.contact_note = payload.contact_note.strip() or None
    db.commit()
    return get_lead_diagnosis(db, lead_id)


def _is_slot_due(
    diagnosis_date: date,
    slot: str,
    now: datetime,
    *,
    tolerance_minutes: int,
    force: bool = False,
) -> bool:
    if diagnosis_date != now.date():
        return diagnosis_date < now.date()
    slot_time = _slot_time(slot)
    if slot_time is None:
        return False
    scheduled = datetime.combine(diagnosis_date, slot_time)
    if force:
        return now >= scheduled
    return scheduled <= now <= scheduled + timedelta(minutes=tolerance_minutes)


def enumerate_due_lead_runs(
    db: Session,
    *,
    lead_id: int | None = None,
    force: bool = False,
    now: datetime | None = None,
) -> Iterator[DueLeadRun]:
    now = now or datetime.now()
    tolerance = settings.schedule_tolerance_minutes
    stmt = (
        select(LeadDiagnosis)
        .where(LeadDiagnosis.deleted.is_(False), LeadDiagnosis.status.in_(ACTIVE_STATUSES))
        .options(selectinload(LeadDiagnosis.runs))
    )
    if lead_id:
        stmt = stmt.where(LeadDiagnosis.id == lead_id)
    for lead in db.scalars(stmt):
        if lead.diagnosis_date > now.date():
            continue
        existing_keys = {run.schedule_key for run in (lead.runs or [])}
        for slot in _schedule_slots(lead):
            schedule_key, schedule_label = _build_schedule_key(lead.diagnosis_date, slot)
            if schedule_key in existing_keys:
                continue
            if _is_slot_due(lead.diagnosis_date, slot, now, tolerance_minutes=tolerance, force=force):
                yield DueLeadRun(lead_id=lead.id, schedule_key=schedule_key, schedule_label=schedule_label)


def submit_due_lead_run(
    db: Session,
    current: CurrentSession,
    lead_id: int,
    *,
    schedule_key: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    require_lead_diagnosis_access(db, current, "can_create")
    lead = db.scalar(
        select(LeadDiagnosis)
        .where(LeadDiagnosis.id == lead_id, LeadDiagnosis.deleted.is_(False))
        .options(selectinload(LeadDiagnosis.runs))
    )
    if lead is None:
        raise ValueError("售前诊断不存在")
    if lead.status not in ACTIVE_STATUSES:
        raise ValueError("当前诊断已结束，无法继续抓取")

    due_items = list(enumerate_due_lead_runs(db, lead_id=lead_id, force=force))
    if schedule_key:
        due_items = [item for item in due_items if item.schedule_key == schedule_key]
    if not due_items and force:
        existing_keys = {run.schedule_key for run in (lead.runs or [])}
        for slot in _schedule_slots(lead):
            key, label = _build_schedule_key(lead.diagnosis_date, slot)
            if schedule_key and key != schedule_key:
                continue
            if key in existing_keys:
                continue
            due_items = [DueLeadRun(lead_id=lead.id, schedule_key=key, schedule_label=label)]
            break
    if not due_items:
        return {"status": "skipped", "message": "当前没有可提交的抓取窗口"}

    item = due_items[0]
    if db.scalar(
        select(LeadDiagnosisRun).where(
            LeadDiagnosisRun.lead_diagnosis_id == lead.id,
            LeadDiagnosisRun.schedule_key == item.schedule_key,
        )
    ):
        return {"status": "skipped", "message": "该时段已提交"}

    platforms = _all_platform_configs()
    request = MonitorTaskCreateRequest(
        monitor_keywords=lead.brand_name,
        competitors=_competitor_payload(lead.competitors_json or []),
        prompts=lead.prompts_json or [],
        platforms=platforms,
    )
    run = LeadDiagnosisRun(
        lead_diagnosis_id=lead.id,
        schedule_key=item.schedule_key,
        schedule_label=item.schedule_label,
        status="pending",
        prompt_count=len(request.prompts),
        platform_count=len(platforms),
    )
    db.add(run)
    db.flush()

    try:
        task = submit_standalone_monitor_task(db, payload=request, created_by=current.user.id)
        run.task_id = task.task_id
        run.status = "submitted"
        lead.status = "collecting"
    except Exception as exc:
        run.status = "failed"
        run.error_message = str(exc)
    db.commit()
    return {
        "status": run.status,
        "schedule_key": run.schedule_key,
        "task_id": run.task_id,
        "message": run.error_message,
    }


def _task_map(db: Session, lead: LeadDiagnosis) -> dict[str, GeoMonitorTask]:
    task_ids = [run.task_id for run in (lead.runs or []) if run.task_id]
    if not task_ids:
        return {}
    rows = list(db.scalars(select(GeoMonitorTask).where(GeoMonitorTask.task_id.in_(task_ids))))
    return {row.task_id: row for row in rows}


def refresh_lead_diagnosis_runs(db: Session, lead_id: int) -> dict[str, Any]:
    lead = db.scalar(
        select(LeadDiagnosis)
        .where(LeadDiagnosis.id == lead_id, LeadDiagnosis.deleted.is_(False))
        .options(selectinload(LeadDiagnosis.runs))
    )
    if lead is None:
        raise ValueError("售前诊断不存在")
    tasks = _task_map(db, lead)
    changed = False
    for run in lead.runs or []:
        if run.status in RUN_TERMINAL or not run.task_id:
            continue
        task = tasks.get(run.task_id)
        if task is None:
            continue
        if task.status in TERMINAL_STATUSES:
            run.status = "completed" if task.completed_items > 0 else "failed"
            if run.status == "failed" and not run.error_message:
                run.error_message = task.last_error or "监测任务未产生有效结果"
            changed = True
    if changed:
        db.commit()
    maybe_finalize_lead_diagnosis(db, lead_id)
    return get_lead_diagnosis(db, lead_id)


def _all_slots_attempted(lead: LeadDiagnosis) -> bool:
    expected = {_build_schedule_key(lead.diagnosis_date, slot)[0] for slot in _schedule_slots(lead)}
    attempted = {run.schedule_key for run in (lead.runs or [])}
    return expected.issubset(attempted)


def _runs_terminal(lead: LeadDiagnosis, tasks: dict[str, GeoMonitorTask]) -> bool:
    for run in lead.runs or []:
        if run.status in {"pending", "submitted"}:
            task = tasks.get(run.task_id or "")
            if task and task.status not in TERMINAL_STATUSES:
                return False
        if run.status == "pending":
            return False
    return bool(lead.runs)


def _after_diagnosis_deadline(lead: LeadDiagnosis, now: datetime) -> bool:
    if lead.diagnosis_date < now.date():
        return True
    if lead.diagnosis_date > now.date():
        return False
    latest_slot = max((_slot_time(slot) or time(20, 30) for slot in _schedule_slots(lead)), default=time(20, 30))
    deadline = datetime.combine(lead.diagnosis_date, latest_slot) + timedelta(hours=2)
    return now >= deadline


def maybe_finalize_lead_diagnosis(db: Session, lead_id: int) -> bool:
    lead = db.scalar(
        select(LeadDiagnosis)
        .where(LeadDiagnosis.id == lead_id, LeadDiagnosis.deleted.is_(False))
        .options(selectinload(LeadDiagnosis.runs))
    )
    if lead is None or lead.status not in ACTIVE_STATUSES:
        return False

    tasks = _task_map(db, lead)
    now = datetime.now()
    ready_by_completion = _all_slots_attempted(lead) and _runs_terminal(lead, tasks)
    ready_by_deadline = _after_diagnosis_deadline(lead, now) and bool(lead.runs)
    if not ready_by_completion and not ready_by_deadline:
        return False

    subtasks = _load_subtasks(db, lead)
    if not subtasks:
        lead.status = "failed"
        db.commit()
        return True

    result = aggregate_lead_diagnosis(lead, subtasks)
    lead.diagnosis_result_json = result
    lead.health_score = result.get("diagnosis", {}).get("health_score") or result.get("kpis", {}).get("health_score")
    lead.status = "ready"
    db.commit()
    return True


def _load_subtasks(db: Session, lead: LeadDiagnosis) -> list[GeoMonitorSubtask]:
    task_ids = [run.task_id for run in (lead.runs or []) if run.task_id and run.status != "failed"]
    if not task_ids:
        return []
    return list(
        db.scalars(
            select(GeoMonitorSubtask)
            .where(GeoMonitorSubtask.task_id.in_(task_ids))
            .order_by(GeoMonitorSubtask.id.asc())
        )
    )


def aggregate_lead_diagnosis(lead: LeadDiagnosis, subtasks: list[GeoMonitorSubtask]) -> dict[str, Any]:
    completed = [item for item in subtasks if item.status in TERMINAL_STATUSES and item.answer_content]
    mentioned = [item for item in completed if item.mention_position]
    ranks = [item.mention_position for item in mentioned if item.mention_position]
    top3 = [item for item in mentioned if item.mention_position and item.mention_position <= 3]

    sentiment_counts: dict[str, int] = {}
    for item in completed:
        key = (item.sentiment or "unknown").lower()
        sentiment_counts[key] = sentiment_counts.get(key, 0) + 1
    positive = sentiment_counts.get("positive", 0) + sentiment_counts.get("neutral", 0)
    positive_rate = round(positive / len(completed) * 100, 1) if completed else 0.0

    mention_rate = round(len(mentioned) / len(completed) * 100, 1) if completed else 0.0
    avg_rank = round(sum(ranks) / len(ranks), 1) if ranks else None
    top3_rate = round(len(top3) / len(completed) * 100, 1) if completed else 0.0

    platform_buckets: dict[str, dict[str, Any]] = {}
    matrix_cells: dict[str, dict[str, Any]] = {}
    source_map: dict[str, dict[str, Any]] = {}

    for item in completed:
        bucket = platform_buckets.setdefault(
            item.platform,
            {"platform": item.platform, "total": 0, "completed": 0, "mentioned": 0, "rank_total": 0.0, "rank_count": 0},
        )
        bucket["total"] += 1
        bucket["completed"] += 1
        if item.mention_position:
            bucket["mentioned"] += 1
            bucket["rank_total"] += item.mention_position
            bucket["rank_count"] += 1

        cell_key = f"{item.prompt}::{item.platform}"
        cell = matrix_cells.setdefault(cell_key, {"prompt": item.prompt, "platform": item.platform, "ranks": [], "mentioned": 0, "total": 0})
        cell["total"] += 1
        if item.mention_position:
            cell["mentioned"] += 1
            cell["ranks"].append(item.mention_position)

        for source in item.reference_list_json or []:
            url = source.get("url") or source.get("site") or source.get("title")
            if not url:
                continue
            key = str(url).split("?")[0]
            row = source_map.setdefault(
                key,
                {"title": source.get("title") or source.get("site") or key, "url": url, "count": 0, "platforms": []},
            )
            row["count"] += 1
            if item.platform not in row["platforms"]:
                row["platforms"].append(item.platform)

    platform_stats = []
    for bucket in platform_buckets.values():
        total = bucket["total"] or 1
        platform_stats.append({
            "platform": bucket["platform"],
            "total": bucket["total"],
            "completed": bucket["completed"],
            "mention_rate": round(bucket["mentioned"] / total * 100, 1),
            "avg_rank": round(bucket["rank_total"] / bucket["rank_count"], 1) if bucket["rank_count"] else None,
        })
    platform_stats.sort(key=lambda row: row["mention_rate"], reverse=True)

    matrix_rows = []
    for cell in matrix_cells.values():
        ranks = cell["ranks"]
        matrix_rows.append({
            "prompt": cell["prompt"],
            "platform": cell["platform"],
            "sample_count": cell["total"],
            "mention_rate": round(cell["mentioned"] / cell["total"] * 100, 1) if cell["total"] else 0.0,
            "avg_rank": round(sum(ranks) / len(ranks), 1) if ranks else None,
        })

    top_sources = sorted(source_map.values(), key=lambda row: row["count"], reverse=True)[:12]
    schedule_round_count = len({run.schedule_key for run in (lead.runs or []) if run.status == "completed"})

    kpis = {
        "mention_rate": mention_rate,
        "avg_rank": avg_rank,
        "top3_rate": top3_rate,
        "positive_rate": positive_rate,
        "completed_count": len(completed),
        "subtask_count": len(subtasks),
        "source_count": len(source_map),
        "task_count": len({item.task_id for item in completed}),
        "schedule_round_count": schedule_round_count,
    }
    health_score = _rule_health_score(kpis)
    rule_highlights = _rule_highlights(kpis, platform_stats)
    diagnosis_block = _rule_diagnosis_block(lead, kpis, rule_highlights)

    ai_insights: dict[str, Any] = {"source": "rule"}
    client = DeepseekClient()
    if client.report_enabled:
        try:
            ai = client.generate_report_insights(
                brand_name=lead.brand_name,
                company_name=lead.brand_name,
                report_type="diagnosis",
                period_label=f"{lead.diagnosis_date.isoformat()}（{schedule_round_count} 次抓取均值）",
                kpis={**kpis, "health_score": health_score},
                platform_stats=platform_stats,
                top_sources=top_sources,
                sentiment_counts=sentiment_counts,
                competitor_names=lead.competitors_json or [],
                rule_highlights=rule_highlights,
            )
            ai_insights = {"source": "deepseek", "model": client.model, **ai}
            if ai.get("health_score") is not None:
                health_score = ai["health_score"]
            diagnosis_block.update({
                "sentiment_summary": ai.get("sentiment_summary") or diagnosis_block.get("sentiment_summary"),
                "strength_points": ai.get("strength_points") or diagnosis_block.get("strength_points"),
                "weakness_points": ai.get("weakness_points") or diagnosis_block.get("weakness_points"),
                "recommendation": ai.get("recommendation") or diagnosis_block.get("recommendation"),
                "health_score": health_score,
            })
        except (DeepseekApiError, RuntimeError):
            ai_insights = {"source": "rule", "fallback_reason": "DeepSeek 不可用，已使用规则引擎"}

    diagnosis_block["health_score"] = health_score
    kpis["health_score"] = health_score

    return {
        "brand_name": lead.brand_name,
        "company_name": lead.brand_name,
        "period_label": f"{lead.diagnosis_date.isoformat()} · 三时段均值（{schedule_round_count} 次有效抓取）",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "kpis": kpis,
        "diagnosis": diagnosis_block,
        "ai_insights": ai_insights,
        "monitor_snapshot": {
            "highlights": ai_insights.get("highlights") or rule_highlights,
            "platform_stats": platform_stats,
            "top_sources": top_sources,
            "sentiment_counts": sentiment_counts,
            "matrix_rows": matrix_rows,
        },
        "runs": [_serialize_run(run) for run in sorted(lead.runs or [], key=lambda row: row.schedule_key)],
    }


def _rule_health_score(kpis: dict[str, Any]) -> int:
    mention = float(kpis.get("mention_rate") or 0)
    top3 = float(kpis.get("top3_rate") or 0)
    positive = float(kpis.get("positive_rate") or 0)
    avg_rank = kpis.get("avg_rank")
    rank_bonus = 0.0
    if avg_rank is not None:
        rank_bonus = max(0.0, 100.0 - float(avg_rank) * 12.0)
    score = mention * 0.35 + top3 * 0.25 + positive * 0.20 + rank_bonus * 0.20
    return max(0, min(100, int(round(score))))


def _rule_highlights(kpis: dict[str, Any], platform_stats: list[dict[str, Any]]) -> list[str]:
    lines = [
        f"品牌提及率 {kpis.get('mention_rate')}%，Top3 露出率 {kpis.get('top3_rate')}%。",
        f"平均推荐排名 {kpis.get('avg_rank') or '—'}，共完成 {kpis.get('completed_count')} 条有效样本。",
    ]
    if platform_stats:
        best = platform_stats[0]
        lines.append(f"表现最好平台提及率 {best.get('mention_rate')}%。")
    return lines[:5]


def _rule_diagnosis_block(lead: LeadDiagnosis, kpis: dict[str, Any], highlights: list[str]) -> dict[str, Any]:
    return {
        "diagnosis_title": f"{lead.brand_name} 售前品牌诊断",
        "health_score": _rule_health_score(kpis),
        "sentiment_summary": f"基于 {kpis.get('schedule_round_count')} 个时段抓取结果，品牌整体提及率 {kpis.get('mention_rate')}%。",
        "strength_points": highlights[0] if highlights else "品牌已在部分 AI 平台获得露出。",
        "weakness_points": "部分平台/问题场景下排名与提及率仍有提升空间，建议补充权威信源与对比内容。",
        "recommendation": "建议签约后开启持续监测，针对低提及平台补充结构化内容与第三方引用。",
    }


def build_lead_diagnosis_export(db: Session, lead_id: int, export_format: str = "pdf") -> tuple[bytes, str, str]:
    detail = get_lead_diagnosis(db, lead_id)
    if detail.get("status") != "ready":
        raise ValueError("诊断尚未完成，暂无法导出")
    result = detail.get("diagnosis_result") or {}
    report = {
        "report_title": f"{detail['brand_name']} 售前品牌诊断报告",
        "report_type": "diagnosis",
        "report_type_label": "售前诊断",
        "status_label": "已完成",
        "tenant_name": detail["brand_name"],
        "data_summary": result.get("diagnosis", {}).get("sentiment_summary"),
        "created_at": detail.get("created_at"),
        "report_content": result,
    }
    return build_report_export(report, "pdf" if export_format == "pdf" else "docx")


def finalize_due_lead_diagnoses(db: Session) -> dict[str, Any]:
    rows = list(
        db.scalars(
            select(LeadDiagnosis)
            .where(LeadDiagnosis.deleted.is_(False), LeadDiagnosis.status.in_(ACTIVE_STATUSES))
            .options(selectinload(LeadDiagnosis.runs))
        )
    )
    finalized = 0
    for lead in rows:
        if maybe_finalize_lead_diagnosis(db, lead.id):
            finalized += 1
    return {"finalized": finalized, "checked": len(rows)}
