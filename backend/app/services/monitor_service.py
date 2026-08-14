from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from kombu.exceptions import OperationalError

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session, joinedload, load_only

from app.api.dependencies import CurrentSession
from app.core.config import settings
from app.core.platform_order import platform_market_rank, ranking_matrix_row_sort_key, sort_platform_codes, sort_platform_items
from app.core.region_catalog import normalize_region_codes
from app.models.brand import BrandAsset, BrandKeywordGroup
from app.models.lead_diagnosis import LeadDiagnosisRun
from app.models.monitor import GeoMonitorScheduleRun, GeoMonitorSubtask, GeoMonitorTask
from app.models.tenant import Tenant
from app.schemas.monitor import FAST_MONITOR_MODE, MonitorTaskCreateRequest, PlatformConfig
from app.services.molizhishu_platforms import filter_submittable_platforms
from app.services.media_proxy_service import public_screenshot_url
from app.services.brand_service import (
    _is_industry_monitor_keyword,
    active_keyword_groups,
    brand_exposure_terms,
    collect_exposure_term_options,
    get_brand_asset,
    is_generic_keyword_group_name,
    keyword_group_display_label,
    keyword_group_monitor_keywords,
    keyword_group_name,
    keyword_group_platforms,
    keyword_group_primary_keyword,
    keyword_group_to_dict,
    list_competitors,
    list_keyword_groups,
    molizhishu_brand_payload,
    molizhishu_monitor_terms,
    ranking_task_is_industry_scoped,
    tenant_purchased_platforms,
)
from app.services.molizhishu_client import MolizhishuApiError, MolizhishuClient
from app.services.ranking_parser import (
    appearance_order_rank_scoped,
    find_best_brand_rank,
    find_best_brand_entry_scoped,
    find_best_brand_hit_scoped,
    find_best_brand_rank_scoped,
    normalize_structured_rankings,
    parse_answer_rankings,
    rankings_for_storage,
)
from app.services.tenant_scope import assert_monitor_task_access, ensure_sales_tenant_access, sales_owned_tenant_ids
from app.services.schedule_context import (
    prompt_monitor_intent,
    lead_diagnosis_runs_for_tasks,
    resolve_task_schedule_context,
    schedule_plan_summary,
    schedule_runs_for_tasks,
    schedule_window_sort_key,
)

TERMINAL_STATUSES = {"completed", "partial_completed", "failed", "stopped"}
SUCCESS_STATUSES = {"completed", "partial_completed"}  # 率类指标分母；与 monitor_sample_metrics 对齐
NON_TERMINAL_STATUSES = {"pending", "processing", "running", "queued"}
# 正文已到但上游榜单未落定：最多再等这么久继续 sync，避免永久卡在 processing
RANK_AWAIT_UPSTREAM_HOURS = 6
_TRANSIENT_SYNC_ERRORS = (MolizhishuApiError, TimeoutError, OperationalError)
logger = logging.getLogger(__name__)


def subtask_inflight_blocks_snapshot_backfill(subtask: GeoMonitorSubtask) -> bool:
    """监测子任务尚未终态时禁止人工补录，避免跑完同步盖掉补录。"""
    status = str(getattr(subtask, "status", None) or "").strip().lower()
    return status not in TERMINAL_STATUSES


def is_manual_snapshot_subtask(subtask: GeoMonitorSubtask) -> bool:
    raw = getattr(subtask, "raw_result_json", None)
    raw = raw if isinstance(raw, dict) else {}
    return str(raw.get("source") or "").strip() == "manual_snapshot"


def _ordered_subtask_ids(db: Session, stmt) -> list[int]:
    """ORDER BY/LIMIT 阶段只取主键，避免宽列进 filesort（MySQL 1038）。

    2026-07-30 - 同 platforms/matrix、补录列表 - stmt 勿带 load_only 胖列；排序后再 hydrate
    """
    id_stmt = stmt.with_only_columns(GeoMonitorSubtask.id, maintain_column_froms=True)
    return list(db.scalars(id_stmt))


def _hydrate_subtasks_in_id_order(db: Session, ordered_ids: list[int], *option_args) -> list[GeoMonitorSubtask]:
    if not ordered_ids:
        return []
    by_id = {
        item.id: item
        for item in db.scalars(
            select(GeoMonitorSubtask).options(*option_args).where(GeoMonitorSubtask.id.in_(ordered_ids))
        ).unique()
    }
    return [by_id[i] for i in ordered_ids if i in by_id]


def _has_structured_rankings(value: Any) -> bool:
    return bool(normalize_structured_rankings(value or []))


def _normalize_subtask_rankings_on_write(subtask: GeoMonitorSubtask) -> None:
    """upsert/补录后把 all_rankings_json 规范成段内序，避免扁平连号入库。"""
    normalized = rankings_for_storage(subtask.answer_content, subtask.all_rankings_json)
    if normalized is not None:
        subtask.all_rankings_json = normalized


def _merge_remote_rank_fields(subtask: GeoMonitorSubtask, item: dict[str, Any]) -> None:
    """合并远端排名字段。

    优先级：人工补录/本地已写入的 mention_position 为准；
    模力非空位次仅在本地为空时作为替补写入。
    远端空包不得冲掉本地已有位次/榜单。
    模力原始值仍保留在 raw_result_json，无需另建字段。
    """
    incoming_mp = item.get("mentionPosition")
    if incoming_mp is not None and subtask.mention_position is None:
        subtask.mention_position = incoming_mp

    incoming_ctx = item.get("mentionContext")
    if incoming_ctx and not subtask.mention_context:
        subtask.mention_context = incoming_ctx
    elif incoming_mp is not None and subtask.mention_position == incoming_mp and not subtask.mention_context:
        # 刚用模力替补写入位次、本地尚无上下文时，可带上远端上下文
        subtask.mention_context = incoming_ctx

    incoming_ranks = item.get("allRankings")
    if _has_structured_rankings(incoming_ranks):
        if not _has_structured_rankings(subtask.all_rankings_json):
            subtask.all_rankings_json = incoming_ranks
    elif not _has_structured_rankings(subtask.all_rankings_json):
        subtask.all_rankings_json = incoming_ranks

    incoming_competitors = item.get("competitorRankings")
    if _has_structured_rankings(incoming_competitors):
        if not _has_structured_rankings(subtask.competitor_rankings_json):
            subtask.competitor_rankings_json = incoming_competitors
    elif not _has_structured_rankings(subtask.competitor_rankings_json):
        subtask.competitor_rankings_json = incoming_competitors


def _subtask_awaiting_upstream_rank(
    subtask: GeoMonitorSubtask,
    *,
    now: datetime | None = None,
    max_age_hours: int = RANK_AWAIT_UPSTREAM_HOURS,
) -> bool:
    """回答已到、排名类问法、位次仍空，且远端 raw 仍非终态 → 继续等上游榜单。"""
    if prompt_monitor_intent(subtask.prompt) != "ranking":
        return False
    if not str(subtask.answer_content or "").strip():
        return False
    if subtask.mention_position is not None:
        return False
    if _has_structured_rankings(subtask.all_rankings_json):
        return False
    raw = subtask.raw_result_json if isinstance(subtask.raw_result_json, dict) else {}
    remote_status = str(raw.get("status") or "").strip()
    if remote_status not in NON_TERMINAL_STATUSES:
        return False
    anchor = subtask.updated_at or now or datetime.now()
    age_limit = timedelta(hours=max(0, max_age_hours))
    if (now or datetime.now()) - anchor > age_limit:
        return False
    return True


def _task_brand_terms_for_rank(db: Session, task: GeoMonitorTask) -> list[str]:
    asset = get_brand_asset(db, task.tenant_id) if task.tenant_id else None
    groups = (
        [keyword_group_to_dict(item) for item in list_keyword_groups(db, task.tenant_id)]
        if task.tenant_id
        else []
    )
    brand_terms = _ranking_match_terms(asset, groups)
    if brand_terms:
        return brand_terms
    keyword = str(task.monitor_keywords or "").strip()
    brand_terms = [keyword] if keyword else []
    request = task.raw_request_json or {}
    for alias in request.get("monitorKeywordAliases") or request.get("monitor_keyword_aliases") or []:
        text = str(alias or "").strip()
        if text and text not in brand_terms:
            brand_terms.append(text)
    return brand_terms


def fill_missing_subtask_ranks_for_task(
    db: Session,
    task: GeoMonitorTask,
    *,
    force_recompute: bool = False,
) -> int:
    """对「排名类 + 正文含品牌」子任务补算位次。

    2026-08-14 - 默认只补空：库内已有非人工位次不覆盖，避免详情/矩阵/补录互相洗数；
    force_recompute=True 才整单重算（运维脚本）。无品牌露出仍清掉非人工脏位次。
    """
    subtasks = list(
        db.scalars(
            select(GeoMonitorSubtask).where(GeoMonitorSubtask.task_id == task.task_id)
        )
    )
    if not subtasks:
        return 0
    brand_terms = _task_brand_terms_for_rank(db, task)
    if not brand_terms:
        return 0
    changed = 0
    for subtask in subtasks:
        if prompt_monitor_intent(subtask.prompt) != "ranking":
            continue
        if not str(subtask.answer_content or "").strip():
            continue
        # 2026-08-12 - 补录勿洗 - manual_snapshot 同步/补算一律跳过（位次以补录当时为准）
        if is_manual_snapshot_subtask(subtask):
            continue
        # 2026-08-11 - 正文未提仍留位次 - 同步后清掉非人工脏位次
        # 2026-08-11 - 同步清脏位次与排名门禁同口径 - 须配置露出词整段出现在正文
        if not _configured_exposure_term_in_text(_answer_body_for_rank(subtask), brand_terms):
            if subtask.mention_position is not None:
                subtask.mention_position = None
                changed += 1
            continue
        # 2026-08-14 - 只补空：已有位次默认信任库，根治「展开重算覆盖」
        if not force_recompute and subtask.mention_position is not None:
            continue
        before = subtask.mention_position
        recompute_subtask_rank_from_answer(db, subtask, task)
        if subtask.mention_position != before:
            changed += 1
    return changed


def ensure_subtask_rank_persisted(
    db: Session,
    subtask: GeoMonitorSubtask,
    task: GeoMonitorTask,
) -> bool:
    """详情/补跑：仅当库内位次为空时校正并落库。返回是否发生写入。

    2026-08-14 - GET 详情可触发只补空写回，读写分离于「默认不覆盖已有值」
    """
    if is_manual_snapshot_subtask(subtask):
        return False
    if prompt_monitor_intent(subtask.prompt) != "ranking":
        return False
    if not str(subtask.answer_content or "").strip():
        return False
    if subtask.mention_position is not None:
        return False
    brand_terms = _task_brand_terms_for_rank(db, task)
    if brand_terms and not _configured_exposure_term_in_text(
        _answer_body_for_rank(subtask), brand_terms
    ):
        # 无露出：显式落 null resolution，避免详情全文路径与矩阵分叉
        from app.services.rank_llm_service import persist_rank_resolution

        persist_rank_resolution(
            subtask,
            BrandRankResolution(rank=None, mentioned=False, source="none", confidence=0.95),
        )
        return True
    before = subtask.mention_position
    recompute_subtask_rank_from_answer(db, subtask, task)
    return subtask.mention_position != before


def _apply_remote_task_counts(task: GeoMonitorTask, status_data: dict[str, Any]) -> None:
    """合并远端进度；0 是合法值，不能用 or 保留旧数。"""
    mapping = (
        ("totalItems", "total_items"),
        ("completedItems", "completed_items"),
        ("failedItems", "failed_items"),
    )
    for remote_key, attr in mapping:
        if remote_key in status_data and status_data[remote_key] is not None:
            setattr(task, attr, status_data[remote_key])


def customer_display_cutoff(now: datetime | None = None) -> datetime:
    """客户侧数据截止时间：昨日 23:59:59.999999（不含今日）。"""
    anchor = now or datetime.now()
    day = anchor.date() - timedelta(days=1)
    return datetime.combine(day, time.max)


def customer_display_date_range(
    *,
    now: datetime | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    default_lookback_days: int | None = 7,
) -> tuple[datetime, datetime]:
    """客户可见区间：结束不晚于昨日；起始默认近 default_lookback_days 天，None 表示不限起始。"""
    cutoff = customer_display_cutoff(now)
    range_end = min(end_at, cutoff) if end_at else cutoff
    if start_at is not None:
        range_start = start_at
    elif default_lookback_days is not None:
        range_start = datetime.combine(
            range_end.date() - timedelta(days=max(0, default_lookback_days - 1)),
            time.min,
        )
    else:
        range_start = datetime(2000, 1, 1)
    if range_start > range_end:
        range_start = datetime.combine(range_end.date(), time.min)
    return range_start, range_end


def resolve_monitor_date_range(
    current: CurrentSession,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    *,
    customer_like: bool = False,
) -> tuple[datetime, datetime]:
    """客户身份截止昨日且不含今日；平台运营可按参数或默认近 7 日。"""
    if current.identity.identity_type == "CUSTOMER" or customer_like:
        return customer_display_date_range(start_at=start_at, end_at=end_at, default_lookback_days=7)
    now = datetime.now()
    range_start = start_at or (now - timedelta(days=7))
    range_end = end_at or now
    if range_start > range_end:
        range_start, range_end = range_end, range_start
    return range_start, range_end


def filter_customer_visible_subtasks(
    db: Session,
    subtasks: list[GeoMonitorSubtask],
    *,
    now: datetime | None = None,
) -> list[GeoMonitorSubtask]:
    """客户侧可见子任务，与单条详情 API 共用检测日 / updated_at 截止昨日规则。"""
    if not subtasks:
        return []
    task_ids = list({item.task_id for item in subtasks if item.task_id})
    schedule_runs_map = schedule_runs_for_tasks(db, task_ids)
    lead_runs_map = lead_diagnosis_runs_for_tasks(db, task_ids)
    tenant_ids = list({
        item.task.tenant_id
        for item in subtasks
        if item.task and item.task.tenant_id
    })
    assets_by_tenant: dict[int, BrandAsset | None] = {
        tenant_id: get_brand_asset(db, tenant_id) for tenant_id in tenant_ids
    }
    schedule_ctx_by_task: dict[str, dict[str, Any]] = {}
    visible: list[GeoMonitorSubtask] = []
    for item in subtasks:
        task = item.task
        if task is None:
            continue
        task_id = task.task_id
        if task_id not in schedule_ctx_by_task:
            asset = assets_by_tenant.get(task.tenant_id) if task.tenant_id else None
            schedule_ctx_by_task[task_id] = _resolve_subtask_schedule_context(
                task,
                schedule_runs_map,
                asset,
                lead_runs_map,
            )
        if customer_subtask_visible(item, now, task=task, schedule_ctx=schedule_ctx_by_task[task_id]):
            visible.append(item)
    return visible


def list_pending_monitor_task_ids(
    db: Session,
    *,
    task_id: str | None = None,
    limit: int = 50,
    terminal_grace_hours: int = 24,
) -> list[str]:
    """Return monitor task ids that still need Molizhishu sync."""
    stmt = select(GeoMonitorTask.task_id).where(GeoMonitorTask.deleted.is_(False))
    if task_id:
        stmt = stmt.where(GeoMonitorTask.task_id == task_id)
    else:
        grace_cutoff = datetime.now() - timedelta(hours=max(0, terminal_grace_hours))
        stmt = stmt.where(
            or_(
                GeoMonitorTask.status.notin_(TERMINAL_STATUSES),
                and_(
                    GeoMonitorTask.status.in_(("partial_completed", "failed", "stopped")),
                    GeoMonitorTask.updated_at >= grace_cutoff,
                ),
            )
        )
    # Oldest-first so backlog cannot starve early pending tasks (CWE-400).
    stmt = stmt.order_by(GeoMonitorTask.updated_at.asc(), GeoMonitorTask.id.asc()).limit(limit)
    return list(db.scalars(stmt))


def _platform_display_names() -> dict[str, str]:
    from app.services.molizhishu_catalog_service import get_supported_platform_catalog

    return {
        str(item.get("code") or ""): str(item.get("name") or item.get("code") or "")
        for item in get_supported_platform_catalog(force_refresh=False)
    }


def _short_task_id(task_id: str) -> str:
    text = str(task_id or "").strip()
    if len(text) <= 16:
        return text
    return f"{text[:8]}…{text[-4:]}"


def _subtask_effective_status(subtask: GeoMonitorSubtask) -> str:
    if subtask.error_message or subtask.status in {"failed", "stopped"}:
        return "failed"
    if subtask.answer_content or subtask.status in {"completed", "partial_completed"}:
        return "completed"
    if subtask.status in {"pending", "queued"}:
        return "pending"
    return "processing"


def _truncate_prompt(text: str, max_len: int = 48) -> str:
    cleaned = " ".join(str(text or "").split())
    if len(cleaned) <= max_len:
        return cleaned
    return cleaned[: max_len - 1] + "…"


def summarize_monitor_task_for_ops(
    task: GeoMonitorTask,
    *,
    tenant_name: str | None = None,
    schedule_run: GeoMonitorScheduleRun | None = None,
    asset: BrandAsset | None = None,
    platform_names: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build operations-dashboard summary for one monitor task (sync/submit visibility)."""
    platform_names = platform_names or _platform_display_names()
    _reconcile_task_progress(task)
    prompts = [str(item) for item in (task.prompts_json or []) if str(item or "").strip()]
    configured_platforms = [
        str(item.get("platform") if isinstance(item, dict) else item)
        for item in (task.platforms_json or [])
        if str(item.get("platform") if isinstance(item, dict) else item or "").strip()
    ]
    configured_platforms = sort_platform_codes(configured_platforms)

    platform_stats: dict[str, dict[str, Any]] = {
        code: {
            "code": code,
            "name": platform_names.get(code, code),
            "total": 0,
            "completed": 0,
            "pending": 0,
            "processing": 0,
            "failed": 0,
            "pending_prompts": [],
        }
        for code in configured_platforms
    }
    for subtask in task.subtasks or []:
        code = str(subtask.platform or "").strip()
        if not code:
            continue
        bucket = platform_stats.setdefault(
            code,
            {
                "code": code,
                "name": platform_names.get(code, code),
                "total": 0,
                "completed": 0,
                "pending": 0,
                "processing": 0,
                "failed": 0,
                "pending_prompts": [],
            },
        )
        bucket["total"] += 1
        effective = _subtask_effective_status(subtask)
        bucket[effective] = int(bucket.get(effective) or 0) + 1
        if effective == "pending":
            pending_prompts = bucket["pending_prompts"]
            if len(pending_prompts) < 5:
                pending_prompts.append(_truncate_prompt(subtask.prompt))

    platform_breakdown = sort_platform_items(list(platform_stats.values()), key="code")
    pending_platforms = [item["name"] for item in platform_breakdown if int(item.get("pending") or 0) > 0]
    processing_platforms = [item["name"] for item in platform_breakdown if int(item.get("processing") or 0) > 0]
    schedule_context = resolve_task_schedule_context(task, schedule_run, asset)

    return {
        "task_id": task.task_id,
        "task_id_short": _short_task_id(task.task_id),
        "tenant_id": task.tenant_id,
        "tenant_name": tenant_name,
        "monitor_keywords": task.monitor_keywords,
        "status": task.status,
        "total_items": task.total_items,
        "completed_items": task.completed_items,
        "failed_items": task.failed_items,
        "progress_text": f"{task.completed_items or 0}/{task.total_items or len(task.subtasks or [])}",
        "prompt_count": len(prompts),
        "prompts": prompts[:8],
        "prompts_preview": "；".join(_truncate_prompt(item) for item in prompts[:3]) or None,
        "platform_count": len(configured_platforms),
        "platform_codes": configured_platforms,
        "platform_breakdown": platform_breakdown,
        "pending_platforms": pending_platforms,
        "processing_platforms": processing_platforms,
        "schedule_label": schedule_context.get("schedule_label"),
        "keyword_group": schedule_context.get("keyword_group"),
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
    }


def summarize_monitor_tasks_for_ops(
    db: Session,
    *,
    task_ids: list[str] | None = None,
    limit: int = 15,
    terminal_grace_hours: int = 24,
) -> list[dict[str, Any]]:
    """Summarize pending/in-progress monitor tasks for the operations dashboard."""
    ids = task_ids or list_pending_monitor_task_ids(
        db,
        limit=limit,
        terminal_grace_hours=terminal_grace_hours,
    )
    if not ids:
        return []

    tasks = list(
        db.scalars(
            select(GeoMonitorTask)
            .options(joinedload(GeoMonitorTask.subtasks))
            .where(GeoMonitorTask.task_id.in_(ids), GeoMonitorTask.deleted.is_(False))
        ).unique()
    )
    task_map = {item.task_id: item for item in tasks}
    ordered_tasks = [task_map[task_id] for task_id in ids if task_id in task_map]

    tenant_ids = {item.tenant_id for item in ordered_tasks if item.tenant_id}
    tenant_map = {
        item.id: item.name
        for item in db.scalars(select(Tenant).where(Tenant.id.in_(tenant_ids), Tenant.deleted.is_(False)))
    } if tenant_ids else {}
    runs_map = schedule_runs_for_tasks(db, ids)
    assets = {
        item.tenant_id: item
        for item in db.scalars(
            select(BrandAsset).where(BrandAsset.tenant_id.in_(tenant_ids), BrandAsset.deleted.is_(False))
        )
    } if tenant_ids else {}
    platform_names = _platform_display_names()

    return [
        summarize_monitor_task_for_ops(
            task,
            tenant_name=tenant_map.get(task.tenant_id) if task.tenant_id else None,
            schedule_run=runs_map.get(task.task_id),
            asset=assets.get(task.tenant_id) if task.tenant_id else None,
            platform_names=platform_names,
        )
        for task in ordered_tasks
    ]


def _validate_tenant_service_available(tenant: Tenant) -> None:
    """模力提交闸门：未开始/到期/停服一律拦截（售前诊断走 submit_standalone_monitor_task 豁免）。"""
    # 2026-08-03 - 先看合同日再看 status，避免「未开始但 status=0」误报成已停止
    today = datetime.now().date()
    if tenant.service_start_date and tenant.service_start_date > today:
        raise ValueError(f"企业服务尚未开始，开始日期为 {tenant.service_start_date}")
    if tenant.service_end_date and tenant.service_end_date < today:
        raise ValueError(f"企业服务已到期，到期日期为 {tenant.service_end_date}")
    if not tenant.status:
        raise ValueError("企业服务已停止，不能提交新的监测任务")


def _reconcile_task_progress(task: GeoMonitorTask) -> None:
    """根据本地子任务终态修正主任务进度，避免远端主状态长期 processing 造成误导。"""
    subtasks = list(task.subtasks or [])
    if not subtasks:
        return
    terminal_count = sum(1 for item in subtasks if item.status in TERMINAL_STATUSES)
    abnormal_count = sum(
        1
        for item in subtasks
        if item.status in {"failed", "stopped"}
        or (item.error_message and not item.answer_content)
    )
    success_count = sum(1 for item in subtasks if item.status in {"completed", "partial_completed"} or item.answer_content)
    task.total_items = task.total_items or len(subtasks)
    task.completed_items = max(task.completed_items or 0, terminal_count)
    # 以本地子任务终态为准（自动重试成功回写后需能下降）
    task.failed_items = abnormal_count
    awaiting_rank = any(_subtask_awaiting_upstream_rank(item) for item in subtasks)
    if awaiting_rank:
        # 正文已到但上游榜单未落定：保持可同步，避免过早 completed 后不再拉结果
        task.status = "processing"
    elif terminal_count >= len(subtasks):
        task.status = "partial_completed" if abnormal_count else "completed"
    elif success_count > 0 and task.status not in TERMINAL_STATUSES:
        task.status = "processing"


def _resolved_subtask_status(current_status: str | None, incoming_status: str | None, has_answer: bool, has_error: bool) -> str:
    """合并远端状态时避免状态倒退：已有回答的子任务不能再展示为排队中。"""
    if has_error:
        return "failed"
    if has_answer:
        return "completed"
    if current_status in TERMINAL_STATUSES and incoming_status in NON_TERMINAL_STATUSES:
        return current_status
    return incoming_status or current_status or "pending"


def _split_keywords(text: str | None) -> list[str]:
    """把任务监控词拆成列表，用于来源聚合展示。"""
    if not text:
        return []
    normalized = str(text).replace("，", ",").replace("、", ",").replace("\n", ",")
    return [item.strip() for item in normalized.split(",") if item.strip()]


def _source_filter_terms(asset: BrandAsset | None) -> list[str]:
    """生成客户侧引用来源过滤词，避免把同名短词和泛行业词误判为有效来源。"""
    if asset is None:
        return []
    result: set[str] = set()
    company_full_name = str(asset.company_full_name or "").strip()
    if company_full_name:
        result.add(company_full_name.lower())
        for prefix in ("北京", "上海", "广州", "深圳", "杭州", "南京", "苏州", "成都", "重庆", "天津", "武汉", "西安"):
            if company_full_name.startswith(prefix) and len(company_full_name) - len(prefix) >= 6:
                result.add(company_full_name[len(prefix) :].lower())

    for term in asset.monitor_keywords_json or []:
        text = str(term or "").strip()
        if not text:
            continue
        is_exact_company = text == company_full_name
        is_legal_company_name = text.endswith("公司") and company_full_name and text in company_full_name and len(text) >= 6
        if is_exact_company or is_legal_company_name:
            result.add(text.lower())
    if asset.official_url:
        result.add(asset.official_url.lower().replace("https://", "").replace("http://", "").split("/")[0])
    return list(result)


def _citation_site_label(source: dict[str, Any]) -> str | None:
    """引用里的中文站名；若 site 实际是 URL/域名则返回 None。"""
    raw = str(source.get("site") or "").strip()
    if raw:
        lower = raw.lower()
        if "://" not in lower:
            has_cjk = any("\u4e00" <= ch <= "\u9fff" for ch in raw)
            if has_cjk or ("." not in raw and len(raw) <= 40):
                # 多标签如「广告传媒,户外大屏」取第一段
                first = re.split(r"[,，/|、]", raw, maxsplit=1)[0].strip()
                if first:
                    return first[:40]
    # site 为空时，从标题尾部「_站名 / - 站名」兜底
    title = str(source.get("title") or "").strip()
    if title:
        m = re.search(r"(?:_|[-–—]\s*)([\u4e00-\u9fffA-Za-z0-9·]{2,24})$", title)
        if m and any("\u4e00" <= ch <= "\u9fff" for ch in m.group(1)):
            return m.group(1)
        if len(title) <= 16 and any("\u4e00" <= ch <= "\u9fff" for ch in title) and "://" not in title:
            return title
    return None


def _is_valid_citation_source(source: dict[str, Any]) -> bool:
    """判断是否为可纳入统计的 AI 引用来源（排除搜索热榜、静态资源/CDN 等噪音）。"""
    title_site = " ".join(str(source.get(key) or "") for key in ("title", "site")).lower()
    url = str(source.get("url") or source.get("site") or "").lower()
    if not title_site.strip() and not url.strip():
        return False
    # 2026-08-04 - 结项高频信源噪音多 - 补搜索页/文库/短视频聚合站黑名单
    noisy_tokens = (
        "window._",
        "search.quark.cn",
        "by2=news",
        "docin.com",
        "haokan.baidu.com",
        "quanmin.baidu.com",
        "aiqicha.baidu.com/details/ranklist",
        "cnpp.cn",
        "cnblogs.com",
    )
    if any(token in title_site or token in url for token in noisy_tokens):
        return False
    # 路径后缀像静态资源则丢弃（避免 ?v=1.css 误伤，只看 path）
    # 2026-08-14 - DeepSeek 引用列表混入 css/png/json - 补 .json，写入/展示统一拦
    path = url.split("?", 1)[0]
    if any(
        path.endswith(ext)
        for ext in (
            ".css", ".js", ".mjs", ".map", ".json",
            ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico",
            ".woff", ".woff2", ".ttf", ".eot",
        )
    ):
        return False
    asset_hosts = (
        "byteimg.com",
        "lf3-static",
        "lf-flow",
        "ibytedapm",
        "cdn.jsdelivr",
        "unpkg.com",
        "googleapis.com",
        "gstatic.com",
        "cloudflare.com/ajax",
        # 2026-08-14 - DeepSeek 站静态域名整站不当信源
        "fe-static.deepseek.com",
        "cdn.deepseek.com",
        # 2026-08-14 - 阿里系 CDN 裸域无后缀也会进引用（g.alicdn / img.alicdn）
        "alicdn.com",
        "taobaocdn.com",
        "tbcdn.cn",
    )
    if any(bit in url for bit in asset_hosts):
        return False
    return True


def _filter_citation_sources(refs: Any) -> list[dict[str, Any]]:
    """写入/展示共用：只保留有效引用 dict。"""
    if not isinstance(refs, list):
        return []
    out: list[dict[str, Any]] = []
    for item in refs:
        if isinstance(item, dict):
            if _is_valid_citation_source(item):
                out.append(item)
            continue
        text = str(item or "").strip()
        if not text:
            continue
        row = {"url": text, "title": text}
        if _is_valid_citation_source(row):
            out.append(row)
    return out


def _light_source_articles_from_refs(refs: Any, *, limit: int = 3) -> list[dict[str, str]]:
    """从 reference_list_json 抽标题/域名，供收录明细关键词筛（hydrate 前也能搜标题）。"""
    from urllib.parse import urlparse

    articles: list[dict[str, str]] = []
    seen: set[str] = set()
    if not isinstance(refs, list):
        return articles
    for source in refs:
        if not isinstance(source, dict) or not _is_valid_citation_source(source):
            continue
        url = str(source.get("url") or "").strip()
        if not url.startswith(("http://", "https://")):
            continue
        key = url.split("?", 1)[0]
        if key in seen:
            continue
        seen.add(key)
        title = str(source.get("title") or source.get("site") or key).strip() or key
        domain = ""
        try:
            domain = (urlparse(url).hostname or "").replace("www.", "")
        except Exception:
            domain = ""
        articles.append({
            "title": title[:120],
            "url": url,
            "domain": domain,
        })
        if len(articles) >= limit:
            break
    return articles


def _snapshot_source_articles(item: GeoMonitorSubtask, *, limit: int = 2) -> list[dict[str, str]]:
    """收录明细用：引用文章标题 + 可点开的原文 URL。"""
    return _light_source_articles_from_refs(item.reference_list_json, limit=limit)


def _is_relevant_source(source: dict[str, Any], terms: list[str]) -> bool:
    """判断引用来源是否与当前企业相关，过滤搜索页热榜和同名无关公司。"""
    if not _is_valid_citation_source(source):
        return False
    if not terms:
        return True
    # 2026-08-13 - 方案 A：相关判定与露出词一致，补 summary（仍不抓网页）
    from app.services.citation_page_match import citation_local_match_text

    title_site = citation_local_match_text(source)
    url = str(source.get("url") or "").lower()
    domain_terms = [term for term in terms if "." in term]
    company_terms = [term for term in terms if "." not in term]
    if any(term.lower() in title_site for term in company_terms):
        return True
    return any(term.lower() in url for term in domain_terms)


def _matched_source_keywords(
    source: dict[str, Any],
    keywords: list[str],
    *,
    allow_page_fetch: bool = False,
    fetch_budget: list[int] | None = None,
) -> list[str]:
    """提取来源中实际命中的监控词。

    2026-08-13 - 方案 A：本地补 summary；物化时可抓网页标题/摘要/正文片段
    """
    from app.services.citation_page_match import matched_source_keywords

    return matched_source_keywords(
        source,
        keywords,
        allow_page_fetch=allow_page_fetch,
        fetch_budget=fetch_budget,
    )


def _aggregate_source_stats(
    completed_items: list[GeoMonitorSubtask],
    *,
    business_day_by_id: dict[int, date],
    subtask_tenant_map: dict[int, int],
    purchased_platforms_by_tenant: dict[int, set[str]],
    exposure_terms_by_tenant: dict[int, list[str]],
    require_exposure: bool = True,
) -> tuple[list[dict[str, Any]], dict[str, int], dict[str, dict[str, int]]]:
    """汇总引用信源。require_exposure=True 时标题/链接须命中露出词才收录。"""
    branded, all_stats, daily, daily_by_platform = _aggregate_source_stats_pair(
        completed_items,
        business_day_by_id=business_day_by_id,
        subtask_tenant_map=subtask_tenant_map,
        purchased_platforms_by_tenant=purchased_platforms_by_tenant,
        exposure_terms_by_tenant=exposure_terms_by_tenant,
    )
    if require_exposure:
        return branded, daily, daily_by_platform
    return all_stats, daily, daily_by_platform


def _finalize_source_stat_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # ponytail: 响应/缓存体积上限；排行页只需头部，超过可后续再做分页接口
    # 2026-08-14 - 日物化旧脏 CDN 在读路径再滤，避免信源页绕过抽屉过滤
    cleaned = [row for row in rows if isinstance(row, dict) and _is_valid_citation_source(row)]
    ranked = sorted(cleaned, key=lambda item: item["count"], reverse=True)[:500]
    for row in ranked:
        row["platforms"] = sort_platform_codes(row["platforms"])[:6]
        row["exposure_terms"] = row["exposure_terms"][:8]
        row["questions"] = row["questions"][:8]
        row["has_exposure"] = bool(row.get("exposure_terms"))
    return ranked


def _aggregate_source_stats_pair_maps(
    completed_items: list[GeoMonitorSubtask],
    *,
    business_day_by_id: dict[int, date],
    subtask_tenant_map: dict[int, int],
    purchased_platforms_by_tenant: dict[int, set[str]],
    exposure_terms_by_tenant: dict[int, list[str]],
    allow_page_fetch: bool = False,
    page_fetch_budget: int = 40,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, int], dict[str, dict[str, int]]]:
    """一次遍历产出未截断的 url→行 map（供日级物化合并）+ 日趋势计数。"""
    branded_map: dict[str, dict[str, Any]] = {}
    all_map: dict[str, dict[str, Any]] = {}
    source_daily_counts: dict[str, int] = {}
    source_daily_counts_by_platform: dict[str, dict[str, int]] = {}
    # 2026-08-13 - 方案 A：单日物化抓网页上限，避免重建卡死
    fetch_budget = [max(0, int(page_fetch_budget))] if allow_page_fetch else None

    def _touch_row(
        bucket: dict[str, dict[str, Any]],
        *,
        key: str,
        source: dict[str, Any],
        url: Any,
        matched_exposure: list[str],
        item: GeoMonitorSubtask,
        biz_day: date | None,
    ) -> None:
        row = bucket.setdefault(
            key,
            {
                "title": source.get("title") or source.get("site") or key,
                "url": url,
                "site": _citation_site_label(source),
                "count": 0,
                "platforms": [],
                "exposure_terms": [],
                "questions": [],
                "latest_time": None,
            },
        )
        row["count"] += 1
        if not row.get("site"):
            site_label = _citation_site_label(source)
            if site_label:
                row["site"] = site_label
        if item.platform and item.platform not in row["platforms"]:
            row["platforms"].append(item.platform)
        for term in matched_exposure:
            if term not in row["exposure_terms"]:
                row["exposure_terms"].append(term)
        if item.prompt and item.prompt not in row["questions"]:
            row["questions"].append(item.prompt)
        # ponytail: latest_time=监测业务日；禁止 updated_at（补录会刷到今天）
        if biz_day is not None:
            candidate = datetime.combine(biz_day, time.max).isoformat(timespec="seconds")
            if row["latest_time"] is None or candidate > row["latest_time"]:
                row["latest_time"] = candidate

    for item in completed_items:
        tenant_id = subtask_tenant_map.get(item.id)
        purchased_platforms = purchased_platforms_by_tenant.get(tenant_id) if tenant_id else None
        if purchased_platforms and item.platform not in purchased_platforms:
            continue
        exposure_terms = exposure_terms_by_tenant.get(tenant_id, []) if tenant_id else []
        for source in item.reference_list_json or []:
            if not _is_valid_citation_source(source):
                continue
            url = source.get("url") or source.get("site") or source.get("title")
            if not url:
                continue
            key = str(url).split("?")[0]
            matched_exposure = _matched_source_keywords(
                source,
                exposure_terms,
                allow_page_fetch=allow_page_fetch,
                fetch_budget=fetch_budget,
            )
            biz_day = business_day_by_id.get(item.id)
            _touch_row(
                all_map,
                key=key,
                source=source,
                url=url,
                matched_exposure=matched_exposure,
                item=item,
                biz_day=biz_day,
            )
            if not matched_exposure:
                continue
            _touch_row(
                branded_map,
                key=key,
                source=source,
                url=url,
                matched_exposure=matched_exposure,
                item=item,
                biz_day=biz_day,
            )
            if biz_day:
                day_key = biz_day.isoformat()
                source_daily_counts[day_key] = source_daily_counts.get(day_key, 0) + 1
                if item.platform:
                    plat_bucket = source_daily_counts_by_platform.setdefault(item.platform, {})
                    plat_bucket[day_key] = plat_bucket.get(day_key, 0) + 1

    return branded_map, all_map, source_daily_counts, source_daily_counts_by_platform


def _aggregate_source_stats_pair(
    completed_items: list[GeoMonitorSubtask],
    *,
    business_day_by_id: dict[int, date],
    subtask_tenant_map: dict[int, int],
    purchased_platforms_by_tenant: dict[int, set[str]],
    exposure_terms_by_tenant: dict[int, list[str]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int], dict[str, dict[str, int]]]:
    """一次遍历产出：含露出词榜 + 全量引用榜；日趋势仍按含露出词计数。"""
    branded_map, all_map, source_daily_counts, source_daily_counts_by_platform = _aggregate_source_stats_pair_maps(
        completed_items,
        business_day_by_id=business_day_by_id,
        subtask_tenant_map=subtask_tenant_map,
        purchased_platforms_by_tenant=purchased_platforms_by_tenant,
        exposure_terms_by_tenant=exposure_terms_by_tenant,
    )
    return (
        _finalize_source_stat_rows(list(branded_map.values())),
        _finalize_source_stat_rows(list(all_map.values())),
        source_daily_counts,
        source_daily_counts_by_platform,
    )


def _effective_tenant_id(current: CurrentSession, requested_tenant_id: int | None) -> int | None:
    """根据当前身份确定任务所属企业，客户端只能写入本企业。"""
    if current.identity.identity_type == "CUSTOMER":
        return current.identity.tenant_id
    return requested_tenant_id


def _build_submit_payload(
    payload: MonitorTaskCreateRequest,
    *,
    monitor_keywords: str | None = None,
    monitor_keyword_aliases: list[str] | None = None,
    competitors: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """把本地请求转换为模力指数提交任务请求。"""
    submittable_codes = filter_submittable_platforms([item.platform for item in payload.platforms])
    if not submittable_codes:
        raise ValueError("未配置支持的监测平台")
    platform_items = [
        item for item in payload.platforms if item.platform in submittable_codes
    ]
    request_body: dict[str, Any] = {
        "prompts": payload.prompts,
        "platforms": [_fast_platform_payload(item) for item in platform_items],
    }
    final_monitor_keywords = monitor_keywords or payload.monitor_keywords
    final_aliases = monitor_keyword_aliases if monitor_keyword_aliases is not None else payload.monitor_keyword_aliases
    final_competitors = competitors if competitors is not None else [item.model_dump() for item in payload.competitors if item.name]
    if final_monitor_keywords:
        request_body["monitorKeywords"] = final_monitor_keywords
    if final_aliases:
        request_body["monitorKeywordAliases"] = final_aliases
    if final_competitors:
        request_body["competitors"] = final_competitors
    if payload.region_code:
        region_codes = normalize_region_codes(payload.region_code)
        if region_codes:
            # ponytail: 模力 batch 接口仅接受单个 regionCode 字符串
            request_body["regionCode"] = region_codes[0]
    callback_url = str(payload.callback_url) if payload.callback_url else settings.molizhishu_callback_url.strip()
    if callback_url:
        request_body["callbackUrl"] = callback_url
    return request_body


def _fast_platform_payload(item: PlatformConfig) -> dict[str, Any]:
    """提交平台配置；快速统一联网 search，深度思考原样；截图强制开启。"""
    # 2026-08-11 - 快速→search 拿信源；reasoning* 不动（已弃用 8/3 提交层全保留 standard）
    payload = item.model_dump()
    payload["screenshot"] = 1
    mode = str(payload.get("mode") or "").strip().lower()
    if mode not in {"reasoning", "reasoning_search"}:
        payload["mode"] = FAST_MONITOR_MODE
    return payload


def _upsert_subtask(db: Session, task_id: str, item: dict[str, Any]) -> GeoMonitorSubtask:
    """按 subTaskId 幂等保存子任务摘要或完整结果。"""
    subtask_id = str(item.get("subTaskId") or "")
    if not subtask_id:
        raise ValueError("监测子任务缺少 subTaskId")
    subtask = db.scalar(select(GeoMonitorSubtask).where(GeoMonitorSubtask.subtask_id == subtask_id))
    if subtask is None:
        subtask = GeoMonitorSubtask(
            subtask_id=subtask_id,
            task_id=task_id,
            platform=item.get("platform") or "",
            mode=item.get("mode") or "",
            prompt=item.get("prompt") or "",
            status=item.get("status") or "pending",
            raw_result_json=item,
        )
        db.add(subtask)
    elif is_manual_snapshot_subtask(subtask):
        # 2026-08-11 - 同步冲掉人工补录 - manual_snapshot 只跟远端状态/费用，不盖正文与锁定元数据
        incoming_answer = item.get("answerContent")
        has_answer = bool(incoming_answer or subtask.answer_content)
        has_error = bool(item.get("errorMessage") or subtask.error_message)
        if item.get("status"):
            subtask.status = _resolved_subtask_status(subtask.status, item.get("status"), has_answer, has_error)
        if item.get("time") is not None:
            subtask.remote_time = item.get("time")
        if item.get("amount") is not None:
            subtask.amount = Decimal(str(item["amount"]))
        if item.get("proxyIp"):
            subtask.proxy_ip = item.get("proxyIp")
        return subtask

    incoming_answer = item.get("answerContent")
    has_answer = bool(incoming_answer or subtask.answer_content)
    has_error = bool(item.get("errorMessage") or subtask.error_message)
    subtask.platform = item.get("platform") or subtask.platform
    subtask.mode = item.get("mode") or subtask.mode
    subtask.prompt = item.get("prompt") or subtask.prompt
    subtask.status = _resolved_subtask_status(subtask.status, item.get("status"), has_answer, has_error)
    subtask.remote_time = item.get("time")
    subtask.page_screenshot = item.get("pageScreenshot") or None
    subtask.answer_content = incoming_answer or subtask.answer_content
    subtask.reference_list_json = _filter_citation_sources(item.get("referenceList")) or None
    subtask.citation_list_json = _filter_citation_sources(item.get("citationList")) or None
    subtask.reasoning_process_json = item.get("reasoningProcess")
    subtask.recommended_questions_json = item.get("recommendedQuestions")
    subtask.media_content_json = item.get("mediaContent")
    subtask.error_message = item.get("errorMessage")
    subtask.proxy_ip = item.get("proxyIp")
    subtask.amount = Decimal(str(item["amount"])) if item.get("amount") is not None else None
    from app.services.brand_analysis_service import preserve_brand_analysis_sentiment_on_upsert

    kept_sentiment, merged_raw = preserve_brand_analysis_sentiment_on_upsert(subtask, item if isinstance(item, dict) else {})
    subtask.sentiment = kept_sentiment
    subtask.raw_result_json = merged_raw
    _merge_remote_rank_fields(subtask, item)
    # 2026-07-27 - 扁平 allRankings 与段内序冲突 - upsert 后按正文分段规范化入库
    _normalize_subtask_rankings_on_write(subtask)
    return subtask


def submit_monitor_task(db: Session, payload: MonitorTaskCreateRequest, current: CurrentSession, *, auto_commit: bool = True) -> GeoMonitorTask:
    """提交模力指数任务并保存主任务与初始子任务。"""
    tenant_id = _effective_tenant_id(current, payload.tenant_id)
    if tenant_id is None:
        raise ValueError("请先选择或绑定企业，再提交 GEO 检测任务")
    tenant = db.scalar(select(Tenant).where(Tenant.id == tenant_id, Tenant.deleted.is_(False)))
    if tenant is None:
        raise ValueError("所属企业不存在")
    ensure_sales_tenant_access(db, current, tenant_id)
    _validate_tenant_service_available(tenant)
    default_monitor_keywords, default_aliases, competitors = molizhishu_brand_payload(db, tenant_id)
    monitor_keywords = payload.monitor_keywords or default_monitor_keywords
    aliases = payload.monitor_keyword_aliases or default_aliases
    request_body = _build_submit_payload(
        payload,
        monitor_keywords=monitor_keywords,
        monitor_keyword_aliases=aliases,
        competitors=competitors,
    )
    response = MolizhishuClient().submit_task(request_body)
    data = response.get("data") or {}
    task_id = data.get("taskId")
    if not task_id:
        raise ValueError("监测任务提交成功但未返回 taskId")
    existing = db.scalar(select(GeoMonitorTask).where(GeoMonitorTask.task_id == task_id))
    if existing is not None:
        raise ValueError(f"任务已存在：{task_id}")
    region_codes = normalize_region_codes(payload.region_code or []) or None
    from app.core.monitor_purpose import normalize_task_purpose

    task = GeoMonitorTask(
        task_id=task_id,
        tenant_id=tenant_id,
        created_by=current.user.id,
        monitor_keywords=monitor_keywords,
        status=data.get("status") or "pending",
        total_items=data.get("totalTask") or data.get("totalItems") or 0,
        completed_items=data.get("completedItems") or 0,
        failed_items=data.get("failedItems") or 0,
        prompts_json=payload.prompts,
        platforms_json=request_body["platforms"],
        region_code_json=region_codes,
        purpose=normalize_task_purpose(getattr(payload, "purpose", None)),
        callback_url=data.get("callbackUrl"),
        poll_url=data.get("pollUrl"),
        raw_request_json=request_body,
        raw_response_json=response,
    )
    db.add(task)
    for subtask in data.get("subTaskList") or []:
        _upsert_subtask(db, task_id, subtask)
    if auto_commit:
        db.commit()
        db.refresh(task)
    else:
        db.flush()
    return task


def submit_standalone_monitor_task(
    db: Session,
    *,
    payload: MonitorTaskCreateRequest,
    created_by: int | None = None,
    tenant_id: int | None = None,
    auto_commit: bool = True,
) -> GeoMonitorTask:
    """提交不依赖企业服务的监测任务（用于售前诊断等场景）。"""
    monitor_keywords = payload.monitor_keywords
    if not monitor_keywords:
        raise ValueError("请先填写品牌或监测词")
    request_body = _build_submit_payload(
        payload,
        monitor_keywords=monitor_keywords,
        monitor_keyword_aliases=payload.monitor_keyword_aliases,
        competitors=[item.model_dump() for item in payload.competitors if item.name],
    )
    response = MolizhishuClient().submit_task(request_body)
    data = response.get("data") or {}
    task_id = data.get("taskId")
    if not task_id:
        raise ValueError("监测任务提交成功但未返回 taskId")
    existing = db.scalar(select(GeoMonitorTask).where(GeoMonitorTask.task_id == task_id))
    if existing is not None:
        raise ValueError(f"任务已存在：{task_id}")
    region_codes = normalize_region_codes(payload.region_code or []) or None
    task = GeoMonitorTask(
        task_id=task_id,
        tenant_id=tenant_id,
        created_by=created_by,
        monitor_keywords=monitor_keywords,
        status=data.get("status") or "pending",
        total_items=data.get("totalTask") or data.get("totalItems") or 0,
        completed_items=data.get("completedItems") or 0,
        failed_items=data.get("failedItems") or 0,
        prompts_json=payload.prompts,
        platforms_json=request_body["platforms"],
        region_code_json=region_codes,
        callback_url=data.get("callbackUrl"),
        poll_url=data.get("pollUrl"),
        raw_request_json=request_body,
        raw_response_json=response,
    )
    db.add(task)
    for subtask in data.get("subTaskList") or []:
        _upsert_subtask(db, task_id, subtask)
    if auto_commit:
        db.commit()
        db.refresh(task)
    else:
        db.flush()
    return task


def list_monitor_tasks(
    db: Session,
    current: CurrentSession,
    *,
    tenant_id: int | None = None,
    purpose: str = "geo",
) -> list[GeoMonitorTask]:
    """读取本地任务列表，不隐式调用模力指数远端。平台预览可传 tenant_id 限定企业。

    默认仅 geo（日常 GEO 监测）；品牌词任务不进任务列表/实时监测。
    """
    from app.core.monitor_purpose import task_purpose_eq

    stmt = (
        select(GeoMonitorTask)
        .where(GeoMonitorTask.deleted.is_(False), task_purpose_eq(purpose))
        .order_by(GeoMonitorTask.id.desc())
    )
    if current.identity.identity_type == "CUSTOMER":
        stmt = stmt.where(GeoMonitorTask.tenant_id == current.identity.tenant_id)
    elif tenant_id is not None:
        stmt = stmt.where(GeoMonitorTask.tenant_id == tenant_id)
    else:
        owned_ids = sales_owned_tenant_ids(db, current)
        if owned_ids is not None:
            if not owned_ids:
                return []
            stmt = stmt.where(GeoMonitorTask.tenant_id.in_(owned_ids))
    return list(db.scalars(stmt.limit(200)))


def _build_source_citation_trend(
    daily_counts: dict[str, int],
    *,
    range_start: datetime,
    range_end: datetime,
    only_with_data: bool = False,
) -> dict[str, Any]:
    """按日构建引用趋势。only_with_data=True 时不补零日（避免四五六月一排 0）。"""
    start = range_start.date()
    end = range_end.date()
    points: list[dict[str, Any]] = []
    if only_with_data:
        for day_key in sorted(daily_counts):
            try:
                day = date.fromisoformat(day_key)
            except ValueError:
                continue
            if day < start or day > end:
                continue
            value = int(daily_counts.get(day_key) or 0)
            if value <= 0:
                continue
            points.append({
                "label": day.strftime("%m-%d"),
                "day_key": day_key,
                "value": value,
            })
    else:
        cursor = start
        while cursor <= end:
            day_key = cursor.isoformat()
            points.append({
                "label": cursor.strftime("%m-%d"),
                "day_key": day_key,
                "value": daily_counts.get(day_key, 0),
            })
            cursor += timedelta(days=1)
    return {
        "start_at": datetime.combine(start, time.min).isoformat(),
        "end_at": datetime.combine(end, time.max).isoformat(),
        "points": points,
    }


def _build_source_citation_trends_by_platform(
    daily_counts_by_platform: dict[str, dict[str, int]],
    *,
    range_start: datetime,
    range_end: datetime,
    only_with_data: bool = False,
) -> dict[str, dict[str, Any]]:
    return {
        platform: _build_source_citation_trend(
            daily_counts,
            range_start=range_start,
            range_end=range_end,
            only_with_data=only_with_data,
        )
        for platform, daily_counts in daily_counts_by_platform.items()
    }


def _compute_customer_source_stats_bundle(
    db: Session,
    tenant_id: int,
    *,
    purchased_platforms: set[str],
    exposure_terms: list[str],
) -> dict[str, Any]:
    """客户信源：监测日≤昨日全历史 + 露出词门槛；供 Redis 冷构建。

    方案 C：优先读 geo_monitor_source_daily 按日合并；缺日/配置变更时按日重建。
    """
    from app.services.monitor_source_rollup_service import build_customer_source_stats_from_daily

    return build_customer_source_stats_from_daily(
        db,
        tenant_id,
        purchased_platforms=purchased_platforms,
        exposure_terms=exposure_terms,
    )


def get_customer_source_stats_bundle(
    db: Session,
    tenant_id: int,
    *,
    purchased_platforms: set[str],
    exposure_terms: list[str],
) -> dict[str, Any]:
    """客户信源聚合：命中长 TTL 缓存则直接返回，语义仍是全部历史。"""
    from app.core.read_cache import (
        SOURCE_STATS_CACHE_TTL,
        get_or_build_json_cache,
        source_stats_cache_key,
        source_stats_config_fingerprint,
    )

    cutoff_day = customer_display_cutoff().date().isoformat()
    config_fp = source_stats_config_fingerprint(exposure_terms, purchased_platforms)
    cache_key = source_stats_cache_key(tenant_id, cutoff_day, config_fp)
    return get_or_build_json_cache(
        cache_key,
        lambda: _compute_customer_source_stats_bundle(
            db,
            tenant_id,
            purchased_platforms=purchased_platforms,
            exposure_terms=exposure_terms,
        ),
        ttl_seconds=SOURCE_STATS_CACHE_TTL,
        lock_ttl_seconds=120,
        wait_seconds=45.0,
    )


def scope_source_analysis_bundle(
    bundle: dict[str, Any],
    allow: frozenset[str] | None,
) -> dict[str, Any]:
    """按平台白名单裁剪信源聚合结果（不改日物化写入口径）。

    2026-08-10 - 观察号若把 purchased 缩进 config_fp，uk(tenant,day) 全失效并踩踏全量物化；
    改为读全量后再滤。行 count 仍是跨端合计，多端同 URL 会略偏高；要精确需按端拆 count。
    """
    if allow is None:
        return bundle

    def _scope_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for row in rows or []:
            plats = [str(p) for p in (row.get("platforms") or []) if str(p) in allow]
            if not plats:
                continue
            cloned = dict(row)
            cloned["platforms"] = sort_platform_codes(plats)
            out.append(cloned)
        return out

    by_plat = bundle.get("source_citation_trend_by_platform") or {}
    scoped_by = {str(k): v for k, v in by_plat.items() if str(k) in allow}
    daily_counts: dict[str, int] = {}
    for trend in scoped_by.values():
        for pt in (trend or {}).get("points") or []:
            day_key = str(pt.get("day_key") or "")
            if not day_key:
                continue
            daily_counts[day_key] = daily_counts.get(day_key, 0) + int(pt.get("value") or 0)
    citation_range_end = customer_display_cutoff()
    positive_days = [date.fromisoformat(k) for k, v in daily_counts.items() if int(v or 0) > 0]
    citation_range_start = datetime.combine(
        min(positive_days) if positive_days else citation_range_end.date(),
        time.min,
    )
    return {
        **bundle,
        "source_stats": _scope_rows(list(bundle.get("source_stats") or [])),
        "source_stats_all": _scope_rows(list(bundle.get("source_stats_all") or [])),
        "source_citation_trend": _build_source_citation_trend(
            daily_counts,
            range_start=citation_range_start,
            range_end=citation_range_end,
            only_with_data=True,
        ),
        "source_citation_trend_by_platform": scoped_by,
    }


def build_source_analysis_summary(
    db: Session,
    current: CurrentSession,
    *,
    tenant_id: int | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    platform: str | None = None,
) -> dict[str, Any]:
    """信源分析页专用轻载荷：只聚合信源，不扫监测任务/子任务大表。

    2026-07-30 - 信源页等整包 summary ~7s - 独立接口走日物化缓存
    2026-08-14 - 支持起止日/平台：区间内重算 count 与趋势，勿前端假筛累计
    """
    from app.services.brand_service import (
        active_keyword_groups,
        brand_exposure_terms,
        get_brand_asset,
        tenant_purchased_platforms,
    )
    from app.services.monitor_source_rollup_service import _bundle_from_day_rows
    from app.services.observer_account import observer_platforms_for_session
    from app.services.tenant_scope import resolve_and_guard_analytics_tenant
    from app.models.monitor import GeoMonitorSourceDaily

    resolved = resolve_and_guard_analytics_tenant(
        db,
        current,
        tenant_id,
        menu_code="platform.sources" if current.identity.identity_type == "PLATFORM" else "customer.sources",
    )
    asset = get_brand_asset(db, resolved)
    exposure = brand_exposure_terms(asset, active_keyword_groups(db, resolved))
    purchased = set(tenant_purchased_platforms(db, resolved, asset))
    # 2026-08-10 - 观察号平台收窄放在 bundle 读后过滤，purchased 保持租户全量以免日物化指纹失效
    allow = observer_platforms_for_session(current)

    cutoff_day = customer_display_cutoff().date()
    end_d = min(end_date, cutoff_day) if end_date is not None else cutoff_day
    start_d = start_date
    if start_d is not None and start_d > end_d:
        start_d = end_d

    # 先暖全日物化缓存（截止昨日），再按区间合并，保证缺日会被补齐
    get_customer_source_stats_bundle(
        db,
        resolved,
        purchased_platforms=purchased,
        exposure_terms=exposure,
    )
    day_rows = list(
        db.scalars(
            select(GeoMonitorSourceDaily).where(
                GeoMonitorSourceDaily.tenant_id == resolved,
                GeoMonitorSourceDaily.stat_date <= end_d,
                *([GeoMonitorSourceDaily.stat_date >= start_d] if start_d is not None else []),
            )
        )
    )
    bundle = _bundle_from_day_rows(
        day_rows,
        cutoff_day=end_d,
        range_start_day=start_d,
    )
    bundle = scope_source_analysis_bundle(bundle, allow)
    platform_code = str(platform or "").strip()
    if platform_code:
        # ponytail: 多端同 URL 的 count 仍是跨端合计；精确分端需日物化拆 count
        def _plat_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
            out: list[dict[str, Any]] = []
            for row in rows or []:
                plats = [str(p) for p in (row.get("platforms") or [])]
                if platform_code not in plats:
                    continue
                cloned = dict(row)
                cloned["platforms"] = sort_platform_codes([platform_code])
                out.append(cloned)
            return out

        by_plat = bundle.get("source_citation_trend_by_platform") or {}
        plat_trend = by_plat.get(platform_code) or {
            "start_at": None,
            "end_at": None,
            "points": [],
        }
        bundle = {
            **bundle,
            "source_stats": _plat_rows(list(bundle.get("source_stats") or [])),
            "source_stats_all": _plat_rows(list(bundle.get("source_stats_all") or [])),
            "source_citation_trend": plat_trend,
            "source_citation_trend_by_platform": {platform_code: plat_trend},
        }

    platform_stats: list[dict[str, Any]] = []
    try:
        from app.services.monitor_stats_service import aggregate_platform_stats, has_daily_stats

        if has_daily_stats(db, [resolved]):
            since = start_d if start_d is not None else (end_d - timedelta(days=29))
            rows = aggregate_platform_stats(
                db,
                tenant_ids=[resolved],
                since=since,
                until=end_d,
            )
            if rows:
                if allow is not None:
                    rows = [row for row in rows if str(row.get("platform") or "") in allow]
                if platform_code:
                    rows = [row for row in rows if str(row.get("platform") or "") == platform_code]
                platform_stats = sort_platform_items(rows)
    except Exception:
        logger.exception("source analysis platform_stats failed tenant_id=%s", resolved)

    return {
        "tenant_id": resolved,
        "start_date": start_d.isoformat() if start_d else None,
        "end_date": end_d.isoformat(),
        "source_stats": bundle.get("source_stats") or [],
        "source_stats_all": bundle.get("source_stats_all") or [],
        "source_citation_trend": bundle.get("source_citation_trend") or {
            "start_at": None,
            "end_at": None,
            "points": [],
        },
        "source_citation_trend_by_platform": bundle.get("source_citation_trend_by_platform") or {},
        "platform_stats": platform_stats,
    }


def _empty_monitor_summary(current: CurrentSession) -> dict[str, Any]:
    return {
        "scope": current.identity.identity_type,
        "tenant_id": current.identity.tenant_id,
        "tenant_count": 0,
        "task_count": 0,
        "subtask_count": 0,
        "completed_count": 0,
        "mention_rate": 0.0,
        "avg_rank": 0.0,
        "platform_count": 0,
        "sentiment_counts": {"正面": 0, "中性": 0, "负面": 0, "未知": 0},
        "platform_stats": [],
        "source_stats": [],
        "source_stats_all": [],
        "source_citation_trend": {"start_at": None, "end_at": None, "points": []},
        "source_citation_trend_by_platform": {},
        "daily_trend": [],
        "daily_labels": [],
        "recent_tasks": [],
        "recent_subtasks": [],
        "summary_task_limit": 0,
    }


def monitor_summary(
    db: Session,
    current: CurrentSession,
    *,
    tenant_id: int | None = None,
) -> dict[str, Any]:
    """Build a read-only dashboard summary from stored Molizhishu task results."""
    # 平台端带 tenant_id 时按客户口径汇总（客户门户预览）
    customer_like = (
        current.identity.identity_type == "CUSTOMER"
        or (current.identity.identity_type == "PLATFORM" and tenant_id is not None)
    )
    summary_task_limit = 200
    # 客户路径信源走日物化，无需拉 reference_list / 截图大字段
    subtask_cols = [
        GeoMonitorSubtask.id,
        GeoMonitorSubtask.subtask_id,
        GeoMonitorSubtask.task_id,
        GeoMonitorSubtask.platform,
        GeoMonitorSubtask.mode,
        GeoMonitorSubtask.prompt,
        GeoMonitorSubtask.status,
        GeoMonitorSubtask.error_message,
        GeoMonitorSubtask.amount,
        GeoMonitorSubtask.mention_position,
        GeoMonitorSubtask.mention_context,
        GeoMonitorSubtask.sentiment,
        GeoMonitorSubtask.updated_at,
    ]
    if not customer_like:
        subtask_cols.extend(
            [
                GeoMonitorSubtask.page_screenshot,
                GeoMonitorSubtask.reference_list_json,
            ]
        )
    stmt = (
        select(GeoMonitorTask)
        .options(
            load_only(
                GeoMonitorTask.id,
                GeoMonitorTask.task_id,
                GeoMonitorTask.tenant_id,
                GeoMonitorTask.monitor_keywords,
                GeoMonitorTask.status,
                GeoMonitorTask.total_items,
                GeoMonitorTask.completed_items,
                GeoMonitorTask.failed_items,
                GeoMonitorTask.prompts_json,
                GeoMonitorTask.platforms_json,
                GeoMonitorTask.callback_url,
                GeoMonitorTask.poll_url,
                GeoMonitorTask.last_error,
                GeoMonitorTask.created_at,
                GeoMonitorTask.updated_at,
            ),
            joinedload(GeoMonitorTask.subtasks).load_only(*subtask_cols),
        )
        .where(GeoMonitorTask.deleted.is_(False))
        .order_by(GeoMonitorTask.id.desc())
        .limit(summary_task_limit)
    )
    if current.identity.identity_type == "CUSTOMER":
        stmt = stmt.where(GeoMonitorTask.tenant_id == current.identity.tenant_id)
    elif tenant_id is not None:
        stmt = stmt.where(GeoMonitorTask.tenant_id == tenant_id)
    else:
        owned_ids = sales_owned_tenant_ids(db, current)
        if owned_ids is not None:
            if not owned_ids:
                return _empty_monitor_summary(current)
            stmt = stmt.where(GeoMonitorTask.tenant_id.in_(owned_ids))
    tasks = list(db.scalars(stmt).unique())
    owned_ids = sales_owned_tenant_ids(db, current)
    tenant_stmt = select(Tenant).where(Tenant.deleted.is_(False))
    if tenant_id is not None:
        tenant_stmt = tenant_stmt.where(Tenant.id == tenant_id)
    elif owned_ids is not None:
        tenant_stmt = tenant_stmt.where(Tenant.id.in_(owned_ids))
    tenant_rows = list(db.scalars(tenant_stmt))
    tenant_map = {item.id: item.name for item in tenant_rows}
    tenant_ids = [task.tenant_id for task in tasks if task.tenant_id]
    asset_rows = list(db.scalars(select(BrandAsset).where(BrandAsset.tenant_id.in_(tenant_ids), BrandAsset.deleted.is_(False)))) if tenant_ids else []
    purchased_platforms_by_tenant = {
        asset.tenant_id: set(tenant_purchased_platforms(db, asset.tenant_id, asset))
        for asset in asset_rows
    }
    exposure_terms_by_tenant = {
        asset.tenant_id: brand_exposure_terms(asset, active_keyword_groups(db, asset.tenant_id))
        for asset in asset_rows
    }
    subtask_tenant_map = {subtask.id: task.tenant_id for task in tasks for subtask in task.subtasks}
    subtasks = [subtask for task in tasks for subtask in task.subtasks]
    if customer_like:
        subtasks = filter_customer_visible_subtasks(db, subtasks)
        visible_task_ids = {item.task_id for item in subtasks if item.task_id}
        tasks = [task for task in tasks if task.task_id in visible_task_ids]
    completed = [item for item in subtasks if item.status in TERMINAL_STATUSES]
    completed_ids = {item.id for item in completed}
    task_by_id = {task.task_id: task for task in tasks if task.task_id}
    completed_task_ids = list({item.task_id for item in completed if item.task_id})
    summary_schedule_runs = schedule_runs_for_tasks(db, completed_task_ids) if completed_task_ids else {}
    summary_lead_runs = lead_diagnosis_runs_for_tasks(db, completed_task_ids) if completed_task_ids else {}
    asset_by_tenant = {asset.tenant_id: asset for asset in asset_rows}

    def _summary_kpi_rank(item: GeoMonitorSubtask) -> float | int | None:
        tenant_id_for_item = subtask_tenant_map.get(item.id)
        task = task_by_id.get(item.task_id or "")
        return kpi_rank_for_subtask(
            item,
            task.monitor_keywords if task is not None else None,
            exposure_terms_by_tenant.get(tenant_id_for_item) or [],
            asset_by_tenant.get(tenant_id_for_item) if tenant_id_for_item else None,
        )

    kpi_rank_by_id = {item.id: _summary_kpi_rank(item) for item in subtasks}
    mentioned = [item for item in completed if kpi_rank_by_id.get(item.id) is not None]

    def _summary_business_day(item: GeoMonitorSubtask) -> date | None:
        task = task_by_id.get(item.task_id or "")
        if task is None:
            return item.updated_at.date() if item.updated_at else None
        tenant_id = subtask_tenant_map.get(item.id) or task.tenant_id
        detect_dt = _subtask_detect_datetime(
            item,
            task,
            resolve_task_schedule_context(
                task,
                summary_schedule_runs.get(item.task_id),
                asset_by_tenant.get(tenant_id),
                summary_lead_runs.get(item.task_id) if not getattr(task, "tenant_id", None) else None,
            ),
        )
        return detect_dt.date() if detect_dt else None

    business_day_by_id: dict[int, date] = {}
    for item in completed:
        day = _summary_business_day(item)
        if day is not None:
            business_day_by_id[item.id] = day

    total_cost = sum(float(item.amount or 0) for item in subtasks)
    mention_rate = round(len(mentioned) / len(completed) * 100, 1) if completed else 0.0
    avg_rank = (
        round(sum(float(kpi_rank_by_id[item.id]) for item in mentioned) / len(mentioned), 1)
        if mentioned
        else None
    )

    sentiment_labels = {
        "positive": "正面",
        "neutral": "中性",
        "negative": "负面",
        "正向": "正面",
        "中立": "中性",
        "负向": "负面",
    }
    sentiment_counts = {"正面": 0, "中性": 0, "负面": 0, "未知": 0}
    for item in completed:
        label = sentiment_labels.get(str(item.sentiment or "").strip().lower(), item.sentiment or "未知")
        if label not in sentiment_counts:
            label = "未知"
        sentiment_counts[label] += 1

    platform_bucket: dict[str, dict[str, Any]] = {}
    for item in subtasks:
        purchased_platforms = purchased_platforms_by_tenant.get(subtask_tenant_map.get(item.id))
        if purchased_platforms and item.platform not in purchased_platforms:
            continue
        bucket = platform_bucket.setdefault(
            item.platform,
            {"platform": item.platform, "total": 0, "completed": 0, "mentioned": 0, "rank_total": 0, "rank_count": 0},
        )
        bucket["total"] += 1
        if item.id in completed_ids:
            bucket["completed"] += 1
        rank = kpi_rank_by_id.get(item.id)
        if rank is not None:
            bucket["mentioned"] += 1
            bucket["rank_total"] += float(rank)
            bucket["rank_count"] += 1
    platform_stats = []
    for bucket in platform_bucket.values():
        total = bucket["total"] or 1
        platform_stats.append({
            "platform": bucket["platform"],
            "total": bucket["total"],
            "completed": bucket["completed"],
            "mention_rate": round(bucket["mentioned"] / total * 100, 1),
            "avg_rank": round(bucket["rank_total"] / bucket["rank_count"], 1) if bucket["rank_count"] else None,
        })
    platform_stats = sort_platform_items(platform_stats)
    summary_tenant_ids = [task.tenant_id for task in tasks if task.tenant_id]
    if customer_like and tenant_id is not None:
        summary_tenant_ids = [tenant_id]
    elif current.identity.identity_type == "CUSTOMER" and current.identity.tenant_id:
        summary_tenant_ids = [current.identity.tenant_id]
    elif owned_ids is not None:
        summary_tenant_ids = owned_ids

    from app.services.monitor_stats_service import (
        aggregate_daily_mention_trend,
        aggregate_platform_stats,
        has_daily_stats,
    )

    if has_daily_stats(db, summary_tenant_ids or None):
        stat_platform_stats = aggregate_platform_stats(
            db,
            tenant_ids=summary_tenant_ids or None,
            since=(datetime.now().date() - timedelta(days=30)),
        )
        if stat_platform_stats:
            platform_stats = sort_platform_items(stat_platform_stats)

    # 客户信源：全历史（≤昨日）+ 露出词门槛；独立长 TTL 缓存，首屏仍出全部历史
    scoped_customer_tenant = (
        int(tenant_id) if customer_like and tenant_id is not None
        else int(current.identity.tenant_id) if current.identity.identity_type == "CUSTOMER" and current.identity.tenant_id
        else None
    )
    if scoped_customer_tenant is not None:
        source_bundle = get_customer_source_stats_bundle(
            db,
            scoped_customer_tenant,
            purchased_platforms=purchased_platforms_by_tenant.get(scoped_customer_tenant) or set(),
            exposure_terms=exposure_terms_by_tenant.get(scoped_customer_tenant) or [],
        )
        source_stats = source_bundle.get("source_stats") or []
        source_stats_all = source_bundle.get("source_stats_all") or []
        source_citation_trend = source_bundle.get("source_citation_trend") or {
            "start_at": None,
            "end_at": None,
            "points": [],
        }
        source_citation_trend_by_platform = source_bundle.get("source_citation_trend_by_platform") or {}
    else:
        source_stats, source_stats_all, source_daily_counts, source_daily_by_platform = _aggregate_source_stats_pair(
            completed,
            business_day_by_id=business_day_by_id,
            subtask_tenant_map=subtask_tenant_map,
            purchased_platforms_by_tenant=purchased_platforms_by_tenant,
            exposure_terms_by_tenant=exposure_terms_by_tenant,
        )
        citation_lookback = 30
        citation_range_end = datetime.now()
        citation_range_start = datetime.combine(
            citation_range_end.date() - timedelta(days=citation_lookback - 1),
            time.min,
        )
        source_citation_trend = _build_source_citation_trend(
            source_daily_counts,
            range_start=citation_range_start,
            range_end=citation_range_end,
            only_with_data=False,
        )
        source_citation_trend_by_platform = _build_source_citation_trends_by_platform(
            source_daily_by_platform,
            range_start=citation_range_start,
            range_end=citation_range_end,
            only_with_data=False,
        )

    today = datetime.now().date()
    trend_end_day = customer_display_cutoff().date() if customer_like else today
    day_labels = []
    daily_trend = []
    trend_offsets = range(7, 0, -1) if customer_like else range(6, -1, -1)
    stat_trend = aggregate_daily_mention_trend(
        db,
        tenant_ids=summary_tenant_ids or None,
        days=len(list(trend_offsets)),
        end_day=trend_end_day,
    ) if has_daily_stats(db, summary_tenant_ids or None) else []
    if stat_trend:
        daily_trend = [{"label": p["label"], "value": p["value"]} for p in stat_trend]
        day_labels = [p["label"] for p in stat_trend]
    else:
        for offset in trend_offsets:
            day = today - timedelta(days=offset)
            value = sum(1 for item in mentioned if business_day_by_id.get(item.id) == day)
            day_labels.append(day.strftime("%m-%d"))
            daily_trend.append({"label": day.strftime("%m-%d"), "value": value})

    recent_tasks = [serialize_task(task) | {"tenant_name": tenant_map.get(task.tenant_id)} for task in tasks[:8]]
    recent_pairs = sorted(
        [(task, item) for task in tasks for item in task.subtasks],
        key=lambda pair: pair[1].updated_at or datetime.min,
        reverse=True,
    )
    recent_subtasks = [
        serialize_summary_subtask(item) | {"tenant_name": tenant_map.get(task.tenant_id)}
        for task, item in recent_pairs[:120]
    ]

    return {
        "scope": "CUSTOMER" if customer_like else current.identity.identity_type,
        "tenant_id": scoped_customer_tenant if customer_like else current.identity.tenant_id,
        "tenant_count": 1 if customer_like else (len(tenant_rows) if current.identity.identity_type == "PLATFORM" else 1),
        "task_count": len(tasks),
        "subtask_count": len(subtasks),
        "completed_count": len(completed),
        "failed_count": sum(1 for item in subtasks if item.status == "failed" or item.error_message),
        "total_cost": round(total_cost, 4),
        "mention_rate": mention_rate,
        "avg_rank": avg_rank,
        "platform_count": len(platform_bucket),
        "sentiment_counts": sentiment_counts,
        "platform_stats": platform_stats,
        "source_stats": source_stats,
        "source_stats_all": source_stats_all,
        "source_citation_trend": source_citation_trend,
        "source_citation_trend_by_platform": source_citation_trend_by_platform,
        "daily_trend": daily_trend,
        "daily_labels": day_labels,
        "recent_tasks": recent_tasks,
        "recent_subtasks": recent_subtasks,
        "summary_task_limit": summary_task_limit,
    }


def get_monitor_task(db: Session, task_id: str, current: CurrentSession) -> GeoMonitorTask:
    """读取本地任务详情，并按身份做租户隔离。"""
    stmt = (
        select(GeoMonitorTask)
        .options(joinedload(GeoMonitorTask.subtasks))
        .where(GeoMonitorTask.task_id == task_id, GeoMonitorTask.deleted.is_(False))
    )
    if current.identity.identity_type == "CUSTOMER":
        stmt = stmt.where(GeoMonitorTask.tenant_id == current.identity.tenant_id)
    task = db.scalar(stmt)
    if task is None:
        raise ValueError("任务不存在或无权访问")
    assert_monitor_task_access(db, current, task.tenant_id, task_id=task.task_id)
    return task


def get_monitor_subtask(db: Session, subtask_id: str, current: CurrentSession) -> GeoMonitorSubtask:
    """读取单个子任务详情，并按身份做租户隔离。"""
    from app.core.monitor_purpose import PURPOSE_BRAND_WORD

    stmt = (
        select(GeoMonitorSubtask)
        .join(GeoMonitorTask, GeoMonitorTask.task_id == GeoMonitorSubtask.task_id)
        .options(joinedload(GeoMonitorSubtask.task))
        .where(
            GeoMonitorSubtask.subtask_id == subtask_id,
            GeoMonitorTask.deleted.is_(False),
        )
    )
    if current.identity.identity_type == "CUSTOMER":
        stmt = stmt.where(GeoMonitorTask.tenant_id == current.identity.tenant_id)
    subtask = db.scalar(stmt)
    if subtask is None:
        raise ValueError("子任务不存在或无权访问")
    if subtask.task is not None:
        assert_monitor_task_access(
            db,
            current,
            subtask.task.tenant_id,
            task_id=subtask.task.task_id,
        )
    if current.identity.identity_type == "CUSTOMER":
        task = subtask.task
        if task is None:
            task = get_monitor_task(db, subtask.task_id, current)
        # 品牌分析页实时展示 brand_word；详情不能再套 GEO「只看到昨天」闸门
        if str(getattr(task, "purpose", "") or "") == PURPOSE_BRAND_WORD:
            return subtask
        asset = get_brand_asset(db, task.tenant_id) if task.tenant_id else None
        schedule_ctx = _resolve_subtask_schedule_context(
            task,
            schedule_runs_for_tasks(db, [task.task_id]),
            asset,
            lead_diagnosis_runs_for_tasks(db, [task.task_id]),
        )
        if not customer_subtask_visible(subtask, task=task, schedule_ctx=schedule_ctx):
            raise ValueError("子任务不存在或无权访问")
    return subtask


def sync_monitor_task(db: Session, task_id: str, current: CurrentSession) -> GeoMonitorTask:
    """手动同步远端状态和结果，只有显式调用该接口才请求模力指数。"""
    task = get_monitor_task(db, task_id, current)
    client = MolizhishuClient()
    try:
        status_response = client.get_task_status(task_id)
        status_data = status_response.get("data") or {}
        task.status = status_data.get("status") or task.status
        _apply_remote_task_counts(task, status_data)
        task.remote_created_at = status_data.get("createdAt") or task.remote_created_at
        task.remote_completed_at = status_data.get("completedAt") or task.remote_completed_at
        for subtask in status_data.get("subTaskList") or []:
            _upsert_subtask(db, task_id, subtask)
        if task.status in TERMINAL_STATUSES or task.completed_items > 0:
            result_response = client.get_task_result(task_id)
            result_data = result_response.get("data") or {}
            task.status = result_data.get("status") or task.status
            _apply_remote_task_counts(task, result_data)
            for subtask in result_data.get("subTaskList") or []:
                _upsert_subtask(db, task_id, subtask)
        # 方案 C：缺口本地补算（须在 reconcile 前，便于 awaiting 判断用补算后位次）
        filled = fill_missing_subtask_ranks_for_task(db, task)
        if filled:
            logger.info("fill_missing_subtask_ranks task_id=%s filled=%s", task_id, filled)
        task.last_error = None
        task.subtasks = list(
            db.scalars(select(GeoMonitorSubtask).where(GeoMonitorSubtask.task_id == task_id))
        )
        _reconcile_task_progress(task)
        from app.services.monitor_auto_retry_service import apply_auto_retry_results, launch_auto_retries_for_task
        from app.services.snapshot_backfill_service import notify_failed_subtasks_for_task

        apply_auto_retry_results(db, task)
        # 回写可能改了 origin；当前若是普通任务则继续对本单发起重试
        task.subtasks = list(
            db.scalars(select(GeoMonitorSubtask).where(GeoMonitorSubtask.task_id == task_id))
        )
        launch_auto_retries_for_task(db, task)
        notify_failed_subtasks_for_task(db, task)
    except Exception as exc:
        if not isinstance(exc, _TRANSIENT_SYNC_ERRORS):
            task.last_error = str(exc)
            db.commit()
        raise
    db.commit()
    try:
        from app.services.monitor_stats_service import refresh_stats_for_task

        refresh_stats_for_task(db, task_id)
        db.commit()
    except Exception as exc:
        # 2026-08-10 - daily_stat 死锁后会话 PendingRollback，勿让后续 get_monitor_task 再炸
        logger.warning("refresh_stats_for_task failed task_id=%s error=%s", task_id, exc)
        try:
            db.rollback()
        except Exception:
            pass
    # ponytail: 日统计落库后再清缓存，避免冷读打到旧 daily_stat
    invalidate_monitor_summary_cache(task.tenant_id)
    try:
        from app.services.brand_analysis_service import parse_sentiments_after_brand_word_sync

        parse_sentiments_after_brand_word_sync(db, task)
    except Exception as exc:
        logger.warning("brand_word sentiment parse failed task_id=%s error=%s", task_id, exc)
    return get_monitor_task(db, task_id, current)


def serialize_task(
    task: GeoMonitorTask,
    *,
    schedule_run: GeoMonitorScheduleRun | None = None,
    asset: BrandAsset | None = None,
    keyword_group_rows: list[BrandKeywordGroup] | None = None,
) -> dict[str, Any]:
    """转换任务为前端友好的字典。"""
    _reconcile_task_progress(task)
    prompts = list(task.prompts_json or [])
    payload = {
        "task_id": task.task_id,
        "tenant_id": task.tenant_id,
        "monitor_keywords": task.monitor_keywords,
        "status": task.status,
        "total_items": task.total_items,
        "completed_items": task.completed_items,
        "failed_items": task.failed_items,
        "prompts": prompts,
        "platforms": task.platforms_json,
        "callback_url": task.callback_url,
        "poll_url": task.poll_url,
        "last_error": task.last_error,
        "created_at": task.created_at.isoformat(),
        "updated_at": task.updated_at.isoformat(),
        "prompt_preview": prompts[0] if prompts else None,
    }
    payload.update(resolve_task_schedule_context(task, schedule_run, asset))
    if keyword_group_rows is not None:
        payload["keyword_group"] = _resolve_display_keyword_group(
            task,
            schedule_run,
            keyword_group_rows,
        )
    return payload


def serialize_tasks_for_display(
    db: Session,
    tasks: list[GeoMonitorTask],
) -> list[dict[str, Any]]:
    task_ids = [task.task_id for task in tasks if task.task_id]
    runs_map = schedule_runs_for_tasks(db, task_ids)
    tenant_ids = {task.tenant_id for task in tasks if task.tenant_id}
    assets = {
        item.tenant_id: item
        for item in db.scalars(
            select(BrandAsset).where(
                BrandAsset.tenant_id.in_(tenant_ids),
                BrandAsset.deleted.is_(False),
            )
        )
    } if tenant_ids else {}
    groups_by_tenant = {
        tenant_id: list_keyword_groups(db, tenant_id)
        for tenant_id in tenant_ids
    }
    return [
        serialize_task(
            task,
            schedule_run=runs_map.get(task.task_id),
            asset=assets.get(task.tenant_id),
            keyword_group_rows=groups_by_tenant.get(task.tenant_id, []),
        )
        for task in tasks
    ]


def serialize_subtask(subtask: GeoMonitorSubtask) -> dict[str, Any]:
    """转换子任务为前端友好的字典。"""
    raw = subtask.raw_result_json if isinstance(subtask.raw_result_json, dict) else {}
    pending = raw.get("screenshot_pending")
    shot_ok = raw.get("screenshot_ok")
    return {
        "subtask_id": subtask.subtask_id,
        "task_id": subtask.task_id,
        "platform": subtask.platform,
        "mode": subtask.mode,
        "prompt": subtask.prompt,
        "status": subtask.status,
        "page_screenshot": public_screenshot_url(subtask.page_screenshot),
        "answer_content": subtask.answer_content,
        "reference_list": _filter_citation_sources(subtask.reference_list_json),
        "citation_list": _filter_citation_sources(subtask.citation_list_json),
        "recommended_questions": subtask.recommended_questions_json or [],
        "error_message": subtask.error_message,
        "mention_position": subtask.mention_position,
        "mention_context": subtask.mention_context,
        "sentiment": subtask.sentiment,
        "competitor_rankings": subtask.competitor_rankings_json or [],
        "all_rankings": subtask.all_rankings_json or [],
        "amount": float(subtask.amount) if subtask.amount is not None else None,
        "raw_result": subtask.raw_result_json,
        "updated_at": subtask.updated_at.isoformat() if subtask.updated_at else None,
        # 2026-08-07 - 异步截图未完成时勿显示「暂无快照请填 URL」
        "screenshot_pending": bool(pending) if pending is not None else False,
        "screenshot_ok": shot_ok if isinstance(shot_ok, bool) else None,
    }


def serialize_summary_subtask(subtask: GeoMonitorSubtask) -> dict[str, Any]:
    """汇总页使用的轻量子任务序列化，避免加载回答正文和原始结果大字段。"""
    reference_count = len(_filter_citation_sources(subtask.reference_list_json))
    return {
        "subtask_id": subtask.subtask_id,
        "platform": subtask.platform,
        "mode": subtask.mode,
        "prompt": subtask.prompt,
        "status": subtask.status,
        "page_screenshot": public_screenshot_url(subtask.page_screenshot),
        "reference_count": reference_count,
        "reference_list": [],
        "error_message": subtask.error_message,
        "mention_position": subtask.mention_position,
        "mention_context": subtask.mention_context,
        "sentiment": subtask.sentiment,
        "amount": float(subtask.amount) if subtask.amount is not None else None,
        "updated_at": subtask.updated_at.isoformat() if subtask.updated_at else None,
    }


def _resolve_matrix_tenant_id(
    current: CurrentSession,
    requested_tenant_id: int | None = None,
) -> int | None:
    if current.identity.identity_type == "CUSTOMER":
        return current.identity.tenant_id
    return requested_tenant_id


def _prompt_belongs_to_group(
    prompt: str,
    monitor_keywords: list[str] | str,
    exposure_terms: list[str] | None = None,
) -> bool:
    del exposure_terms
    text = (prompt or "").strip()
    keywords = (
        monitor_keywords
        if isinstance(monitor_keywords, list)
        else [str(monitor_keywords or "").strip()]
    )
    for keyword in keywords:
        token = str(keyword or "").strip()
        if token and token == text:
            return True
    for keyword in keywords:
        token = str(keyword or "").strip()
        if token and token in text:
            return True
    return False


def _group_filter_matches(group: dict[str, Any], filter_text: str) -> bool:
    text = str(filter_text or "").strip()
    if not text:
        return False
    if text == str(group.get("name") or "").strip():
        return True
    return text in keyword_group_monitor_keywords(group)


def _keyword_group_option(group: dict[str, Any]) -> dict[str, Any] | None:
    keywords = keyword_group_monitor_keywords(group)
    if not keywords:
        return None
    return {
        "monitor_keyword": keywords[0],
        "name": str(group.get("name") or "").strip() or keywords[0],
        "monitor_keywords": keywords,
        "exposure_terms": [
            str(term or "").strip()
            for term in (group.get("exposure_terms") or [])
            if str(term or "").strip()
        ],
    }


def _resolve_keyword_group_filter(
    filter_text: str,
    keyword_groups: list[dict[str, Any]],
) -> dict[str, Any] | None:
    text = str(filter_text or "").strip()
    if not text:
        return None
    if text.startswith("id:"):
        target = text[3:].strip()
        return next((group for group in keyword_groups if str(group.get("id")) == target), None)
    if text.startswith("idx:"):
        try:
            target_index = int(text[4:])
        except ValueError:
            return None
        sorted_groups = sorted(keyword_groups, key=lambda item: int(item.get("sort_order") or 0))
        if 0 <= target_index < len(sorted_groups):
            return sorted_groups[target_index]
        return None
    return next((group for group in keyword_groups if _group_filter_matches(group, text)), None)


def _keyword_groups_for_exposure_term(
    exposure_term: str,
    keyword_groups: list[dict[str, Any]],
    *,
    asset: BrandAsset | None = None,
) -> list[dict[str, Any]]:
    """露出词下拉项对应词组；监测 prompt 是行业词，不能靠 prompt 子串匹配。"""
    text = str(exposure_term or "").strip()
    if not text:
        return []
    matched = [
        group for group in keyword_groups
        if group.get("status", True)
        and text in [str(term or "").strip() for term in (group.get("exposure_terms") or [])]
    ]
    if matched:
        return matched
    if asset is not None:
        asset_terms = {
            str(asset.brand_short_name or "").strip(),
            str(asset.brand_name or "").strip(),
            str(asset.company_full_name or "").strip(),
            *[str(item or "").strip() for item in (asset.aliases_json or [])],
        }
        asset_terms.discard("")
        if text in asset_terms:
            return [
                group for group in keyword_groups
                if group.get("status", True) and keyword_group_monitor_keywords(group)
            ]
    return []


def _filter_subtasks_by_keyword_group(
    subtasks: list[GeoMonitorSubtask],
    keyword_group: str,
    keyword_groups: list[dict[str, Any]],
) -> list[GeoMonitorSubtask]:
    selected_group = _resolve_keyword_group_filter(keyword_group, keyword_groups)
    if selected_group is None:
        return []
    return [
        item for item in subtasks
        if _prompt_belongs_to_group(
            item.prompt or "",
            keyword_group_monitor_keywords(selected_group),
            selected_group.get("exposure_terms") or [],
        )
    ]


def _filter_subtasks_by_monitor_keyword(
    subtasks: list[GeoMonitorSubtask],
    monitor_keyword: str,
) -> list[GeoMonitorSubtask]:
    text = str(monitor_keyword or "").strip()
    if not text:
        return subtasks
    lower = text.lower()
    return [
        item for item in subtasks
        if (item.prompt or "").strip() == text or lower in (item.prompt or "").lower()
    ]


def _filter_subtasks_by_exposure_term(
    subtasks: list[GeoMonitorSubtask],
    exposure_term: str,
    keyword_groups: list[dict[str, Any]],
    *,
    asset: BrandAsset | None = None,
) -> list[GeoMonitorSubtask]:
    text = str(exposure_term or "").strip()
    if not text:
        return subtasks
    groups = _keyword_groups_for_exposure_term(text, keyword_groups, asset=asset)
    if groups:
        return [
            item for item in subtasks
            if any(
                _prompt_belongs_to_group(
                    item.prompt or "",
                    keyword_group_monitor_keywords(group),
                    group.get("exposure_terms") or [],
                )
                for group in groups
            )
        ]
    return [item for item in subtasks if text in (item.prompt or "")]


def _filter_subtasks_by_scope(
    subtasks: list[GeoMonitorSubtask],
    *,
    keyword_group: str | None,
    monitor_keyword: str | None,
    exposure_term: str | None,
    keyword_groups: list[dict[str, Any]],
    asset: BrandAsset | None = None,
) -> list[GeoMonitorSubtask]:
    result = subtasks
    group_filter = str(keyword_group or "").strip()
    monitor_filter = str(monitor_keyword or "").strip()
    exposure_filter = str(exposure_term or "").strip()
    if group_filter:
        result = _filter_subtasks_by_keyword_group(result, group_filter, keyword_groups)
    if monitor_filter:
        result = _filter_subtasks_by_monitor_keyword(result, monitor_filter)
    if exposure_filter:
        result = _filter_subtasks_by_exposure_term(
            result,
            exposure_filter,
            keyword_groups,
            asset=asset,
        )
    return result


def _filter_subtasks_by_monitor_group(
    subtasks: list[GeoMonitorSubtask],
    group_filter: str,
    keyword_groups: list[dict[str, Any]],
) -> list[GeoMonitorSubtask]:
    """Filter subtasks by monitor keyword group or a specific exposure term."""
    text = str(group_filter or "").strip()
    if not text:
        return subtasks
    selected_group = next(
        (group for group in keyword_groups if _group_filter_matches(group, text)),
        None,
    )
    if selected_group:
        return [
            item for item in subtasks
            if _prompt_belongs_to_group(
                item.prompt or "",
                keyword_group_monitor_keywords(selected_group),
                selected_group.get("exposure_terms") or [],
            )
        ]
    for group in keyword_groups:
        for term in group.get("exposure_terms") or []:
            if str(term or "").strip() == text:
                return [
                    item for item in subtasks
                    if text in (item.prompt or "")
                ]
    keyword_text = text.lower()
    return [
        item for item in subtasks
        if keyword_text in (item.prompt or "").lower()
    ]


def _resolve_prompt_keyword_group(
    prompt: str,
    groups: list[BrandKeywordGroup],
) -> BrandKeywordGroup | None:
    best: tuple[int, BrandKeywordGroup] | None = None
    for group in groups:
        score = _prompt_group_match_score(prompt, group)
        if score >= 0 and (best is None or score > best[0]):
            best = (score, group)
    return best[1] if best else None


def _prompt_group_name(prompt: str, groups: list[BrandKeywordGroup]) -> str | None:
    group = _resolve_prompt_keyword_group(prompt, groups)
    if group is None:
        return None
    return keyword_group_display_label(group) or keyword_group_primary_keyword(group) or None


def _prompt_monitor_keyword(prompt: str, groups: list[BrandKeywordGroup]) -> str | None:
    group = _resolve_prompt_keyword_group(prompt, groups)
    if group is None:
        return None
    return _matrix_group_monitor_label(group) or None


def _common_keyword_prefix_len(left: str, right: str) -> int:
    count = 0
    for left_char, right_char in zip(left, right):
        if left_char != right_char:
            break
        count += 1
    return count


def _prompt_keyword_match_score(prompt: str, keyword: str) -> int:
    text = (prompt or "").strip()
    token = (keyword or "").strip()
    if not text or not token:
        return -1
    if text == token:
        return 2000 + len(token)
    if token in text:
        return 1500 + len(token)
    if text in token:
        return 1400 + len(text)
    prefix = _common_keyword_prefix_len(text, token)
    # ponytail: 行业问法常只有「推荐/哪家好」差异，前缀 ≥4 字即视为同一监控词
    if prefix >= 4:
        return 500 + prefix
    return -1


def _resolve_prompt_monitor_keyword(prompt: str, groups: list[BrandKeywordGroup]) -> str | None:
    """将监测问题归到词组内具体 monitor keyword（非词组主标签）。"""
    text = (prompt or "").strip()
    if not text:
        return None
    ranked: list[tuple[int, str]] = []
    for group in groups:
        if getattr(group, "deleted", False) or not getattr(group, "status", True):
            continue
        for keyword in keyword_group_monitor_keywords(group):
            score = _prompt_keyword_match_score(text, str(keyword or "").strip())
            if score >= 0:
                ranked.append((score, str(keyword).strip()))
    if ranked:
        return max(ranked, key=lambda item: (item[0], len(item[1])))[1]
    group = _resolve_prompt_keyword_group(prompt, groups)
    if group is None:
        return None
    return _matrix_group_monitor_label(group) or None


def _matrix_group_monitor_label(group: BrandKeywordGroup) -> str:
    """矩阵图 Y 轴标签：优先用词组独立配置的 monitor_keyword，避免共用监测问题文案。"""
    explicit = str(group.monitor_keyword or "").strip()
    if explicit:
        return explicit
    name = keyword_group_name(group)
    if not is_generic_keyword_group_name(name):
        return name
    keywords = keyword_group_monitor_keywords(group)
    return keywords[0] if keywords else name


def _prompt_group_match_score(prompt: str, group: BrandKeywordGroup) -> int:
    text = (prompt or "").strip()
    if not text:
        return -1
    explicit = str(group.monitor_keyword or "").strip()
    if explicit:
        if text == explicit:
            return 2000 + len(explicit)
        if explicit in text:
            return 1500 + len(explicit)
        if text in explicit:
            return 1400 + len(text)
    best = -1
    for keyword in keyword_group_monitor_keywords(group):
        token = str(keyword or "").strip()
        if not token:
            continue
        if text == token:
            return 1200 + len(token)
        if token in text:
            best = max(best, 800 + len(token))
        elif text in token:
            best = max(best, 700 + len(text))
    return best


def _group_row_labels(group: BrandKeywordGroup) -> set[str]:
    labels: set[str] = set()
    for text in (
        _matrix_group_monitor_label(group),
        keyword_group_display_label(group),
        keyword_group_name(group),
        str(group.monitor_keyword or "").strip(),
    ):
        if text:
            labels.add(text)
    return labels


def _prompt_key_for_monitor_keyword(
    group: BrandKeywordGroup,
    keyword: str,
    rows: list[dict[str, Any]],
    prompt_set: dict[str, str | None],
) -> str:
    text = str(keyword or "").strip()
    if not text:
        return ""
    if text in prompt_set:
        return text

    labels = _group_row_labels(group)
    matched_prompts: list[str] = []
    for row in rows:
        row_label = str(row.get("keyword_group") or "").strip()
        if labels and row_label not in labels:
            continue
        cells = row.get("cells") or {}
        if text in cells:
            return text
        for prompt in cells:
            prompt_text = str(prompt or "").strip()
            if not prompt_text:
                continue
            if text == prompt_text or text in prompt_text or prompt_text in text:
                matched_prompts.append(prompt_text)
    if matched_prompts:
        return sorted(
            matched_prompts,
            key=lambda prompt: _prompt_group_match_score(prompt, group),
            reverse=True,
        )[0]

    ranked_candidates: list[tuple[int, str]] = []
    for candidate in prompt_set:
        score = _prompt_group_match_score(candidate, group)
        if score >= 0 and (text == candidate or text in candidate or candidate in text):
            ranked_candidates.append((score, candidate))
    if ranked_candidates:
        return max(ranked_candidates, key=lambda item: (item[0], len(item[1])))[1]
    return ""


def _filter_matrix_columns_for_scope(
    columns: list[dict[str, Any]],
    prompt_set: dict[str, str | None],
    *,
    keyword_group: str | None,
    monitor_keyword: str | None,
    exposure_term: str | None,
) -> list[dict[str, Any]]:
    """筛选后只保留本次 prompt_set 里真有数据的列，避免 6 列共用 1 个 cell。"""
    if not any(str(value or "").strip() for value in (keyword_group, monitor_keyword, exposure_term)):
        return columns
    allowed = set(prompt_set.keys())
    return [col for col in columns if col.get("prompt") in allowed]


def _build_matrix_columns(
    keyword_groups: list[BrandKeywordGroup],
    prompt_set: dict[str, str | None],
    rows: list[dict[str, Any]] | None = None,
    *,
    platform: str | None = None,
    asset: BrandAsset | None = None,
) -> list[dict[str, Any]]:
    """按监测词建列：每个词组的每个 monitor keyword 各占一列。

    platform 有值时只保留词组配置含该平台的列（企业配置未勾的平台不展示空行）。
    """
    from app.core.platform_order import platforms_compatible

    matrix_rows = rows or []
    selected = str(platform or "").strip() or None
    eligible = sorted(
        [
            group for group in keyword_groups
            if group.status
            and not group.deleted
            and (str(group.monitor_keyword or "").strip() or keyword_group_monitor_keywords(group))
        ],
        key=lambda item: int(item.sort_order or 0),
    )

    columns: list[dict[str, Any]] = []
    seen_prompts: set[str] = set()
    for group in eligible:
        group_platforms = keyword_group_platforms(group, asset)
        # 2026-07-28 - 热力按词组平台裁列 - 未配置该平台的词不占行
        if selected and group_platforms:
            if not any(platforms_compatible(selected, code) for code in group_platforms):
                continue
        keywords = keyword_group_monitor_keywords(group)
        if not keywords:
            explicit = str(group.monitor_keyword or "").strip()
            keywords = [explicit] if explicit else []
        for keyword in keywords:
            text = str(keyword or "").strip()
            if not text:
                continue
            prompt_key = _prompt_key_for_monitor_keyword(group, text, matrix_rows, prompt_set)
            if not prompt_key or prompt_key in seen_prompts:
                continue
            seen_prompts.add(prompt_key)
            columns.append({
                "prompt": prompt_key,
                "group_name": keyword_group_display_label(group),
                "monitor_keyword": text,
                "group_id": group.id,
                "platforms": list(group_platforms),
            })

    if columns:
        return columns

    visible_prompts = sorted(
        prompt_set.keys(),
        key=lambda text: (prompt_set[text] or "zzz", text),
    )
    return [
        {
            "prompt": prompt,
            "group_name": prompt_set.get(prompt) or _prompt_group_name(prompt, keyword_groups),
            "monitor_keyword": (
                _matrix_group_monitor_label(matched)
                if (matched := _resolve_prompt_keyword_group(prompt, keyword_groups))
                else None
            ),
            "group_id": (
                matched.id
                if (matched := _resolve_prompt_keyword_group(prompt, keyword_groups))
                else None
            ),
            "platforms": (
                keyword_group_platforms(matched, asset)
                if (matched := _resolve_prompt_keyword_group(prompt, keyword_groups))
                else []
            ),
        }
        for prompt in visible_prompts
    ]


def _keyword_group_from_schedule_key(
    schedule_key: str | None,
    groups: list[BrandKeywordGroup],
) -> BrandKeywordGroup | None:
    text = str(schedule_key or "").strip()
    if "-kw" not in text:
        return None
    suffix = text.rsplit("-kw", 1)[1]
    for group in groups:
        if str(group.id) == suffix or str(group.sort_order) == suffix:
            return group
    return None


def _resolve_display_keyword_group(
    task: GeoMonitorTask,
    schedule_run: GeoMonitorScheduleRun | None,
    keyword_group_rows: list[BrandKeywordGroup] | None,
) -> str | None:
    rows = keyword_group_rows or []
    matched = _keyword_group_from_schedule_key(
        schedule_run.schedule_key if schedule_run else None,
        rows,
    )
    if matched:
        label = keyword_group_display_label(matched)
        if label:
            return label
    prompts = list(task.prompts_json or [])
    if prompts:
        name = _prompt_group_name(str(prompts[0]), rows)
        if name:
            return name
    fallback = str(task.monitor_keywords or "").strip()
    return fallback or None


def _snapshot_minute(value: datetime | None) -> str | None:
    if not value:
        return None
    bucket = value.replace(second=0, microsecond=0)
    return bucket.strftime("%Y-%m-%d %H:%M")


def _matrix_row_key(
    bucket_key: str,
    platform: str,
    *,
    all_platforms: bool,
    keyword_group: str | None,
) -> str:
    parts = [bucket_key, keyword_group or "", platform if all_platforms else ""]
    return "|".join(part for part in parts if part)


def _ranking_matrix_row_limit(
    *,
    requested_limit: int,
    range_start_day: date,
    range_end_day: date,
    all_platforms: bool,
    purchased_platforms: list[str],
    keyword_group_count: int,
) -> int:
    """全平台×多日时默认 120 行会砍掉月初；按区间抬高保留下限。"""
    base = max(1, int(requested_limit or 0))
    span_days = max(1, (range_end_day - range_start_day).days + 1)
    platform_factor = max(1, len(purchased_platforms) if all_platforms else 1)
    group_factor = max(1, int(keyword_group_count or 1))
    needed = span_days * platform_factor * group_factor
    # ponytail: 年×多平台×多词组可上千行；8000 够月/季，超了再谈分页
    return min(max(base, needed), 8000)


def matrix_platform_visible(platform: str | None, purchased_platforms: list[str]) -> bool:
    """排名矩阵仅展示企业当前配置的监测平台；无配置时保留全部（兼容旧数据）。

    购买 deepseek 或 deepseek_mobile 任一端时，两端子任务都可见，避免漏数。
    """
    from app.core.platform_order import expand_platform_codes

    purchased = {code for code in purchased_platforms if code}
    if not purchased:
        return True
    text = str(platform or "").strip()
    if not text:
        return False
    return text in expand_platform_codes(purchased)


def _matrix_day_key(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.date().isoformat()


def _schedule_window_date(schedule_ctx: dict[str, Any] | None) -> date | None:
    window_key = str((schedule_ctx or {}).get("schedule_window_key") or "").strip()
    if len(window_key) >= 8 and window_key[:8].isdigit():
        try:
            return datetime.strptime(window_key[:8], "%Y%m%d").date()
        except ValueError:
            pass
    schedule_label = str((schedule_ctx or {}).get("schedule_label") or "").strip()
    if len(schedule_label) >= 10:
        try:
            return datetime.strptime(schedule_label[:10], "%Y-%m-%d").date()
        except ValueError:
            pass
    return None


def _subtask_detect_datetime(
    subtask: GeoMonitorSubtask,
    task: GeoMonitorTask | None,
    schedule_ctx: dict[str, Any] | None,
) -> datetime | None:
    """检测日优先取调度批次，避免运营补录更新 updated_at 后客户侧看不到历史格子。"""
    detect_date = _schedule_window_date(schedule_ctx)
    if detect_date is not None:
        return datetime.combine(detect_date, time.min)
    if task and task.created_at:
        return task.created_at
    return subtask.updated_at


def _resolve_subtask_schedule_context(
    task: GeoMonitorTask,
    schedule_runs_map: dict[str, GeoMonitorScheduleRun],
    asset: BrandAsset | None,
    lead_runs_map: dict[str, LeadDiagnosisRun],
) -> dict[str, Any]:
    lead_run = None
    if not getattr(task, "tenant_id", None):
        lead_run = lead_runs_map.get(task.task_id)
    return resolve_task_schedule_context(
        task,
        schedule_runs_map.get(task.task_id),
        asset,
        lead_run,
    )


def _matrix_day_label(day_key: str, schedule_round_count: int = 0) -> str:
    """Format matrix row date; schedule_round_count = max runs averaged in any cell (not prompt count)."""
    text = str(day_key or "").strip()
    if not text:
        return "-"
    try:
        label = datetime.fromisoformat(text).strftime("%Y-%m-%d")
    except ValueError:
        label = text
    if schedule_round_count > 1:
        return f"{label}（{schedule_round_count}次均值）"
    return label


def _dedupe_matrix_cell_samples(
    samples: list[dict[str, Any]],
    *,
    max_samples: int | None = None,
) -> list[dict[str, Any]]:
    """Keep one sample per schedule window (latest), optionally capped by daily frequency."""
    by_window: dict[str, dict[str, Any]] = {}
    for sample in samples:
        window_key = str(
            sample.get("schedule_window_key")
            or sample.get("task_id")
            or sample.get("subtask_id")
            or ""
        ).strip()
        if not window_key:
            continue
        existing = by_window.get(window_key)
        sample_at = sample.get("_updated_at") or datetime.min
        existing_at = existing.get("_updated_at") if existing else datetime.min
        if existing is None or sample_at >= existing_at:
            by_window[window_key] = sample
    ordered = sorted(
        by_window.values(),
        key=lambda item: item.get("_updated_at") or datetime.min,
        reverse=True,
    )
    scheduled = [item for item in ordered if item.get("schedule_source") != "lead_diagnosis"]
    lead_samples = [item for item in ordered if item.get("schedule_source") == "lead_diagnosis"]
    if max_samples and max_samples > 0 and len(scheduled) > max_samples:
        scheduled = scheduled[:max_samples]
    return sorted(
        scheduled + lead_samples,
        key=lambda item: item.get("_updated_at") or datetime.min,
        reverse=True,
    )


def _matrix_row_schedule_round_count(cells: dict[str, dict[str, Any]]) -> int:
    """Max schedule rounds represented in a row (per prompt-platform daily average)."""
    counts = [
        int(cell.get("rank_sample_count") or cell.get("sample_count") or 0)
        for cell in cells.values()
        if cell
    ]
    return max(counts) if counts else 0


def _average_mention_position(values: list[int | float]) -> float | None:
    if not values:
        return None
    total = sum(float(value) for value in values)
    return round(total / len(values), 1)


def _matrix_cell_snapshot(sample: dict[str, Any]) -> dict[str, Any]:
    return {
        "subtask_id": sample.get("subtask_id"),
        "task_id": sample.get("task_id"),
        "mention_position": sample.get("mention_position"),
        "raw_mention_position": sample.get("raw_mention_position"),
        "brand_mentioned": sample.get("brand_mentioned"),
        "monitor_keyword": sample.get("monitor_keyword"),
        "prompt_intent": sample.get("prompt_intent"),
        "schedule_window_key": sample.get("schedule_window_key"),
        "schedule_label": sample.get("schedule_label"),
        "schedule_source": sample.get("schedule_source"),
        "updated_at": sample.get("updated_at"),
        "status": sample.get("status"),
        "page_screenshot": sample.get("page_screenshot"),
        "sentiment": sample.get("sentiment"),
        "rank_source": sample.get("rank_source"),
        "rank_confidence": sample.get("rank_confidence"),
        "rank_category": sample.get("rank_category"),
        "rank_basis": sample.get("rank_basis"),
    }


def _finalize_matrix_cell(samples: list[dict[str, Any]]) -> dict[str, Any]:
    ranks = [
        float(sample["mention_position"])
        for sample in samples
        if sample.get("mention_position") is not None
    ]
    latest = max(
        samples,
        key=lambda sample: sample.get("_updated_at") or datetime.min,
    )
    avg_rank = _average_mention_position(ranks)
    snapshots = sorted(
        [_matrix_cell_snapshot(sample) for sample in samples],
        key=lambda item: schedule_window_sort_key(item.get("schedule_window_key")),
    )
    return {
        "subtask_id": latest["subtask_id"],
        "mention_position": avg_rank,
        "raw_mention_position": latest.get("raw_mention_position"),
        "brand_mentioned": any(sample.get("brand_mentioned") for sample in samples),
        "monitor_keyword": latest.get("monitor_keyword"),
        "prompt_intent": latest.get("prompt_intent"),
        "status": latest.get("status"),
        "page_screenshot": latest.get("page_screenshot"),
        "sentiment": latest.get("sentiment"),
        "updated_at": latest.get("updated_at"),
        "sample_count": len(samples),
        "rank_sample_count": len(ranks),
        "rank_source": latest.get("rank_source"),
        "rank_confidence": latest.get("rank_confidence"),
        "rank_category": latest.get("rank_category"),
        "rank_basis": latest.get("rank_basis"),
        "snapshots": snapshots,
    }


def _strip_html_for_match(text: str | None) -> str:
    if not text:
        return ""
    cleaned = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", cleaned).strip()


def _brand_match_terms(asset: BrandAsset | None, keyword_groups: list[dict[str, Any]] | None = None) -> list[str]:
    """Collect brand/company terms for legacy exposure/sentiment views."""
    if asset is None:
        return []
    anchors = [
        str(asset.brand_name or "").strip(),
        str(asset.brand_short_name or "").strip(),
        str(asset.company_full_name or "").strip(),
    ]
    terms: list[str] = []
    for item in anchors:
        if item and item not in terms:
            terms.append(item)
    for value in asset.aliases_json or []:
        text = str(value or "").strip()
        if text and not _is_industry_monitor_keyword(text, asset) and text not in terms:
            terms.append(text)
    groups = keyword_groups or []
    if not groups:
        groups = [{"monitor_keyword": asset.brand_name, "exposure_terms": asset.monitor_keywords_json or [], "status": True}]
    for term in brand_exposure_terms(asset, [group for group in groups if group.get("status", True)]):
        if term not in terms:
            terms.append(term)
    return [term for term in terms if not _is_industry_monitor_keyword(term, asset)]


def _ranking_match_terms(asset: BrandAsset | None, keyword_groups: list[dict[str, Any]] | None = None) -> list[str]:
    """露出词：用于在推荐排名列表中匹配品牌位置。"""
    if asset is None:
        return []
    groups = keyword_groups or []
    active_groups = [group for group in groups if group.get("status", True)]
    terms = brand_exposure_terms(asset, active_groups)
    if terms:
        return terms
    return [
        str(value or "").strip()
        for value in (asset.aliases_json or [])
        if str(value or "").strip()
    ]


def _brand_term_match_fragments(term: str) -> list[str]:
    """Extract matchable fragments from long company/brand terms."""
    text = str(term or "").strip()
    if not text:
        return []
    fragments: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        token = value.strip()
        if len(token) >= 2 and token not in seen:
            seen.add(token)
            fragments.append(token)

    add(text)
    stripped = re.sub(
        r"(?:控股)?(?:集团)?(?:股份)?(?:有限)?(?:科技)?公司|集团有限公司|股份有限公司|科技有限公司|有限公司",
        "",
        text,
    ).strip()
    if stripped:
        add(stripped)
        if len(stripped) > 4:
            add(stripped[-4:])
            add(stripped[-3:])
            add(stripped[-2:])
        for prefix in (
            "北京", "上海", "广州", "深圳", "杭州", "成都", "南京", "武汉", "西安", "苏州",
        ):
            if stripped.startswith(prefix) and len(stripped) > len(prefix) + 1:
                add(stripped[len(prefix):])
    for match in re.findall(r"[\u4e00-\u9fff]{2,}", text):
        add(match)
    return fragments


def _brand_appears_in_text(text: str | None, brand_terms: list[str]) -> bool:
    # 2026-07-27 - 短行「北京」反向命中「北京艾迪亚」- 只认 term/核心片段 ⊆ 正文
    normalized = (text or "").lower()
    if not normalized:
        return False
    for term in brand_terms:
        text_value = term.strip().lower()
        if text_value and text_value in normalized:
            return True
        for fragment in _brand_term_match_fragments(term):
            token = fragment.lower()
            if _significant_brand_fragment(token) and token in normalized:
                return True
    return False


_GENERIC_BRAND_FRAGMENTS = frozenset({
    "集团", "控股", "有限", "公司", "中国", "广告", "传媒", "媒体", "地铁", "自有", "运营商",
})


def _significant_brand_fragment(token: str) -> bool:
    text = str(token or "").strip()
    return len(text) >= 3 and text not in _GENERIC_BRAND_FRAGMENTS


def _subtask_brand_text(subtask: GeoMonitorSubtask) -> str:
    answer_text = _strip_html_for_match(subtask.answer_content)
    mention_text = _strip_html_for_match(subtask.mention_context)
    return " ".join(part for part in (answer_text, mention_text) if part).strip()


def _plaintext_field(field: str | None) -> str:
    """Keep line breaks for list/category rank parsing."""
    if not field:
        return ""
    # 2026-07-30 - 表内 <br> 先变空格再剥其它标签，避免 | 行被拆断导致品牌表只剩首行
    cleaned = re.sub(r"<br\s*/?>", " ", str(field), flags=re.I)
    cleaned = re.sub(r"<[^>]+>", "\n", cleaned)
    cleaned = re.sub(r"\r", "\n", cleaned)
    return cleaned.strip()


def _answer_body_for_rank(subtask: GeoMonitorSubtask) -> str:
    """排名用正文：仅 answer_content。

    2026-08-11 - 仅 mention_context 有品牌却写出位次 - 排名判定/解析不拼 context
    """
    return _plaintext_field(getattr(subtask, "answer_content", None))


def _answer_loaded_for_rank_gate(subtask: GeoMonitorSubtask) -> bool:
    """读路径：answer_content 已加载才做「正文必须含品牌」门禁；未加载则跳过以免 N+1。

    2026-08-14 - 禁止 hasattr(instance, 'answer_content')：会触发 SQLAlchemy deferred 懒加载，
    矩阵轻量误开门禁，折叠「—」与详情 manual 锁「1」分叉并写回 snapshot 改 KPI。
    """
    try:
        from sqlalchemy import inspect as sa_inspect

        insp = sa_inspect(subtask)
    except Exception:
        # 单测 SimpleNamespace 等非 ORM：仅实例 __dict__ 已带正文才开门禁
        return "answer_content" in getattr(subtask, "__dict__", {})
    return "answer_content" not in insp.unloaded


def _configured_exposure_term_in_text(text: str | None, brand_terms: list[str]) -> bool:
    """正文是否出现配置露出词整段（不走公司名自动切片短片段）。

    2026-08-11 - 排名匹配须正文对得上露出词 - 门禁只用配置词，避免切片假阳性
    """
    normalized = (text or "").lower()
    if not normalized:
        return False
    for term in brand_terms:
        token = str(term or "").strip().lower()
        if len(token) >= 2 and token in normalized:
            return True
    return False


def _line_is_negative_rank_context(line: str) -> bool:
    """假货/贴牌等负面点名行：可计提及，不计推荐位次。"""
    plain = re.sub(r"\*\*", "", str(line or ""))
    if not plain.strip():
        return False
    return any(
        h in plain
        for h in ("假货", "贴牌", "山寨", "重灾", "假一赔", "冒牌", "盗版")
    )


def _answer_excluding_negative_rank_context(text: str) -> str:
    """排名用正文：去掉负面语境行（避坑指南里正向推荐仍保留）。"""
    return "\n".join(
        ln for ln in str(text or "").splitlines() if not _line_is_negative_rank_context(ln)
    )


def _brand_in_answer_for_rank(subtask: GeoMonitorSubtask, brand_terms: list[str]) -> bool:
    # 2026-08-11 - 有绝对对得上的露出词才算匹配 - 排名门禁改配置词整段命中
    return _configured_exposure_term_in_text(_answer_body_for_rank(subtask), brand_terms)


def _subtask_answer_plaintext(subtask: GeoMonitorSubtask) -> str:
    """回答+提及上下文（情感等）；排名位次请用 _answer_body_for_rank。"""
    parts = [
        _plaintext_field(subtask.answer_content),
        _plaintext_field(subtask.mention_context),
    ]
    return "\n".join(part for part in parts if part).strip()


def _name_matches_brand(name: str, brand_terms: list[str]) -> bool:
    """榜单项是否命中品牌：只允许品牌词/核心片段 ⊆ 条目名。

    2026-07-27 - 「北京」「北」命中别名「北京艾迪亚」假阳性 - 去掉 name⊆term 反向包含
    """
    normalized = name.strip().lower()
    if not normalized:
        return False
    for term in brand_terms:
        text = term.strip().lower()
        if not text:
            continue
        if text in normalized:
            return True
        for fragment in _brand_term_match_fragments(term):
            token = fragment.lower()
            if _significant_brand_fragment(token) and token in normalized:
                return True
    return False


def _collect_ranking_entries(subtask: GeoMonitorSubtask) -> list[dict[str, Any]]:
    """正文解析优先排在前；JSON 殿后作兜底（find_* 取首次命中＝优先正文名次）。"""
    # 2026-08-11 - 排名解析勿拼 mention_context，避免仅 context 有品牌时虚抬榜
    text = _answer_body_for_rank(subtask)
    return [
        *parse_answer_rankings(text),
        *normalize_structured_rankings(subtask.all_rankings_json or []),
    ]


def _ranking_scope_text(monitor_keywords: str | None, prompt: str | None) -> str:
    return " ".join(
        part.strip()
        for part in (str(monitor_keywords or "").strip(), str(prompt or "").strip())
        if part and str(part).strip()
    )


def _find_brand_in_rankings(
    subtask: GeoMonitorSubtask,
    brand_terms: list[str],
    asset: BrandAsset | None,
    *,
    monitor_keywords: str | None = None,
) -> tuple[int | float | None, bool, str | None]:
    """Match exposure terms in structured or parsed answer rankings (best / frontmost)."""

    def match_name(name: str) -> bool:
        return _name_matches_brand(name, brand_terms)

    def skip_name(name: str) -> bool:
        # 只跳过纯行业/场景词（如「电梯广告」），勿把「艾迪亚传媒」「分众传媒」当行业词丢掉
        text = str(name or "").strip()
        if not text or asset is None:
            return False
        if any(token in text for token in ("公司", "集团", "控股", "股份", "有限")):
            return False
        if any(brand in text for brand in brand_terms if brand and len(brand) >= 2):
            return False
        # 「XX传媒」多为公司名：含 2+ 汉字专名时不跳过
        if text.endswith(("传媒", "广告", "媒体")) and len(text) >= 4:
            return False
        return _is_industry_monitor_keyword(text, asset)

    answer = _answer_body_for_rank(subtask)
    scope = _ranking_scope_text(monitor_keywords, subtask.prompt)
    stored = normalize_structured_rankings(subtask.all_rankings_json or [])
    # 2026-08-12 - parse 与 all_rankings 叠成双份同名，去标题重排把第6抬成第11 - 有入库榜只用入库榜
    parsed = parse_answer_rankings(answer)
    merged = stored if stored else parsed
    if not merged:
        return None, False, None
    rank, matched, entry = find_best_brand_hit_scoped(merged, match_name, scope, skip_name=skip_name)
    # 2026-08-12 - 入库脏标题榜无品牌时回退正文表解析（系统名称列）
    if entry is None and stored and parsed and parsed is not merged:
        rank, matched, entry = find_best_brand_hit_scoped(
            parsed, match_name, scope, skip_name=skip_name
        )
        if entry is not None:
            merged = parsed
    if entry is None:
        return rank, matched, None
    category = str(entry.get("category") or "").strip() or None
    # 2026-08-12 - 合并榜同样去掉小节标题虚占位
    local = _structured_rank_excluding_headers(merged, entry, brand_terms)
    if local is not None:
        return local, True, category
    try:
        return float(entry["rank"]), True, category
    except (TypeError, ValueError):
        return None, True, category



def _is_brand_like_appearance_token(name: str, brand_terms: list[str] | None = None) -> bool:
    """出场序候选须像品牌专名，排除色号/材质/卖点文案加粗。

    2026-08-11 - 中古风答把 H1379/肤感/黑胡桃也计入出场 → 大王椰虚抬到33
    2026-08-11 - 实木板答把「木种/北美品牌/杉木芯」计入 → 大王椰虚抬到17
    """
    text = str(name or "").strip()
    if not text:
        return False
    # 配置露出词：仅整词/整词+板材放行，避免「大王椰生态板打柜体」靠子串混进出场池
    if brand_terms:
        norm = text.strip()
        for term in brand_terms:
            token = str(term or "").strip()
            if token and (norm == token or norm == f"{token}板材"):
                return True
    # 2026-08-12 - 顿号旁「上海/广州」地名、含「品牌」的类别词勿进池
    if text in {
        "上海", "北京", "广州", "深圳", "杭州", "成都", "南京", "武汉", "西安", "重庆",
        "天津", "苏州", "宁波", "青岛", "长沙", "郑州", "东莞", "佛山", "合肥", "沈阳",
    }:
        return False
    if "品牌" in text:
        return False
    # 2026-08-12 - 「**方案A（稳妥通用）**」加粗进池 → 语文下万唯被抬成类内第2
    if re.fullmatch(r"方案[A-Za-z0-9甲乙丙丁一二三四五六七八九十]+", text):
        return False
    # 去掉「芬兰的UPM」国别前缀再判
    text = re.sub(
        r"^(?:丹麦|芬兰|瑞典|意大利|德国|日本|美国|北美|国产|中国)的",
        "",
        text,
    ).strip()
    if not text:
        return False
    if any(
        ch in text
        for ch in (
            "/", "\\", "｜", "（", "）", "(", ")", "，", ",", "。", "；", ";", "#", "-",
            "、", "“", "”", "「", "」", "『", "』", "+", "%",
        )
    ):
        return False
    if " " in text or "\t" in text:
        return False
    if text.startswith(("#", "-", "·")):
        return False
    if "的" in text:
        return False
    if re.search(r"\d", text):
        return False
    if text.endswith(("品牌", "级", "芯", "策略", "截面", "核心", "名字", "主流", "顶配", "谈", "费", "好", "贵", "强", "足", "旺", "有", "味", "题", "练", "量", "龄", "素", "剂", "腥", "剧", "屏", "路", "区", "桥", "类", "卷", "解", "译", "词", "款", "分")):
        return False
    category_tokens = frozenset({
        "木种", "等级", "柜体", "柜门", "儿童房", "避坑", "主流", "顶配", "性价比",
        "高端", "中高端", "国产一线", "北美品牌", "欧洲品牌", "中高端主流", "高端顶配",
        "高性价比", "最大", "建材",
    })
    if text in category_tokens:
        return False
    if "主流" in text or "顶配" in text:
        return False
    prose_hints = (
        "质感", "环保", "防潮", "细腻", "复古", "木纹", "饱和", "肤感", "对纹",
        "进口", "一线", "性价比", "原木", "稳定", "高级", "国产", "国民", "潮湿",
        "重要", "推荐", "追求", "预算", "上限", "极致", "选择", "策略", "侧面",
        "横截面", "给你", "直接", "适合", "建议", "价格", "亲民", "偏高", "假货",
        "门店", "业主", "交界", "产业", "库存", "评价", "操作", "准确", "最新",
        "理解", "寻找", "获取", "加工", "额外", "很贵", "必弯", "精确", "握钉",
        "不易", "开裂", "花色", "平整", "轻奢", "现代", "耐磨", "耐刮", "免漆",
        "溢价", "零裁", "零售", "适中", "靠近", "现货", "户型", "用途", "型号",
        "充足", "人气", "授权", "定金", "样板", "对比", "服务", "态度", "踩坑",
        "周边", "堆满", "灵活", "核对", "批次", "有效", "常用", "变形", "普及",
        "成熟", "适配", "翻新", "保养", "繁琐", "干净", "清爽", "简约", "百搭",
        "温润", "色泽", "爆款", "老气", "奶油", "中古", "日式", "中式", "极简",
        "异形", "圆弧", "护墙", "一体化", "基材", "溢价", "北部", "交界",
        "柜体", "柜门", "衣柜", "橱柜", "厨卫", "开放", "无拉", "设计师", "主推",
        "生态", "免漆", "附带", "按需", "挑选", "柔和", "棕调", "发红", "暗沉",
        # 2026-08-12 - A+B：DHA/教辅/短剧/广告卖点句不得进出场池（润科虚高到14）
        # 勿用「宝宝」子串：会误杀「兔宝宝」
        "嫌", "腥味", "原味", "月龄", "香精", "色素", "防腐", "胶囊",
        "过敏", "开封", "接受度", "配方", "基础题", "题量", "预习", "规划",
        "竖屏", "漫剧", "配音", "剪辑", "品效", "刊例", "旅客", "激励",
        "裁切", "开料", "合适", "哪些", "目标", "独家", "经营权", "整合",
        "嫌腥", "部分宝宝",
        # 2026-08-12 - C1：教辅品类/卖点不得进出场（万唯虚高到28）
        "讲解", "练习", "试卷", "知识点", "例题", "易错", "拔高", "中考",
        "专项", "听力", "翻译", "文言文", "同步", "课时", "单元", "分层",
        "查漏", "错题", "题型", "统考", "预习", "复习", "微课", "导图",
        "考点", "背诵", "压轴", "竞赛", "校内", "课本", "生字", "短语",
        "语法", "框架", "冲刺", "夯实", "细致", "拆解", "标注", "漏洞",
        "轻量", "拓展", "扎实", "对接", "整理", "模型", "贴合", "通用",
        "新颖", "贴近", "周测", "期末", "实词", "虚词", "满分",
        # 2026-08-12 - 印章表行「物电同源/定制报价」加粗当品牌 → 动码行内虚第2
        "物电同源", "定制报价", "强防伪", "防伪溯源", "粗略价格", "信创要求",
        "远程授权", "文本比对", "风险预警", "智能审批",
    )
    if any(h in text for h in prose_hints):
        return False
    if text in {"宝宝"} or (text.endswith("宝宝") and text != "兔宝宝"):
        return False
    if text.startswith(("从", "到", "让", "把", "被", "用", "可", "还", "并", "且", "如果", "以及", "家里", "选", "做", "谁", "就", "这是", "靠近")):
        return False
    material_hints = (
        "多层板", "颗粒板", "欧松", "生态板", "实木", "黑胡桃", "白蜡", "水曲柳",
        "榆木", "橡木", "柚木", "胡桃", "板材", "杉木", "松木", "橡胶木", "北极松",
        "免漆板", "柜体板",
    )
    if any(h in text for h in material_hints):
        return False
    # 2026-08-11 - 门店题把地名/卖场/动作加粗计入出场 → 驻马店列表第4虚抬到12
    place_hints = (
        "大道", "西段", "东段", "南段", "北段", "商圈", "美凯龙", "居然之家",
        "家居广场", "旗舰店", "直营店", "专卖店", "总店", "仓库店", "集群",
        "建材城", "装饰城", "建材中心", "交易中心", "商业城", "产业园", "环渤海",
        "环路", "机场",
    )
    if any(h in text for h in place_hints):
        return False
    if re.search(r"[区市县镇乡路]$", text) and len(text) <= 6:
        return False
    if any(h in text for h in ("距离", "配送", "方便", "不用", "跑")):
        return False
    action_hints = (
        "确认", "查防伪", "防伪", "问价", "打听", "口碑", "备选", "实物", "小样",
        "仓库", "一张", "一整套", "开工", "导航", "搜索",
    )
    if any(h in text for h in action_hints):
        return False
    # 2026-08-11 - 方案A：小节标题/卖点加粗（全包价、避坑指南、工厂直营）不得进出场池
    junk_hints = (
        "重点", "指南", "全包", "自建", "大宗", "集散", "直营", "批发", "工厂",
        "什么", "怎么", "参考", "陷阱", "概念", "编码", "规格", "工艺", "PET",
        "门板", "辅材", "封边", "拿货", "出租", "假一赔", "关于价格", "左右",
        "本地大牌", "贴牌", "喷码", "付款", "砍价", "单价", "通货", "高端",
        "生活馆", "体验店", "澳松", "高能", "工长", "最爱",
        # 2026-08-11 - 档内卖点加粗（大豆胶/难燃板/顺芯板）把类内第4抬到7
        "大豆", "无醛胶", "难燃", "顺芯", "握钉", "楠香", "触感", "纹理", "LSB",
    )
    if any(h in text for h in junk_hints):
        return False
    if text in {"淘宝", "京东", "天猫", "拼多多", "红星美凯龙", "最大", "建材", "操作"}:
        return False
    # 2026-08-12 - A+B：非配置词须像强专名（纯中文2-6 / 拉丁品牌），否则不进池
    if not _is_strong_appearance_proper_name(text):
        return False
    # 过长不像点名品牌（中文品牌名通常很短）
    if len(text) > 10:
        return False
    return True


def _is_strong_appearance_proper_name(text: str) -> bool:
    """出场池非配置词：只收短中文专名或拉丁品牌词。"""
    value = str(text or "").strip()
    if not value:
        return False
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9.\-]{1,19}", value):
        return True
    if re.fullmatch(r"[\u4e00-\u9fff]{2,6}", value):
        return True
    # 中英夹杂品牌：有戏AI / 神经猫 等仍偏描述时交给上游黑名单
    if re.fullmatch(r"[\u4e00-\u9fffA-Za-z]{2,8}", value) and not re.search(r"\s", value):
        return True
    return False


_ENUM_BOLD_GAP_RE = re.compile(r"^[\s\"'“”「」]*[、，,/和与或以及]+[\s\"'“”「」]*$")
_QUOTE_BRAND_RE = re.compile(r"[「『\"“]([^「『\"“」』\"”]{1,20})[」』\"”]")
_PAREN_ENUM_RE = re.compile(r"[（(]([^）)]{2,120})[）)]")


def _appearance_enum_source_texts(chunk: str) -> list[str]:
    """加粗块内枚举源：优先括号内顿号列表，避免「追求…（兔宝宝、大王椰）」整段切开失败。

    2026-08-12 - A：括号内顿号抽不出大王椰 → mentioned 却 rank=None
    """
    text = str(chunk or "").strip()
    if not text:
        return []
    sources: list[str] = []
    for match in _PAREN_ENUM_RE.finditer(text):
        inner = match.group(1).strip()
        if re.search(r"[、，,]", inner):
            sources.append(inner)
    if sources:
        return sources
    if re.search(r"[、，,]", text):
        return [text]
    return []


def _quoted_brand_parts(line: str) -> list[str]:
    """引号包裹的并列品牌：「大王椰」、「千年舟」 / “兔宝宝”、“大王椰”。"""
    parts = [m.group(1).strip() for m in _QUOTE_BRAND_RE.finditer(str(line or ""))]
    return [p for p in parts if p]


def _normalize_appearance_enum_part(
    raw_name: str,
    brand_terms: list[str] | None = None,
) -> str:
    """顿号项清洗：去引号/括号，并收「大王椰的华东旗舰店」「大王椰板材专卖店」为露出词。"""
    from app.services.ranking_parser import _clean_item_name

    name = _clean_item_name(raw_name)
    if not name:
        return ""
    # 2026-08-12 - A：切开后残留「大王椰）」/「“千年舟」
    name = re.sub(r"^[（(「『\"“]+|[）)」』\"”]+$", "", name).strip()
    # 书名号《万唯初中…》→ 内文再匹配
    book = re.fullmatch(r"《([^》]{1,40})》", name)
    if book:
        name = book.group(1).strip()
    # 2026-08-12 - 「预算有限时 → 找天赐」顿号左格：去掉箭头前散文再剥「找」
    if re.search(r"[→➡]", name):
        name = re.split(r"[→➡]", name)[-1].strip()
    name = re.sub(r"^[\-–—·•▪\d\.、．\s→➡]+", "", name).strip()
    # 2026-08-12 - 「找天赐」「可选择艾迪亚」选型句前缀
    name = re.sub(r"^(?:可以关注|可选择|可选|选择|找)", "", name).strip()
    name = re.sub(r"^[\-–—·•▪\d\.、．\s→➡]+", "", name).strip()
    if "：" in name or ":" in name:
        name = re.split(r"[：:]", name)[-1].strip()
        name = _clean_item_name(name)
        name = re.sub(r"^[（(「『\"“]+|[）)」』\"”]+$", "", name).strip()
    # 2026-08-12 - **艾迪亚/亦智** 取含露出词的一侧
    if brand_terms and re.search(r"[/／]", name):
        for part in re.split(r"[/／]", name):
            part = part.strip()
            if part and _configured_exposure_term_in_text(part, brand_terms):
                name = part
                break
        else:
            left = re.split(r"[/／]", name, 1)[0].strip()
            if 2 <= len(left) <= 10:
                name = left
    if "的" in name:
        left = name.split("的", 1)[0].strip()
        if 2 <= len(left) <= 12:
            name = left
    # 大王椰等全国连锁… / 艾迪亚这类代理 → 截断
    name = re.sub(r"等.*$", "", name).strip()
    name = re.sub(r"(?:这类|这种|那种).*$", "", name).strip()
    # 兔宝宝红旗总店 / 大王椰板材专卖店 → 去掉地名/门店后缀
    name = re.sub(
        r"(?:板材)?(?:红旗|华东|铁西|于洪|望花|九路)?(?:专卖店|总店|直营店|旗舰店|授权店|体验店|门店)$",
        "",
        name,
    ).strip()
    # 露出词+残余后缀再坍缩（双保险）
    if brand_terms and name:
        for term in sorted(
            (str(t or "").strip() for t in brand_terms),
            key=len,
            reverse=True,
        ):
            if len(term) < 2 or term not in name:
                continue
            idx = name.find(term)
            before = name[:idx]
            after = name[idx + len(term) :]
            before_ok = (not before) or before.endswith(
                ("了", "如", "是", "和", "与", "或", "、", "，", ",", "：", ":", "有", "到", "（", "(", "《")
            )
            after_ok = (not after) or after in {"）", ")", "」", "』", "”", '"', "'", "》"} or any(
                after.startswith(s) or s in after
                for s in (
                    "板材", "专卖", "总店", "直营", "旗舰", "（", "(", "店", "控股",
                    # 2026-08-12 - C1：万唯大小卷 / 万唯同步听力 / 万唯《文言文
                    "大小卷", "同步", "听力", "初中", "中考", "系列", "教辅",
                )
            )
            if before_ok and after_ok:
                return term
            # 2026-08-12 - C1：仅坍缩已知产品后缀，避免「万唯新初一分班考」整句变第1
            if idx == 0 and after and len(after) <= 12:
                if any(
                    after.startswith(s)
                    for s in (
                        "大小卷", "同步听力", "同步", "听力", "初中", "中考",
                        "系列", "教辅", "板材", "控股", "集团",
                    )
                ):
                    return term
    return name


def _collect_brand_appearance_tokens(text: str, brand_terms: list[str] | None = None) -> list[str]:
    """方案A：优先顿号/并列品牌枚举出场；孤立加粗专名作兜底。

    2026-08-11 - 只扫加粗会把卖点当品牌、又漏未加粗列表（合肥/莆田虚高、设计师漏排）
    2026-08-12 - A：括号内顿号 + 引号并列；配置露出词顿号格即使单格也入池
    """
    from app.services.ranking_parser import _looks_like_company_list_name

    if not text:
        return []

    skip_labels = frozenset({
        "怎么去", "特点", "推荐理由", "定位", "推荐", "导航", "注意", "提醒", "优势",
        "地址", "电话", "主打", "适合", "避坑", "总结", "建议", "理由", "特色",
        "价格", "服务", "环境", "规模", "口碑", "高端家用", "性价比", "工装",
    })
    activity_hints = (
        "买", "装", "采购", "装修", "工程", "包工", "预算", "付全款", "木工",
        "保命", "潜规则", "问清楚", "送货", "上楼", "大批量", "几张",
    )
    tokens: list[str] = []
    seen: set[str] = set()

    def add(raw_name: str, *, from_enum: bool) -> bool:
        name = _normalize_appearance_enum_part(raw_name, brand_terms)
        if not name or name in seen:
            return False
        if name in skip_labels:
            return False
        if any(x in name for x in ("市场", "商城", "卖场", "地标", "区域", "首选", "次选")):
            return False
        if re.match(r"^\d+\s*[\.、．]", name):
            return False
        if any(h in name for h in activity_hints):
            return False
        if name.endswith(("理由", "提醒", "建议", "方法", "潜规则")):
            return False
        if from_enum:
            if len(name) < 2 or len(name) > 10:
                return False
            # 纯文本顿号更严：超过 6 字基本是半句话不是品牌
            if not _looks_like_company_list_name(name):
                return False
        else:
            if not (2 <= len(name) <= 8):
                return False
            if not _looks_like_company_list_name(name):
                return False
        if not _is_brand_like_appearance_token(name, brand_terms):
            return False
        seen.add(name)
        tokens.append(name)
        return True

    def _plain_part_looks_brand(name: str) -> bool:
        if not name or name in skip_labels:
            return False
        if not (2 <= len(name) <= 6):
            return False
        if not _looks_like_company_list_name(name):
            return False
        return _is_brand_like_appearance_token(name, brand_terms)

    for raw_line in str(text).splitlines():
        line = re.sub(r"<[^>]+>", " ", raw_line)
        line = re.sub(r"\s+", " ", line).strip()
        if not line:
            continue

        bold_matches = list(re.finditer(r"\*\*([^*]+)\*\*", line))
        consumed: set[int] = set()
        line_had_bold_enum = False

        # 1) 单个加粗块内的顿号枚举：**兔宝宝、千年舟、大王椰** / **追求…（兔宝宝、大王椰）**
        for idx, match in enumerate(bold_matches):
            chunk = match.group(1).strip()
            sources = _appearance_enum_source_texts(chunk)
            if not sources:
                continue
            got = 0
            for src in sources:
                for part in re.split(r"[、，,]", src):
                    if add(part, from_enum=True):
                        got += 1
            if got:
                consumed.add(idx)
                line_had_bold_enum = True

        # 2) 多个加粗由顿号/和/或连接：**千年舟**、**莫干山**或**兔宝宝**
        idx = 0
        while idx < len(bold_matches):
            if idx in consumed:
                idx += 1
                continue
            run = [idx]
            cursor = idx
            while cursor + 1 < len(bold_matches):
                gap = line[bold_matches[cursor].end() : bold_matches[cursor + 1].start()]
                if not _ENUM_BOLD_GAP_RE.match(gap):
                    break
                run.append(cursor + 1)
                cursor += 1
            if len(run) >= 2:
                got_run = 0
                for bi in run:
                    if add(bold_matches[bi].group(1), from_enum=True):
                        got_run += 1
                    consumed.add(bi)
                if got_run:
                    line_had_bold_enum = True
                idx = cursor + 1
                continue
            idx += 1

        # 3) 未加粗顿号列表（本行已有加粗枚举则跳过，避免「从高端的…」残片）
        unwrapped = re.sub(r"\*\*[^*]+\*\*", " ", line)
        unwrapped = re.sub(r"\s+", " ", unwrapped).strip()
        if (not line_had_bold_enum) and re.search(r"[、，,]", unwrapped):
            parts = re.split(r"[、，,]", unwrapped)
            # 找长度>=2 的连续「像品牌」片段再提交，减少半句话误切
            cluster: list[str] = []

            def flush_cluster() -> None:
                nonlocal cluster
                if len(cluster) >= 2:
                    for part in cluster:
                        add(part, from_enum=True)
                cluster = []

            for part in parts:
                name = _normalize_appearance_enum_part(part, brand_terms)
                if name and (name in seen or _plain_part_looks_brand(name)):
                    cluster.append(part)
                else:
                    flush_cluster()
            flush_cluster()
            # 配置露出词整词落在顿号格但簇不足 2：仍单格入池（AniShort）
            for part in parts:
                name = _normalize_appearance_enum_part(part, brand_terms)
                if not name or not brand_terms or name in seen:
                    continue
                if any(
                    name == str(t or "").strip() or name == f"{str(t or '').strip()}板材"
                    for t in brand_terms
                    if str(t or "").strip()
                ):
                    add(part, from_enum=True)

        # 3b) 引号并列：「大王椰」、「千年舟」——无有效加粗枚举时也收
        # 2026-08-12 - A：同行「**地点A**或**地点B**」假枚举不得挡住引号品牌列表
        if not line_had_bold_enum:
            quoted = _quoted_brand_parts(unwrapped if unwrapped else line)
            if len(quoted) >= 2:
                for part in quoted:
                    add(part, from_enum=True)
            else:
                for part in quoted:
                    name = _normalize_appearance_enum_part(part, brand_terms)
                    if name and brand_terms and any(
                        name == str(t or "").strip() or name == f"{str(t or '').strip()}板材"
                        for t in brand_terms
                        if str(t or "").strip()
                    ):
                        add(part, from_enum=True)

        # 3c) 书名号《万唯初中…》含露出词 → 坍缩入池
        # 2026-08-12 - C1：教辅书名推荐未进顿号枚举时仍可定位品牌
        # 2026-08-12 - 书名过长 from_enum 被 >10 字拒绝 → 改为坍缩成露出词入池
        # 2026-08-12 - 「万唯《初中文言文…》」露出词在书名号外
        for match in re.finditer(
            r"(?:([\u4e00-\u9fffA-Za-z]{2,12})《([^》]{2,40})》|《([^》]{2,40})》)",
            line,
        ):
            prefix = (match.group(1) or "").strip()
            title = (match.group(2) or match.group(3) or "").strip()
            blob = f"{prefix}{title}"
            if not (brand_terms and _configured_exposure_term_in_text(blob, brand_terms)):
                continue
            collapsed = False
            for term in sorted(
                (str(t or "").strip() for t in brand_terms),
                key=len,
                reverse=True,
            ):
                if len(term) >= 2 and term in blob:
                    add(term, from_enum=True)
                    collapsed = True
                    break
            if not collapsed:
                add(prefix or title, from_enum=True)

        # 4) 孤立加粗专名兜底：**爱格** / **大王椰**
        for idx, match in enumerate(bold_matches):
            if idx in consumed:
                continue
            add(match.group(1), from_enum=False)

    return tokens


def _appearance_pool_usable_for_rank(tokens: list[str], brand_terms: list[str]) -> bool:
    """B：全局出场序弱信号——池内须像专名，且露出词落在可排序枚举里。

    2026-08-12 - 卖点句污染池仍给出 11/14/40 → 无合格池则只记提及不写位次
    """
    if not tokens or not brand_terms:
        return False
    brand_at: int | None = None
    for index, token in enumerate(tokens):
        if not _is_brand_like_appearance_token(token, brand_terms):
            return False
        if brand_at is None and _configured_exposure_term_in_text(token, brand_terms):
            brand_at = index
    return brand_at is not None


def _brand_token_appearance_rank(text: str, brand_terms: list[str]) -> int | None:
    """方案 B/A：正文品牌出场序——顿号枚举优先，孤立加粗兜底。

    2026-08-11 - 门店题地点编号被当成品牌第2 - 改按正文品牌点名顺序（兔宝宝/莫干山/千年舟/大王椰→4）
    2026-08-11 - 方案A：未加粗顿号列表也计入，避免合肥虚高到17、莆田虚高到16
    """
    if not text or not brand_terms:
        return None
    tokens = _collect_brand_appearance_tokens(text, brand_terms)
    if not _appearance_pool_usable_for_rank(tokens, brand_terms):
        return None
    for index, token in enumerate(tokens, 1):
        if _configured_exposure_term_in_text(token, brand_terms):
            return index
    return None


def _line_local_brand_enum_rank(
    text: str,
    brand_terms: list[str],
    *,
    min_brands: int = 3,
) -> int | None:
    """P1：单行≥min_brands 个品牌顿号/并列时，取露出词在该行的局部名次（多行取最小）。

    2026-08-11 - 候选池缺「同行局部序」时全文虚高进不了 min；≥3 避免宿州「大王椰、鹏鸿」冲成第1
    2026-08-12 - 选型句「→ 找天赐、艾迪亚」仅 2 品牌也要行内序
    2026-08-12 - markdown 表行卖点加粗勿当行内枚举（动码表行虚第2）；表序走系统名称列
    2026-08-12 - 「还有像A和B」补充并列非负面 → 2 品牌行内第2（勿空位次/全文虚高）
    2026-08-12 - 「频繁出现的品牌（如A、B）」按格序；勿被不分先后长榜盖掉
    """
    from app.services.ranking_parser import (
        _is_markdown_table_line,
        _split_markdown_table_cells,
        _clean_item_name,
        _looks_like_company_list_name,
    )

    if not text or not brand_terms:
        return None
    best: int | None = None
    for raw_line in str(text).splitlines():
        if _line_is_negative_rank_context(raw_line):
            continue
        # 产品表数据行（首格像品牌）：位次走系统名称列，勿用格内卖点 token 抢序
        # 场景矩阵「3城以上|…找艾迪亚」首格非品牌，仍允许行内序
        if _is_markdown_table_line(raw_line):
            cells = _split_markdown_table_cells(raw_line)
            if len(cells) >= 3:
                first = _clean_item_name(re.sub(r"\*\*", "", cells[0] or ""))
                if first and (
                    _configured_exposure_term_in_text(first, brand_terms)
                    or _looks_like_company_list_name(first)
                ):
                    continue
        if not _configured_exposure_term_in_text(raw_line, brand_terms):
            continue
        tokens = _collect_brand_appearance_tokens(raw_line, brand_terms)
        need = min_brands
        if re.search(
            r"[→➡]|找[\u4e00-\u9fffA-Za-z]{2,}|"
            r"对号入座|怎么选|按需求|"
            r"还有像|补充一点|等特色|特色品牌|"
            r"频繁出现|头部选择",
            raw_line,
        ):
            need = min(2, min_brands)
        if len(tokens) < need:
            continue
        for index, token in enumerate(tokens, 1):
            if _configured_exposure_term_in_text(token, brand_terms):
                if best is None or index < best:
                    best = index
                break
    return best


def _section_nomination_brand_rank(body: str, brand_terms: list[str]) -> int | None:
    """小分类内点名行序：书名号 / Name： / 可选择Name / 单品牌 bullet。

    2026-08-12 - 「四、全科」下《万唯…》唯一推荐；「二、工具平台」下 AniShort：为首条
    """
    from app.services.ranking_parser import _looks_like_company_list_name, _clean_item_name

    if not body or not brand_terms:
        return None
    skip_heads = frozenset({
        "特点", "说明", "提醒", "注意", "组合", "任务", "方案", "内容", "适合", "优势", "短板",
        "讲解", "练习", "专项", "拓展", "进阶", "预习",
    })
    slots: list[str] = []
    for raw in str(body).splitlines():
        plain = re.sub(r"<[^>]+>", " ", raw)
        plain = re.sub(r"\s+", " ", plain).strip()
        if not plain or plain in {"---", "-", "—"}:
            continue
        bare = re.sub(r"\*\*", "", plain)
        # 万唯《书名》/《万唯书名》；裸《朝花夕拾》名著不占点名位
        # 2026-08-12 - 语文节名著书名号抢槽 → 专项万唯从第1抬到第3
        branded_books = re.findall(
            r"(?:([\u4e00-\u9fffA-Za-z]{2,12})《([^》]{2,40})》|《([^》]{2,40})》)",
            bare,
        )
        if branded_books:
            added = False
            for prefix, inner_a, inner_b in branded_books:
                title = (inner_a or inner_b or "").strip()
                blob = f"{(prefix or '').strip()}{title}"
                if not blob:
                    continue
                if _configured_exposure_term_in_text(blob, brand_terms):
                    slots.append(blob)
                    added = True
                elif (prefix or "").strip() and _looks_like_company_list_name(
                    (prefix or "").strip()
                ):
                    slots.append(blob)
                    added = True
            if added:
                continue
        text = re.sub(r"^[-*•·▪]\s*", "", bare).strip()
        lead = re.match(
            r"^([A-Za-z][A-Za-z0-9]{1,24}|[\u4e00-\u9fff][A-Za-z0-9\u4e00-\u9fff &]{0,22}?)\s*[：:]",
            text,
        )
        if lead:
            head = _clean_item_name(lead.group(1))
            if head and head not in skip_heads and (
                _configured_exposure_term_in_text(head, brand_terms)
                or _looks_like_company_list_name(head)
                or re.match(r"^[A-Za-z]", head)
            ):
                slots.append(head)
                continue
        choose = re.search(
            r"(?:可以关注|可选择|可选|选择|找)([\u4e00-\u9fffA-Za-z]{2,24})",
            bare,
        )
        if choose:
            slots.append(choose.group(1))
            continue
        if re.match(r"^[-*•·▪]\s+", plain) and _configured_exposure_term_in_text(bare, brand_terms):
            if bare.count("、") < 2 and bare.count("，") < 2:
                slots.append(bare)
    if not slots:
        return None
    for index, slot in enumerate(slots, 1):
        if _configured_exposure_term_in_text(slot, brand_terms):
            return index
    return None


# 档位族仍保留语义提示；「第N站」走结构，不再靠无限扩充主持词
_TIER_SECTION_HINTS = (
    "高端", "顶配", "主流", "性价比", "预算", "中端", "低端", "刚需", "进口", "一线", "档",
)
# 2026-08-12 - 「其他值得关注/实力品牌参考」点名算小节内排名（非全文出场、非清空）
_SECONDARY_MENTION_HEADING_RE = re.compile(
    r"(?:其他|其它).{0,12}(?:品牌|参考|关注)|值得关注|实力品牌参考|拓展阅读|参考品牌"
)
_PRIMARY_RANK_HEADING_RE = re.compile(
    r"主流|速览|对比|重点|品牌推荐|推荐清单|选型建议|分档|按场景"
)
_TIER_VENUE_HINTS = (
    "市场", "商城", "卖场", "地标", "门店", "建材城", "白马", "专卖店", "旗舰店", "直营店",
    "居然之家", "美凯龙",
)
_SECTION_SKIP_LABELS = frozenset({
    "怎么去", "特点", "推荐理由", "定位", "推荐", "导航", "注意", "提醒", "优势",
    "地址", "电话", "主打", "适合", "总结", "建议", "理由", "特色", "价格", "服务",
    "有什么", "怎么逛", "重点看什么", "适合谁", "选购建议",
})
_STATION_LABEL_RE = re.compile(r"第[一二三四五六七八九十百零〇\d]+站")
_CHAPTER_LABEL_RE = re.compile(
    r"^(?:#{1,3}\s*)?([一二三四五六七八九十]+)[、．.]\s*(.+)$"
)


def _short_tier_section_title(title: str) -> str:
    text = re.sub(r"\*\*", "", str(title or ""))
    text = re.sub(r"^[一二三四五六七八九十]+[、.．]\s*", "", text)
    text = re.sub(r"^\d+[、.．]\s*", "", text)
    text = re.sub(r"[（(].*?[)）]", "", text)
    text = re.sub(r"\s+", "", text).strip(" ：:.-—")
    return text[:24]


def _is_venue_only_section_title(title: str) -> bool:
    """纯卖场/市场地名不作分类（避免宿州「白马商城」类内第1冲掉全文出场序）。"""
    raw = re.sub(r"\*\*", "", str(title or ""))
    if _STATION_LABEL_RE.search(raw):
        return False
    # 大章「二、大型建材市场」允许带市场字，不当纯卖场名
    if _CHAPTER_LABEL_RE.match(re.sub(r"^#+\s*", "", raw.strip())):
        return False
    text = _short_tier_section_title(raw)
    blob = f"{text}{raw}"
    return any(h in blob for h in _TIER_VENUE_HINTS)


def _category_section_label(title: str) -> str | None:
    """S1b：结构小节类名。第N站 / 大章「一、二、」/ 档位标题；单点卖场名排除。

    2026-08-11 - 分类不再堆主持词；门店「第二站」应类内计位，白马商城仍走全文出场
    2026-08-11 - 莆田「二、大型建材市场」内顿号第4被全文抬到7 - 大章即便带「市场」也走类内
    """
    raw = re.sub(r"\*\*", "", str(title or "")).strip()
    raw = re.sub(r"^#+\s*", "", raw).strip()
    if not raw:
        return None
    station = _STATION_LABEL_RE.search(raw)
    if station:
        return station.group(0)
    chapter = _CHAPTER_LABEL_RE.match(raw)
    if chapter:
        body = chapter.group(2).strip()
        label = _short_tier_section_title(body)
        if label and label not in _SECTION_SKIP_LABELS and 2 <= len(label) <= 16:
            return label
        return None
    text = _short_tier_section_title(raw)
    if not text or len(text) > 16:
        return None
    # 档位标题可含顿号（预算充足、追求极致环保）；其它带顿号/冒号的整句不当类名
    has_sep = any(ch in text for ch in ("、", "：", ":", "；"))
    if has_sep:
        if not any(h in text for h in _TIER_SECTION_HINTS):
            return None
        text = re.sub(r"[、：:;；]", "", text)[:16]
        if not text:
            return None
    if text in _SECTION_SKIP_LABELS:
        return None
    if _is_venue_only_section_title(raw):
        return None
    # 步骤标题（第一步/第二步）不当品牌分类
    if re.match(r"^第[一二三四五六七八九十\d]+步", text):
        return None
    if any(h in text for h in _TIER_SECTION_HINTS):
        return text
    # 2026-08-12 - 教辅 ### 语法&阅读 未当小节 → 万唯听力吃到脏结构化第7
    topic = text.replace("＆", "&")
    bare = _strip_section_decorations(topic)
    if topic in _TOPIC_SECTION_LABELS or text in _TOPIC_SECTION_LABELS or bare in _TOPIC_SECTION_LABELS:
        if bare in _TOPIC_SECTION_LABELS:
            return bare
        return topic if topic in _TOPIC_SECTION_LABELS else text
    # 2026-08-12 - ### 🗣️英语 等学科标题切开，避免跨科编号把万唯抬到第7/9
    if bare in _SUBJECT_SECTION_LABELS:
        return bare
    # 2026-08-12 - 「全国性品牌」下「可选择艾迪亚」须类内点名第1
    if bare in _GEO_BRAND_SECTION_LABELS or text in _GEO_BRAND_SECTION_LABELS:
        return bare if bare in _GEO_BRAND_SECTION_LABELS else text
    # 2026-08-12 - 「其他值得关注」等须走类内序，否则只能吃全文出场虚高
    sec = _secondary_section_label(raw)
    if sec:
        return sec
    return None


_TOPIC_SECTION_LABELS = frozenset({
    "词汇", "语法", "阅读", "作文", "讲解预习", "专项练习",
    "语法&阅读", "语法阅读", "同步练习", "单元试卷", "必读书配套",
    "讲解", "练习", "预习",
})
# 2026-08-12 - 教辅 ### 📖语文/🗣️英语 须切开，否则整章「分学科教辅」连号/出场序虚高
_SUBJECT_SECTION_LABELS = frozenset({
    "语文", "数学", "英语", "物理", "化学", "生物", "历史", "地理",
    "道法", "道德与法治", "小四门", "体育", "科学",
})
# 2026-08-12 - 短剧/投放「全国性品牌」小标题
_GEO_BRAND_SECTION_LABELS = frozenset({
    "全国性品牌", "全国品牌", "本地品牌", "区域品牌", "国际品牌",
})
_SECTION_DECORATION_RE = re.compile(r"[📚📕📗📘📙📝📖🗣️📐🗺️🧮📌✅❌🔍🏅🏆🥇⚙️🤔*#\s]+")


def _strip_section_decorations(text: str) -> str:
    return _SECTION_DECORATION_RE.sub("", str(text or ""))


def _secondary_section_label(title: str) -> str | None:
    raw = re.sub(r"\*\*", "", str(title or "")).strip()
    raw = re.sub(r"^#+\s*", "", raw).strip()
    if not raw:
        return None
    bare = _strip_section_decorations(_short_tier_section_title(raw)).strip(" ：:.-—|")
    probe = bare or _strip_section_decorations(raw)
    if not probe or not _SECONDARY_MENTION_HEADING_RE.search(probe):
        return None
    return (bare or probe)[:16] or None


def _heading_title_from_line(raw_line: str) -> str | None:
    plain = re.sub(r"<[^>]+>", " ", str(raw_line or ""))
    plain = re.sub(r"\s+", " ", plain).strip()
    if not plain:
        return None
    bare = re.sub(r"\*\*", "", plain)
    bare = re.sub(r"^#{1,3}\s*", "", bare).strip()
    bare = _strip_section_decorations(bare).strip(" ：:.-—|")
    if re.match(r"^(?:#{1,3}\s*|[一二三四五六七八九十]+[、.．]|\d+[、.．])", plain):
        return bare[:40] or None
    if re.fullmatch(r"\*\*[^*]{2,40}\*\*\s*$", plain):
        return bare[:40] or None
    return None


def _brand_only_in_secondary_mention(text: str, brand_terms: list[str]) -> bool:
    """品牌是否只出现在「其他/参考/值得关注」类小节（未进主推荐表/速览）。"""
    if not text or not brand_terms:
        return False
    in_secondary = False
    saw_primary = False
    saw_secondary = False
    for raw in str(text).splitlines():
        title = _heading_title_from_line(raw)
        if title:
            if _SECONDARY_MENTION_HEADING_RE.search(title):
                in_secondary = True
            elif _PRIMARY_RANK_HEADING_RE.search(title) or _category_section_label(title):
                in_secondary = False
            elif re.search(r"如何选择|三点建议|给你三点|按需选择", title):
                # 建议段里的点名也不算正式榜位
                in_secondary = True
        if not _configured_exposure_term_in_text(raw, brand_terms):
            continue
        if in_secondary:
            saw_secondary = True
        else:
            saw_primary = True
    return saw_secondary and not saw_primary


def _drop_soft_ranks_beaten_by_structured(
    candidates: list[BrandRankResolution],
) -> list[BrandRankResolution]:
    """有结构化位次时，勿让建议句/全文出场序更靠前的软信号盖掉主表。

    2026-08-12 - 动码主表第4被「可以关注动码」line_enum 盖成第1
    2026-08-12 - 有主表时「其他/参考」小节内第1也不得盖掉主表位次
    """
    has_structured = any(
        item.source == "structured" and item.rank is not None for item in candidates
    )
    if not has_structured:
        return candidates
    kept: list[BrandRankResolution] = []
    for item in candidates:
        basis = str(item.rank_basis or "")
        # 保留教辅等正式 section_local 与 structured 一起 min；丢掉 secondary/建议软信号
        if item.source == "appearance" and basis in {
            "line_enum_local",
            "brand_token_order",
            "appearance_beyond_top3",
            "secondary_section_local",
            "",
        }:
            continue
        kept.append(item)
    return kept


def _numbered_list_brand_rank(text: str, brand_terms: list[str]) -> int | None:
    """小节内 1. 2. 3. 编号推荐：返回含露出词的条目序号。"""
    if not text or not brand_terms:
        return None
    items: list[str] = []
    for raw in str(text).splitlines():
        plain = re.sub(r"<[^>]+>", " ", raw)
        plain = re.sub(r"\s+", " ", plain).strip()
        bare = re.sub(r"\*\*", "", plain)
        # 允许 ### 1. 同行条目；跨行分档见 _numbered_subheading_brand_rank
        bare = re.sub(r"^#{1,3}\s*", "", bare)
        match = re.match(r"^(\d+)\s*[\.、．]\s+(.+)$", bare)
        if not match:
            continue
        items.append(match.group(2).strip())
    if len(items) < 2:
        return None
    for index, body in enumerate(items, 1):
        if _configured_exposure_term_in_text(body, brand_terms):
            return index
    return None


def _numbered_subheading_brand_rank(text: str, brand_terms: list[str]) -> int | None:
    """### 1. / ### 2. 分档小标题：品牌为该档主推（标题或书名行）→ 返回标题序号。

    2026-08-12 - 万唯在「### 2. 中等生」下却被节内卖点 token 抬成第5
    2026-08-12 - 勿把「1. 卖场：兔宝宝、…、大王椰」顿号并列当成第1档主推
    """
    if not text or not brand_terms:
        return None
    header_re = re.compile(r"^#{0,3}\s*(\d+)\s*[\.、．]\s+(.+)$")
    blocks: list[tuple[int, str, list[str]]] = []
    current_num: int | None = None
    current_heading = ""
    current_parts: list[str] = []

    def flush() -> None:
        nonlocal current_num, current_heading, current_parts
        if current_num is not None:
            blocks.append((current_num, current_heading, current_parts))
        current_num = None
        current_heading = ""
        current_parts = []

    for raw in str(text).splitlines():
        plain = re.sub(r"<[^>]+>", " ", raw)
        plain = re.sub(r"\s+", " ", plain).strip()
        bare = re.sub(r"\*\*", "", plain)
        match = header_re.match(bare)
        if match:
            flush()
            current_num = int(match.group(1))
            current_heading = match.group(2).strip()
            current_parts = []
            continue
        if current_num is not None:
            current_parts.append(bare)
    flush()
    if len(blocks) < 2:
        return None
    for num, heading, parts in blocks:
        if _configured_exposure_term_in_text(heading, brand_terms):
            return num
        for line in parts:
            text_line = str(line or "").strip()
            if not text_line or not _configured_exposure_term_in_text(text_line, brand_terms):
                continue
            # 卖场/方案里的多品牌顿号并列 ≠ 该编号档的主推书
            if text_line.count("、") >= 2:
                continue
            return num
    return None


def _looks_like_tier_section_title(title: str) -> bool:
    return _category_section_label(title) is not None


def _tier_local_brand_token_rank(
    text: str,
    brand_terms: list[str],
) -> tuple[int | None, str | None]:
    """分档/小类内品牌点名序（S1b：第N站 + 大章一、二、 + 档位；单点卖场名不走）。

    2026-08-11 - 方案C：高性价比下大王椰应为类内第1，并带回类名供展示
    2026-08-11 - S1b：第二站内大王椰、福庆 → 1（第二站），不靠无限主持词
    2026-08-11 - 大章「二、大型建材市场」类内顿号序，避免全文专卖店品牌把位次抬到7
    """
    from app.services.ranking_parser import _clean_item_name

    if not text or not brand_terms:
        return None, None

    lines = str(text).splitlines()
    # 同行：「**高性价比…**：**大王椰**、**鹏鸿**」
    for raw_line in lines:
        line = re.sub(r"<[^>]+>", " ", raw_line)
        line = re.sub(r"\s+", " ", line).strip()
        bolds = re.findall(r"\*\*([^*]+)\*\*", line)
        if len(bolds) < 2:
            continue
        title_raw = _clean_item_name(bolds[0])
        title_label = _category_section_label(title_raw)
        if not title_label:
            continue
        stripped = re.sub(r"\*\*" + re.escape(bolds[0]) + r"\*\*", " ", line, count=1)
        tokens = _collect_brand_appearance_tokens(stripped, brand_terms)
        tokens = [t for t in tokens if _short_tier_section_title(t) != title_label]
        for index, token in enumerate(tokens, 1):
            if _configured_exposure_term_in_text(token, brand_terms):
                return index, title_label

    # 分节：markdown / 第N站 / 一、二、 标题，直到下一节
    sections: list[tuple[str, list[str]]] = []
    current_title: str | None = None
    current_lines: list[str] = []

    def flush() -> None:
        nonlocal current_title, current_lines
        if current_title is not None:
            sections.append((current_title, current_lines))
        current_title = None
        current_lines = []

    header_re = re.compile(
        r"^(?:#{1,3}\s*|[一二三四五六七八九十]+[、.．]\s*|\d+[、.．]\s*)(.+)$"
    )
    for raw_line in lines:
        line = re.sub(r"<[^>]+>", " ", raw_line)
        plain = re.sub(r"\s+", " ", line).strip()
        if not plain:
            if current_title is not None:
                current_lines.append(raw_line)
            continue
        header_body = None
        bare = re.sub(r"\*\*", "", plain)
        m = header_re.match(bare)
        if m:
            header_body = m.group(1).strip()
        else:
            # ### 第二站：… 在去掉 # 后若整行以第N站开头
            station_line = re.match(
                r"^#{0,3}\s*(第[一二三四五六七八九十百零〇\d]+站.*)$",
                bare,
            )
            if station_line:
                header_body = station_line.group(1).strip()
            else:
                only_bold = re.fullmatch(r"\*\*([^*]+)\*\*\s*$", plain)
                if only_bold:
                    header_body = only_bold.group(1).strip()
                else:
                    # 2026-08-11 - DeepSeek「- **兼顾品质与性价比**」未当小节 → 类内第4进不了池只剩结构化9
                    bullet_bold = re.fullmatch(r"[-*•]\s*\*\*([^*]+)\*\*\s*$", plain)
                    if bullet_bold:
                        header_body = bullet_bold.group(1).strip()
        # 2026-08-12 - 先用整行再认 header_body：去掉「四、」后「试卷类」认不出 → 万唯全文虚第5
        label = None
        if header_body:
            label = _category_section_label(bare) or _category_section_label(header_body)
        if label:
            flush()
            current_title = label
            current_lines = []
            continue
        if current_title is not None:
            current_lines.append(raw_line)

    flush()

    for title, body_lines in sections:
        body = "\n".join(body_lines)
        # 2026-08-12 - ### 1./2./3. 分档跨行点名优先于卖点 token 出场
        sub_heading = _numbered_subheading_brand_rank(body, brand_terms)
        if sub_heading is not None:
            return sub_heading, title
        # 2026-08-12 - 编号列表类内序；仅短小节（≤6条或主题小节），避免「分学科教辅」跨科连号虚高
        numbered = _numbered_list_brand_rank(body, brand_terms)
        if numbered is not None:
            item_n = sum(
                1
                for raw in body_lines
                if re.match(
                    r"^\s*(?:#{1,3}\s*)?(?:\d+)\s*[\.、．]\s+",
                    re.sub(r"\*\*", "", re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", raw)).strip()),
                )
            )
            if title in _TOPIC_SECTION_LABELS or item_n <= 6:
                return numbered, title
        tokens = _collect_brand_appearance_tokens(body, brand_terms)
        for index, token in enumerate(tokens, 1):
            if _configured_exposure_term_in_text(token, brand_terms):
                return index, title
        # 2026-08-12 - token 池吃不到书名号/「AniShort：」/「可选择X」时走点名行序
        nominated = _section_nomination_brand_rank(body, brand_terms)
        if nominated is not None:
            return nominated, title
    return None, None


def _appearance_order_rank(
    text: str,
    brand_terms: list[str],
    scope: str | None = None,
    *,
    allow_global: bool = True,
) -> int | None:
    """品牌出场序：优先正文加粗/顿号点名序（方案B）；再退回提名行序。"""
    from app.services.ranking_parser import _is_company_nomination_line

    # 方案 B：先按品牌 token 出场序，避免门店题把「第N个地点下的品牌」算成第N
    token_rank = _brand_token_appearance_rank(text, brand_terms)
    if token_rank is not None:
        return token_rank

    if scope:
        scoped = appearance_order_rank_scoped(
            text,
            lambda line: _brand_appears_in_text(line, brand_terms),
            scope,
        )
        if scoped is not None:
            return scoped
        if not allow_global:
            return None

    if not allow_global:
        return None

    order = 0
    for raw_line in text.splitlines():
        line = re.sub(r"<[^>]+>", " ", raw_line)
        line = re.sub(r"\s+", " ", line).strip()
        if not line or len(line) > 120:
            continue
        if _is_category_header_line(line):
            if not _is_company_nomination_line(line):
                continue
        elif not _is_company_nomination_line(line):
            continue
        order += 1
        if _brand_appears_in_text(line, brand_terms):
            return order
    return None


def _preferred_column_table_rank(answer_text: str, brand_terms: list[str]) -> int | None:
    """选型表「首选推荐」列：品牌首次出现在首选列的数据行序（1-based）。

    2026-07-29 - Kimi 选型表首选第一行被 LLM 判成第4 - 规则直接读首选列，不依赖 LLM
    2026-07-30 - 「可以首选松下」列表句误触发 - 仅认首选推荐/首选+备选真表头，排除 bullet
    """
    if not answer_text or not brand_terms:
        return None
    lines = [str(line or "").strip() for line in answer_text.splitlines()]
    for idx, header in enumerate(lines):
        if "首选" not in header:
            continue
        # 列表/散文里的「可以首选 XX」不是选型表头
        if header.lstrip().startswith(("*", "-", "•", "·", "▪")):
            continue
        if not (
            "首选推荐" in header
            or ("备选" in header and "首选" in header)
        ):
            continue
        # 表头需同时能分出首选列；常见「首选推荐」「首选」+「备选」
        if "\t" in header:
            cols = [c.strip() for c in header.split("\t")]
        elif re.search(r"\s{2,}", header):
            cols = [c.strip() for c in re.split(r"\s{2,}", header) if c.strip()]
        else:
            continue
        preferred_idx = next(
            (i for i, c in enumerate(cols) if "首选" in c),
            None,
        )
        if preferred_idx is None:
            continue
        row_no = 0
        for data in lines[idx + 1 :]:
            if not data:
                if row_no:
                    break
                continue
            if data.startswith(("一、", "二、", "三、", "四、", "五、", "##", "关键提醒")):
                break
            if data.lstrip().startswith(("*", "-", "•", "·", "▪")):
                break
            if "\t" in data:
                cells = [c.strip() for c in data.split("\t")]
            elif re.search(r"\s{2,}", data):
                cells = [c.strip() for c in re.split(r"\s{2,}", data) if c.strip()]
            else:
                continue
            if len(cells) <= preferred_idx:
                continue
            row_no += 1
            if _brand_appears_in_text(cells[preferred_idx], brand_terms):
                return row_no
    return None


def _is_category_header_line(line: str) -> bool:
    from app.services.ranking_parser import _is_category_header
    return _is_category_header(line)


@dataclass(frozen=True)
class BrandRankResolution:
    rank: int | float | None
    mentioned: bool
    source: str
    confidence: float = 1.0
    category: str | None = None
    rank_basis: str | None = None
    evidence: str | None = None


def _matched_brand_category(
    subtask: GeoMonitorSubtask,
    brand_terms: list[str],
    rank: int | float,
) -> str | None:
    target = float(rank)
    for entry in _collect_ranking_entries(subtask):
        name = str(entry.get("name") or "").strip()
        if not name or not _name_matches_brand(name, brand_terms):
            continue
        entry_rank = entry.get("rank")
        if entry_rank is None:
            continue
        try:
            if float(entry_rank) == target:
                category = str(entry.get("category") or "").strip()
                return category or None
        except (TypeError, ValueError):
            continue
    return None


def _rank_sort_key(rank: int | float) -> float:
    try:
        return float(rank)
    except (TypeError, ValueError):
        return float("inf")


def _pick_frontmost_resolution(
    candidates: list[BrandRankResolution],
    *,
    mentioned: bool,
) -> BrandRankResolution:
    """方案 X：自动规则里取名次最靠前（数字最小）的一条。"""
    numeric = [item for item in candidates if item.rank is not None]
    if not numeric:
        return BrandRankResolution(
            rank=None,
            mentioned=mentioned,
            source="none",
            confidence=0.9 if not mentioned else 0.4,
        )
    return min(numeric, key=lambda item: _rank_sort_key(item.rank))  # type: ignore[arg-type]


def _resolve_brand_rank_detail(
    subtask: GeoMonitorSubtask,
    monitor_keywords: str | None,
    brand_terms: list[str],
    asset: BrandAsset | None = None,
) -> BrandRankResolution:
    """Resolve brand rank with provenance for matrix display and LLM fallback.

    2026-07-27 - 方案X 全自动规则取最前 - 结构化/点名序/库内位次取 min；人工锁与 LLM 仍优先
    ponytail: 乐观偏差会抬高 Top3；若改回保守瀑布，收紧候选池即可
    """
    # 露出类：context 仍可算「提及」；排名类位次必须正文含品牌
    combined_text = _subtask_brand_text(subtask)
    has_brand_anywhere = _brand_appears_in_text(combined_text, brand_terms)
    answer_text = _answer_body_for_rank(subtask)
    # 2026-08-11 - 排名「匹配成功」= 正文含配置露出词整段，不用自动切片短片段
    has_brand_in_answer = _configured_exposure_term_in_text(answer_text, brand_terms)
    if prompt_monitor_intent(subtask.prompt) != "ranking":
        return BrandRankResolution(
            rank=None,
            mentioned=has_brand_anywhere,
            source="exposure",
            confidence=1.0,
        )

    raw = getattr(subtask, "raw_result_json", None)
    raw = raw if isinstance(raw, dict) else {}
    if raw.get("source") == "manual_snapshot" and subtask.mention_position is not None:
        # 仅用户手填名次才锁定；自动解析的名次允许规则/重算覆盖
        # 旧补录无 flag 时默认锁定，避免已手填名次被重算冲掉
        if raw.get("manual_rank_locked", True):
            return BrandRankResolution(
                rank=subtask.mention_position,
                mentioned=True,
                source="manual",
                confidence=1.0,
            )

    # 2026-08-11 - 正文完全未提品牌仍写出位次 - 非人工路径一律要求 answer 含露出词
    if not has_brand_in_answer:
        return BrandRankResolution(
            rank=None,
            mentioned=False,
            source="none",
            confidence=0.95,
        )

    # 2026-08-11 - 假货/贴牌等负面点名不进推荐位次，只保留提及
    rankable_text = _answer_excluding_negative_rank_context(answer_text)
    has_brand_in_rankable = _configured_exposure_term_in_text(rankable_text, brand_terms)
    if not has_brand_in_rankable:
        return BrandRankResolution(
            rank=None,
            mentioned=True,
            source="exposure",
            confidence=0.9,
            rank_basis="negative_context_skip",
        )

    # 2026-07-29 - 任何情况取最优 - 已存 LLM 结果改为候选，不再短路挡住更好的规则位次
    stored_llm_candidate: BrandRankResolution | None = None
    stored_resolution = raw.get("rank_resolution")
    if isinstance(stored_resolution, dict) and stored_resolution.get("source") == "llm":
        rank_raw = stored_resolution.get("rank")
        rank_value: int | float | None
        if rank_raw is None:
            rank_value = None
        else:
            try:
                parsed = float(rank_raw)
                rank_value = int(parsed) if parsed.is_integer() else parsed
            except (TypeError, ValueError):
                rank_value = None
        try:
            confidence = float(stored_resolution.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        evidence = str(stored_resolution.get("evidence") or "").strip() or None
        # evidence 须能在正文定位，避免 LLM 只吃了 mention_context；负面行证据作废
        if evidence and evidence not in rankable_text:
            stored_llm_candidate = None
        elif evidence and _line_is_negative_rank_context(evidence):
            stored_llm_candidate = None
        else:
            stored_llm_candidate = BrandRankResolution(
                rank=rank_value,
                mentioned=bool(stored_resolution.get("mentioned")),
                source="llm",
                confidence=max(0.0, min(1.0, confidence)),
                category=str(stored_resolution.get("category") or "").strip() or None,
                rank_basis=str(stored_resolution.get("rank_basis") or "").strip() or None,
                evidence=evidence,
            )

    monitor_keyword = str(monitor_keywords or "").strip()
    scope = _ranking_scope_text(monitor_keyword, subtask.prompt)
    candidates: list[BrandRankResolution] = []
    mentioned = has_brand_in_answer
    if stored_llm_candidate is not None:
        candidates.append(stored_llm_candidate)
        mentioned = mentioned or stored_llm_candidate.mentioned

    rank_from_list, in_ranking_list, list_category = _find_brand_in_rankings(
        subtask,
        brand_terms,
        asset,
        monitor_keywords=monitor_keyword,
    )
    # 2026-07-27 - 正文无露出却 structured 虚抬名次 - 榜命中须同时正文有品牌
    # 结构化命中也须落在非负面正文（避免假货句被解析进榜）
    # 2026-08-12 - 「排名不分先后」对比表入库长榜勿当推荐位次；位次改走行内枚举（派雅频繁出现第2）
    unordered_list_table = bool(re.search(r"\|[^\n]*不分先后[^\n]*\|", rankable_text))
    if has_brand_in_rankable and rank_from_list is not None and not unordered_list_table:
        category = list_category or _matched_brand_category(subtask, brand_terms, rank_from_list)
        basis = "table" if "|" in rankable_text and "企业" in rankable_text else "section"
        candidates.append(
            BrandRankResolution(
                rank=rank_from_list,
                mentioned=True,
                source="structured",
                confidence=0.95,
                category=category,
                rank_basis=basis,
            )
        )
        mentioned = True
    elif has_brand_in_rankable and in_ranking_list:
        mentioned = True

    preferred_rank = _preferred_column_table_rank(rankable_text, brand_terms) if has_brand_in_rankable else None
    if preferred_rank is not None:
        candidates.append(
            BrandRankResolution(
                rank=preferred_rank,
                mentioned=True,
                source="structured",
                confidence=0.95,
                rank_basis="preferred_column",
            )
        )
        mentioned = True

    token_rank = _brand_token_appearance_rank(rankable_text, brand_terms) if has_brand_in_rankable else None

    # 2026-08-12 - 「其他/参考」仅点名：用小节内序，禁用全文出场/建议句局部序（免虚成 10/18）
    secondary_only = bool(
        has_brand_in_rankable and _brand_only_in_secondary_mention(rankable_text, brand_terms)
    )

    # 2026-08-11 - 方案C：分档小类内点名序优先于全文出场序，并带回类名
    # 2026-08-12 - 其他值得关注/实力品牌参考：点名也算排名（小节内序）
    if has_brand_in_rankable:
        tier_rank, tier_title = _tier_local_brand_token_rank(rankable_text, brand_terms)
        if tier_rank is not None:
            is_secondary_sec = bool(
                tier_title and _SECONDARY_MENTION_HEADING_RE.search(str(tier_title))
            )
            candidates.append(
                BrandRankResolution(
                    rank=tier_rank,
                    mentioned=True,
                    source="appearance",
                    confidence=0.72,
                    category=tier_title,
                    rank_basis=(
                        "secondary_section_local" if is_secondary_sec else "section_local"
                    ),
                )
            )
            mentioned = True

    # 2026-08-11 - P1：同行≥3品牌顿号局部序进候选池，与全文/类内一起 min
    if has_brand_in_rankable and not secondary_only:
        line_rank = _line_local_brand_enum_rank(rankable_text, brand_terms)
        if line_rank is not None:
            candidates.append(
                BrandRankResolution(
                    rank=line_rank,
                    mentioned=True,
                    source="appearance",
                    confidence=0.7,
                    rank_basis="line_enum_local",
                )
            )
            mentioned = True

    # 2026-08-12 - B：全局出场仅合格 token/scoped；关掉提名行序免卖点虚高
    # 2026-08-12 - 已有类内/同行局部序时勿再加全文出场进 min（否则 语法&阅读第3 被全文第2 冲掉）
    if has_brand_in_rankable and not secondary_only:
        local_bases = {
            str(item.rank_basis or "")
            for item in candidates
            if item.rank is not None
        }
        if not local_bases.intersection(
            {"section_local", "line_enum_local", "secondary_section_local"}
        ):
            appearance_rank = _appearance_order_rank(
                rankable_text,
                brand_terms,
                scope,
                allow_global=False,
            )
            if appearance_rank is not None:
                beyond = int(appearance_rank) > 3
                candidates.append(
                    BrandRankResolution(
                        rank=appearance_rank,
                        mentioned=True,
                        source="appearance",
                        confidence=0.45 if beyond else 0.55,
                        rank_basis="brand_token_order" if token_rank == appearance_rank else (
                            "appearance_beyond_top3" if beyond else None
                        ),
                    )
                )
                mentioned = True

    # 2026-08-12 - B：无合格枚举池时不回退旧 api/地点序（散文露出只记提及）
    # 2026-08-12 - 有主表结构化位次时，丢掉建议句/全文出场软信号，免第4被盖成第1
    candidates = _drop_soft_ranks_beaten_by_structured(candidates)

    return _pick_frontmost_resolution(candidates, mentioned=mentioned)


def _resolve_brand_rank(
    subtask: GeoMonitorSubtask,
    monitor_keywords: str | None,
    brand_terms: list[str],
    asset: BrandAsset | None = None,
) -> tuple[int | float | None, bool]:
    """Return brand list rank for ranking prompts; exposure prompts only report mention."""
    detail = _resolve_brand_rank_detail(subtask, monitor_keywords, brand_terms, asset)
    return detail.rank, detail.mentioned


def _looks_like_structured_rank_header(
    name: str,
    brand_terms: list[str] | None = None,
) -> bool:
    """结构化脏榜：把「词汇」「语法&阅读」等小节标题当成选手。"""
    if brand_terms and _configured_exposure_term_in_text(name, brand_terms):
        return False
    text = re.sub(r"[📚📕📗📘📙📝📖🗣️📐🗺️🧮📌✅❌*#\s]+", "", str(name or "")).strip()
    text = text.replace("＆", "&")
    if not text or len(text) > 16:
        return False
    from app.services.ranking_parser import SUBSECTION_LABELS, _is_subsection_label

    if _is_subsection_label(text) or text in SUBSECTION_LABELS:
        return True
    if text in _TOPIC_SECTION_LABELS or text in _SUBJECT_SECTION_LABELS:
        return True
    return False


def _structured_rank_excluding_headers(
    merged: list[dict[str, Any]],
    entry: dict[str, Any],
    brand_terms: list[str],
) -> float | None:
    """同类目内去掉小节标题后重排位次。"""
    try:
        original = float(entry["rank"])
    except (TypeError, ValueError, KeyError):
        return None
    cat = str(entry.get("category") or "").strip()
    if not cat:
        return original
    peers: list[dict[str, Any]] = []
    for item in merged:
        if str(item.get("category") or "").strip() != cat:
            continue
        name = str(item.get("name") or "").strip()
        if not name or _looks_like_structured_rank_header(name, brand_terms):
            continue
        peers.append(item)
    if len(peers) < 2:
        return original

    def sort_key(item: dict[str, Any]) -> float:
        try:
            return float(item.get("rank"))
        except (TypeError, ValueError):
            return float("inf")

    peers.sort(key=sort_key)
    # 2026-08-12 - 同类同名重复（双份榜）按名去重，保留更靠前的一份
    unique_peers: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    for item in peers:
        name = str(item.get("name") or "").strip()
        if name in seen_names:
            continue
        seen_names.add(name)
        unique_peers.append(item)
    peers = unique_peers
    if len(peers) < 2:
        return original

    target_name = str(entry.get("name") or "").strip()
    target_rank = entry.get("rank")
    for index, item in enumerate(peers, 1):
        if item is entry:
            return float(index)
        if str(item.get("name") or "").strip() == target_name and item.get("rank") == target_rank:
            return float(index)
    for index, item in enumerate(peers, 1):
        if str(item.get("name") or "").strip() == target_name:
            return float(index)
    return original


def _find_brand_in_structured_rankings(
    subtask: GeoMonitorSubtask,
    brand_terms: list[str],
    asset: BrandAsset | None,
    *,
    monitor_keywords: str | None = None,
    normalize_cache: dict[Any, list[dict[str, Any]]] | None = None,
) -> tuple[int | float | None, bool, str | None]:
    """仅用 all_rankings_json 匹配品牌位次（不读 answer_content）。"""

    def match_name(name: str) -> bool:
        return _name_matches_brand(name, brand_terms)

    def skip_name(name: str) -> bool:
        text = str(name or "").strip()
        if not text or asset is None:
            return False
        if any(token in text for token in ("公司", "集团", "控股", "股份", "有限")):
            return False
        if any(brand in text for brand in brand_terms if brand and len(brand) >= 2):
            return False
        if text.endswith(("传媒", "广告", "媒体")) and len(text) >= 4:
            return False
        return _is_industry_monitor_keyword(text, asset)

    raw = subtask.all_rankings_json or []
    merged = _normalize_structured_rankings_cached(raw, normalize_cache)
    if not merged:
        return None, False, None
    scope = _ranking_scope_text(monitor_keywords, subtask.prompt)
    rank, matched, entry = find_best_brand_hit_scoped(merged, match_name, scope, skip_name=skip_name)
    if entry is None:
        return rank, matched, None
    category = str(entry.get("category") or "").strip() or None
    # 2026-08-12 - 结构化把小节标题计入连号 → 万唯听力虚成第7；同类去标题重排
    local = _structured_rank_excluding_headers(merged, entry, brand_terms)
    if local is not None:
        return local, True, category
    try:
        return float(entry["rank"]), True, category
    except (TypeError, ValueError):
        return None, True, category


def _structured_rankings_cache_key(raw_entries: list[Any] | None) -> tuple[Any, ...]:
    """榜单内容指纹：同请求内相同 JSON 只 normalize 一次。"""
    parts: list[tuple[str, Any, Any]] = []
    for item in raw_entries or []:
        if not isinstance(item, dict):
            continue
        name = str(
            item.get("name")
            or item.get("brandName")
            or item.get("brand_name")
            or item.get("title")
            or ""
        ).strip()
        parts.append((name, item.get("rank"), item.get("category") or item.get("type")))
    return tuple(parts)


def _raw_structured_ranks_collapsed(raw_entries: list[Any] | None) -> bool:
    """模力脏榜特征：多条显式位次且全部相同（常见全员第1）。"""
    ranks: list[float] = []
    for item in raw_entries or []:
        if not isinstance(item, dict):
            continue
        raw_rank = item.get("rank")
        if raw_rank is None:
            continue
        try:
            ranks.append(float(raw_rank))
        except (TypeError, ValueError):
            continue
    return len(ranks) >= 2 and len(set(ranks)) == 1


def _normalize_structured_rankings_cached(
    raw_entries: list[Any] | None,
    cache: dict[Any, list[dict[str, Any]]] | None,
) -> list[dict[str, Any]]:
    if not raw_entries:
        return []
    if cache is None:
        return normalize_structured_rankings(raw_entries)
    key = _structured_rankings_cache_key(raw_entries)
    hit = cache.get(key)
    if hit is not None:
        return hit
    merged = normalize_structured_rankings(raw_entries)
    cache[key] = merged
    return merged


def _should_reconcile_structured_rank(subtask: GeoMonitorSubtask) -> bool:
    """轻量路径是否必须扫结构化榜。

    - 无 mention_position：必须从榜单取位
    - 榜单同位次扎堆 / 位次=1：脏榜高发区，必须与出场序对账
    - 其余：信任已写入的 mention_position（日统计重建后应已纠正）
    """
    raw = subtask.all_rankings_json or []
    if subtask.mention_position is None:
        return True
    if _raw_structured_ranks_collapsed(raw):
        return True
    try:
        return abs(float(subtask.mention_position) - 1.0) < 1e-9
    except (TypeError, ValueError):
        return True


def _structured_reconcile_override_ok(
    stored_rank: int | float | None,
    list_rank: int | float | None,
) -> bool:
    """对账覆盖护栏：库内好名次被文末同名衍生品拉飞时拒绝覆盖。

    允许小幅纠偏（如脏全员第1→出场序第4）；拒绝 1→22 这类跃迁。
    """
    if stored_rank is None or list_rank is None:
        return False
    try:
        stored = float(stored_rank)
        listed = float(list_rank)
    except (TypeError, ValueError):
        return False
    if stored == listed:
        return False
    delta = abs(listed - stored)
    # 2026-07-27 - 万唯热力图 1+22+27→16.7 - 对账命中靠后产品名时拒覆盖
    if stored <= 3 and listed >= 10:
        return False
    if delta >= 5:
        return False
    return True


def _orm_attr_loaded(obj: Any, key: str) -> bool:
    """True if attribute is already in identity map; False means would lazy-load."""
    try:
        from sqlalchemy import inspect as sa_inspect

        insp = sa_inspect(obj)
        return key not in insp.unloaded
    except Exception:
        return True


def _stored_display_rank_source(subtask: GeoMonitorSubtask) -> tuple[str, dict[str, Any]]:
    """从 raw_result_json 推断 mention_position 的写入来源（读路径 provenance）。

    矩阵等轻量扫描未 load raw_result_json 时禁止触发懒加载（否则 N+1 可达数秒）。
    """
    if not _orm_attr_loaded(subtask, "raw_result_json"):
        return "stored", {}
    raw = getattr(subtask, "raw_result_json", None)
    raw = raw if isinstance(raw, dict) else {}
    if raw.get("source") == "manual_snapshot":
        return "manual", raw
    stored = raw.get("rank_resolution")
    if isinstance(stored, dict) and str(stored.get("source") or "").strip() == "llm":
        return "llm", raw
    return "stored", raw


def _read_display_brand_rank(
    subtask: GeoMonitorSubtask,
    monitor_keywords: str | None,
    brand_terms: list[str],
    asset: BrandAsset | None = None,
    *,
    allow_full_parse: bool = False,
    normalize_cache: dict[Any, list[dict[str, Any]]] | None = None,
) -> BrandRankResolution:
    """读路径展示位次：mention_position 为权威；缺失再 JSON；仅空位次时详情可全文解析。

    写路径（recompute_subtask_rank_from_answer）仍走 _resolve_brand_rank_detail，
    算完后写回 mention_position，不经过本函数。
    """
    # ponytail: 轻量扫描常不带 mention_context；未加载则跳过，勿 N+1
    if _orm_attr_loaded(subtask, "mention_context"):
        mention_text = _strip_html_for_match(getattr(subtask, "mention_context", None))
        has_brand_in_mention = _brand_appears_in_text(mention_text, brand_terms)
    else:
        has_brand_in_mention = False
    if prompt_monitor_intent(subtask.prompt) != "ranking":
        return BrandRankResolution(
            rank=None,
            mentioned=has_brand_in_mention or subtask.mention_position is not None,
            source="exposure",
            confidence=1.0,
        )

    # 2026-08-11 - 正文未提仍展示位次 - 已加载 answer 时非人工名次须正文含品牌
    answer_gate_ready = _answer_loaded_for_rank_gate(subtask)
    has_brand_in_answer = _brand_in_answer_for_rank(subtask, brand_terms) if answer_gate_ready else True

    if subtask.mention_position is not None:
        source, raw = _stored_display_rank_source(subtask)
        # 2026-07-28 - 手填名次绝对锁定 - 读路径禁止对账/全文改写
        if source == "manual" and raw.get("manual_rank_locked", True):
            return BrandRankResolution(
                rank=subtask.mention_position,
                mentioned=True,
                source="manual",
                confidence=1.0,
            )
        if answer_gate_ready and not has_brand_in_answer:
            return BrandRankResolution(
                rank=None,
                mentioned=False,
                source="none",
                confidence=0.95,
            )
        # 人工/LLM 锁定；已写入的自动名次与矩阵同读库值，脏数据靠 recompute 写回
        # 2026-08-12 - 详情勿在有 mention_position 时全文重算覆盖，否则展开 7→2
        stored = raw.get("rank_resolution") if isinstance(raw.get("rank_resolution"), dict) else {}
        confidence = 1.0 if source == "manual" else 0.9
        if source == "llm":
            try:
                confidence = float(stored.get("confidence", 0.9))
            except (TypeError, ValueError):
                confidence = 0.9
            confidence = max(0.0, min(1.0, confidence))
        # 轻量路径：仅在脏榜高发区与结构化榜对账，其余信任 mention_position
        # 2026-07-27 - 矩阵未 load raw 时对账会把补录第1改成文末第22 - raw 未加载则跳过对账
        if (
            source == "stored"
            and not allow_full_parse
            and _orm_attr_loaded(subtask, "raw_result_json")
            and _should_reconcile_structured_rank(subtask)
        ):
            rank_from_list, _, list_category = _find_brand_in_structured_rankings(
                subtask,
                brand_terms,
                asset,
                monitor_keywords=str(monitor_keywords or "").strip(),
                normalize_cache=normalize_cache,
            )
            if (
                rank_from_list is not None
                and _structured_reconcile_override_ok(
                    subtask.mention_position,
                    rank_from_list,
                )
            ):
                return BrandRankResolution(
                    rank=rank_from_list,
                    mentioned=True,
                    source="structured",
                    confidence=0.95,
                    category=list_category,
                    rank_basis="table",
                )
        return BrandRankResolution(
            rank=subtask.mention_position,
            mentioned=True,
            source=source,
            confidence=confidence,
            category=str(stored.get("category") or "").strip() or None,
            rank_basis=str(stored.get("rank_basis") or "").strip() or None,
            evidence=str(stored.get("evidence") or "").strip() or None,
        )

    if answer_gate_ready and not has_brand_in_answer:
        return BrandRankResolution(
            rank=None,
            mentioned=False,
            source="none",
            confidence=0.95,
        )

    monitor_keyword = str(monitor_keywords or "").strip()
    rank_from_list, in_ranking_list, list_category = _find_brand_in_structured_rankings(
        subtask,
        brand_terms,
        asset,
        monitor_keywords=monitor_keyword,
        normalize_cache=normalize_cache,
    )
    if rank_from_list is not None:
        return BrandRankResolution(
            rank=rank_from_list,
            mentioned=True,
            source="structured",
            confidence=0.95,
            category=list_category,
            rank_basis="table",
        )
    if in_ranking_list:
        return BrandRankResolution(
            rank=None,
            mentioned=True,
            source="structured",
            confidence=0.5,
        )

    if allow_full_parse:
        # mention_position 为空时才全文解析，避免与权威列打架
        return _resolve_brand_rank_detail(subtask, monitor_keywords, brand_terms, asset)

    return BrandRankResolution(
        rank=None,
        mentioned=has_brand_in_mention,
        source="none",
        confidence=0.9 if not has_brand_in_mention else 0.3,
    )


def _resolve_brand_rank_detail_matrix_light(
    subtask: GeoMonitorSubtask,
    monitor_keywords: str | None,
    brand_terms: list[str],
    asset: BrandAsset | None = None,
) -> BrandRankResolution:
    """矩阵单元格：权威列 + JSON，不触达 answer_content。"""
    return _read_display_brand_rank(
        subtask,
        monitor_keywords,
        brand_terms,
        asset,
        allow_full_parse=False,
    )


def kpi_rank_for_subtask(
    subtask: GeoMonitorSubtask,
    monitor_keywords: str | None,
    brand_terms: list[str],
    asset: BrandAsset | None = None,
) -> float | int | None:
    """日统计/摘要 KPI 用位次：与矩阵轻量读路径一致，纠正脏 mention_position。

    不走全文解析/LLM，避免聚合扫库时放大成本。
    """
    if prompt_monitor_intent(subtask.prompt) != "ranking":
        return subtask.mention_position
    detail = _read_display_brand_rank(
        subtask,
        monitor_keywords,
        brand_terms,
        asset,
        allow_full_parse=False,
    )
    if detail.rank is not None:
        return detail.rank
    return None


def _matrix_cell_rank(
    subtask: GeoMonitorSubtask,
    monitor_keywords: str | None,
    asset: BrandAsset | None,
    keyword_groups: list[dict[str, Any]] | None = None,
    *,
    ranking_terms: list[str] | None = None,
    normalize_cache: dict[Any, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    terms = ranking_terms if ranking_terms is not None else _ranking_match_terms(asset, keyword_groups)
    detail = _read_display_brand_rank(
        subtask,
        monitor_keywords,
        terms,
        asset,
        allow_full_parse=False,
        normalize_cache=normalize_cache,
    )
    return {
        "mention_position": detail.rank,
        "raw_mention_position": subtask.mention_position,
        "brand_mentioned": detail.mentioned,
        "monitor_keyword": monitor_keywords,
        "prompt_intent": prompt_monitor_intent(subtask.prompt),
        "rank_source": detail.source,
        "rank_confidence": detail.confidence,
        "rank_category": detail.category,
        "rank_basis": detail.rank_basis,
    }


def serialize_subtask_for_display(
    subtask: GeoMonitorSubtask,
    *,
    monitor_keywords: str | None = None,
    asset: BrandAsset | None = None,
    keyword_groups: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Serialize subtask with brand-aware rank for customer-facing views.

    2026-08-14 - 展示只读库内权威（allow_full_parse=False）；缺位次靠 ensure/补跑落库，
    禁止详情全文现算与矩阵轻量路径分叉。
    """
    data = serialize_subtask(subtask)
    ranking_terms = _ranking_match_terms(asset, keyword_groups)
    detail = _read_display_brand_rank(
        subtask,
        monitor_keywords,
        ranking_terms,
        asset,
        allow_full_parse=False,
    )
    data["raw_mention_position"] = subtask.mention_position
    data["brand_mentioned"] = detail.mentioned
    data["brand_rank"] = detail.rank
    data["mention_position"] = detail.rank
    data["prompt_intent"] = prompt_monitor_intent(subtask.prompt)
    data["rank_source"] = detail.source
    data["rank_confidence"] = detail.confidence
    data["rank_category"] = detail.category
    data["rank_basis"] = detail.rank_basis
    return data


def ranking_matrix(
    db: Session,
    current: CurrentSession,
    *,
    platform: str | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    keyword: str | None = None,
    monitor_group: str | None = None,
    keyword_group: str | None = None,
    monitor_keyword: str | None = None,
    exposure_term: str | None = None,
    limit_rows: int = 120,
    tenant_id: int | None = None,
) -> dict[str, Any]:
    """Build prompt × daily-average ranking matrix for realtime monitor view."""
    resolved_tenant_id = _resolve_matrix_tenant_id(current, tenant_id)
    if resolved_tenant_id is None:
        raise ValueError("排名矩阵仅支持客户侧查看，请使用企业账号登录")

    customer_like = (
        current.identity.identity_type == "CUSTOMER"
        or (current.identity.identity_type == "PLATFORM" and tenant_id is not None)
    )
    range_start, range_end = resolve_monitor_date_range(
        current, start_at, end_at, customer_like=customer_like,
    )

    asset = get_brand_asset(db, resolved_tenant_id)
    keyword_group_rows = list_keyword_groups(db, resolved_tenant_id)
    keyword_groups = [
        keyword_group_to_dict(item)
        for item in keyword_group_rows
        if item.status and item.monitor_keyword
    ] if keyword_group_rows else active_keyword_groups(db, resolved_tenant_id)
    purchased_platforms = tenant_purchased_platforms(db, resolved_tenant_id, asset) if asset else []
    # 2026-08-07 - 观察号矩阵列仅 kimi/元宝
    from app.services.observer_account import narrow_platform_codes, observer_platforms_for_session

    purchased_platforms = narrow_platform_codes(
        purchased_platforms,
        observer_platforms_for_session(current),
    )
    daily_sample_cap = int(getattr(asset, "schedule_frequency", 0) or 0) or None
    platform_filter = str(platform or "").strip()
    all_platforms = not platform_filter or platform_filter.lower() == "all"
    selected_platform = None if all_platforms else platform_filter
    allow = observer_platforms_for_session(current)
    if selected_platform and allow is not None and selected_platform not in allow:
        selected_platform = None
        all_platforms = True

    # 快路径：按 schedule_key 业务日取 task，避免 45 天宽窗扫 2000 条
    range_start_day = range_start.date()
    range_end_day = range_end.date()
    start_key, end_key_exclusive = _workspace_schedule_key_bounds(range_start_day, range_end_day)
    schedule_task_ids = [
        tid
        for tid in db.scalars(
            select(GeoMonitorScheduleRun.task_id).where(
                GeoMonitorScheduleRun.tenant_id == resolved_tenant_id,
                GeoMonitorScheduleRun.task_id.isnot(None),
                GeoMonitorScheduleRun.schedule_key >= start_key,
                GeoMonitorScheduleRun.schedule_key < end_key_exclusive,
            )
        )
        if tid
    ]
    schedule_task_ids = list(dict.fromkeys(schedule_task_ids))
    # 2026-08-11 - 多平台缺口各建 bft 时 schedule_run 只挂一个 task，豆包等补录被矩阵丢掉 - 并入窗内未挂日程的完成态 task
    matrix_task_ids = list(schedule_task_ids)
    if schedule_task_ids:
        matrix_task_ids = list(
            dict.fromkeys(
                [
                    *schedule_task_ids,
                    *_ranking_matrix_orphan_task_ids(
                        db,
                        tenant_id=resolved_tenant_id,
                        range_start=range_start,
                        range_end=range_end,
                        scheduled_task_ids=schedule_task_ids,
                        selected_platform=selected_platform,
                    ),
                ]
            )
        )

    light_cols = (
        GeoMonitorSubtask.subtask_id,
        GeoMonitorSubtask.task_id,
        GeoMonitorSubtask.platform,
        GeoMonitorSubtask.prompt,
        GeoMonitorSubtask.status,
        GeoMonitorSubtask.mention_position,
        GeoMonitorSubtask.all_rankings_json,
        GeoMonitorSubtask.sentiment,
        GeoMonitorSubtask.updated_at,
    )
    stmt = (
        select(GeoMonitorSubtask)
        .join(GeoMonitorTask, GeoMonitorTask.task_id == GeoMonitorSubtask.task_id)
        .where(
            GeoMonitorTask.deleted.is_(False),
            GeoMonitorTask.tenant_id == resolved_tenant_id,
            GeoMonitorTask.purpose == "geo",
            GeoMonitorSubtask.status.in_(("completed", "partial_completed")),
        )
        .order_by(GeoMonitorSubtask.updated_at.desc())
    )
    if matrix_task_ids:
        stmt = stmt.where(GeoMonitorSubtask.task_id.in_(matrix_task_ids))
    else:
        stmt = stmt.where(
            or_(
                GeoMonitorSubtask.updated_at >= range_start - timedelta(days=45),
                GeoMonitorTask.created_at >= range_start - timedelta(days=45),
            ),
        )
    if selected_platform:
        stmt = stmt.where(GeoMonitorSubtask.platform == selected_platform)

    # ponytail: 全平台×多词×多日轻松超 2000；截断会把冷门词变成「—」。有 schedule 范围时略放宽。
    fetch_limit = 3500 if matrix_task_ids else 2000
    if selected_platform:
        fetch_limit = min(fetch_limit, 2500)
    # 2026-07-30 - 1038 类风险 - ranking 矩阵 ORDER BY 勿带 JSON 宽列，id-first 再 hydrate
    ordered_ids = _ordered_subtask_ids(db, stmt.limit(fetch_limit))
    subtasks = _hydrate_subtasks_in_id_order(
        db,
        ordered_ids,
        joinedload(GeoMonitorSubtask.task).load_only(
            GeoMonitorTask.monitor_keywords,
            GeoMonitorTask.created_at,
        ),
        load_only(*light_cols),
    )
    legacy_group_filter = str(monitor_group or keyword or "").strip()
    scoped_group = str(keyword_group or "").strip()
    scoped_monitor = str(monitor_keyword or "").strip()
    scoped_exposure = str(exposure_term or "").strip()
    if scoped_group or scoped_monitor or scoped_exposure:
        subtasks = _filter_subtasks_by_scope(
            subtasks,
            keyword_group=scoped_group or None,
            monitor_keyword=scoped_monitor or None,
            exposure_term=scoped_exposure or None,
            keyword_groups=keyword_groups,
            asset=asset,
        )
    elif legacy_group_filter:
        subtasks = _filter_subtasks_by_monitor_group(subtasks, legacy_group_filter, keyword_groups)

    if not all_platforms and subtasks:
        selected_platform = subtasks[0].platform

    task_ids = list({item.task_id for item in subtasks if item.task_id})
    schedule_runs_map = schedule_runs_for_tasks(db, task_ids)
    lead_runs_map = lead_diagnosis_runs_for_tasks(db, task_ids)

    prompt_set: dict[str, str | None] = {}
    task_rows: dict[str, dict[str, Any]] = {}
    # ponytail: 词表每格不变，提到循环外；normalize 结果按榜单指纹缓存
    ranking_terms = _ranking_match_terms(asset, keyword_groups)
    normalize_cache: dict[Any, list[dict[str, Any]]] = {}

    for item in subtasks:
        prompt = (item.prompt or "").strip()
        task_id = (item.task_id or "").strip()
        if not prompt or not task_id or item.task is None:
            continue
        if prompt_monitor_intent(prompt) != "ranking":
            continue
        schedule_ctx = _resolve_subtask_schedule_context(
            item.task,
            schedule_runs_map,
            asset,
            lead_runs_map,
        )
        detect_dt = _subtask_detect_datetime(item, item.task, schedule_ctx)
        if detect_dt is None:
            continue
        if detect_dt < range_start or detect_dt > range_end:
            continue
        if not matrix_platform_visible(item.platform, purchased_platforms):
            continue
        day_key = detect_dt.date().isoformat()
        keyword_group = (
            _resolve_display_keyword_group(
                item.task,
                schedule_runs_map.get(task_id),
                keyword_group_rows,
            )
            or _prompt_group_name(prompt, keyword_group_rows)
            or schedule_ctx.get("keyword_group")
        )
        prompt_set.setdefault(prompt, _prompt_group_name(prompt, keyword_group_rows))
        row_key = _matrix_row_key(
            day_key,
            item.platform,
            all_platforms=all_platforms,
            keyword_group=keyword_group,
        )
        bucket = task_rows.setdefault(row_key, {
            "day_key": day_key,
            "task_id": task_id,
            "platform": item.platform if all_platforms else None,
            "keyword_group": keyword_group,
            "latest_at": None,
            "cell_samples": {},
        })
        if item.updated_at and (
            bucket["latest_at"] is None or item.updated_at > bucket["latest_at"]
        ):
            bucket["latest_at"] = item.updated_at
            bucket["task_id"] = task_id
        monitor_keywords = item.task.monitor_keywords if item.task else None
        rank_payload = _matrix_cell_rank(
            item,
            monitor_keywords,
            asset,
            keyword_groups,
            ranking_terms=ranking_terms,
            normalize_cache=normalize_cache,
        )
        cell = {
            "subtask_id": item.subtask_id,
            "task_id": task_id,
            "schedule_window_key": schedule_ctx.get("schedule_window_key"),
            "schedule_label": schedule_ctx.get("schedule_label"),
            "schedule_source": schedule_ctx.get("schedule_source"),
            "status": item.status,
            "page_screenshot": None,
            "sentiment": item.sentiment,
            "updated_at": item.updated_at.isoformat() if item.updated_at else None,
            **rank_payload,
            "_updated_at": item.updated_at,
        }
        bucket["cell_samples"].setdefault(prompt, []).append(cell)

    sorted_tasks = sorted(
        task_rows.values(),
        key=lambda row: ranking_matrix_row_sort_key(
            day_key=row.get("day_key"),
            keyword_group=row.get("keyword_group"),
            platform=row.get("platform"),
        ),
        reverse=True,
    )
    row_limit = _ranking_matrix_row_limit(
        requested_limit=limit_rows,
        range_start_day=range_start_day,
        range_end_day=range_end_day,
        all_platforms=all_platforms,
        purchased_platforms=purchased_platforms,
        keyword_group_count=len(keyword_groups),
    )
    sorted_tasks = sorted_tasks[:row_limit]
    rows = []
    for bucket in sorted_tasks:
        day_key = bucket.get("day_key") or ""
        cells = {
            prompt: _finalize_matrix_cell(
                _dedupe_matrix_cell_samples(samples, max_samples=daily_sample_cap)
            )
            for prompt, samples in (bucket.get("cell_samples") or {}).items()
        }
        round_count = _matrix_row_schedule_round_count(cells)
        rows.append({
            "task_id": bucket["task_id"],
            "platform": bucket.get("platform"),
            "day_key": day_key,
            "schedule_key": None,
            "schedule_window_key": day_key,
            "schedule_label": _matrix_day_label(day_key, round_count),
            "schedule_source": "daily_avg",
            "keyword_group": bucket.get("keyword_group"),
            "snapshot_at": day_key,
            "sample_count": round_count,
            "cells": cells,
        })

    columns = _build_matrix_columns(
        keyword_group_rows,
        prompt_set,
        rows,
        platform=selected_platform,
        asset=asset,
    )
    columns = _filter_matrix_columns_for_scope(
        columns,
        prompt_set,
        keyword_group=scoped_group or None,
        monitor_keyword=scoped_monitor or None,
        exposure_term=scoped_exposure or None,
    )

    group_map: dict[str, list[str]] = {}
    for column in columns:
        group_name = column["group_name"] or "其他监测问题"
        group_map.setdefault(group_name, []).append(column["prompt"])
    prompt_groups = [{"name": name, "prompts": prompts} for name, prompts in group_map.items()]

    schedule_round_count = len({row.get("day_key") for row in rows if row.get("day_key")})

    return {
        "platform": selected_platform,
        "all_platforms": all_platforms,
        "brand_name": asset.brand_name if asset else None,
        "start_at": range_start.isoformat(),
        "end_at": range_end.isoformat(),
        "display_period": "through_yesterday" if customer_like else "custom",
        "columns": columns,
        "rows": rows,
        "schedule_round_count": schedule_round_count,
        "task_count": len(rows),
        "schedule_plan": schedule_plan_summary(asset),
        "prompt_groups": prompt_groups,
        "keyword_group_options": [
            option
            for group in keyword_groups
            if (option := _keyword_group_option(group))
        ],
        "exposure_term_options": collect_exposure_term_options(keyword_groups, asset=asset),
        "purchased_platforms": purchased_platforms,
    }


SENTIMENT_LABEL_MAP = {
    "positive": "正面",
    "neutral": "中性",
    "negative": "负面",
    "正向": "正面",
    "中立": "中性",
    "负向": "负面",
    "正面": "正面",
    "中性": "中性",
    "负面": "负面",
}


def _normalize_sentiment_label(raw: str | None) -> str:
    text = str(raw or "").strip()
    if not text:
        return "未知"
    lowered = text.lower()
    if lowered in SENTIMENT_LABEL_MAP:
        return SENTIMENT_LABEL_MAP[lowered]
    if text in SENTIMENT_LABEL_MAP:
        return SENTIMENT_LABEL_MAP[text]
    return "未知"


def _answer_excerpt(content: str | None, limit: int = 120) -> str:
    text = _strip_html_for_match(content)
    if len(text) <= limit:
        return text
    return f"{text[:limit]}…"


def _top3_rate_from_ranking_rows(ranking_rows: list[dict[str, Any]]) -> float:
    ranking_total = len(ranking_rows)
    if not ranking_total:
        return 0.0
    top3 = sum(
        1
        for row in ranking_rows
        if row.get("brand_rank") is not None and float(row["brand_rank"]) <= 3
    )
    return round(top3 / ranking_total * 100, 1)


def customer_subtask_visible(
    subtask: GeoMonitorSubtask,
    now: datetime | None = None,
    *,
    task: GeoMonitorTask | None = None,
    schedule_ctx: dict[str, Any] | None = None,
) -> bool:
    """客户侧是否可见：只认监测业务日 ≤ 昨日。禁止用 updated_at（补录会把库时间刷到今天）。"""
    cutoff = customer_display_cutoff(now)
    if task is None:
        return bool(subtask.updated_at and subtask.updated_at <= cutoff)
    detect_dt = _subtask_detect_datetime(subtask, task, schedule_ctx)
    if detect_dt is not None:
        return detect_dt <= cutoff
    # ponytail: 无业务日上下文时才回退 updated_at；有业务日绝不用改库时间当闸门。
    return bool(subtask.updated_at and subtask.updated_at <= cutoff)


def invalidate_monitor_summary_cache(
    tenant_id: int | None = None,
    *,
    bust_overview: bool = False,
) -> None:
    """补录/同步后清理监测摘要与运营总览缓存，避免仍读旧数据。

    默认不打掉运营总览（任务同步很频繁）；补录/品牌变更请显式 bust_overview=True。
    """
    from app.core.read_cache import invalidate_dashboard_caches

    invalidate_dashboard_caches(tenant_id, bust_overview=bust_overview)


def filter_subtasks_for_customer(
    subtasks: list[GeoMonitorSubtask],
    now: datetime | None = None,
    *,
    task: GeoMonitorTask | None = None,
    db: Session | None = None,
) -> list[GeoMonitorSubtask]:
    schedule_ctx: dict[str, Any] | None = None
    if task is not None and db is not None:
        schedule_runs_map = schedule_runs_for_tasks(db, [task.task_id])
        lead_runs_map = lead_diagnosis_runs_for_tasks(db, [task.task_id])
        asset = get_brand_asset(db, task.tenant_id) if task.tenant_id else None
        schedule_ctx = _resolve_subtask_schedule_context(task, schedule_runs_map, asset, lead_runs_map)
    return [
        item
        for item in subtasks
        if customer_subtask_visible(
            item,
            now,
            task=task or getattr(item, "task", None),
            schedule_ctx=schedule_ctx,
        )
    ]


def _workspace_visible_day_keys(
    daily_ranking: dict[str, list[dict[str, Any]]],
    daily_exposure: dict[str, list[dict[str, Any]]],
    *,
    cutoff: datetime,
) -> list[str]:
    cutoff_day = cutoff.date().isoformat()
    keys = set(daily_ranking) | set(daily_exposure)
    return sorted(key for key in keys if key <= cutoff_day)


def _workspace_day_label(day_key: str) -> str:
    try:
        return datetime.strptime(day_key, "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError:
        return day_key


def _round_metrics_from_rows(
    ranking_rows: list[dict[str, Any]],
    exposure_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    ranking_total = len(ranking_rows)
    ranking_mentioned = sum(1 for row in ranking_rows if row.get("brand_mentioned"))
    rank_values = [float(row["brand_rank"]) for row in ranking_rows if row.get("brand_rank") is not None]
    exposure_recognized = [row for row in exposure_rows if row.get("sentiment") in ("正面", "中性", "负面")]
    negative_count = sum(1 for row in exposure_rows if row.get("sentiment") == "负面")
    return {
        "ranking_sample_count": ranking_total,
        "mentioned_count": ranking_mentioned,
        "brand_mention_rate": round(ranking_mentioned / ranking_total * 100, 1) if ranking_total else 0.0,
        "avg_brand_rank": round(sum(rank_values) / len(rank_values), 1) if rank_values else None,
        "top3_rate": _top3_rate_from_ranking_rows(ranking_rows),
        "exposure_sample_count": len(exposure_rows),
        "negative_count": negative_count,
        "negative_rate": round(negative_count / len(exposure_recognized) * 100, 1) if exposure_recognized else 0.0,
    }


def _platform_stats_from_ranking_rows(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    bucket: dict[str, dict[str, Any]] = {}
    for row in rows:
        code = str(row.get("platform") or "").strip()
        if not code:
            continue
        pb = bucket.setdefault(
            code,
            {"total": 0, "mentioned": 0, "rank_total": 0.0, "rank_count": 0},
        )
        pb["total"] += 1
        if row.get("brand_mentioned"):
            pb["mentioned"] += 1
        if row.get("brand_rank") is not None:
            pb["rank_total"] += float(row["brand_rank"])
            pb["rank_count"] += 1
    return bucket


def _platform_highlight_entry(
    code: str,
    stats: dict[str, Any] | None,
    previous_stats: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if stats is None or stats.get("total", 0) == 0:
        return {
            "platform": code,
            "mention_rate": 0.0,
            "avg_rank": None,
            "sample_count": 0,
            "mention_rate_delta": None,
            "avg_rank_delta": None,
        }
    total = stats["total"] or 1
    mention_rate = round(stats["mentioned"] / total * 100, 1)
    avg_rank = round(stats["rank_total"] / stats["rank_count"], 1) if stats["rank_count"] else None
    mention_rate_delta = None
    avg_rank_delta = None
    if previous_stats and previous_stats.get("total", 0) > 0:
        prev_total = previous_stats["total"]
        prev_mention_rate = round(previous_stats["mentioned"] / prev_total * 100, 1)
        mention_rate_delta = round(mention_rate - prev_mention_rate, 1)
        prev_avg_rank = (
            round(previous_stats["rank_total"] / previous_stats["rank_count"], 1)
            if previous_stats["rank_count"]
            else None
        )
        if avg_rank is not None and prev_avg_rank is not None:
            avg_rank_delta = round(avg_rank - prev_avg_rank, 1)
    return {
        "platform": code,
        "mention_rate": mention_rate,
        "avg_rank": avg_rank,
        "sample_count": stats["total"],
        "mention_rate_delta": mention_rate_delta,
        "avg_rank_delta": avg_rank_delta,
    }


def _build_workspace_kpi_trends(
    daily_ranking: dict[str, list[dict[str, Any]]],
    daily_exposure: dict[str, list[dict[str, Any]]],
    range_start: datetime,
    range_end: datetime,
) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    cursor = range_start.date()
    end = range_end.date()
    while cursor <= end:
        day_key = cursor.isoformat()
        metrics = _round_metrics_from_rows(
            daily_ranking.get(day_key, []),
            daily_exposure.get(day_key, []),
        )
        points.append({
            "label": cursor.strftime("%m-%d"),
            "mention_rate": metrics["brand_mention_rate"],
            "avg_brand_rank": metrics["avg_brand_rank"],
            "top3_rate": metrics["top3_rate"],
            "negative_count": metrics["negative_count"],
        })
        cursor += timedelta(days=1)
    return points


def compute_workspace_health_score(
    *,
    brand_mention_rate: float,
    top3_rate: float,
    avg_brand_rank: float | None,
    competitor_count: int = 0,
    competitor_score: int | None = None,
) -> dict[str, int | None]:
    """客户工作台健康分：默认可见度 60% + 排名 40%；配置竞品时纳入竞品优势 20%。"""
    visibility = round(float(brand_mention_rate or 0) * 0.6 + float(top3_rate or 0) * 0.4)
    rank_score: int | None = None
    if avg_brand_rank is not None:
        rank_score = round(max(0.0, min(100.0, 100.0 - (float(avg_brand_rank) - 1.0) * 20.0)))

    use_competitor = competitor_count > 0 and competitor_score is not None
    if use_competitor:
        if rank_score is not None:
            health_score = round(visibility * 0.5 + rank_score * 0.3 + competitor_score * 0.2)
        else:
            health_score = round(visibility * 0.65 + competitor_score * 0.35)
    elif rank_score is not None:
        health_score = round(visibility * 0.6 + rank_score * 0.4)
    else:
        health_score = visibility

    return {
        "health_score": health_score,
        "visibility_score": visibility,
        "rank_score": rank_score,
        "competitor_score": competitor_score if use_competitor else None,
    }


def _workspace_competitor_score(
    db: Session,
    current: CurrentSession,
    tenant_id: int,
    competitor_count: int,
) -> dict[str, float | int | None]:
    """较竞品维度：品牌露出率相对最强竞品的领先幅度映射为 0–100 分。"""
    if competitor_count <= 0:
        return {
            "competitor_score": None,
            "top_competitor_mention_rate": None,
            "competitor_lead_delta": None,
        }
    from app.services.competitor_analytics_service import build_competitor_compare_summary

    summary = build_competitor_compare_summary(
        db, current, tenant_id=tenant_id, days=7, subtask_limit=150,
    )
    if int(summary.get("sample_total") or 0) <= 0:
        return {
            "competitor_score": None,
            "top_competitor_mention_rate": None,
            "competitor_lead_delta": None,
        }
    brand_row = next((row for row in summary.get("rows", []) if row.get("is_brand")), None)
    comp_rows = [row for row in summary.get("rows", []) if not row.get("is_brand")]
    if brand_row is None or not comp_rows:
        return {
            "competitor_score": None,
            "top_competitor_mention_rate": None,
            "competitor_lead_delta": None,
        }
    brand_rate = float(brand_row.get("mention_rate") or 0)
    top_comp_rate = max(float(row.get("mention_rate") or 0) for row in comp_rows)
    lead_delta = round(brand_rate - top_comp_rate, 1)
    return {
        "competitor_score": round(max(0.0, min(100.0, 50.0 + lead_delta))),
        "top_competitor_mention_rate": top_comp_rate,
        "competitor_lead_delta": lead_delta,
    }


def _resolve_workspace_brief_tenant_id(current: CurrentSession, tenant_id: int | None) -> int:
    if current.identity.identity_type == "CUSTOMER":
        if current.identity.tenant_id is None:
            raise ValueError("运营工作台简报仅支持客户企业账号")
        return current.identity.tenant_id
    if current.identity.identity_type == "PLATFORM":
        if tenant_id is None:
            raise ValueError("平台端预览客户工作台需指定企业")
        return tenant_id
    raise ValueError("运营工作台简报仅支持客户企业账号或平台预览")


def _tenant_service_period_fields(db: Session, tenant_id: int) -> dict[str, str | None]:
    tenant = db.scalar(select(Tenant).where(Tenant.id == tenant_id, Tenant.deleted.is_(False)))
    return {
        "service_start_date": tenant.service_start_date.isoformat() if tenant and tenant.service_start_date else None,
        "service_end_date": tenant.service_end_date.isoformat() if tenant and tenant.service_end_date else None,
    }


def _workspace_brief_from_daily_stats(
    db: Session,
    *,
    tenant_id: int,
    asset,
    keyword_groups: list,
    keyword_group_rows: list | None = None,
    purchased_platforms: list[str],
    trend_start: datetime,
    trend_end: datetime,
    range_end: datetime,
) -> dict[str, Any]:
    """ponytail: 日统计快路径 + 词热度/词×平台轻量聚合；不含快照/信源。"""
    from app.services.monitor_stats_service import (
        filter_daily_stat_rows_by_platforms,
        list_daily_stats_for_tenant,
        platform_bucket_from_stat_rows,
        workspace_kpi_trends_from_stats,
        workspace_metrics_from_stat_rows,
    )

    daily_stat_by_day: dict[str, list] = {}
    for row in filter_daily_stat_rows_by_platforms(
        list_daily_stats_for_tenant(
            db,
            tenant_id,
            since=trend_start.date(),
            until=range_end.date(),
        ),
        # 2026-08-07 - 本期结论/趋势按 purchased（观察号已收窄为 kimi/元宝）重算
        purchased_platforms,
    ):
        daily_stat_by_day.setdefault(row.stat_date.isoformat(), []).append(row)

    visible_days = sorted(
        day
        for day, rows in daily_stat_by_day.items()
        if date.fromisoformat(day) <= range_end.date()
        and sum(int(item.completed_count or 0) for item in rows) > 0
    )
    latest_day = visible_days[-1] if visible_days else None
    previous_day = visible_days[-2] if len(visible_days) >= 2 else None

    period_end_day = min(trend_end.date(), range_end.date())
    period_rows: list = []
    for day_key, rows in daily_stat_by_day.items():
        day = date.fromisoformat(day_key)
        if trend_start.date() <= day <= period_end_day:
            period_rows.extend(rows)
    # 多日筛选：KPI/平台露出用区间汇总；单日仍等同最新监测日
    period_metrics = workspace_metrics_from_stat_rows(period_rows)
    display_metrics = workspace_metrics_from_stat_rows(daily_stat_by_day.get(latest_day or "", []))
    kpi_metrics = period_metrics if (trend_end.date() - trend_start.date()).days > 0 else display_metrics
    round_comparison: dict[str, Any] = {
        "has_previous": False,
        "latest_schedule_label": None,
        "previous_schedule_label": None,
        "avg_brand_rank_delta": None,
        "mention_rate_delta": None,
        "top3_rate_delta": None,
        "negative_count_delta": None,
    }
    latest_schedule = None
    previous_schedule = None

    if latest_day:
        latest_label = _workspace_day_label(latest_day)
        latest_schedule = {
            "schedule_window_key": latest_day,
            "schedule_label": f"{latest_label} 监测",
            "completed_subtasks": int(display_metrics["ranking_sample_count"] or 0),
            "total_subtasks": int(display_metrics["ranking_sample_count"] or 0),
        }
        round_comparison["latest_schedule_label"] = latest_schedule["schedule_label"]
        if previous_day:
            previous_metrics = workspace_metrics_from_stat_rows(daily_stat_by_day[previous_day])
            previous_schedule = {
                "schedule_window_key": previous_day,
                "schedule_label": f"{_workspace_day_label(previous_day)} 监测",
                "completed_subtasks": int(previous_metrics["ranking_sample_count"] or 0),
                "total_subtasks": int(previous_metrics["ranking_sample_count"] or 0),
            }
            round_comparison["has_previous"] = True
            round_comparison["previous_schedule_label"] = previous_schedule["schedule_label"]
            if display_metrics["avg_brand_rank"] is not None and previous_metrics["avg_brand_rank"] is not None:
                round_comparison["avg_brand_rank_delta"] = round(
                    float(display_metrics["avg_brand_rank"]) - float(previous_metrics["avg_brand_rank"]),
                    1,
                )
            round_comparison["mention_rate_delta"] = round(
                float(display_metrics["brand_mention_rate"]) - float(previous_metrics["brand_mention_rate"]),
                1,
            )
            round_comparison["top3_rate_delta"] = round(
                float(display_metrics["top3_rate"]) - float(previous_metrics["top3_rate"]),
                1,
            )

    period_platform_stats = platform_bucket_from_stat_rows(period_rows) if period_rows else {}
    latest_platform_stats = (
        platform_bucket_from_stat_rows(daily_stat_by_day[latest_day])
        if latest_day
        else {}
    )
    previous_platform_stats = (
        platform_bucket_from_stat_rows(daily_stat_by_day[previous_day])
        if previous_day
        else {}
    )
    platform_stats_for_ui = period_platform_stats or latest_platform_stats
    platform_highlights = [
        _platform_highlight_entry(
            code,
            platform_stats_for_ui.get(code),
            previous_platform_stats.get(code) if round_comparison.get("has_previous") else None,
        )
        for code in purchased_platforms
    ]
    kpi_trends = workspace_kpi_trends_from_stats(
        db,
        tenant_id,
        trend_start,
        trend_end,
        platforms=purchased_platforms,
    )

    plan = schedule_plan_summary(asset)
    schedule_times = plan.get("schedule_times") or []
    next_schedule_hint = f"每日 {('、'.join(schedule_times))}" if schedule_times else plan.get("schedule_type_label")

    light = _workspace_keyword_platform_light(
        db,
        tenant_id=tenant_id,
        keyword_group_rows=list(keyword_group_rows or []),
        keyword_groups=keyword_groups,
        purchased_platforms=purchased_platforms,
        trend_start=trend_start,
        trend_end=trend_end,
        range_end=range_end,
    )

    return {
        "tenant_id": tenant_id,
        "brand_name": asset.brand_name if asset else None,
        "company_name": asset.company_full_name if asset else None,
        "start_at": trend_start.isoformat(),
        "end_at": range_end.isoformat(),
        "trend_start_at": trend_start.isoformat(),
        "trend_end_at": trend_end.isoformat(),
        "display_period": "through_yesterday",
        "display_day": latest_day,
        "platform_period_label": (
            f"{trend_start.date().isoformat()} ~ {period_end_day.isoformat()}"
            if (trend_end.date() - trend_start.date()).days > 0
            else (f"最新监测日 {latest_day}" if latest_day else None)
        ),
        "latest_schedule": latest_schedule,
        "previous_schedule": previous_schedule,
        "round_comparison": round_comparison,
        "kpi_trends": kpi_trends,
        "next_schedule_hint": next_schedule_hint,
        "schedule_plan": plan,
        "kpis": {
            "ranking_sample_count": kpi_metrics["ranking_sample_count"],
            # 2026-08-13 - 本期结论展示提及 N/M，与竞品页同源分子
            "mentioned_count": int(kpi_metrics.get("mentioned_count") or 0),
            "brand_mention_rate": kpi_metrics["brand_mention_rate"],
            "avg_brand_rank": kpi_metrics["avg_brand_rank"],
            "top3_rate": kpi_metrics["top3_rate"],
            "exposure_sample_count": 0,
            "negative_count": 0,
            "negative_rate": 0.0,
            "source_count": 0,
            "keyword_group_count": len(keyword_groups),
            "competitor_count": len(list_competitors(db, tenant_id)),
        },
        "purchased_platforms": purchased_platforms,
        "platform_highlights": platform_highlights,
        "top_sources": [],
        "recent_snapshots": [],
        "alerts": [],
        "keyword_heats": light["keyword_heats"],
        "keyword_platform_heatmap": light["keyword_platform_heatmap"],
        **_tenant_service_period_fields(db, tenant_id),
    }


def _workspace_monitor_keyword_labels(keyword_groups: list) -> list[str]:
    """Chip / 热力图行标签：展开各组全部监测词（与前端 brand 口径一致）。

    不截断：词多时由前端按行高自适应 + wrap 滚动展示。
    """
    labels: list[str] = []
    seen: set[str] = set()
    for group in keyword_groups:
        for token in keyword_group_monitor_keywords(group):
            primary = str(token or "").strip()
            if primary and primary not in seen:
                seen.add(primary)
                labels.append(primary)
    return labels


def _workspace_match_monitor_keyword(
    prompt: str,
    keyword_group_rows: list,
    keyword_labels: list[str],
) -> str | None:
    """归到具体监测词，禁止整组塌缩到主词（多词一组时否则只剩一个有热度）。"""
    text = (prompt or "").strip()
    if not text or not keyword_labels:
        return None
    label_set = set(keyword_labels)
    if keyword_group_rows:
        resolved = _resolve_prompt_monitor_keyword(text, keyword_group_rows)
        if resolved and resolved in label_set:
            return resolved
    best: str | None = None
    best_score = -1
    for label in keyword_labels:
        score = _prompt_keyword_match_score(text, label)
        if score > best_score or (score == best_score and best is not None and len(label) > len(best)):
            best_score = score
            best = label
    return best if best_score >= 0 else None


def _workspace_period_day_bounds(
    trend_start: datetime,
    trend_end: datetime,
    range_end: datetime,
) -> tuple[date, date]:
    period_end = min(trend_end.date(), range_end.date())
    period_start = trend_start.date()
    if period_start > period_end:
        period_start = period_end
    return period_start, period_end


def _snapshot_recency_key(item: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(item.get("detect_day") or ""),
        str(item.get("updated_at") or ""),
        str(item.get("subtask_id") or ""),
    )


def _diversify_snapshots_by_detect_day(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按检测日轮询取样，避免 limit/首页被最新一两天塞满。"""
    if len(rows) <= 1:
        return list(rows)
    by_day: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        day = str(row.get("detect_day") or "")
        by_day.setdefault(day, []).append(row)
    for day_rows in by_day.values():
        day_rows.sort(key=_snapshot_recency_key, reverse=True)
    days_sorted = sorted(by_day.keys(), reverse=True)
    cursors = {day: 0 for day in days_sorted}
    out: list[dict[str, Any]] = []
    while True:
        progressed = False
        for day in days_sorted:
            idx = cursors[day]
            bucket = by_day[day]
            if idx < len(bucket):
                out.append(bucket[idx])
                cursors[day] = idx + 1
                progressed = True
        if not progressed:
            break
    return out


def _workspace_period_snapshot_pool(
    snapshot_candidates: list[dict[str, Any]],
    *,
    trend_start: datetime,
    trend_end: datetime,
    range_end: datetime,
    rank_scope: str = "prefer_ranked",
    diversify_days: bool = False,
) -> list[dict[str, Any]]:
    """周期内完整样本池（未截断）。"""
    period_start, period_end = _workspace_period_day_bounds(trend_start, trend_end, range_end)
    in_period: list[dict[str, Any]] = []
    for item in snapshot_candidates:
        day_raw = item.get("detect_day")
        if not day_raw:
            continue
        try:
            day = date.fromisoformat(str(day_raw)[:10])
        except ValueError:
            continue
        if period_start <= day <= period_end:
            in_period.append(item)
    if not in_period:
        return []

    scope = str(rank_scope or "prefer_ranked").strip().lower()
    if scope == "ranked":
        pool = [row for row in in_period if row.get("brand_rank") is not None]
        pool.sort(key=_snapshot_recency_key, reverse=True)
    elif scope == "all":
        pool = list(in_period)
        pool.sort(key=_snapshot_recency_key, reverse=True)
    else:
        # prefer_ranked（默认）
        ranked = [row for row in in_period if row.get("brand_rank") is not None]
        unranked = [row for row in in_period if row.get("brand_rank") is None]
        ranked.sort(key=_snapshot_recency_key, reverse=True)
        unranked.sort(key=_snapshot_recency_key, reverse=True)
        pool = ranked + unranked

    if diversify_days:
        return _diversify_snapshots_by_detect_day(pool)
    return pool


def _workspace_period_snapshots(
    snapshot_candidates: list[dict[str, Any]],
    *,
    trend_start: datetime,
    trend_end: datetime,
    range_end: datetime,
    limit: int = 24,
    rank_scope: str = "prefer_ranked",
) -> list[dict[str, Any]]:
    """收录明细按数据周期取样本，禁止只钉死 latest_day（否则切周期列表不变）。

    rank_scope:
    - prefer_ranked：有位次优先再补未提及（工作台样本默认）
    - ranked：只要有位次
    - all：有无位次都按时间倒序，供「全部」切换真正能看到未提及
    """
    pool = _workspace_period_snapshot_pool(
        snapshot_candidates,
        trend_start=trend_start,
        trend_end=trend_end,
        range_end=range_end,
        rank_scope=rank_scope,
        diversify_days=False,
    )
    if str(rank_scope or "").strip().lower() == "prefer_ranked":
        # 保持旧行为：先排满有位次，再补未提及到 limit
        ranked = [row for row in pool if row.get("brand_rank") is not None]
        unranked = [row for row in pool if row.get("brand_rank") is None]
        out = ranked[:limit]
        if len(out) < limit:
            out.extend(unranked[: limit - len(out)])
        return out
    return pool[:limit]


def _inclusion_snapshot_has_display_rank(row: dict[str, Any]) -> bool:
    """收录明细「有位次」= UI 展示「第 N 位」，须 hydration 后 brand_rank 非空。"""
    return row.get("brand_rank") is not None


_INCLUSION_HYDRATE_BATCH = 25


def _hydrate_inclusion_light_batch(
    db: Session,
    page_light: list[dict[str, Any]],
    *,
    asset,
    keyword_groups: list[dict[str, Any]],
    match_terms: list[str],
) -> list[dict[str, Any]]:
    if not page_light:
        return []
    page_pks = [int(item["_pk"]) for item in page_light if item.get("_pk") is not None]
    subtasks = _hydrate_subtasks_in_id_order(
        db,
        page_pks,
        joinedload(GeoMonitorSubtask.task).load_only(
            GeoMonitorTask.monitor_keywords,
            GeoMonitorTask.created_at,
            GeoMonitorTask.total_items,
            GeoMonitorTask.completed_items,
        ),
        load_only(
            GeoMonitorSubtask.subtask_id,
            GeoMonitorSubtask.task_id,
            GeoMonitorSubtask.platform,
            GeoMonitorSubtask.prompt,
            GeoMonitorSubtask.status,
            GeoMonitorSubtask.mention_context,
            GeoMonitorSubtask.page_screenshot,
            GeoMonitorSubtask.reference_list_json,
            GeoMonitorSubtask.mention_position,
            GeoMonitorSubtask.all_rankings_json,
            GeoMonitorSubtask.sentiment,
            GeoMonitorSubtask.updated_at,
        ),
    )
    by_pk = {item.id: item for item in subtasks}
    recent_snapshots: list[dict[str, Any]] = []
    for light in page_light:
        item = by_pk.get(int(light["_pk"]))
        if item is None or item.task is None:
            row = {k: v for k, v in light.items() if k != "_pk"}
            row.setdefault("sentiment", None)
            row.setdefault("answer_excerpt", None)
            row.setdefault("page_screenshot", None)
            row.setdefault("source_articles", [])
            recent_snapshots.append(row)
            continue
        monitor_keywords = item.task.monitor_keywords
        brand_rank, brand_mentioned = _resolve_brand_rank(
            item,
            monitor_keywords,
            match_terms,
            asset,
        )
        recent_snapshots.append({
            "subtask_id": item.subtask_id,
            "task_id": item.task_id,
            "platform": item.platform,
            "prompt": item.prompt,
            "keyword_group": light.get("keyword_group"),
            "monitor_keyword": light.get("monitor_keyword"),
            "schedule_label": light.get("schedule_label"),
            "schedule_window_key": light.get("schedule_window_key"),
            "detect_day": light.get("detect_day"),
            "prompt_intent": light.get("prompt_intent") or prompt_monitor_intent(item.prompt),
            "brand_rank": brand_rank,
            "brand_mentioned": brand_mentioned,
            "sentiment": _normalize_sentiment_label(item.sentiment),
            "answer_excerpt": _answer_excerpt(item.mention_context, 100),
            "page_screenshot": public_screenshot_url(item.page_screenshot),
            "source_articles": _snapshot_source_articles(item),
            "updated_at": item.updated_at.isoformat() if item.updated_at else None,
        })
    return recent_snapshots


def _filter_inclusion_snapshots_by_keyword(
    rows: list[dict[str, Any]],
    keyword: str | None,
) -> list[dict[str, Any]]:
    query = str(keyword or "").strip().lower()
    if not query:
        return rows
    out: list[dict[str, Any]] = []
    for row in rows:
        haystack = " ".join(
            str(row.get(key) or "")
            for key in ("monitor_keyword", "prompt", "keyword_group", "platform")
        ).lower()
        articles = row.get("source_articles") or []
        if isinstance(articles, list):
            for article in articles[:3]:
                if not isinstance(article, dict):
                    continue
                haystack += f" {article.get('title') or ''} {article.get('domain') or ''}"
        if query in haystack.lower():
            out.append(row)
    return out


def _inclusion_scan_columns(*, with_refs: bool) -> list[Any]:
    cols: list[Any] = [
        GeoMonitorSubtask.id,
        GeoMonitorSubtask.subtask_id,
        GeoMonitorSubtask.task_id,
        GeoMonitorSubtask.platform,
        GeoMonitorSubtask.prompt,
        GeoMonitorSubtask.mention_position,
        GeoMonitorSubtask.updated_at,
        GeoMonitorTask.monitor_keywords,
        GeoMonitorTask.created_at,
    ]
    if with_refs:
        cols.append(GeoMonitorSubtask.reference_list_json)
    return cols


def list_inclusion_snapshots(
    db: Session,
    current: CurrentSession,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    tenant_id: int | None = None,
    platform: str | None = None,
    keyword: str | None = None,
    page: int = 1,
    limit: int = 10,
    rank_scope: str = "ranked",
) -> dict[str, Any]:
    """信源页「收录明细」专用：按周期/平台直查子任务，避免吃 workspace-brief 全局 24 条样本。

    「8 次引用」是信源引用次数；本列表是监测子任务行。
    rank_scope=ranked|all 与前端「有位次/含未提及」对齐；勿用 prefer_ranked，否则有位次装满后切换无差别。
    进池优先 schedule_key 业务日 task_id（与热力同源），禁止只靠 updated_at 截断。
    2026-07-30 - 收录明细条数假齐+只堆最新天 - 返回截断前 total，按 detect_day 轮询，服务端分页
    2026-07-30 - 含未提及/翻页 5s - 轻量扫池只 hydrate 当前页；池内有位次用 mention_position 近似
    """
    from types import SimpleNamespace

    tenant_id = _resolve_workspace_brief_tenant_id(current, tenant_id)
    range_end = customer_display_cutoff()
    start_at = datetime.combine(start_date, time.min) if start_date else None
    end_at = datetime.combine(end_date, time.max) if end_date else None
    trend_start, trend_end = customer_display_date_range(
        start_at=start_at,
        end_at=end_at,
        default_lookback_days=7 if not start_at and not end_at else None,
    )
    page = max(1, int(page or 1))
    limit = max(1, min(50, int(limit or 10)))

    asset = get_brand_asset(db, tenant_id)
    keyword_group_rows = list_keyword_groups(db, tenant_id)
    keyword_groups = [
        keyword_group_to_dict(item)
        for item in keyword_group_rows
        if item.status and item.monitor_keyword
    ] if keyword_group_rows else active_keyword_groups(db, tenant_id)
    purchased_platforms = tenant_purchased_platforms(db, tenant_id, asset) if asset else []
    purchased_set = set(purchased_platforms)

    scope = str(rank_scope or "ranked").strip().lower()
    if scope not in {"ranked", "all"}:
        scope = "ranked"

    empty = {
        "recent_snapshots": [],
        "purchased_platforms": purchased_platforms,
        "rank_scope": scope,
        "total": 0,
        "page": page,
        "page_size": limit,
    }

    platform_key = str(platform or "").strip()
    if platform_key in ("", "all"):
        platform_key = ""
    if platform_key and purchased_set:
        from app.core.platform_order import expand_platform_codes

        if platform_key not in expand_platform_codes(purchased_set):
            return empty

    # 2026-07-27 - 收录明细须跟上边近7/30/全部同一周期：可见性按 detect_day∈[start,昨日]
    # 2026-07-31 - 批量回写 updated_at 占满扫描窗导致有位次也全空 - 改按 schedule_key 业务日进池（与热力/词×平台同源）
    # 已弃用：按 updated_at DESC limit 800/5000 再滤 detect_day
    period_start, period_end_day = _workspace_period_day_bounds(trend_start, trend_end, range_end)
    start_key, end_key_exclusive = _workspace_schedule_key_bounds(period_start, period_end_day)
    schedule_task_ids = [
        tid
        for tid in db.scalars(
            select(GeoMonitorScheduleRun.task_id).where(
                GeoMonitorScheduleRun.tenant_id == tenant_id,
                GeoMonitorScheduleRun.task_id.isnot(None),
                GeoMonitorScheduleRun.schedule_key >= start_key,
                GeoMonitorScheduleRun.schedule_key < end_key_exclusive,
            )
        )
        if tid
    ]
    schedule_task_ids = list(dict.fromkeys(schedule_task_ids))

    conditions = [
        GeoMonitorTask.deleted.is_(False),
        GeoMonitorTask.tenant_id == tenant_id,
        GeoMonitorTask.purpose == "geo",
        GeoMonitorSubtask.status.in_(("completed", "partial_completed")),
    ]
    if schedule_task_ids:
        conditions.append(GeoMonitorSubtask.task_id.in_(schedule_task_ids))
    else:
        # 无调度记录时回退宽窗（旧数据/手工任务）；仍靠下方 detect_day 收口
        lookback_start = trend_start - timedelta(days=14)
        conditions.append(
            or_(
                GeoMonitorSubtask.updated_at >= lookback_start,
                GeoMonitorTask.created_at >= lookback_start,
            )
        )
    if platform_key:
        from app.core.platform_order import platform_code_family

        family = platform_code_family(platform_key)
        conditions.append(
            GeoMonitorSubtask.platform.in_(family) if len(family) > 1 else GeoMonitorSubtask.platform == platform_key
        )
    elif purchased_set:
        from app.core.platform_order import expand_platform_codes

        conditions.append(GeoMonitorSubtask.platform.in_(expand_platform_codes(purchased_set)))

    # 2026-08-03 - 有位次仍出未提及 - SQL mention_position 与 _resolve_brand_rank 口径不一致，不在 SQL 预筛
    # ponytail: ranked 在 hydration 后按 brand_rank 过滤；扫描窗可能略大，上限 scan_limit 兜底。

    # 调度窗内行数通常可控；仍设天花板防异常租户拖垮
    scan_limit = 8000
    # 2026-07-31 - 顶栏搜标题收录明细搜不到 - 有 keyword 时把 reference 标题带进轻池再筛
    keyword_q = str(keyword or "").strip()
    scan_stmt = (
        select(*_inclusion_scan_columns(with_refs=bool(keyword_q)))
        .join(GeoMonitorTask, GeoMonitorTask.task_id == GeoMonitorSubtask.task_id)
        .where(*conditions)
        .order_by(GeoMonitorSubtask.updated_at.desc())
        .limit(scan_limit)
    )
    scan_rows = list(db.execute(scan_stmt).all())
    if not scan_rows:
        return empty

    task_ids = list({row.task_id for row in scan_rows if row.task_id})
    schedule_runs_map = schedule_runs_for_tasks(db, task_ids)
    lead_runs_map = lead_diagnosis_runs_for_tasks(db, task_ids)

    light_candidates: list[dict[str, Any]] = []
    for row in scan_rows:
        task_proxy = SimpleNamespace(
            task_id=row.task_id,
            tenant_id=tenant_id,
            created_at=row.created_at,
            monitor_keywords=row.monitor_keywords,
        )
        sub_proxy = SimpleNamespace(updated_at=row.updated_at)
        schedule_ctx = _resolve_subtask_schedule_context(
            task_proxy,  # type: ignore[arg-type]
            schedule_runs_map,
            asset,
            lead_runs_map,
        )
        detect_dt = _subtask_detect_datetime(sub_proxy, task_proxy, schedule_ctx)  # type: ignore[arg-type]
        if detect_dt is None or detect_dt > range_end or detect_dt < trend_start:
            continue
        monitor_keywords = row.monitor_keywords
        keyword_group = _prompt_group_name(row.prompt or "", keyword_group_rows) or monitor_keywords
        display_keyword = (
            _resolve_prompt_monitor_keyword(row.prompt or "", keyword_group_rows)
            or str(row.prompt or "").strip()
            or str(monitor_keywords or "").strip()
            or keyword_group
        )
        light_row: dict[str, Any] = {
            "_pk": row.id,
            "subtask_id": row.subtask_id,
            "task_id": row.task_id,
            "platform": row.platform,
            "prompt": row.prompt,
            "keyword_group": keyword_group,
            "monitor_keyword": display_keyword,
            "schedule_label": schedule_ctx.get("schedule_label"),
            "schedule_window_key": schedule_ctx.get("schedule_window_key"),
            "detect_day": detect_dt.date().isoformat(),
            "prompt_intent": prompt_monitor_intent(row.prompt),
            "brand_rank": row.mention_position,
            "brand_mentioned": row.mention_position is not None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }
        if keyword_q:
            light_row["source_articles"] = _light_source_articles_from_refs(
                getattr(row, "reference_list_json", None),
                limit=3,
            )
        light_candidates.append(light_row)

    # 已在 SQL 按 scope 过滤；池内用 all 保持时间序 + 日轮询
    pool = _workspace_period_snapshot_pool(
        light_candidates,
        trend_start=trend_start,
        trend_end=trend_end,
        range_end=range_end,
        rank_scope="all",
        diversify_days=True,
    )
    pool = _filter_inclusion_snapshots_by_keyword(pool, keyword)
    match_terms = _ranking_match_terms(asset, keyword_groups) if asset else []
    offset = (page - 1) * limit

    if scope == "ranked":
        # 2026-08-03 - 有位次仍出未提及 - 按 hydration 后 brand_rank 计数/分页，勿信 mention_position
        recent_snapshots: list[dict[str, Any]] = []
        total_ranked = 0
        for batch_start in range(0, len(pool), _INCLUSION_HYDRATE_BATCH):
            batch_light = pool[batch_start: batch_start + _INCLUSION_HYDRATE_BATCH]
            for row in _hydrate_inclusion_light_batch(
                db,
                batch_light,
                asset=asset,
                keyword_groups=keyword_groups,
                match_terms=match_terms,
            ):
                if not _inclusion_snapshot_has_display_rank(row):
                    continue
                if total_ranked >= offset and len(recent_snapshots) < limit:
                    recent_snapshots.append(row)
                total_ranked += 1
        return {
            "recent_snapshots": recent_snapshots,
            "purchased_platforms": purchased_platforms,
            "rank_scope": scope,
            "total": total_ranked,
            "page": page,
            "page_size": limit,
        }

    total = len(pool)
    page_light = pool[offset: offset + limit]
    if not page_light:
        return {
            "recent_snapshots": [],
            "purchased_platforms": purchased_platforms,
            "rank_scope": scope,
            "total": total,
            "page": page,
            "page_size": limit,
        }

    recent_snapshots = _hydrate_inclusion_light_batch(
        db,
        page_light,
        asset=asset,
        keyword_groups=keyword_groups,
        match_terms=match_terms,
    )

    return {
        "recent_snapshots": recent_snapshots,
        "purchased_platforms": purchased_platforms,
        "rank_scope": scope,
        "total": total,
        "page": page,
        "page_size": limit,
    }



def _workspace_pick_snapshot_subtask_ids(
    db: Session,
    *,
    tenant_id: int,
    purchased_set: set[str],
    trend_start: datetime,
    range_end: datetime,
    lookback_start: datetime,
    period_days: int,
    latest_day: str | None,
    pick_limit: int = 48,
) -> list[str]:
    """两阶段取样：先轻量扫 id，再按日轮询；避免一次 ORM 拉上千条 JSON 字段导致 30s 超时。"""
    # 轻量扫足够多的 id，保证本月能覆盖多日（重字段只 hydrate pick_limit 条）
    scan_limit = min(3_000, max(240, period_days * 40))
    scan_stmt = (
        select(
            GeoMonitorSubtask.subtask_id,
            GeoMonitorSubtask.platform,
            GeoMonitorSubtask.updated_at,
        )
        .join(GeoMonitorTask, GeoMonitorTask.task_id == GeoMonitorSubtask.task_id)
        .where(
            GeoMonitorTask.deleted.is_(False),
            GeoMonitorTask.tenant_id == tenant_id,
            GeoMonitorTask.purpose == "geo",
            GeoMonitorSubtask.status.in_(("completed", "partial_completed")),
            or_(
                GeoMonitorSubtask.updated_at >= lookback_start,
                GeoMonitorTask.created_at >= lookback_start,
            ),
        )
        .order_by(GeoMonitorSubtask.updated_at.desc())
        .limit(scan_limit)
    )
    by_day: dict[str, list[str]] = {}
    latest_ids: list[str] = []
    from app.core.platform_order import expand_platform_codes

    purchased_family = expand_platform_codes(purchased_set) if purchased_set else set()
    for subtask_id, platform, updated_at in db.execute(scan_stmt):
        if purchased_family and platform not in purchased_family:
            continue
        if updated_at is None:
            continue
        if updated_at < trend_start or updated_at > range_end:
            continue
        day_key = updated_at.date().isoformat()
        by_day.setdefault(day_key, []).append(str(subtask_id))
        if latest_day and day_key == latest_day and len(latest_ids) < 24:
            latest_ids.append(str(subtask_id))

    picked: list[str] = []
    seen: set[str] = set()
    for sid in latest_ids:
        if sid not in seen:
            seen.add(sid)
            picked.append(sid)

    days = sorted(by_day.keys(), reverse=True)
    round_idx = 0
    while len(picked) < pick_limit and days:
        progressed = False
        for day in days:
            bucket = by_day[day]
            if round_idx < len(bucket):
                sid = bucket[round_idx]
                if sid not in seen:
                    seen.add(sid)
                    picked.append(sid)
                    progressed = True
                    if len(picked) >= pick_limit:
                        break
        if not progressed:
            break
        round_idx += 1
    return picked


def _workspace_schedule_key_bounds(period_start: date, period_end: date) -> tuple[str, str]:
    """schedule_key 形如 20260701-0930-kw20；用字典序 [start, end+1) 对齐业务检测日。"""
    return period_start.strftime("%Y%m%d"), (period_end + timedelta(days=1)).strftime("%Y%m%d")


def _ranking_matrix_orphan_task_ids(
    db: Session,
    *,
    tenant_id: int,
    range_start: datetime,
    range_end: datetime,
    scheduled_task_ids: list[str],
    selected_platform: str | None = None,
) -> list[str]:
    """业务日窗内已完成、但未出现在本窗 schedule_run.task_id 里的 task。

    缺口补录曾按平台各建 bft，而 schedule_run 唯一键只挂一个 task_id，导致其它平台补录进不了热力。
    用 task.created_at（缺口占位写成场次时刻）收口，避免再扫 45 天宽窗。
    """
    if not scheduled_task_ids:
        return []
    conditions = [
        GeoMonitorTask.deleted.is_(False),
        GeoMonitorTask.tenant_id == tenant_id,
        GeoMonitorTask.purpose == "geo",
        GeoMonitorSubtask.status.in_(("completed", "partial_completed")),
        GeoMonitorTask.created_at >= range_start,
        GeoMonitorTask.created_at <= range_end,
        GeoMonitorTask.task_id.notin_(scheduled_task_ids),
    ]
    if selected_platform:
        conditions.append(GeoMonitorSubtask.platform == selected_platform)
    return list(
        dict.fromkeys(
            tid
            for tid in db.scalars(
                select(GeoMonitorTask.task_id)
                .join(GeoMonitorSubtask, GeoMonitorSubtask.task_id == GeoMonitorTask.task_id)
                .where(*conditions)
            )
            if tid
        )
    )


def _workspace_keyword_platform_light(
    db: Session,
    *,
    tenant_id: int,
    keyword_group_rows: list,
    keyword_groups: list,
    purchased_platforms: list[str],
    trend_start: datetime,
    trend_end: datetime,
    range_end: datetime,
) -> dict[str, Any]:
    """ponytail: 词热度 + 词×平台提及率；不走 ranking_matrix（limit 2000 + 复杂位次）。

    口径：区间内 mention_position 非空视为提及；按监控主词×平台聚合。
    周期按调度业务日（schedule_key 日期前缀），与日统计/KPI 一致；禁止裸 updated_at
   （补录改写后会出现「KPI 随周期变、热力不变」）。
    """
    keywords = _workspace_monitor_keyword_labels(keyword_groups)
    platforms = list(purchased_platforms or [])
    empty = {
        "keyword_heats": [{"name": name, "heat": None} for name in keywords],
        "keyword_platform_heatmap": {
            "platforms": platforms,
            "platform_labels": [_platform_display_names().get(code, code) for code in platforms],
            "keywords": keywords,
            "data": [],
            "source": "light",
        },
    }
    if not keywords or not platforms:
        return empty

    purchased_set = set(platforms)
    period_start, period_end_day = _workspace_period_day_bounds(trend_start, trend_end, range_end)
    start_key, end_key_exclusive = _workspace_schedule_key_bounds(period_start, period_end_day)
    task_ids = [
        tid
        for tid in db.scalars(
            select(GeoMonitorScheduleRun.task_id).where(
                GeoMonitorScheduleRun.tenant_id == tenant_id,
                GeoMonitorScheduleRun.task_id.isnot(None),
                GeoMonitorScheduleRun.schedule_key >= start_key,
                GeoMonitorScheduleRun.schedule_key < end_key_exclusive,
            )
        )
        if tid
    ]
    task_ids = list(dict.fromkeys(task_ids))
    # 2026-08-11 - 词×平台与综合露出脱节：日统计含孤儿补录，light 热力只认 schedule_run - 并入同窗孤儿 task
    if task_ids:
        range_start_dt = datetime.combine(period_start, time.min)
        range_end_dt = datetime.combine(period_end_day, time.max)
        task_ids = list(
            dict.fromkeys(
                [
                    *task_ids,
                    *_ranking_matrix_orphan_task_ids(
                        db,
                        tenant_id=tenant_id,
                        range_start=range_start_dt,
                        range_end=range_end_dt,
                        scheduled_task_ids=task_ids,
                    ),
                ]
            )
        )

    bucket: dict[tuple[str, str], dict[str, int]] = {}
    if task_ids:
        mentioned_expr = case((GeoMonitorSubtask.mention_position.isnot(None), 1), else_=0)
        rows = list(
            db.execute(
                select(
                    GeoMonitorSubtask.platform,
                    GeoMonitorSubtask.prompt,
                    func.count().label("total"),
                    func.coalesce(func.sum(mentioned_expr), 0).label("mentioned"),
                )
                .where(
                    GeoMonitorSubtask.task_id.in_(task_ids),
                    GeoMonitorSubtask.status.in_(("completed", "partial_completed")),
                    GeoMonitorSubtask.platform.in_(platforms),
                )
                .group_by(GeoMonitorSubtask.platform, GeoMonitorSubtask.prompt)
            ).all()
        )
        for platform, prompt, total, mentioned in rows:
            # 购买 deepseek 时把 deepseek_mobile 计入 deepseek 列，避免漏数
            from app.core.platform_order import platforms_compatible

            canon = None
            if platform in purchased_set:
                canon = platform
            else:
                for code in purchased_set:
                    if platforms_compatible(platform, code):
                        canon = code
                        break
            if canon is None:
                continue
            if prompt_monitor_intent(prompt) != "ranking":
                continue
            keyword = _workspace_match_monitor_keyword(prompt or "", keyword_group_rows, keywords)
            if not keyword:
                continue
            key = (keyword, canon)
            stats = bucket.setdefault(key, {"mentioned": 0, "total": 0})
            stats["total"] += int(total or 0)
            stats["mentioned"] += int(mentioned or 0)

    data: list[list[float | int]] = []
    keyword_avgs: list[float] = []
    for y_index, keyword in enumerate(keywords):
        rates: list[float] = []
        for x_index, platform in enumerate(platforms):
            stats = bucket.get((keyword, platform))
            if not stats or stats["total"] <= 0:
                data.append([x_index, y_index, -1])
                continue
            rate = round(stats["mentioned"] / stats["total"] * 1000) / 10
            data.append([x_index, y_index, rate])
            rates.append(rate)
        keyword_avgs.append(sum(rates) / len(rates) if rates else 0.0)

    max_avg = max(keyword_avgs) if keyword_avgs else 0.0
    has_samples = any(item[2] >= 0 for item in data)
    keyword_heats: list[dict[str, Any]] = []
    for name, avg in zip(keywords, keyword_avgs):
        if not has_samples:
            keyword_heats.append({"name": name, "heat": None})
        elif max_avg <= 0:
            keyword_heats.append({"name": name, "heat": 0})
        else:
            keyword_heats.append({"name": name, "heat": int(round((avg / max_avg) * 100))})

    platform_names = _platform_display_names()
    return {
        "keyword_heats": keyword_heats,
        "keyword_platform_heatmap": {
            "platforms": platforms,
            "platform_labels": [platform_names.get(code, code) for code in platforms],
            "keywords": keywords,
            "data": data,
            "source": "light",
        },
    }


def _workspace_brief_full_from_daily_stats(
    db: Session,
    current: CurrentSession,
    *,
    tenant_id: int,
    asset,
    keyword_group_rows: list,
    keyword_groups: list,
    purchased_platforms: list[str],
    trend_start: datetime,
    trend_end: datetime,
    range_end: datetime,
) -> dict[str, Any]:
    """ponytail: 有日统计时 full 走快路径——KPI/趋势用日表，子任务仅补快照/信源（limit 50）。"""
    base = _workspace_brief_from_daily_stats(
        db,
        tenant_id=tenant_id,
        asset=asset,
        keyword_groups=keyword_groups,
        keyword_group_rows=keyword_group_rows,
        purchased_platforms=purchased_platforms,
        trend_start=trend_start,
        trend_end=trend_end,
        range_end=range_end,
    )
    latest_day = base.get("display_day")
    purchased_set = set(purchased_platforms)
    round_comparison = base.get("round_comparison") or {}

    period_days = max(1, (min(trend_end, range_end).date() - trend_start.date()).days + 1)
    lookback_start = trend_start - timedelta(days=1)
    # ponytail: 禁止一次 ORM 拉 2000 条重字段（实测 ~17s → 前端 30s timeout）；两阶段只 hydrate ~48 条
    picked_ids = _workspace_pick_snapshot_subtask_ids(
        db,
        tenant_id=tenant_id,
        purchased_set=purchased_set,
        trend_start=trend_start,
        range_end=range_end,
        lookback_start=lookback_start,
        period_days=period_days,
        latest_day=str(latest_day) if latest_day else None,
        pick_limit=48,
    )
    subtasks: list = []
    if picked_ids:
        stmt = (
            select(GeoMonitorSubtask)
            .join(GeoMonitorTask, GeoMonitorTask.task_id == GeoMonitorSubtask.task_id)
            .options(
                joinedload(GeoMonitorSubtask.task).load_only(
                    GeoMonitorTask.monitor_keywords,
                    GeoMonitorTask.created_at,
                    GeoMonitorTask.total_items,
                    GeoMonitorTask.completed_items,
                ),
                load_only(
                    GeoMonitorSubtask.subtask_id,
                    GeoMonitorSubtask.task_id,
                    GeoMonitorSubtask.platform,
                    GeoMonitorSubtask.prompt,
                    GeoMonitorSubtask.status,
                    GeoMonitorSubtask.mention_context,
                    GeoMonitorSubtask.page_screenshot,
                    GeoMonitorSubtask.reference_list_json,
                    GeoMonitorSubtask.mention_position,
                    GeoMonitorSubtask.all_rankings_json,
                    GeoMonitorSubtask.sentiment,
                    GeoMonitorSubtask.updated_at,
                ),
            )
            .where(GeoMonitorSubtask.subtask_id.in_(picked_ids))
        )
        loaded = {item.subtask_id: item for item in db.scalars(stmt)}
        subtasks = [loaded[sid] for sid in picked_ids if sid in loaded]

    task_ids = list({item.task_id for item in subtasks if item.task_id})
    schedule_runs_map = schedule_runs_for_tasks(db, task_ids)
    lead_runs_map = lead_diagnosis_runs_for_tasks(db, task_ids)

    latest_ranking: list[dict[str, Any]] = []
    latest_exposure: list[dict[str, Any]] = []
    snapshot_candidates: list[dict[str, Any]] = []
    daily_source_maps: dict[str, dict[str, dict[str, Any]]] = {}

    for item in subtasks:
        if item.task is None:
            continue
        intent = prompt_monitor_intent(item.prompt)
        schedule_ctx = _resolve_subtask_schedule_context(
            item.task,
            schedule_runs_map,
            asset,
            lead_runs_map,
        )
        detect_dt = _subtask_detect_datetime(item, item.task, schedule_ctx)
        if detect_dt is None or detect_dt > range_end or detect_dt < trend_start:
            continue

        monitor_keywords = item.task.monitor_keywords
        brand_rank, brand_mentioned = _resolve_brand_rank(
            item,
            monitor_keywords,
            _ranking_match_terms(asset, keyword_groups),
            asset,
        )
        keyword_group = _prompt_group_name(item.prompt or "", keyword_group_rows) or monitor_keywords
        sentiment_label = _normalize_sentiment_label(item.sentiment)
        day_key = detect_dt.date().isoformat()
        display_keyword = (
            _resolve_prompt_monitor_keyword(item.prompt or "", keyword_group_rows)
            or str(item.prompt or "").strip()
            or str(monitor_keywords or "").strip()
            or keyword_group
        )

        row_payload = {
            "subtask_id": item.subtask_id,
            "task_id": item.task_id,
            "platform": item.platform,
            "prompt": item.prompt,
            "keyword_group": keyword_group,
            "monitor_keyword": display_keyword,
            "schedule_label": schedule_ctx.get("schedule_label"),
            "schedule_window_key": schedule_ctx.get("schedule_window_key"),
            "detect_day": day_key,
            "prompt_intent": intent,
            "brand_rank": brand_rank,
            "brand_mentioned": brand_mentioned,
            "sentiment": sentiment_label,
            "answer_excerpt": _answer_excerpt(item.mention_context, 100),
            "page_screenshot": public_screenshot_url(item.page_screenshot),
            "source_articles": _snapshot_source_articles(item),
            "updated_at": item.updated_at.isoformat() if item.updated_at else None,
        }
        snapshot_candidates.append(row_payload)
        if latest_day and day_key == latest_day:
            if intent == "ranking":
                latest_ranking.append(row_payload)
            else:
                latest_exposure.append(row_payload)

        for source in item.reference_list_json or []:
            if not _is_valid_citation_source(source):
                continue
            url = source.get("url") or source.get("site") or source.get("title")
            if not url:
                continue
            key = str(url).split("?")[0]
            day_src_map = daily_source_maps.setdefault(day_key, {})
            day_src = day_src_map.setdefault(
                key,
                {
                    "title": source.get("title") or source.get("site") or key,
                    "url": key,
                    "count": 0,
                    "platforms": [],
                },
            )
            day_src["count"] += 1
            if item.platform and item.platform not in day_src["platforms"]:
                day_src["platforms"].append(item.platform)

    exposure_metrics = _round_metrics_from_rows([], latest_exposure)
    negative_count = exposure_metrics["negative_count"]
    negative_rate = exposure_metrics["negative_rate"]
    exposure_sample_count = exposure_metrics["exposure_sample_count"]

    latest_day_source_map = daily_source_maps.get(latest_day or "", {})
    top_sources = sorted(latest_day_source_map.values(), key=lambda row: row["count"], reverse=True)[:5]
    for row in top_sources:
        row["platforms"] = sort_platform_codes(row["platforms"])[:4]
    # 2026-08-14 - summary 路径与 full 一致：信源数量=最新日全部引用
    source_count_total = sum(int(row.get("count") or 0) for row in latest_day_source_map.values())

    recent_snapshots = _workspace_period_snapshots(
        snapshot_candidates,
        trend_start=trend_start,
        trend_end=trend_end,
        range_end=range_end,
        limit=24,
    )

    alerts: list[dict[str, str]] = []
    if not subtasks:
        alerts.append({
            "level": "info",
            "message": "截至昨日暂无已完成检测结果，请等待定时监测任务返回。",
        })
    elif negative_count > 0:
        alerts.append({
            "level": "warn",
            "message": f"截至昨日，口碑类问题中有 {negative_count} 条负面样本，建议查看实时检测详情。",
        })
    if round_comparison.get("has_previous"):
        rank_delta = round_comparison.get("avg_brand_rank_delta")
        if rank_delta is not None and rank_delta > 0.5:
            alerts.append({
                "level": "warn",
                "message": f"较上一轮「{round_comparison.get('previous_schedule_label') or '上一调度'}」，平均品牌排名下滑 {rank_delta} 位。",
            })
        mention_delta = round_comparison.get("mention_rate_delta")
        if mention_delta is not None and mention_delta < -5:
            alerts.append({
                "level": "warn",
                "message": f"较上一轮，关键词露出率下降 {abs(mention_delta):.1f}%。",
            })

    platform_names = _platform_display_names()
    for highlight in base.get("platform_highlights") or []:
        if highlight["sample_count"] == 0 and highlight["platform"] in purchased_set:
            label = platform_names.get(highlight["platform"], highlight["platform"])
            alerts.append({
                "level": "info",
                "message": f"平台 {label} 截至昨日暂无推荐类返回，请确认监测配置。",
            })

    kpis = dict(base["kpis"])
    kpis.update({
        "exposure_sample_count": exposure_sample_count,
        "negative_count": negative_count,
        "negative_rate": negative_rate,
        "source_count": source_count_total,
    })

    competitor_count = int(kpis.get("competitor_count") or 0)
    competitor_metrics = _workspace_competitor_score(db, current, tenant_id, competitor_count)
    health = compute_workspace_health_score(
        brand_mention_rate=float(kpis.get("brand_mention_rate") or 0),
        top3_rate=float(kpis.get("top3_rate") or 0),
        avg_brand_rank=kpis.get("avg_brand_rank"),
        competitor_count=competitor_count,
        competitor_score=competitor_metrics.get("competitor_score"),
    )

    return {
        **base,
        "kpis": kpis,
        "top_sources": top_sources,
        "recent_snapshots": recent_snapshots,
        "alerts": alerts,
        "health_score": health["health_score"],
        "visibility_score": health["visibility_score"],
        "rank_score": health["rank_score"],
        "competitor_score": health["competitor_score"],
        "top_competitor_mention_rate": competitor_metrics.get("top_competitor_mention_rate"),
        "competitor_lead_delta": competitor_metrics.get("competitor_lead_delta"),
    }


def workspace_brief(
    db: Session,
    current: CurrentSession,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    tenant_id: int | None = None,
    scope: str = "full",
    purpose: str = "geo",
) -> dict[str, Any]:
    """Customer workspace dashboard: schedule round, intent-aware KPIs, snapshots, top sources.

    CUSTOMER：强制本企业。PLATFORM：可传 tenant_id 做只读预览（口径与客户一致，截至昨日）。
    scope=summary：仅日统计 KPI/趋势，供切换周期；不含快照/信源。
    purpose=geo：日常 GEO 监测（默认）；purpose=brand_word：仅品牌词，供品牌分析页。
    """
    from app.core.monitor_purpose import PURPOSE_BRAND_WORD, PURPOSE_GEO, normalize_task_purpose, task_purpose_eq

    purpose = normalize_task_purpose(purpose)
    tenant_id = _resolve_workspace_brief_tenant_id(current, tenant_id)

    range_end = customer_display_cutoff()
    start_at = datetime.combine(start_date, time.min) if start_date else None
    end_at = datetime.combine(end_date, time.max) if end_date else None
    trend_start, trend_end = customer_display_date_range(
        start_at=start_at,
        end_at=end_at,
        default_lookback_days=7 if not start_at and not end_at else None,
    )

    asset = get_brand_asset(db, tenant_id)
    if purpose == PURPOSE_BRAND_WORD:
        from app.services.brand_service import active_brand_word_groups, list_brand_word_groups

        keyword_group_rows = list_brand_word_groups(db, tenant_id)
        keyword_groups = active_brand_word_groups(db, tenant_id)
        purchased_platforms = sort_platform_codes(
            list({
                code
                for group in keyword_groups
                for code in keyword_group_platforms(group, asset)
            })
        ) if keyword_groups else (tenant_purchased_platforms(db, tenant_id, asset) if asset else [])
    else:
        keyword_group_rows = list_keyword_groups(db, tenant_id)
        keyword_groups = [
            keyword_group_to_dict(item)
            for item in keyword_group_rows
            if item.status and item.monitor_keyword
        ] if keyword_group_rows else active_keyword_groups(db, tenant_id)
        purchased_platforms = tenant_purchased_platforms(db, tenant_id, asset) if asset else []

    # 2026-08-07 - 观察号工作台口径只含 kimi/元宝
    from app.services.observer_account import narrow_platform_codes, observer_platforms_for_session

    purchased_platforms = narrow_platform_codes(
        purchased_platforms,
        observer_platforms_for_session(current),
    )

    from app.services.monitor_stats_service import has_daily_stats

    # 日预聚合仅含 geo；品牌词必须走原始子任务路径
    if purpose == PURPOSE_GEO and scope == "summary" and has_daily_stats(db, [tenant_id]):
        return _workspace_brief_from_daily_stats(
            db,
            tenant_id=tenant_id,
            asset=asset,
            keyword_groups=keyword_groups,
            keyword_group_rows=keyword_group_rows,
            purchased_platforms=purchased_platforms,
            trend_start=trend_start,
            trend_end=trend_end,
            range_end=range_end,
        )

    if purpose == PURPOSE_GEO and scope == "full" and has_daily_stats(db, [tenant_id]):
        return _workspace_brief_full_from_daily_stats(
            db,
            current,
            tenant_id=tenant_id,
            asset=asset,
            keyword_group_rows=keyword_group_rows,
            keyword_groups=keyword_groups,
            purchased_platforms=purchased_platforms,
            trend_start=trend_start,
            trend_end=trend_end,
            range_end=range_end,
        )

    purchased_set = set(purchased_platforms)

    from app.services.monitor_stats_service import (
        filter_daily_stat_rows_by_platforms,
        has_daily_stats,
        list_daily_stats_for_tenant,
        platform_bucket_from_stat_rows,
        workspace_kpi_trends_from_stats,
        workspace_metrics_from_stat_rows,
    )

    use_daily_stats = purpose == PURPOSE_GEO and has_daily_stats(db, [tenant_id])
    daily_stat_by_day: dict[str, list] = {}
    trend_span_days = (trend_end.date() - trend_start.date()).days + 1
    if use_daily_stats:
        for row in filter_daily_stat_rows_by_platforms(
            list_daily_stats_for_tenant(
                db,
                tenant_id,
                since=trend_start.date(),
                until=range_end.date(),
            ),
            purchased_platforms,
        ):
            daily_stat_by_day.setdefault(row.stat_date.isoformat(), []).append(row)

    lookback_start = trend_start - timedelta(days=max(45, trend_span_days + 14) if not use_daily_stats else 7)
    subtask_limit = 100 if use_daily_stats else 400

    stmt = (
        select(GeoMonitorSubtask)
        .join(GeoMonitorTask, GeoMonitorTask.task_id == GeoMonitorSubtask.task_id)
        .where(
            GeoMonitorTask.deleted.is_(False),
            GeoMonitorTask.tenant_id == tenant_id,
            task_purpose_eq(purpose),
            GeoMonitorSubtask.status.in_(("completed", "partial_completed")),
            or_(
                GeoMonitorSubtask.updated_at >= lookback_start,
                GeoMonitorTask.created_at >= lookback_start,
            ),
        )
        .order_by(GeoMonitorSubtask.updated_at.desc())
        .limit(subtask_limit)
    )
    # 2026-07-30 - 1038 类风险 - workspace brief ORDER BY 勿带 screenshot/JSON，id-first 再 hydrate
    ordered_ids = _ordered_subtask_ids(db, stmt)
    subtasks = _hydrate_subtasks_in_id_order(
        db,
        ordered_ids,
        joinedload(GeoMonitorSubtask.task).load_only(
            GeoMonitorTask.monitor_keywords,
            GeoMonitorTask.created_at,
            GeoMonitorTask.total_items,
            GeoMonitorTask.completed_items,
        ),
        load_only(
            GeoMonitorSubtask.subtask_id,
            GeoMonitorSubtask.task_id,
            GeoMonitorSubtask.platform,
            GeoMonitorSubtask.prompt,
            GeoMonitorSubtask.status,
            GeoMonitorSubtask.mention_context,
            GeoMonitorSubtask.page_screenshot,
            GeoMonitorSubtask.reference_list_json,
            GeoMonitorSubtask.mention_position,
            GeoMonitorSubtask.all_rankings_json,
            GeoMonitorSubtask.sentiment,
            GeoMonitorSubtask.updated_at,
        ),
    )
    if purchased_set:
        subtasks = [item for item in subtasks if item.platform in purchased_set]

    task_ids = list({item.task_id for item in subtasks if item.task_id})
    schedule_runs_map = schedule_runs_for_tasks(db, task_ids)
    lead_runs_map = lead_diagnosis_runs_for_tasks(db, task_ids)

    ranking_rows: list[dict[str, Any]] = []
    exposure_rows: list[dict[str, Any]] = []
    daily_ranking: dict[str, list[dict[str, Any]]] = {}
    daily_exposure: dict[str, list[dict[str, Any]]] = {}
    source_map: dict[str, dict[str, Any]] = {}
    snapshot_candidates: list[dict[str, Any]] = []
    daily_source_maps: dict[str, dict[str, dict[str, Any]]] = {}

    for item in subtasks:
        if item.task is None:
            continue
        intent = prompt_monitor_intent(item.prompt)
        schedule_ctx = _resolve_subtask_schedule_context(
            item.task,
            schedule_runs_map,
            asset,
            lead_runs_map,
        )
        detect_dt = _subtask_detect_datetime(item, item.task, schedule_ctx)
        if detect_dt is None or detect_dt > range_end or detect_dt < trend_start:
            continue

        monitor_keywords = item.task.monitor_keywords
        brand_rank, brand_mentioned = _resolve_brand_rank(
            item,
            monitor_keywords,
            _ranking_match_terms(asset, keyword_groups),
            asset,
        )
        keyword_group = _prompt_group_name(item.prompt or "", keyword_group_rows) or monitor_keywords
        sentiment_label = _normalize_sentiment_label(item.sentiment)
        day_key = detect_dt.date().isoformat()
        display_keyword = (
            _resolve_prompt_monitor_keyword(item.prompt or "", keyword_group_rows)
            or str(item.prompt or "").strip()
            or str(monitor_keywords or "").strip()
            or keyword_group
        )

        row_payload = {
            "subtask_id": item.subtask_id,
            "task_id": item.task_id,
            "platform": item.platform,
            "prompt": item.prompt,
            "keyword_group": keyword_group,
            "monitor_keyword": display_keyword,
            "schedule_label": schedule_ctx.get("schedule_label"),
            "schedule_window_key": schedule_ctx.get("schedule_window_key"),
            "detect_day": day_key,
            "prompt_intent": intent,
            "brand_rank": brand_rank,
            "brand_mentioned": brand_mentioned,
            "sentiment": sentiment_label,
            "answer_excerpt": _answer_excerpt(item.mention_context, 100),
            "page_screenshot": public_screenshot_url(item.page_screenshot),
            "source_articles": _snapshot_source_articles(item),
            "updated_at": item.updated_at.isoformat() if item.updated_at else None,
        }
        snapshot_candidates.append(row_payload)

        if intent == "ranking":
            ranking_rows.append(row_payload)
            daily_ranking.setdefault(day_key, []).append(row_payload)

        else:
            exposure_rows.append(row_payload)
            daily_exposure.setdefault(day_key, []).append(row_payload)

        for source in item.reference_list_json or []:
            if not _is_valid_citation_source(source):
                continue
            url = source.get("url") or source.get("site") or source.get("title")
            if not url:
                continue
            key = str(url).split("?")[0]
            src = source_map.setdefault(
                key,
                {
                    "title": source.get("title") or source.get("site") or key,
                    "url": key,
                    "count": 0,
                    "platforms": [],
                },
            )
            src["count"] += 1
            if item.platform and item.platform not in src["platforms"]:
                src["platforms"].append(item.platform)

            day_src_map = daily_source_maps.setdefault(day_key, {})
            day_src = day_src_map.setdefault(
                key,
                {
                    "title": source.get("title") or source.get("site") or key,
                    "url": key,
                    "count": 0,
                    "platforms": [],
                },
            )
            day_src["count"] += 1
            if item.platform and item.platform not in day_src["platforms"]:
                day_src["platforms"].append(item.platform)

    latest_day: str | None = None
    previous_day: str | None = None
    latest_schedule = None
    previous_schedule = None
    display_metrics = _round_metrics_from_rows([], [])
    round_comparison: dict[str, Any] = {
        "has_previous": False,
        "latest_schedule_label": None,
        "previous_schedule_label": None,
        "avg_brand_rank_delta": None,
        "mention_rate_delta": None,
        "top3_rate_delta": None,
        "negative_count_delta": None,
    }

    visible_days = _workspace_visible_day_keys(daily_ranking, daily_exposure, cutoff=range_end)
    if use_daily_stats and daily_stat_by_day:
        stat_days = sorted(
            day
            for day, rows in daily_stat_by_day.items()
            if date.fromisoformat(day) <= range_end.date()
            and sum(int(item.completed_count or 0) for item in rows) > 0
        )
        if stat_days:
            visible_days = stat_days
    if visible_days:
        latest_day = visible_days[-1]
        latest_ranking_rows = daily_ranking.get(latest_day, [])
        latest_exposure_rows = daily_exposure.get(latest_day, [])
        display_metrics = _round_metrics_from_rows(latest_ranking_rows, latest_exposure_rows)
        if use_daily_stats and daily_stat_by_day.get(latest_day):
            stat_metrics = workspace_metrics_from_stat_rows(daily_stat_by_day[latest_day])
            # Top3 以日表为准，避免 limit 子任务采样把上轮/本轮算成 0
            stat_metrics["negative_count"] = display_metrics["negative_count"]
            stat_metrics["negative_rate"] = display_metrics["negative_rate"]
            stat_metrics["exposure_sample_count"] = display_metrics["exposure_sample_count"]
            display_metrics = stat_metrics
        latest_label = _workspace_day_label(latest_day)
        latest_schedule = {
            "schedule_window_key": latest_day,
            "schedule_label": f"{latest_label} 监测",
            "completed_subtasks": len(latest_ranking_rows) + len(latest_exposure_rows),
            "total_subtasks": len(latest_ranking_rows) + len(latest_exposure_rows),
        }
        round_comparison["latest_schedule_label"] = latest_schedule["schedule_label"]
        if len(visible_days) >= 2:
            previous_day = visible_days[-2]
            previous_ranking_rows = daily_ranking.get(previous_day, [])
            previous_exposure_rows = daily_exposure.get(previous_day, [])
            previous_metrics = _round_metrics_from_rows(previous_ranking_rows, previous_exposure_rows)
            if use_daily_stats and previous_day and daily_stat_by_day.get(previous_day):
                stat_prev = workspace_metrics_from_stat_rows(daily_stat_by_day[previous_day])
                stat_prev["negative_count"] = previous_metrics["negative_count"]
                stat_prev["negative_rate"] = previous_metrics["negative_rate"]
                stat_prev["exposure_sample_count"] = previous_metrics["exposure_sample_count"]
                previous_metrics = stat_prev
            previous_schedule = {
                "schedule_window_key": previous_day,
                "schedule_label": f"{_workspace_day_label(previous_day)} 监测",
                "completed_subtasks": len(previous_ranking_rows) + len(previous_exposure_rows),
                "total_subtasks": len(previous_ranking_rows) + len(previous_exposure_rows),
            }
            round_comparison["has_previous"] = True
            round_comparison["previous_schedule_label"] = previous_schedule["schedule_label"]
            if display_metrics["avg_brand_rank"] is not None and previous_metrics["avg_brand_rank"] is not None:
                round_comparison["avg_brand_rank_delta"] = round(
                    display_metrics["avg_brand_rank"] - previous_metrics["avg_brand_rank"],
                    1,
                )
            round_comparison["mention_rate_delta"] = round(
                display_metrics["brand_mention_rate"] - previous_metrics["brand_mention_rate"],
                1,
            )
            round_comparison["top3_rate_delta"] = round(
                display_metrics["top3_rate"] - previous_metrics["top3_rate"],
                1,
            )
            round_comparison["negative_count_delta"] = (
                display_metrics["negative_count"] - previous_metrics["negative_count"]
            )
    elif ranking_rows or exposure_rows:
        display_metrics = _round_metrics_from_rows(ranking_rows, exposure_rows)

    ranking_total = display_metrics["ranking_sample_count"]
    brand_mention_rate = display_metrics["brand_mention_rate"]
    avg_brand_rank = display_metrics["avg_brand_rank"]
    top3_rate = display_metrics["top3_rate"]
    negative_count = display_metrics["negative_count"]
    negative_rate = display_metrics["negative_rate"]
    exposure_sample_count = display_metrics["exposure_sample_count"]
    competitor_count = len(list_competitors(db, tenant_id))

    latest_platform_stats = _platform_stats_from_ranking_rows(
        daily_ranking.get(latest_day, []) if latest_day else ranking_rows
    )
    previous_platform_stats = _platform_stats_from_ranking_rows(
        daily_ranking.get(previous_day, []) if previous_day else []
    )
    if use_daily_stats and latest_day and daily_stat_by_day.get(latest_day):
        latest_platform_stats = platform_bucket_from_stat_rows(daily_stat_by_day[latest_day])
        if previous_day and daily_stat_by_day.get(previous_day):
            previous_platform_stats = platform_bucket_from_stat_rows(daily_stat_by_day[previous_day])
    platform_highlights = [
        _platform_highlight_entry(
            code,
            latest_platform_stats.get(code),
            previous_platform_stats.get(code) if round_comparison.get("has_previous") else None,
        )
        for code in purchased_platforms
    ]
    kpi_trends = (
        workspace_kpi_trends_from_stats(
            db,
            tenant_id,
            trend_start,
            trend_end,
            platforms=purchased_platforms,
        )
        if use_daily_stats and daily_stat_by_day
        else _build_workspace_kpi_trends(daily_ranking, daily_exposure, trend_start, trend_end)
    )

    latest_day_source_map = daily_source_maps.get(latest_day or "", {})
    top_sources = sorted(latest_day_source_map.values(), key=lambda row: row["count"], reverse=True)[:5]
    if not top_sources:
        top_sources = sorted(source_map.values(), key=lambda row: row["count"], reverse=True)[:5]
    for row in top_sources:
        row["platforms"] = sort_platform_codes(row["platforms"])[:4]
    # 2026-08-14 - 「信源数量」= 最新日全部引用次数，勿只加 Top5（与列表卡片区分）
    source_count_total = sum(int(row.get("count") or 0) for row in latest_day_source_map.values())
    if source_count_total <= 0:
        source_count_total = sum(int(row.get("count") or 0) for row in source_map.values())

    recent_snapshots = _workspace_period_snapshots(
        snapshot_candidates,
        trend_start=trend_start,
        trend_end=trend_end,
        range_end=range_end,
        limit=24,
    )

    alerts: list[dict[str, str]] = []
    if not subtasks:
        alerts.append({
            "level": "info",
            "message": "截至昨日暂无已完成检测结果，请等待定时监测任务返回。",
        })
    elif negative_count > 0:
        alerts.append({
            "level": "warn",
            "message": f"截至昨日，口碑类问题中有 {negative_count} 条负面样本，建议查看实时检测详情。",
        })
    if round_comparison.get("has_previous"):
        rank_delta = round_comparison.get("avg_brand_rank_delta")
        if rank_delta is not None and rank_delta > 0.5:
            alerts.append({
                "level": "warn",
                "message": f"较上一轮「{round_comparison.get('previous_schedule_label') or '上一调度'}」，平均品牌排名下滑 {rank_delta} 位。",
            })
        mention_delta = round_comparison.get("mention_rate_delta")
        if mention_delta is not None and mention_delta < -5:
            alerts.append({
                "level": "warn",
                "message": f"较上一轮，关键词露出率下降 {abs(mention_delta):.1f}%。",
            })
        neg_delta = round_comparison.get("negative_count_delta")
        if neg_delta is not None and neg_delta > 0:
            alerts.append({
                "level": "warn",
                "message": f"较上一轮，负面样本增加 {neg_delta} 条。",
            })
    platform_names = _platform_display_names()
    for highlight in platform_highlights:
        if highlight["sample_count"] == 0 and highlight["platform"] in purchased_set:
            label = platform_names.get(highlight["platform"], highlight["platform"])
            alerts.append({
                "level": "info",
                "message": f"平台 {label} 截至昨日暂无推荐类返回，请确认监测配置。",
            })

    plan = schedule_plan_summary(asset)
    schedule_times = plan.get("schedule_times") or []
    next_schedule_hint = f"每日 {('、'.join(schedule_times))}" if schedule_times else plan.get("schedule_type_label")

    competitor_metrics = _workspace_competitor_score(db, current, tenant_id, competitor_count)
    health = compute_workspace_health_score(
        brand_mention_rate=brand_mention_rate,
        top3_rate=top3_rate,
        avg_brand_rank=avg_brand_rank,
        competitor_count=competitor_count,
        competitor_score=competitor_metrics.get("competitor_score"),
    )

    return {
        "tenant_id": tenant_id,
        "brand_name": asset.brand_name if asset else None,
        "company_name": asset.company_full_name if asset else None,
        "start_at": trend_start.isoformat(),
        "end_at": range_end.isoformat(),
        "trend_start_at": trend_start.isoformat(),
        "trend_end_at": trend_end.isoformat(),
        "display_period": "through_yesterday",
        "display_day": latest_day,
        "platform_period_label": (
            f"最新监测日 {latest_day}" if latest_day else None
        ),
        "latest_schedule": latest_schedule,
        "previous_schedule": previous_schedule,
        "round_comparison": round_comparison,
        "kpi_trends": kpi_trends,
        "next_schedule_hint": next_schedule_hint,
        "schedule_plan": plan,
        "kpis": {
            "ranking_sample_count": ranking_total,
            "mentioned_count": int(display_metrics.get("mentioned_count") or 0),
            "brand_mention_rate": brand_mention_rate,
            "avg_brand_rank": avg_brand_rank,
            "top3_rate": top3_rate,
            "exposure_sample_count": exposure_sample_count,
            "negative_count": negative_count,
            "negative_rate": negative_rate,
            "source_count": source_count_total,
            "keyword_group_count": len(keyword_groups),
            "competitor_count": competitor_count,
        },
        "purchased_platforms": purchased_platforms,
        "platform_highlights": platform_highlights,
        "top_sources": top_sources,
        "recent_snapshots": recent_snapshots,
        "alerts": alerts,
        "health_score": health["health_score"],
        "visibility_score": health["visibility_score"],
        "rank_score": health["rank_score"],
        "competitor_score": health["competitor_score"],
        "top_competitor_mention_rate": competitor_metrics.get("top_competitor_mention_rate"),
        "competitor_lead_delta": competitor_metrics.get("competitor_lead_delta"),
        **_tenant_service_period_fields(db, tenant_id),
    }


# ponytail: 阈值默认 3；运行时读库（短缓存），多 worker 也跟着开关变。
BACKFILL_WEAK_RANK_AFTER = 3


def backfill_weak_rank_threshold(db=None) -> int:
    from app.services.system_config_service import get_runtime_config

    try:
        value = int(get_runtime_config("snapshot_backfill_weak_rank_after", db=db))
    except (TypeError, ValueError, KeyError):
        return BACKFILL_WEAK_RANK_AFTER
    return max(0, value)


def subtask_weak_rank_needs_backfill(
    subtask: GeoMonitorSubtask,
    *,
    effective_rank: int | None = None,
    use_effective_rank: bool = False,
    brand_mentioned: bool | None = None,
) -> bool:
    """除展示位次前 N（默认 Top3）外，其余一律待补录。

    brand_mentioned 保留参数兼容旧调用，不再参与判断。
    """
    del brand_mentioned  # 口径：只有前三放过，未提及/无位次也进补录
    if use_effective_rank:
        pos = effective_rank
    else:
        pos = subtask.mention_position
    if pos is None:
        return True
    try:
        return int(pos) > backfill_weak_rank_threshold()
    except (TypeError, ValueError):
        return True


def subtask_needs_snapshot_backfill(
    subtask: GeoMonitorSubtask,
    *,
    effective_rank: int | None = None,
    use_effective_rank: bool = False,
    brand_mentioned: bool | None = None,
) -> bool:
    """失败/无回答，或已有回答但展示位次不在前 N，需要快照补录。

    硬失败（无正文）须先完成自动重试 1 次；重试中或尚未发起时不进补录。
    """
    if not (subtask.answer_content or "").strip():
        if subtask.status in {"failed", "stopped"} or (
            subtask.error_message and subtask.status in TERMINAL_STATUSES
        ):
            from app.services.monitor_auto_retry_service import subtask_failure_awaits_or_in_auto_retry

            if subtask_failure_awaits_or_in_auto_retry(subtask):
                return False
            return True
        return False
    return subtask_weak_rank_needs_backfill(
        subtask,
        effective_rank=effective_rank,
        use_effective_rank=use_effective_rank,
        brand_mentioned=brand_mentioned,
    )


def recompute_subtask_rank_from_answer(
    db: Session,
    subtask: GeoMonitorSubtask,
    task: GeoMonitorTask,
    *,
    override_mention_position: int | None = None,
    force: bool = False,
) -> None:
    """根据正文重算 mention_position，供聚合与健康分使用。

    2026-08-12 - 补录勿洗 - 默认跳过 manual_snapshot；仅补录写入（force）或手填 override 才动。
    """
    # 先规范化榜单，再算品牌位次，避免手填/重算仍读到扁平连号
    _normalize_subtask_rankings_on_write(subtask)
    if override_mention_position is not None:
        subtask.mention_position = override_mention_position
        return
    # 批量洗数/同步补算不得冲掉补录位次；新补录解析请显式 force=True
    if not force and is_manual_snapshot_subtask(subtask):
        return

    asset = get_brand_asset(db, task.tenant_id) if task.tenant_id else None
    groups = (
        [keyword_group_to_dict(item) for item in list_keyword_groups(db, task.tenant_id)]
        if task.tenant_id
        else []
    )
    brand_terms = _ranking_match_terms(asset, groups)
    if not brand_terms:
        keyword = str(task.monitor_keywords or "").strip()
        brand_terms = [keyword] if keyword else []
        request = task.raw_request_json or {}
        for alias in request.get("monitorKeywordAliases") or request.get("monitor_keyword_aliases") or []:
            text = str(alias or "").strip()
            if text and text not in brand_terms:
                brand_terms.append(text)

    has_brand_in_answer = bool(brand_terms) and _brand_in_answer_for_rank(subtask, brand_terms)

    # 2026-07-29 - 补录留空重算仍吃旧 mention_position/api 与旧 llm resolution，位次看似不变 - 自动解析前清掉再算
    raw = dict(subtask.raw_result_json or {})
    raw.pop("rank_resolution", None)
    raw["manual_rank_locked"] = False
    subtask.raw_result_json = raw
    subtask.mention_position = None

    # 2026-08-11 - 正文完全未提 → 直接清空
    if not has_brand_in_answer:
        from app.services.rank_llm_service import persist_rank_resolution

        persist_rank_resolution(
            subtask,
            BrandRankResolution(rank=None, mentioned=False, source="none", confidence=0.95),
        )
        return

    resolution = _resolve_brand_rank_detail(subtask, task.monitor_keywords, brand_terms, asset)
    from app.services.rank_llm_service import persist_rank_resolution, resolve_rank_with_optional_llm

    resolution = resolve_rank_with_optional_llm(
        subtask=subtask,
        task=task,
        resolution=resolution,
        brand_terms=brand_terms,
        asset=asset,
    )
    rank = resolution.rank
    if rank is not None:
        subtask.mention_position = int(rank) if float(rank).is_integer() else rank
    else:
        # 方案 B：抽不出出场序则空位次（勿保留旧地点序脏值）
        subtask.mention_position = None
    persist_rank_resolution(subtask, resolution)
