"""快照补录：失败子任务粘贴分享链接，自动解析正文与信源，重算排名并触发聚合。"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import and_, false, func, or_, select
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
from app.services.media_proxy_service import public_screenshot_url
from app.services.monitor_service import (
    backfill_weak_rank_threshold,
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
from app.services.ranking_parser import rankings_for_storage
from app.services.share_page_fetch_service import fetch_share_page
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
    "deepseek.cn": {"deepseek", "deepseek_mobile"},
    "yuanbao.tencent.com": {"yuanbao"},
    "qianwen.com": {"qianwen", "qianwen_mobile"},
    "tongyi.aliyun.com": {"qianwen", "qianwen_mobile"},
    "kimi.com": {"kimi", "kimi_mobile"},
    "moonshot.cn": {"kimi", "kimi_mobile"},
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
        "created_by_user_id": lead.created_by_user_id if lead else None,
    }


def resolve_backfill_owner_user_id(
    db: Session,
    task: GeoMonitorTask,
    *,
    lead_ctx: dict[str, Any] | None = None,
) -> int | None:
    """补录待办归属销售：签约企业 → tenant.owner_user_id；售前 → 诊断创建人。"""
    if task.tenant_id:
        tenant = db.get(Tenant, task.tenant_id)
        if tenant and tenant.owner_user_id:
            return int(tenant.owner_user_id)
    ctx = lead_ctx if lead_ctx is not None else _lead_context_for_task(db, task.task_id)
    creator = ctx.get("created_by_user_id")
    if creator:
        return int(creator)
    return None


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


def subtask_backfill_dismissed(subtask: GeoMonitorSubtask) -> bool:
    """运营已忽略该子任务的待补录提醒。"""
    return getattr(subtask, "backfill_dismissed_at", None) is not None


def clear_subtask_backfill_dismiss(subtask: GeoMonitorSubtask) -> None:
    subtask.backfill_dismissed_at = None
    subtask.backfill_dismissed_by = None


def notify_failed_subtasks_for_task(db: Session, task: GeoMonitorTask) -> int:
    """任务进入终态或存在失败子任务时，为待补录项写入单条通知。"""
    if task.status not in TERMINAL_STATUSES and (task.failed_items or 0) <= 0:
        return 0
    count = 0
    for subtask in task.subtasks or []:
        if subtask_backfill_dismissed(subtask):
            continue
        ctx = build_snapshot_backfill_item(db, subtask, task)
        if not ctx.get("needs_backfill"):
            continue
        _notify_subtask_backfill(db, subtask, task, ctx=ctx)
        count += 1
    return count


def _notify_subtask_backfill(
    db: Session,
    subtask: GeoMonitorSubtask,
    task: GeoMonitorTask,
    *,
    ctx: dict[str, Any] | None = None,
) -> None:
    payload = ctx or build_snapshot_backfill_item(db, subtask, task)
    scope = payload.get("brand_name") or payload.get("tenant_name") or task.monitor_keywords or "监测任务"
    prompt_preview = (subtask.prompt or "")[:80]
    rank = payload.get("mention_position")
    if rank is not None and (subtask.answer_content or "").strip():
        title = "排名落后待补录"
        message = f"{scope} · {subtask.platform} · 第{int(rank)}名 · {prompt_preview}"
    else:
        title = "快照待补录"
        message = f"{scope} · {subtask.platform} · {prompt_preview}"
    persist_backfill_notification(
        db,
        subtask_id=subtask.subtask_id,
        title=title,
        message=message,
        payload=payload,
    )


def apply_snapshot_backfill(
    db: Session,
    *,
    subtask_id: str,
    snapshot_url: str | None = None,
    answer_content: str | None = None,
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

    url_raw = str(snapshot_url or "").strip()
    # 无链接：只改排名，快照 URL / 正文 / 信源沿用原值
    if not url_raw:
        if mention_position is None:
            raise ValueError("未填写分享链接时，请填写品牌排名")
        if not (subtask.answer_content or subtask.page_screenshot):
            raise ValueError("当前无可用快照，请粘贴分享链接补录")
        previous_raw = dict(subtask.raw_result_json or {})
        clear_subtask_backfill_dismiss(subtask)
        subtask.error_message = None
        subtask.status = "completed"
        recompute_subtask_rank_from_answer(
            db, subtask, task, override_mention_position=mention_position
        )
        manual_meta = {
            "source": "manual_snapshot",
            "snapshot_url": previous_raw.get("snapshot_url") or subtask.page_screenshot,
            "operator_user_id": current.user.id,
            "rank_only": True,
            "manual_rank_locked": True,
            "replaced": False,
        }
        if previous_raw.get("source"):
            manual_meta["replaced_previous_source"] = previous_raw.get("source")
        raw = dict(subtask.raw_result_json or previous_raw or {})
        raw.update(manual_meta)
        subtask.raw_result_json = raw

        write_operation_log(
            db,
            current,
            "排名补录",
            _snapshot_backfill_log_description(db, subtask, task, action_type="排名补录"),
            target_module="快照补录",
            tenant_id=task.tenant_id,
            risk_level="正常",
        )
        db.flush()
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
            invalidate_monitor_summary_cache(task.tenant_id, bust_overview=True)
        else:
            invalidate_monitor_summary_cache(bust_overview=True)
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
            "rank_only": True,
        }

    url = validate_snapshot_url(url_raw, platform=subtask.platform)
    # 只要补录就从分享页抓取并覆盖正文；可选手工正文仅作抓取失败时的兼容兜底
    fetched_refs: list[dict[str, Any]] = []
    fetch_meta: dict[str, Any] = {}
    content = (answer_content or "").strip()
    try:
        fetched = fetch_share_page(url)
        content = (fetched.answer_content or "").strip()
        fetched_refs = list(fetched.references or [])
        fetch_meta = {
            "fetch_host": fetched.source_host,
            "fetch_title": fetched.title,
            "fetch_reference_count": len(fetched_refs),
        }
    except ValueError:
        if not content:
            raise
        fetch_meta = {"fetch_skipped": True, "fetch_fallback": "manual_answer"}
    if not content:
        raise ValueError("未能解析分享页正文")

    previous_answer = subtask.answer_content
    previous_raw = dict(subtask.raw_result_json or {})
    previous_source = previous_raw.get("source")

    clear_subtask_backfill_dismiss(subtask)
    subtask.page_screenshot = url
    subtask.answer_content = content
    subtask.error_message = None
    subtask.status = "completed"
    subtask.mention_context = None

    refs: list[dict[str, Any]] = []
    if reference_urls:
        for index, item in enumerate(reference_urls, start=1):
            text = str(item or "").strip()
            if text:
                refs.append({"index": index, "url": text, "title": text})
    if not refs and fetched_refs:
        refs = fetched_refs
    subtask.reference_list_json = refs or None
    subtask.citation_list_json = None

    if sentiment:
        subtask.sentiment = sentiment.strip().lower()
    elif previous_answer:
        subtask.sentiment = None

    # 2026-07-27 - 补录写榜丢掉 category - 入库保留段内序与分类
    subtask.all_rankings_json = rankings_for_storage(_subtask_answer_plaintext(subtask), None)
    subtask.competitor_rankings_json = None

    recompute_subtask_rank_from_answer(db, subtask, task, override_mention_position=mention_position)

    manual_meta = {
        "source": "manual_snapshot",
        "snapshot_url": url,
        "operator_user_id": current.user.id,
        "replaced": bool(previous_answer),
        # 手填名次才锁定；空着走解析结果，后续规则升级可重算
        "manual_rank_locked": mention_position is not None,
        **fetch_meta,
    }
    if previous_answer:
        manual_meta["replaced_previous_source"] = previous_source
        manual_meta["replaced_previous_answer_preview"] = excerpt_sensitive_text(previous_answer, limit=80)
    # 在重算后的 raw 上合并补录元数据，避免冲掉 rank_resolution
    raw = dict(subtask.raw_result_json or previous_raw or {})
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
        invalidate_monitor_summary_cache(task.tenant_id, bust_overview=True)
    else:
        invalidate_monitor_summary_cache(bust_overview=True)
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
    tenant_name: str | None = None,
    lead_ctx: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if tenant_name is None and task.tenant_id:
        tenant = db.get(Tenant, task.tenant_id)
        tenant_name = tenant.name if tenant else None
    if lead_ctx is None:
        lead_ctx = _lead_context_for_task(db, task.task_id)
    source = resolve_monitor_task_source(
        task,
        has_lead_run=bool(lead_ctx.get("lead_diagnosis_id")),
    )
    if schedule_ctx is None:
        schedule_ctx = _schedule_context_for_task(db, task)
    owner_user_id = resolve_backfill_owner_user_id(db, task, lead_ctx=lead_ctx)
    return {
        "subtask_id": subtask.subtask_id,
        "task_id": task.task_id,
        "tenant_id": task.tenant_id,
        "tenant_name": tenant_name,
        "owner_user_id": owner_user_id,
        "platform": subtask.platform,
        "prompt": subtask.prompt,
        "error_message": subtask.error_message,
        "source": source,
        "monitor_keywords": task.monitor_keywords,
        "task_status": task.status,
        "updated_at": subtask.updated_at.isoformat() if subtask.updated_at else None,
        "task_created_at": task.created_at.isoformat() if task.created_at else None,
        "schedule_key": schedule_ctx.get("schedule_key"),
        "schedule_window_key": schedule_ctx.get("schedule_window_key"),
        "schedule_label": schedule_ctx.get("schedule_label"),
        "schedule_source": schedule_ctx.get("schedule_source"),
        "region_code": schedule_ctx.get("region_code"),
        "region_label": schedule_ctx.get("region_label"),
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
    region_label = str(ctx.get("region_label") or "").strip()
    prompt_text = (subtask.prompt or "").strip() or "—"
    if len(prompt_text) > 60:
        prompt_text = prompt_text[:59] + "…"

    detail_parts: list[str] = [scope]
    if schedule_label:
        detail_parts.append(schedule_label)
    if region_label and region_label != "全部区域":
        detail_parts.append(region_label)
    if keyword_group:
        detail_parts.append(f"词组「{keyword_group}」")
    detail_parts.append(platform_label)
    detail_parts.append(f"问题「{prompt_text}」")
    rank_text = subtask.mention_position
    if rank_text is not None:
        detail_parts.append(f"排名 {int(rank_text)}")
    return f"{action_type}：" + " · ".join(detail_parts)


def subtask_backfill_eligible(subtask: GeoMonitorSubtask, *, pending_only: bool = False) -> bool:
    """待补录项，或已有回答可覆盖更正的子任务。已忽略的不进运营列表。"""
    if subtask_backfill_dismissed(subtask):
        return False
    if pending_only:
        return subtask_needs_snapshot_backfill(subtask)
    if subtask_needs_snapshot_backfill(subtask):
        return True
    return bool((subtask.answer_content or "").strip())


def dismiss_snapshot_backfill(
    db: Session,
    *,
    subtask_id: str,
    current: CurrentSession,
) -> dict[str, Any]:
    """永久忽略该子任务待补录：保留答案/排名，退出列表与提醒。"""
    if current.identity.identity_type != "PLATFORM":
        raise PermissionError("仅平台运营端可忽略快照补录")

    subtask = get_monitor_subtask(db, subtask_id, current)
    task = get_monitor_task(db, subtask.task_id, current)

    if subtask_backfill_dismissed(subtask):
        item = build_snapshot_backfill_item(db, subtask, task)
        return {"subtask_id": subtask.subtask_id, "backfill_dismissed": True, "item": item}

    item_probe = build_snapshot_backfill_item(db, subtask, task)
    if not item_probe.get("needs_backfill"):
        raise ValueError("当前子任务不在待补录状态，无需忽略")

    subtask.backfill_dismissed_at = datetime.now(UTC).replace(tzinfo=None)
    subtask.backfill_dismissed_by = current.user.id
    dismiss_desc = _snapshot_backfill_log_description(db, subtask, task, action_type="忽略补录")
    write_operation_log(
        db,
        current,
        "忽略补录",
        f"{dismiss_desc} · 子任务 {subtask.subtask_id}",
        target_module="快照补录",
        tenant_id=task.tenant_id,
        risk_level="关注",
    )
    db.commit()
    resolve_subtask_backfill_notification(db, subtask.subtask_id)
    db.refresh(subtask)
    item = build_snapshot_backfill_item(db, subtask, task)
    return {"subtask_id": subtask.subtask_id, "backfill_dismissed": True, "item": item}


def undismiss_snapshot_backfill(
    db: Session,
    *,
    subtask_id: str,
    current: CurrentSession,
) -> dict[str, Any]:
    """取消忽略：若仍待补录则回列表并重新通知。"""
    if current.identity.identity_type != "PLATFORM":
        raise PermissionError("仅平台运营端可取消忽略快照补录")

    subtask = get_monitor_subtask(db, subtask_id, current)
    task = get_monitor_task(db, subtask.task_id, current)

    if not subtask_backfill_dismissed(subtask):
        item = build_snapshot_backfill_item(db, subtask, task)
        return {"subtask_id": subtask.subtask_id, "backfill_dismissed": False, "item": item}

    clear_subtask_backfill_dismiss(subtask)
    undismiss_desc = _snapshot_backfill_log_description(db, subtask, task, action_type="取消忽略补录")
    write_operation_log(
        db,
        current,
        "取消忽略补录",
        f"{undismiss_desc} · 子任务 {subtask.subtask_id}",
        target_module="快照补录",
        tenant_id=task.tenant_id,
        risk_level="正常",
    )
    db.commit()
    db.refresh(subtask)
    item = build_snapshot_backfill_item(db, subtask, task)
    if item.get("needs_backfill"):
        _notify_subtask_backfill(db, subtask, task, ctx=item)
    return {"subtask_id": subtask.subtask_id, "backfill_dismissed": False, "item": item}


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
    tenant_name: str | None = None,
    lead_ctx: dict[str, Any] | None = None,
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
    ctx = build_backfill_notification_context(
        db,
        subtask,
        task,
        schedule_ctx=schedule_ctx,
        tenant_name=tenant_name,
        lead_ctx=lead_ctx,
    )

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
    # 对外展示走代理；勿覆盖 serialize 后的脱敏 URL（include_ops 合并时会带上本字段）
    ctx["page_screenshot"] = public_screenshot_url(subtask.page_screenshot)
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
    ctx["rank_source"] = rank_display.get("rank_source")
    ctx["rank_category"] = rank_display.get("rank_category")
    ctx["rank_basis"] = rank_display.get("rank_basis")
    # 与卡片展示位次一致，避免库内 raw 差位却已重算进 Top3 仍标「待补录」
    display_rank = rank_display.get("mention_position")
    effective: int | None
    try:
        effective = int(display_rank) if display_rank is not None else None
    except (TypeError, ValueError):
        effective = None
    needs = subtask_needs_snapshot_backfill(
        subtask,
        effective_rank=effective,
        use_effective_rank=True,
        brand_mentioned=rank_display.get("brand_mentioned"),
    )
    dismissed = subtask_backfill_dismissed(subtask)
    ctx["backfill_dismissed"] = dismissed
    # 列表口径：已忽略不再算待补录；详情深链仍可通过 backfill_dismissed 看到并取消忽略
    ctx["needs_backfill"] = bool(needs) and not dismissed
    ctx["needs_backfill_raw"] = bool(needs)
    return ctx


def _lead_context_from_maps(
    db: Session,
    task_id: str,
    lead_runs_map: dict[str, LeadDiagnosisRun],
    lead_cache: dict[int, LeadDiagnosis],
) -> dict[str, Any]:
    run = lead_runs_map.get(task_id)
    if run is None:
        return {}
    lead = lead_cache.get(run.lead_diagnosis_id)
    if lead is None:
        lead = db.get(LeadDiagnosis, run.lead_diagnosis_id)
        if lead is not None:
            lead_cache[run.lead_diagnosis_id] = lead
    return {
        "lead_diagnosis_id": run.lead_diagnosis_id,
        "brand_name": lead.brand_name if lead else None,
        "created_by_user_id": lead.created_by_user_id if lead else None,
    }


def _snapshot_backfill_sort_key(schedule_ctx: dict[str, Any], subtask: GeoMonitorSubtask) -> str:
    return "|".join(
        [
            str(schedule_ctx.get("schedule_key") or ""),
            str(subtask.platform or ""),
            str(subtask.prompt or ""),
        ]
    )


def _resolve_snapshot_backfill_source(
    task: GeoMonitorTask,
    lead_ctx: dict[str, Any],
) -> str:
    return resolve_monitor_task_source(
        task,
        has_lead_run=bool(lead_ctx.get("lead_diagnosis_id")),
    )


def _matches_keyword_group_filter(
    subtask: GeoMonitorSubtask,
    task: GeoMonitorTask,
    *,
    keyword_group_filter: str,
    keyword_group_dicts: list[dict[str, Any]],
    keyword_group_rows: list,
) -> bool:
    if not keyword_group_filter:
        return True
    matched_group = _resolve_prompt_keyword_group(subtask.prompt or "", keyword_group_rows)
    keyword_group_label = (
        keyword_group_display_label(matched_group)
        if matched_group is not None
        else str(task.monitor_keywords or "").strip() or None
    )
    return _snapshot_backfill_matches_keyword_group(
        subtask,
        {
            "keyword_group": keyword_group_label,
            "monitor_keywords": task.monitor_keywords,
        },
        keyword_group=keyword_group_filter,
        keyword_group_dicts=keyword_group_dicts,
    )


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
    allowed_lead_task_ids: list[str] | None = None,
    detect_date: date | None = None,
    source: str | None = None,
    platform: str | None = None,
    keyword: str | None = None,
    keyword_group: str | None = None,
    pending_only: bool = False,
    offset: int = 0,
    limit: int = 50,
    include_summary: bool = True,
) -> dict[str, Any]:
    """运营端快照补录列表（含汇总统计），可按企业/检测日/来源/平台/关键词筛选。

    include_summary=False 时尽早凑齐本页后停止扫描，供首屏轻量加载；
    汇总请另请求 include_summary=True（可走短缓存）。
    """
    platform_code = str(platform or "").strip()
    keyword_text = str(keyword or "").strip()
    keyword_group_filter = str(keyword_group or "").strip()
    source_filter = str(source or "").strip()

    stmt = (
        select(GeoMonitorSubtask)
        .join(GeoMonitorTask, GeoMonitorTask.task_id == GeoMonitorSubtask.task_id)
        .where(
            GeoMonitorTask.deleted.is_(False),
            # 品牌词不进补录运营台；售前无 tenant 的 lead 任务仍可进
            or_(GeoMonitorTask.purpose == "geo", GeoMonitorTask.tenant_id.is_(None)),
        )
        .order_by(GeoMonitorTask.created_at.desc(), GeoMonitorSubtask.updated_at.desc())
    )
    if tenant_ids is not None:
        if allowed_lead_task_ids is not None:
            lead_scope = (
                and_(
                    GeoMonitorTask.tenant_id.is_(None),
                    GeoMonitorTask.task_id.in_(allowed_lead_task_ids),
                )
                if allowed_lead_task_ids
                else false()
            )
            if tenant_ids:
                stmt = stmt.where(or_(GeoMonitorTask.tenant_id.in_(tenant_ids), lead_scope))
            else:
                stmt = stmt.where(lead_scope)
        else:
            stmt = stmt.where(GeoMonitorTask.tenant_id.in_(tenant_ids))
    elif tenant_id is not None:
        stmt = stmt.where(GeoMonitorTask.tenant_id == tenant_id)
    elif allowed_lead_task_ids is not None:
        if not allowed_lead_task_ids:
            stmt = stmt.where(false())
        else:
            stmt = stmt.where(
                GeoMonitorTask.tenant_id.is_(None),
                GeoMonitorTask.task_id.in_(allowed_lead_task_ids),
            )

    if platform_code:
        stmt = stmt.where(GeoMonitorSubtask.platform == platform_code)
    if source_filter == "lead_diagnosis":
        if allowed_lead_task_ids is not None:
            if not allowed_lead_task_ids:
                stmt = stmt.where(false())
            else:
                stmt = stmt.where(
                    GeoMonitorTask.tenant_id.is_(None),
                    GeoMonitorTask.task_id.in_(allowed_lead_task_ids),
                )
        else:
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

    # 已忽略项不进运营列表（取消忽略仅靠 subtask_id 深链进详情）
    stmt = stmt.where(GeoMonitorSubtask.backfill_dismissed_at.is_(None))

    no_answer = or_(GeoMonitorSubtask.answer_content.is_(None), GeoMonitorSubtask.answer_content == "")
    if pending_only:
        fail_pending = and_(
            no_answer,
            or_(
                GeoMonitorSubtask.status.in_(("failed", "stopped")),
                and_(
                    GeoMonitorSubtask.error_message.isnot(None),
                    GeoMonitorSubtask.error_message != "",
                    GeoMonitorSubtask.status.in_(tuple(TERMINAL_STATUSES)),
                ),
            ),
        )
        # 有回答先全捞，再按展示位次筛：仅前 N 放过（库内 Top3 但展示无位次也要进）
        stmt = stmt.where(or_(fail_pending, ~no_answer))
    if keyword_text:
        stmt = stmt.where(GeoMonitorSubtask.prompt.like(f"%{keyword_text}%"))

    has_scope_filter = bool(
        tenant_id
        or tenant_ids
        or detect_date
        or platform_code
        or keyword_text
        or keyword_group_filter
        or source_filter
    )
    if tenant_id is None and not tenant_ids:
        # ponytail: 无筛选时收紧扫描上限，避免 2500~4000 行全进内存再 slice
        scan_cap = min(max(limit * 12, 400), 800) if not has_scope_filter else min(max(limit * 20, 800), 1500)
    else:
        scan_cap = None
    # 首屏轻量：缩小扫描窗口，稍后再拉全量汇总
    if not include_summary:
        light_cap = max(int(limit or 50) * 5, 100)
        scan_cap = light_cap if scan_cap is None else min(scan_cap, light_cap)
    if scan_cap is not None:
        stmt = stmt.limit(scan_cap)

    rows = list(db.scalars(stmt))
    task_ids = {item.task_id for item in rows}
    tasks = {
        item.task_id: item
        for item in db.scalars(select(GeoMonitorTask).where(GeoMonitorTask.task_id.in_(task_ids)))
    } if task_ids else {}
    schedule_runs_map = schedule_runs_for_tasks(db, list(task_ids))
    lead_runs_map = lead_diagnosis_runs_for_tasks(db, list(task_ids))

    tenant_name_map: dict[int, str] = {}
    if tasks:
        tenant_ids_in_page = {task.tenant_id for task in tasks.values() if task.tenant_id}
        if tenant_ids_in_page:
            tenant_name_map = {
                row.id: row.name
                for row in db.scalars(select(Tenant).where(Tenant.id.in_(tenant_ids_in_page)))
            }

    keyword_groups_cache: dict[int, list] = {}
    keyword_group_dict_cache: dict[int, list[dict[str, Any]]] = {}
    brand_asset_cache: dict[int, BrandAsset | None] = {}
    lead_cache: dict[int, LeadDiagnosis] = {}

    candidates: list[tuple[GeoMonitorSubtask, GeoMonitorTask, dict[str, Any], dict[str, Any], dict[str, Any]]] = []
    pending_count = 0
    overwrite_count = 0
    for subtask in rows:
        task = tasks.get(subtask.task_id)
        # 列表预筛：pending_only 时 SQL 可能仍带上 raw>阈值项，最终以展示位次为准再滤。
        if task is None or not subtask_backfill_eligible(subtask, pending_only=False):
            continue

        lead_ctx = _lead_context_from_maps(db, task.task_id, lead_runs_map, lead_cache)
        task_source = _resolve_snapshot_backfill_source(task, lead_ctx)
        if source_filter and task_source != source_filter:
            continue

        keyword_group_rows: list = []
        keyword_group_dicts: list[dict[str, Any]] = []
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

        if not _matches_keyword_group_filter(
            subtask,
            task,
            keyword_group_filter=keyword_group_filter,
            keyword_group_dicts=keyword_group_dicts,
            keyword_group_rows=keyword_group_rows,
        ):
            continue

        schedule_ctx = _schedule_context_for_task(
            db,
            task,
            schedule_runs_map=schedule_runs_map,
            lead_runs_map=lead_runs_map,
            brand_asset_cache=brand_asset_cache,
        )
        item = build_snapshot_backfill_item(
            db,
            subtask,
            task,
            schedule_runs_map=schedule_runs_map,
            lead_runs_map=lead_runs_map,
            keyword_groups_cache=keyword_groups_cache,
            keyword_group_dict_cache=keyword_group_dict_cache,
            brand_asset_cache=brand_asset_cache,
            tenant_name=tenant_name_map.get(task.tenant_id) if task.tenant_id else None,
            lead_ctx=lead_ctx,
        )
        needs = bool(item.get("needs_backfill"))
        has_answer = bool(item.get("has_answer"))
        if pending_only and not needs:
            continue
        candidates.append((subtask, task, schedule_ctx, lead_ctx, item))
        if needs:
            pending_count += 1
        elif has_answer:
            overwrite_count += 1

    candidates.sort(
        key=lambda row: _snapshot_backfill_sort_key(row[2], row[0]),
        reverse=True,
    )
    total = len(candidates)
    page_offset = max(0, int(offset or 0))
    page_candidates = candidates[page_offset:page_offset + limit]
    page_items = [item for _subtask, _task, _schedule_ctx, _lead_ctx, item in page_candidates]
    return {
        "items": page_items,
        "summary": {
            "total": total,
            "pending": pending_count,
            "overwrite": overwrite_count,
            "shown": len(page_items),
            "offset": page_offset,
            "limit": limit,
            "has_more": page_offset + len(page_items) < total,
            "scan_capped": bool(scan_cap is not None and len(rows) >= scan_cap),
            "summary_partial": not include_summary,
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
