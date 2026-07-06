"""快照补录：失败子任务粘贴分享链接 + 回答正文，重算排名并触发聚合。"""

from __future__ import annotations

from datetime import date
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentSession
from app.models.brand import BrandAsset
from app.models.lead_diagnosis import LeadDiagnosis, LeadDiagnosisRun
from app.models.monitor import GeoMonitorScheduleRun, GeoMonitorSubtask, GeoMonitorTask
from app.models.tenant import Tenant
from app.services.brand_service import (
    get_brand_asset,
    keyword_group_display_label,
    keyword_group_monitor_keywords,
    keyword_group_name,
    keyword_group_to_dict,
    list_keyword_groups,
)
from app.services.operation_log_service import write_operation_log
from app.services.monitor_service import (
    TERMINAL_STATUSES,
    _platform_display_names,
    _prompt_belongs_to_group,
    _reconcile_task_progress,
    _resolve_keyword_group_filter,
    _resolve_prompt_keyword_group,
    _subtask_answer_plaintext,
    get_monitor_subtask,
    get_monitor_task,
    recompute_subtask_rank_from_answer,
    serialize_subtask_for_display,
    subtask_needs_snapshot_backfill,
)
from app.core.masking import excerpt_sensitive_text
from app.services.ranking_parser import parse_answer_rankings
from app.services.schedule_context import (
    lead_diagnosis_runs_for_tasks,
    resolve_monitor_task_source,
    resolve_task_schedule_context,
    schedule_runs_for_tasks,
)
from app.services.system_notification_service import (
    resolve_subtask_backfill_notification,
    upsert_subtask_backfill_notification as persist_backfill_notification,
)

_SNAPSHOT_HOST_HINTS: dict[str, set[str]] = {
    "doubao.com": {"doubao", "doubao_mobile"},
    "deepseek.com": {"deepseek", "deepseek_mobile"},
    "yuanbao.tencent.com": {"yuanbao"},
    "qianwen.com": {"qianwen"},
    "kimi.com": {"kimi", "kimi_mobile"},
    "quark.cn": {"quark"},
}


def _normalize_host(netloc: str) -> str:
    host = (netloc or "").strip().lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def validate_snapshot_url(url: str, *, platform: str | None = None) -> str:
    """校验分享链接格式；平台与域名不匹配时仅告警，不阻断。"""
    value = (url or "").strip()
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("快照链接须为 http 或 https 地址")
    if not parsed.netloc:
        raise ValueError("快照链接无效")
    if len(value) > 1000:
        raise ValueError("快照链接过长")
    host = _normalize_host(parsed.netloc)
    if platform:
        expected = next((codes for suffix, codes in _SNAPSHOT_HOST_HINTS.items() if host.endswith(suffix)), None)
        if expected and platform not in expected:
            raise ValueError(f"链接域名与平台 {platform} 可能不匹配，请确认后再提交")
    return value


def _brand_terms_for_task(db: Session, task: GeoMonitorTask, asset: BrandAsset | None) -> list[str]:
    groups = (
        [keyword_group_to_dict(item) for item in list_keyword_groups(db, task.tenant_id)]
        if task.tenant_id
        else []
    )
    if asset is not None:
        from app.services.monitor_service import _ranking_match_terms

        terms = _ranking_match_terms(asset, groups)
        if terms:
            return terms
    terms: list[str] = []
    keyword = str(task.monitor_keywords or "").strip()
    if keyword:
        terms.append(keyword)
    request = task.raw_request_json or {}
    for alias in request.get("monitorKeywordAliases") or request.get("monitor_keyword_aliases") or []:
        text = str(alias or "").strip()
        if text and text not in terms:
            terms.append(text)
    return terms or ([keyword] if keyword else [])


def _lead_context_for_task(db: Session, task_id: str) -> dict[str, Any]:
    run = db.scalar(select(LeadDiagnosisRun).where(LeadDiagnosisRun.task_id == task_id))
    if run is None:
        return {}
    lead = db.get(LeadDiagnosis, run.lead_diagnosis_id)
    return {
        "lead_diagnosis_id": run.lead_diagnosis_id,
        "brand_name": lead.brand_name if lead else None,
    }


def _schedule_context_for_task(
    db: Session,
    task: GeoMonitorTask,
    *,
    schedule_runs_map: dict[str, GeoMonitorScheduleRun] | None = None,
    lead_runs_map: dict[str, LeadDiagnosisRun] | None = None,
    brand_asset_cache: dict[int, BrandAsset | None] | None = None,
) -> dict[str, Any]:
    """与实时监测一致的调度批次：签约企业优先 GeoMonitorScheduleRun，不用售前诊断挂靠批次。"""
    asset = None
    if task.tenant_id:
        if brand_asset_cache is not None:
            if task.tenant_id not in brand_asset_cache:
                try:
                    brand_asset_cache[task.tenant_id] = get_brand_asset(db, task.tenant_id)
                except Exception:
                    brand_asset_cache[task.tenant_id] = None
            asset = brand_asset_cache[task.tenant_id]
        else:
            try:
                asset = get_brand_asset(db, task.tenant_id)
            except Exception:
                asset = None

    schedule_run = (schedule_runs_map or {}).get(task.task_id)
    if schedule_run is None:
        schedule_run = db.scalar(
            select(GeoMonitorScheduleRun).where(GeoMonitorScheduleRun.task_id == task.task_id)
        )

    lead_run = None
    if not task.tenant_id:
        lead_run = (lead_runs_map or {}).get(task.task_id)
        if lead_run is None:
            lead_run = db.scalar(select(LeadDiagnosisRun).where(LeadDiagnosisRun.task_id == task.task_id))

    return resolve_task_schedule_context(task, schedule_run, asset, lead_run)


def notify_failed_subtasks_for_task(db: Session, task: GeoMonitorTask) -> int:
    """任务进入终态或存在失败子任务时，为待补录项写入单条通知。"""
    if task.status not in TERMINAL_STATUSES and (task.failed_items or 0) <= 0:
        return 0
    count = 0
    for subtask in task.subtasks or []:
        if subtask_needs_snapshot_backfill(subtask):
            _notify_subtask_backfill(db, subtask, task)
            count += 1
    return count


def _notify_subtask_backfill(db: Session, subtask: GeoMonitorSubtask, task: GeoMonitorTask) -> None:
    ctx = build_snapshot_backfill_item(db, subtask, task)
    scope = ctx.get("brand_name") or ctx.get("tenant_name") or task.monitor_keywords or "监测任务"
    prompt_preview = (subtask.prompt or "")[:80]
    title = "快照待补录"
    message = f"{scope} · {subtask.platform} · {prompt_preview}"
    persist_backfill_notification(
        db,
        subtask_id=subtask.subtask_id,
        title=title,
        message=message,
        payload=ctx,
    )


def apply_snapshot_backfill(
    db: Session,
    *,
    subtask_id: str,
    snapshot_url: str,
    answer_content: str,
    current: CurrentSession,
    mention_position: int | None = None,
    sentiment: str | None = None,
    reference_urls: list[str] | None = None,
) -> dict[str, Any]:
    if current.identity.identity_type != "PLATFORM":
        raise PermissionError("仅平台运营端可执行快照补录")

    subtask = get_monitor_subtask(db, subtask_id, current)
    task = get_monitor_task(db, subtask.task_id, current)

    previous_stat_date = None
    if task.tenant_id:
        from app.services.monitor_stats_service import _detect_stat_date
        from app.services.schedule_context import lead_diagnosis_runs_for_tasks, schedule_runs_for_tasks

        schedule_run = schedule_runs_for_tasks(db, [task.task_id]).get(task.task_id)
        lead_run = lead_diagnosis_runs_for_tasks(db, [task.task_id]).get(task.task_id)
        asset = get_brand_asset(db, task.tenant_id)
        previous_stat_date = _detect_stat_date(
            subtask,
            task,
            schedule_run=schedule_run,
            lead_run=lead_run,
            asset=asset,
        )

    url = validate_snapshot_url(snapshot_url, platform=subtask.platform)
    content = (answer_content or "").strip()
    if not content:
        raise ValueError("请粘贴 AI 回答正文")

    previous_answer = subtask.answer_content
    previous_raw = dict(subtask.raw_result_json or {})
    previous_source = previous_raw.get("source")

    subtask.page_screenshot = url
    subtask.answer_content = content
    subtask.error_message = None
    subtask.status = "completed"
    subtask.mention_context = None

    refs: list[dict[str, Any]] = []
    for index, item in enumerate(reference_urls or [], start=1):
        text = str(item or "").strip()
        if text:
            refs.append({"index": index, "url": text, "title": text})
    subtask.reference_list_json = refs or None
    subtask.citation_list_json = None

    if sentiment:
        subtask.sentiment = sentiment.strip().lower()
    elif previous_answer:
        subtask.sentiment = None

    parsed = parse_answer_rankings(_subtask_answer_plaintext(subtask))
    subtask.all_rankings_json = [
        {"name": entry.get("name"), "rank": entry.get("rank")} for entry in parsed
    ] if parsed else None
    subtask.competitor_rankings_json = None

    asset = get_brand_asset(db, task.tenant_id) if task.tenant_id else None
    recompute_subtask_rank_from_answer(db, subtask, task, override_mention_position=mention_position)

    manual_meta = {
        "source": "manual_snapshot",
        "snapshot_url": url,
        "operator_user_id": current.user.id,
        "replaced": bool(previous_answer),
    }
    if previous_answer:
        manual_meta["replaced_previous_source"] = previous_source
        manual_meta["replaced_previous_answer_preview"] = excerpt_sensitive_text(previous_answer, limit=80)
    raw = dict(previous_raw)
    raw.update(manual_meta)
    subtask.raw_result_json = raw

    _reconcile_task_progress(task)
    task.failed_items = sum(
        1 for item in (task.subtasks or []) if item.status in {"failed", "stopped"} and not item.answer_content
    )
    task.completed_items = sum(1 for item in (task.subtasks or []) if item.answer_content)

    action_type = "快照覆盖" if previous_answer else "快照补录"
    write_operation_log(
        db,
        current,
        action_type,
        _snapshot_backfill_log_description(db, subtask, task, action_type=action_type),
        target_module="快照补录",
        tenant_id=task.tenant_id,
        risk_level="关注" if previous_answer else "正常",
    )

    db.flush()

    run = db.scalar(select(LeadDiagnosisRun).where(LeadDiagnosisRun.task_id == task.task_id))
    if run is not None and run.status == "failed" and (task.completed_items or 0) > 0:
        run.status = "completed"
        run.error_message = None

    db.commit()
    from app.services.monitor_stats_service import refresh_stats_after_subtask_backfill
    from app.services.monitor_service import invalidate_monitor_summary_cache

    if task.tenant_id:
        refresh_stats_after_subtask_backfill(
            db,
            task=task,
            subtask=subtask,
            previous_stat_date=previous_stat_date,
        )
        db.commit()
        invalidate_monitor_summary_cache(task.tenant_id)
    else:
        invalidate_monitor_summary_cache()
    resolve_subtask_backfill_notification(db, subtask.subtask_id)

    from app.services.lead_diagnosis_service import refresh_lead_diagnosis_after_backfill

    refresh_lead_diagnosis_after_backfill(db, task.task_id)

    db.refresh(subtask)
    db.refresh(task)
    asset = get_brand_asset(db, task.tenant_id) if task.tenant_id else None
    groups = (
        [keyword_group_to_dict(item) for item in list_keyword_groups(db, task.tenant_id)]
        if task.tenant_id
        else []
    )
    display = serialize_subtask_for_display(
        subtask,
        monitor_keywords=task.monitor_keywords,
        asset=asset,
        keyword_groups=groups,
    )
    return {
        "subtask": display,
        "task": {
            "task_id": task.task_id,
            "status": task.status,
            "completed_items": task.completed_items,
            "failed_items": task.failed_items,
        },
        "brand_terms": _brand_terms_for_task(db, task, asset),
        "lead_context": _lead_context_for_task(db, task.task_id),
    }


def build_backfill_notification_context(
    db: Session,
    subtask: GeoMonitorSubtask,
    task: GeoMonitorTask,
    *,
    schedule_ctx: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tenant_name = None
    if task.tenant_id:
        tenant = db.get(Tenant, task.tenant_id)
        tenant_name = tenant.name if tenant else None
    lead_ctx = _lead_context_for_task(db, task.task_id)
    source = resolve_monitor_task_source(
        task,
        has_lead_run=bool(lead_ctx.get("lead_diagnosis_id")),
    )
    if schedule_ctx is None:
        schedule_ctx = _schedule_context_for_task(db, task)
    return {
        "subtask_id": subtask.subtask_id,
        "task_id": task.task_id,
        "tenant_id": task.tenant_id,
        "tenant_name": tenant_name,
        "platform": subtask.platform,
        "prompt": subtask.prompt,
        "error_message": subtask.error_message,
        "source": source,
        "monitor_keywords": task.monitor_keywords,
        "task_status": task.status,
        "updated_at": subtask.updated_at.isoformat() if subtask.updated_at else None,
        "task_created_at": task.created_at.isoformat() if task.created_at else None,
        "schedule_key": schedule_ctx.get("schedule_window_key") or schedule_ctx.get("schedule_key"),
        "schedule_label": schedule_ctx.get("schedule_label"),
        "schedule_source": schedule_ctx.get("schedule_source"),
        "lead_diagnosis_id": lead_ctx.get("lead_diagnosis_id") if source == "lead_diagnosis" else None,
        "brand_name": lead_ctx.get("brand_name") if source == "lead_diagnosis" else None,
    }


def _snapshot_backfill_log_description(
    db: Session,
    subtask: GeoMonitorSubtask,
    task: GeoMonitorTask,
    *,
    action_type: str,
) -> str:
    """操作日志描述：仅使用业务可识别的企业/周期/词组/平台/问题，不含子任务 ID。"""
    ctx = build_backfill_notification_context(db, subtask, task)
    keyword_group = None
    if task.tenant_id:
        try:
            groups = list_keyword_groups(db, task.tenant_id)
            matched = _resolve_prompt_keyword_group(subtask.prompt or "", groups)
            if matched is not None:
                keyword_group = keyword_group_display_label(matched)
        except Exception:
            keyword_group = None
    if not keyword_group:
        keyword_group = str(task.monitor_keywords or "").strip() or None

    platform_names = _platform_display_names()
    platform_label = platform_names.get(subtask.platform or "", subtask.platform or "—")
    scope = ctx.get("brand_name") or ctx.get("tenant_name") or "未命名任务"
    schedule_label = str(ctx.get("schedule_label") or "").strip()
    prompt_text = (subtask.prompt or "").strip() or "—"
    if len(prompt_text) > 60:
        prompt_text = prompt_text[:59] + "…"

    detail_parts: list[str] = [scope]
    if schedule_label:
        detail_parts.append(schedule_label)
    if keyword_group:
        detail_parts.append(f"词组「{keyword_group}」")
    detail_parts.append(platform_label)
    detail_parts.append(f"问题「{prompt_text}」")
    rank_text = subtask.mention_position
    if rank_text is not None:
        detail_parts.append(f"排名 {int(rank_text)}")
    return f"{action_type}：" + " · ".join(detail_parts)


def subtask_backfill_eligible(subtask: GeoMonitorSubtask, *, pending_only: bool = False) -> bool:
    """待补录项，或已有回答可覆盖更正的子任务。"""
    if pending_only:
        return subtask_needs_snapshot_backfill(subtask)
    if subtask_needs_snapshot_backfill(subtask):
        return True
    return bool((subtask.answer_content or "").strip())


def build_snapshot_backfill_item(
    db: Session,
    subtask: GeoMonitorSubtask,
    task: GeoMonitorTask,
    *,
    schedule_runs_map: dict[str, GeoMonitorScheduleRun] | None = None,
    lead_runs_map: dict[str, LeadDiagnosisRun] | None = None,
    keyword_groups_cache: dict[int, list] | None = None,
    keyword_group_dict_cache: dict[int, list[dict[str, Any]]] | None = None,
    brand_asset_cache: dict[int, BrandAsset | None] | None = None,
) -> dict[str, Any]:
    """运营端快照补录单条展示字段，与列表/通知/详情抽屉共用。"""
    keyword_groups_cache = keyword_groups_cache if keyword_groups_cache is not None else {}
    keyword_group_dict_cache = keyword_group_dict_cache if keyword_group_dict_cache is not None else {}
    brand_asset_cache = brand_asset_cache if brand_asset_cache is not None else {}

    schedule_ctx = _schedule_context_for_task(
        db,
        task,
        schedule_runs_map=schedule_runs_map,
        lead_runs_map=lead_runs_map,
        brand_asset_cache=brand_asset_cache,
    )
    ctx = build_backfill_notification_context(db, subtask, task, schedule_ctx=schedule_ctx)

    if task.tenant_id:
        if task.tenant_id not in keyword_groups_cache:
            try:
                orm_groups = list_keyword_groups(db, task.tenant_id)
            except Exception:
                orm_groups = []
            keyword_groups_cache[task.tenant_id] = orm_groups
            keyword_group_dict_cache[task.tenant_id] = [
                keyword_group_to_dict(item)
                for item in orm_groups
                if item.status and item.monitor_keyword
            ]
        keyword_group_rows = keyword_groups_cache[task.tenant_id]
        keyword_group_dicts = keyword_group_dict_cache[task.tenant_id]
    else:
        keyword_group_rows = []
        keyword_group_dicts = []

    matched_group = _resolve_prompt_keyword_group(subtask.prompt or "", keyword_group_rows)
    if matched_group is not None:
        ctx["keyword_group"] = keyword_group_display_label(matched_group)
    else:
        ctx["keyword_group"] = str(task.monitor_keywords or "").strip() or None
    ctx["sentiment"] = subtask.sentiment
    ctx["page_screenshot"] = subtask.page_screenshot
    ctx["needs_backfill"] = subtask_needs_snapshot_backfill(subtask)
    ctx["has_answer"] = bool((subtask.answer_content or "").strip())
    ctx["status"] = subtask.status

    asset = brand_asset_cache.get(task.tenant_id) if task.tenant_id else None
    if task.tenant_id and task.tenant_id not in brand_asset_cache:
        try:
            brand_asset_cache[task.tenant_id] = get_brand_asset(db, task.tenant_id)
        except Exception:
            brand_asset_cache[task.tenant_id] = None
        asset = brand_asset_cache[task.tenant_id]

    rank_display = serialize_subtask_for_display(
        subtask,
        monitor_keywords=task.monitor_keywords,
        asset=asset,
        keyword_groups=keyword_group_dicts,
    )
    ctx["mention_position"] = rank_display.get("mention_position")
    ctx["raw_mention_position"] = rank_display.get("raw_mention_position")
    ctx["brand_rank"] = rank_display.get("brand_rank", rank_display.get("mention_position"))
    ctx["brand_mentioned"] = rank_display.get("brand_mentioned")
    ctx["prompt_intent"] = rank_display.get("prompt_intent")
    return ctx


def _snapshot_backfill_matches_keyword_group(
    subtask: GeoMonitorSubtask,
    ctx: dict[str, Any],
    *,
    keyword_group: str,
    keyword_group_dicts: list[dict[str, Any]],
) -> bool:
    group_filter = str(keyword_group or "").strip()
    if not group_filter:
        return True
    selected = _resolve_keyword_group_filter(group_filter, keyword_group_dicts) if keyword_group_dicts else None
    if selected is not None:
        return _prompt_belongs_to_group(
            subtask.prompt or "",
            keyword_group_monitor_keywords(selected),
            selected.get("exposure_terms") or [],
        )
    lower = group_filter.lower()
    haystacks = [
        ctx.get("keyword_group") or "",
        subtask.prompt or "",
        ctx.get("monitor_keywords") or "",
    ]
    return any(lower in str(text).lower() for text in haystacks if text)


def list_snapshot_backfill_page(
    db: Session,
    *,
    tenant_id: int | None = None,
    tenant_ids: list[int] | None = None,
    detect_date: date | None = None,
    source: str | None = None,
    platform: str | None = None,
    keyword: str | None = None,
    keyword_group: str | None = None,
    pending_only: bool = False,
    offset: int = 0,
    limit: int = 50,
) -> dict[str, Any]:
    """运营端快照补录列表（含汇总统计），可按企业/检测日/来源/平台/关键词筛选。"""
    stmt = (
        select(GeoMonitorSubtask)
        .join(GeoMonitorTask, GeoMonitorTask.task_id == GeoMonitorSubtask.task_id)
        .where(GeoMonitorTask.deleted.is_(False))
        .order_by(GeoMonitorTask.created_at.desc(), GeoMonitorSubtask.updated_at.desc())
    )
    scan_cap = max(limit * 50, 5000) if tenant_id is None and not tenant_ids else None
    if scan_cap is not None:
        stmt = stmt.limit(scan_cap)
    if tenant_ids:
        stmt = stmt.where(GeoMonitorTask.tenant_id.in_(tenant_ids))
    elif tenant_id is not None:
        stmt = stmt.where(GeoMonitorTask.tenant_id == tenant_id)
    platform_code = str(platform or "").strip()
    if platform_code:
        stmt = stmt.where(GeoMonitorSubtask.platform == platform_code)
    keyword_text = str(keyword or "").strip()
    keyword_group_filter = str(keyword_group or "").strip()
    source_filter = str(source or "").strip()
    if source_filter == "lead_diagnosis":
        lead_task_ids = select(LeadDiagnosisRun.task_id).where(LeadDiagnosisRun.task_id.isnot(None))
        stmt = stmt.where(
            GeoMonitorTask.tenant_id.is_(None),
            GeoMonitorTask.task_id.in_(lead_task_ids),
        )
    elif source_filter == "tenant_monitor":
        lead_task_ids = select(LeadDiagnosisRun.task_id).where(LeadDiagnosisRun.task_id.isnot(None))
        stmt = stmt.where(
            or_(
                GeoMonitorTask.tenant_id.isnot(None),
                GeoMonitorTask.task_id.notin_(lead_task_ids),
            )
        )
    if detect_date is not None:
        day_prefix = detect_date.strftime("%Y%m%d")
        lead_task_ids = select(LeadDiagnosisRun.task_id).where(
            LeadDiagnosisRun.task_id.isnot(None),
            LeadDiagnosisRun.schedule_key.like(f"{day_prefix}-%"),
        )
        schedule_task_ids = select(GeoMonitorScheduleRun.task_id).where(
            GeoMonitorScheduleRun.schedule_key.like(f"{day_prefix}%"),
        )
        stmt = stmt.where(
            or_(
                GeoMonitorTask.task_id.in_(lead_task_ids),
                GeoMonitorTask.task_id.in_(schedule_task_ids),
                func.date(GeoMonitorTask.created_at) == detect_date,
            )
        )

    rows = list(db.scalars(stmt))
    task_ids = {item.task_id for item in rows}
    tasks = {
        item.task_id: item
        for item in db.scalars(select(GeoMonitorTask).where(GeoMonitorTask.task_id.in_(task_ids)))
    } if task_ids else {}
    schedule_runs_map = schedule_runs_for_tasks(db, list(task_ids))
    lead_runs_map = lead_diagnosis_runs_for_tasks(db, list(task_ids))

    all_items: list[dict[str, Any]] = []
    keyword_groups_cache: dict[int, list] = {}
    keyword_group_dict_cache: dict[int, list[dict[str, Any]]] = {}
    brand_asset_cache: dict[int, BrandAsset | None] = {}
    for subtask in rows:
        task = tasks.get(subtask.task_id)
        if task is None or not subtask_backfill_eligible(subtask, pending_only=pending_only):
            continue
        if platform_code and subtask.platform != platform_code:
            continue
        ctx = build_snapshot_backfill_item(
            db,
            subtask,
            task,
            schedule_runs_map=schedule_runs_map,
            lead_runs_map=lead_runs_map,
            keyword_groups_cache=keyword_groups_cache,
            keyword_group_dict_cache=keyword_group_dict_cache,
            brand_asset_cache=brand_asset_cache,
        )
        if source_filter and ctx.get("source") != source_filter:
            continue
        group_dicts = keyword_group_dict_cache.get(task.tenant_id, []) if task.tenant_id else []
        if not _snapshot_backfill_matches_keyword_group(
            subtask,
            ctx,
            keyword_group=keyword_group_filter,
            keyword_group_dicts=group_dicts,
        ):
            continue
        if keyword_text and keyword_text.lower() not in (subtask.prompt or "").lower():
            continue
        all_items.append(ctx)
    all_items.sort(
        key=lambda row: (
            str(row.get("schedule_key") or ""),
            str(row.get("platform") or ""),
            str(row.get("prompt") or ""),
        ),
        reverse=True,
    )
    total = len(all_items)
    pending = sum(1 for row in all_items if row.get("needs_backfill"))
    overwrite = sum(1 for row in all_items if row.get("has_answer") and not row.get("needs_backfill"))
    page_offset = max(0, int(offset or 0))
    page_items = all_items[page_offset:page_offset + limit]
    return {
        "items": page_items,
        "summary": {
            "total": total,
            "pending": pending,
            "overwrite": overwrite,
            "shown": len(page_items),
            "offset": page_offset,
            "limit": limit,
            "has_more": page_offset + len(page_items) < total,
            "scan_capped": bool(scan_cap is not None and len(rows) >= scan_cap),
        },
    }


def list_snapshot_backfill_items(
    db: Session,
    *,
    tenant_id: int | None = None,
    detect_date: date | None = None,
    source: str | None = None,
    platform: str | None = None,
    keyword: str | None = None,
    keyword_group: str | None = None,
    pending_only: bool = False,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """运营端快照补录列表（仅条目，兼容旧调用）。"""
    return list_snapshot_backfill_page(
        db,
        tenant_id=tenant_id,
        detect_date=detect_date,
        source=source,
        platform=platform,
        keyword=keyword,
        keyword_group=keyword_group,
        pending_only=pending_only,
        limit=limit,
    )["items"]


def list_pending_snapshot_backfills(db: Session, *, limit: int = 50) -> list[dict[str, Any]]:
    """运营端待补录列表：仅失败或无回答的子任务。"""
    return list_snapshot_backfill_items(db, pending_only=True, limit=limit)
