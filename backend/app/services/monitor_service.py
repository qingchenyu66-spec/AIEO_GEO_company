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
    find_best_brand_rank_scoped,
    normalize_structured_rankings,
    parse_answer_rankings,
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


def _has_structured_rankings(value: Any) -> bool:
    return bool(normalize_structured_rankings(value or []))


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


def fill_missing_subtask_ranks_for_task(db: Session, task: GeoMonitorTask) -> int:
    """对「排名类 + 正文含品牌 + 无位次」子任务本地补算，返回写入位次条数。"""
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
        if not _brand_appears_in_text(_subtask_brand_text(subtask), brand_terms):
            continue
        before = subtask.mention_position
        recompute_subtask_rank_from_answer(db, subtask, task)
        if subtask.mention_position != before:
            changed += 1
    return changed


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
    """提交新监测任务前校验企业服务状态，停服或过期企业不再产生扣费任务。"""
    today = datetime.now().date()
    if not tenant.status:
        raise ValueError("企业服务已停止，不能提交新的监测任务")
    if tenant.service_start_date and tenant.service_start_date > today:
        raise ValueError(f"企业服务尚未开始，开始日期为 {tenant.service_start_date}")
    if tenant.service_end_date and tenant.service_end_date < today:
        raise ValueError(f"企业服务已到期，到期日期为 {tenant.service_end_date}")


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
    """判断是否为可纳入统计的 AI 引用来源（排除搜索热榜等噪音）。"""
    title_site = " ".join(str(source.get(key) or "") for key in ("title", "site")).lower()
    url = str(source.get("url") or source.get("site") or "").lower()
    noisy_tokens = ("window._", "search.quark.cn", "by2=news")
    if not title_site.strip() and not url.strip():
        return False
    return not any(token in title_site or token in url for token in noisy_tokens)


def _snapshot_source_articles(item: GeoMonitorSubtask, *, limit: int = 2) -> list[dict[str, str]]:
    """收录明细用：引用文章标题 + 可点开的原文 URL。"""
    from urllib.parse import urlparse

    articles: list[dict[str, str]] = []
    seen: set[str] = set()
    for source in item.reference_list_json or []:
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


def _is_relevant_source(source: dict[str, Any], terms: list[str]) -> bool:
    """判断引用来源是否与当前企业相关，过滤搜索页热榜和同名无关公司。"""
    if not _is_valid_citation_source(source):
        return False
    if not terms:
        return True
    title_site = " ".join(str(source.get(key) or "") for key in ("title", "site")).lower()
    url = str(source.get("url") or "").lower()
    domain_terms = [term for term in terms if "." in term]
    company_terms = [term for term in terms if "." not in term]
    if any(term in title_site for term in company_terms):
        return True
    return any(term in url for term in domain_terms)


def _matched_source_keywords(source: dict[str, Any], keywords: list[str]) -> list[str]:
    """提取来源中实际命中的监控词。"""
    text = " ".join(str(source.get(key) or "") for key in ("title", "site", "url")).lower()
    matched = [keyword for keyword in keywords if keyword.lower() in text]
    return list(dict.fromkeys(matched))


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
    ranked = sorted(rows, key=lambda item: item["count"], reverse=True)[:500]
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
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, int], dict[str, dict[str, int]]]:
    """一次遍历产出未截断的 url→行 map（供日级物化合并）+ 日趋势计数。"""
    branded_map: dict[str, dict[str, Any]] = {}
    all_map: dict[str, dict[str, Any]] = {}
    source_daily_counts: dict[str, int] = {}
    source_daily_counts_by_platform: dict[str, dict[str, int]] = {}

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
            matched_exposure = _matched_source_keywords(source, exposure_terms)
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
    """提交平台配置；保留企业配置的 mode/screenshot（与模力计费项一致）。"""
    return item.model_dump()


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
    subtask.reference_list_json = item.get("referenceList")
    subtask.citation_list_json = item.get("citationList")
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
            joinedload(GeoMonitorTask.subtasks).load_only(
                GeoMonitorSubtask.id,
                GeoMonitorSubtask.subtask_id,
                GeoMonitorSubtask.task_id,
                GeoMonitorSubtask.platform,
                GeoMonitorSubtask.mode,
                GeoMonitorSubtask.prompt,
                GeoMonitorSubtask.status,
                GeoMonitorSubtask.page_screenshot,
                GeoMonitorSubtask.reference_list_json,
                GeoMonitorSubtask.error_message,
                GeoMonitorSubtask.amount,
                GeoMonitorSubtask.mention_position,
                GeoMonitorSubtask.mention_context,
                GeoMonitorSubtask.sentiment,
                GeoMonitorSubtask.updated_at,
            ),
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
    mentioned = [item for item in completed if item.mention_position is not None]
    task_by_id = {task.task_id: task for task in tasks if task.task_id}
    completed_task_ids = list({item.task_id for item in completed if item.task_id})
    summary_schedule_runs = schedule_runs_for_tasks(db, completed_task_ids) if completed_task_ids else {}
    summary_lead_runs = lead_diagnosis_runs_for_tasks(db, completed_task_ids) if completed_task_ids else {}
    asset_by_tenant = {asset.tenant_id: asset for asset in asset_rows}

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
        round(sum(item.mention_position for item in mentioned) / len(mentioned), 1)
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
        if item.mention_position is not None:
            bucket["mentioned"] += 1
            bucket["rank_total"] += item.mention_position
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
    invalidate_monitor_summary_cache(task.tenant_id)
    try:
        from app.services.monitor_stats_service import refresh_stats_for_task

        refresh_stats_for_task(db, task_id)
        db.commit()
    except Exception as exc:
        logger.warning("refresh_stats_for_task failed task_id=%s error=%s", task_id, exc)
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
    return {
        "subtask_id": subtask.subtask_id,
        "task_id": subtask.task_id,
        "platform": subtask.platform,
        "mode": subtask.mode,
        "prompt": subtask.prompt,
        "status": subtask.status,
        "page_screenshot": public_screenshot_url(subtask.page_screenshot),
        "answer_content": subtask.answer_content,
        "reference_list": subtask.reference_list_json or [],
        "citation_list": subtask.citation_list_json or [],
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
    }


def serialize_summary_subtask(subtask: GeoMonitorSubtask) -> dict[str, Any]:
    """汇总页使用的轻量子任务序列化，避免加载回答正文和原始结果大字段。"""
    reference_count = len(subtask.reference_list_json or [])
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
) -> list[dict[str, Any]]:
    """按监测词建列：每个词组的每个 monitor keyword 各占一列。"""
    matrix_rows = rows or []
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
    """排名矩阵仅展示企业当前配置的监测平台；无配置时保留全部（兼容旧数据）。"""
    purchased = {code for code in purchased_platforms if code}
    if not purchased:
        return True
    text = str(platform or "").strip()
    return bool(text and text in purchased)


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
    normalized = (text or "").lower()
    if not normalized:
        return False
    for term in brand_terms:
        text_value = term.strip().lower()
        if text_value and (text_value in normalized or normalized in text_value):
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


def _subtask_answer_plaintext(subtask: GeoMonitorSubtask) -> str:
    """Keep line breaks for list/category rank parsing."""
    parts: list[str] = []
    for field in (subtask.answer_content, subtask.mention_context):
        if not field:
            continue
        cleaned = re.sub(r"<[^>]+>", "\n", str(field))
        cleaned = re.sub(r"\r", "\n", cleaned)
        parts.append(cleaned)
    return "\n".join(parts).strip()


def _name_matches_brand(name: str, brand_terms: list[str]) -> bool:
    normalized = name.strip().lower()
    if not normalized:
        return False
    for term in brand_terms:
        text = term.strip().lower()
        if not text:
            continue
        if text in normalized or normalized in text:
            return True
        for fragment in _brand_term_match_fragments(term):
            token = fragment.lower()
            if _significant_brand_fragment(token) and (token in normalized or normalized in token):
                return True
    return False


def _collect_ranking_entries(subtask: GeoMonitorSubtask) -> list[dict[str, Any]]:
    """正文解析优先排在前；JSON 殿后作兜底（find_* 取首次命中＝优先正文名次）。"""
    text = _subtask_answer_plaintext(subtask)
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

    answer = _subtask_answer_plaintext(subtask)
    scope = _ranking_scope_text(monitor_keywords, subtask.prompt)
    merged = [
        *parse_answer_rankings(answer),
        *normalize_structured_rankings(subtask.all_rankings_json or []),
    ]
    if not merged:
        return None, False, None
    entry = find_best_brand_entry_scoped(merged, match_name, scope, skip_name=skip_name)
    if entry is None:
        rank, matched = find_best_brand_rank_scoped(merged, match_name, scope, skip_name=skip_name)
        return rank, matched, None
    category = str(entry.get("category") or "").strip() or None
    try:
        return float(entry["rank"]), True, category
    except (TypeError, ValueError):
        return None, True, category



def _appearance_order_rank(
    text: str,
    brand_terms: list[str],
    scope: str | None = None,
    *,
    allow_global: bool = True,
) -> int | None:
    """When answer has no category/numbered list, rank by company-nomination line order."""
    from app.services.ranking_parser import _is_company_nomination_line

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
            # 分类行本身若是「一、XX有限公司」仍算提名
            if not _is_company_nomination_line(line):
                continue
        elif not _is_company_nomination_line(line):
            continue
        order += 1
        if _brand_appears_in_text(line, brand_terms):
            return order
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


def _resolve_brand_rank_detail(
    subtask: GeoMonitorSubtask,
    monitor_keywords: str | None,
    brand_terms: list[str],
    asset: BrandAsset | None = None,
) -> BrandRankResolution:
    """Resolve brand rank with provenance for matrix display and LLM fallback."""
    combined_text = _subtask_brand_text(subtask)
    has_brand_in_text = _brand_appears_in_text(combined_text, brand_terms)
    if prompt_monitor_intent(subtask.prompt) != "ranking":
        return BrandRankResolution(
            rank=None,
            mentioned=has_brand_in_text,
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
        return BrandRankResolution(
            rank=rank_value,
            mentioned=bool(stored_resolution.get("mentioned")),
            source="llm",
            confidence=max(0.0, min(1.0, confidence)),
            category=str(stored_resolution.get("category") or "").strip() or None,
            rank_basis=str(stored_resolution.get("rank_basis") or "").strip() or None,
            evidence=str(stored_resolution.get("evidence") or "").strip() or None,
        )

    monitor_keyword = str(monitor_keywords or "").strip()
    is_industry_task = ranking_task_is_industry_scoped(monitor_keyword, subtask.prompt, asset)
    scope = _ranking_scope_text(monitor_keyword, subtask.prompt)
    answer_text = _subtask_answer_plaintext(subtask)
    has_parsed_entries = bool(_collect_ranking_entries(subtask))

    rank_from_list, in_ranking_list, list_category = _find_brand_in_rankings(
        subtask,
        brand_terms,
        asset,
        monitor_keywords=monitor_keyword,
    )
    if rank_from_list is not None:
        category = list_category or _matched_brand_category(subtask, brand_terms, rank_from_list)
        basis = "table" if "|" in answer_text and "企业" in answer_text else "section"
        return BrandRankResolution(
            rank=rank_from_list,
            mentioned=True,
            source="structured",
            confidence=0.95,
            category=category,
            rank_basis=basis,
        )
    if in_ranking_list:
        return BrandRankResolution(
            rank=None,
            mentioned=True,
            source="structured",
            confidence=0.5,
        )

    if has_brand_in_text:
        appearance_rank = _appearance_order_rank(
            answer_text,
            brand_terms,
            scope,
            allow_global=not has_parsed_entries,
        )
        if appearance_rank is not None:
            # 点名序只采信 Top3；更深位次易被字段行/补充段虚高，宁记「提及无位次」
            if int(appearance_rank) <= 3:
                return BrandRankResolution(
                    rank=appearance_rank,
                    mentioned=True,
                    source="appearance",
                    confidence=0.55,
                )
            return BrandRankResolution(
                rank=None,
                mentioned=True,
                source="appearance",
                confidence=0.45,
                rank_basis="appearance_beyond_top3",
            )

    if is_industry_task:
        return BrandRankResolution(
            rank=None,
            mentioned=has_brand_in_text,
            source="none",
            confidence=0.9 if not has_brand_in_text else 0.4,
        )

    # 本地已解析出名单但品牌不在名单上（仅出现在建议段）→ 勿回退旧 mention_position 虚高值
    if has_parsed_entries:
        return BrandRankResolution(
            rank=None,
            mentioned=has_brand_in_text,
            source="none",
            confidence=0.9 if not has_brand_in_text else 0.4,
        )

    if subtask.mention_position is not None and has_brand_in_text:
        return BrandRankResolution(
            rank=subtask.mention_position,
            mentioned=True,
            source="api",
            confidence=0.6,
        )

    return BrandRankResolution(
        rank=None,
        mentioned=has_brand_in_text,
        source="none",
        confidence=0.9 if not has_brand_in_text else 0.3,
    )


def _resolve_brand_rank(
    subtask: GeoMonitorSubtask,
    monitor_keywords: str | None,
    brand_terms: list[str],
    asset: BrandAsset | None = None,
) -> tuple[int | float | None, bool]:
    """Return brand list rank for ranking prompts; exposure prompts only report mention."""
    detail = _resolve_brand_rank_detail(subtask, monitor_keywords, brand_terms, asset)
    return detail.rank, detail.mentioned


def _find_brand_in_structured_rankings(
    subtask: GeoMonitorSubtask,
    brand_terms: list[str],
    asset: BrandAsset | None,
    *,
    monitor_keywords: str | None = None,
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

    merged = normalize_structured_rankings(subtask.all_rankings_json or [])
    if not merged:
        return None, False, None
    scope = _ranking_scope_text(monitor_keywords, subtask.prompt)
    entry = find_best_brand_entry_scoped(merged, match_name, scope, skip_name=skip_name)
    if entry is None:
        rank, matched = find_best_brand_rank_scoped(merged, match_name, scope, skip_name=skip_name)
        return rank, matched, None
    category = str(entry.get("category") or "").strip() or None
    try:
        return float(entry["rank"]), True, category
    except (TypeError, ValueError):
        return None, True, category


def _stored_display_rank_source(subtask: GeoMonitorSubtask) -> tuple[str, dict[str, Any]]:
    """从 raw_result_json 推断 mention_position 的写入来源（读路径 provenance）。"""
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
) -> BrandRankResolution:
    """读路径展示位次：mention_position 为权威；缺失再 JSON；详情可再全文解析。

    写路径（recompute_subtask_rank_from_answer）仍走 _resolve_brand_rank_detail，
    算完后写回 mention_position，不经过本函数。
    """
    mention_text = _strip_html_for_match(getattr(subtask, "mention_context", None))
    has_brand_in_mention = _brand_appears_in_text(mention_text, brand_terms)
    if prompt_monitor_intent(subtask.prompt) != "ranking":
        return BrandRankResolution(
            rank=None,
            mentioned=has_brand_in_mention or subtask.mention_position is not None,
            source="exposure",
            confidence=1.0,
        )

    if subtask.mention_position is not None:
        source, raw = _stored_display_rank_source(subtask)
        # 人工/LLM 锁定；自动写入的 mention_position 可能来自模力「全员第1」脏榜，详情允许重算
        if source in {"manual", "llm"} or not allow_full_parse:
            stored = raw.get("rank_resolution") if isinstance(raw.get("rank_resolution"), dict) else {}
            confidence = 1.0 if source == "manual" else 0.9
            if source == "llm":
                try:
                    confidence = float(stored.get("confidence", 0.9))
                except (TypeError, ValueError):
                    confidence = 0.9
                confidence = max(0.0, min(1.0, confidence))
            # 轻量路径：结构化榜已按出场序纠正时，与脏 mention_position 冲突则采信榜单
            if source == "stored" and not allow_full_parse:
                rank_from_list, _, list_category = _find_brand_in_structured_rankings(
                    subtask,
                    brand_terms,
                    asset,
                    monitor_keywords=str(monitor_keywords or "").strip(),
                )
                if rank_from_list is not None:
                    try:
                        if float(rank_from_list) != float(subtask.mention_position):
                            return BrandRankResolution(
                                rank=rank_from_list,
                                mentioned=True,
                                source="structured",
                                confidence=0.95,
                                category=list_category,
                                rank_basis="table",
                            )
                    except (TypeError, ValueError):
                        pass
            return BrandRankResolution(
                rank=subtask.mention_position,
                mentioned=True,
                source=source,
                confidence=confidence,
                category=str(stored.get("category") or "").strip() or None,
                rank_basis=str(stored.get("rank_basis") or "").strip() or None,
                evidence=str(stored.get("evidence") or "").strip() or None,
            )

    monitor_keyword = str(monitor_keywords or "").strip()
    rank_from_list, in_ranking_list, list_category = _find_brand_in_structured_rankings(
        subtask,
        brand_terms,
        asset,
        monitor_keywords=monitor_keyword,
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


def _matrix_cell_rank(
    subtask: GeoMonitorSubtask,
    monitor_keywords: str | None,
    asset: BrandAsset | None,
    keyword_groups: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    ranking_terms = _ranking_match_terms(asset, keyword_groups)
    detail = _read_display_brand_rank(
        subtask,
        monitor_keywords,
        ranking_terms,
        asset,
        allow_full_parse=False,
    )
    return {
        "mention_position": detail.rank,
        "raw_mention_position": subtask.mention_position,
        "brand_mentioned": detail.mentioned,
        "monitor_keyword": monitor_keywords,
        "ranking_terms": ranking_terms,
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
    """Serialize subtask with brand-aware rank for customer-facing views."""
    data = serialize_subtask(subtask)
    ranking_terms = _ranking_match_terms(asset, keyword_groups)
    detail = _read_display_brand_rank(
        subtask,
        monitor_keywords,
        ranking_terms,
        asset,
        allow_full_parse=True,
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
    daily_sample_cap = int(getattr(asset, "schedule_frequency", 0) or 0) or None
    platform_filter = str(platform or "").strip()
    all_platforms = not platform_filter or platform_filter.lower() == "all"
    selected_platform = None if all_platforms else platform_filter

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
        .options(
            joinedload(GeoMonitorSubtask.task).load_only(
                GeoMonitorTask.monitor_keywords,
                GeoMonitorTask.created_at,
            ),
            load_only(*light_cols),
        )
        .where(
            GeoMonitorTask.deleted.is_(False),
            GeoMonitorTask.tenant_id == resolved_tenant_id,
            GeoMonitorTask.purpose == "geo",
            GeoMonitorSubtask.status.in_(("completed", "partial_completed")),
        )
        .order_by(GeoMonitorSubtask.updated_at.desc())
    )
    if schedule_task_ids:
        stmt = stmt.where(GeoMonitorSubtask.task_id.in_(schedule_task_ids))
    else:
        stmt = stmt.where(
            or_(
                GeoMonitorSubtask.updated_at >= range_start - timedelta(days=45),
                GeoMonitorTask.created_at >= range_start - timedelta(days=45),
            ),
        )
    if selected_platform:
        stmt = stmt.where(GeoMonitorSubtask.platform == selected_platform)

    # ponytail: 全平台×多词×多日轻松超 2000；截断会把冷门词变成「—」。有 schedule 范围时放宽。
    fetch_limit = 5000 if schedule_task_ids else 2000
    if selected_platform:
        fetch_limit = min(fetch_limit, 3000)
    subtasks = list(db.scalars(stmt.limit(fetch_limit)).unique())
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
        rank_payload = _matrix_cell_rank(item, monitor_keywords, asset, keyword_groups)
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

    columns = _build_matrix_columns(keyword_group_rows, prompt_set, rows)
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
        list_daily_stats_for_tenant,
        platform_bucket_from_stat_rows,
        workspace_kpi_trends_from_stats,
        workspace_metrics_from_stat_rows,
    )

    daily_stat_by_day: dict[str, list] = {}
    for row in list_daily_stats_for_tenant(
        db,
        tenant_id,
        since=trend_start.date(),
        until=range_end.date(),
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
    kpi_trends = workspace_kpi_trends_from_stats(db, tenant_id, trend_start, trend_end)

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
    """Chip / 热力图行标签：展开各组全部监测词（与前端 brand 口径一致）。"""
    labels: list[str] = []
    seen: set[str] = set()
    for group in keyword_groups:
        for token in keyword_group_monitor_keywords(group):
            primary = str(token or "").strip()
            if primary and primary not in seen:
                seen.add(primary)
                labels.append(primary)
    return labels[:24]


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
    return trend_start.date(), period_end


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

    def _recency_key(item: dict[str, Any]) -> tuple[str, str, str]:
        return (
            str(item.get("detect_day") or ""),
            str(item.get("updated_at") or ""),
            str(item.get("subtask_id") or ""),
        )

    scope = str(rank_scope or "prefer_ranked").strip().lower()
    if scope == "ranked":
        pool = [row for row in in_period if row.get("brand_rank") is not None]
        pool.sort(key=_recency_key, reverse=True)
        return pool[:limit]
    if scope == "all":
        pool = list(in_period)
        pool.sort(key=_recency_key, reverse=True)
        return pool[:limit]

    # prefer_ranked（默认）
    ranked = [row for row in in_period if row.get("brand_rank") is not None]
    unranked = [row for row in in_period if row.get("brand_rank") is None]
    ranked.sort(key=_recency_key, reverse=True)
    unranked.sort(key=_recency_key, reverse=True)
    out = ranked[:limit]
    if len(out) < limit:
        out.extend(unranked[: limit - len(out)])
    return out


def list_inclusion_snapshots(
    db: Session,
    current: CurrentSession,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    tenant_id: int | None = None,
    platform: str | None = None,
    limit: int = 48,
    rank_scope: str = "ranked",
) -> dict[str, Any]:
    """信源页「收录明细」专用：按周期/平台直查子任务，避免吃 workspace-brief 全局 24 条样本。

    「8 次引用」是信源引用次数；本列表是监测子任务行。
    rank_scope=ranked|all 与前端「有排名/全部」对齐；勿用 prefer_ranked，否则有排名装满 limit 后切换无差别。
    """
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
    keyword_group_rows = list_keyword_groups(db, tenant_id)
    keyword_groups = [
        keyword_group_to_dict(item)
        for item in keyword_group_rows
        if item.status and item.monitor_keyword
    ] if keyword_group_rows else active_keyword_groups(db, tenant_id)
    purchased_platforms = tenant_purchased_platforms(db, tenant_id, asset) if asset else []
    purchased_set = set(purchased_platforms)

    platform_key = str(platform or "").strip()
    if platform_key in ("", "all"):
        platform_key = ""
    if platform_key and purchased_set and platform_key not in purchased_set:
        return {"recent_snapshots": [], "purchased_platforms": purchased_platforms}

    lookback_start = trend_start - timedelta(days=1)
    # 平台已筛时多取一些；全平台仍限量，避免拖垮接口
    fetch_cap = min(240, max(limit * 4, 80 if platform_key else 120))
    conditions = [
        GeoMonitorTask.deleted.is_(False),
        GeoMonitorTask.tenant_id == tenant_id,
        GeoMonitorTask.purpose == "geo",
        GeoMonitorSubtask.status.in_(("completed", "partial_completed")),
        or_(
            GeoMonitorSubtask.updated_at >= lookback_start,
            GeoMonitorTask.created_at >= lookback_start,
        ),
        GeoMonitorSubtask.updated_at <= range_end,
    ]
    if platform_key:
        conditions.append(GeoMonitorSubtask.platform == platform_key)
    elif purchased_set:
        conditions.append(GeoMonitorSubtask.platform.in_(purchased_set))

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
        .where(*conditions)
        .order_by(GeoMonitorSubtask.updated_at.desc())
        .limit(fetch_cap)
    )
    subtasks = list(db.scalars(stmt).unique())
    task_ids = list({item.task_id for item in subtasks if item.task_id})
    schedule_runs_map = schedule_runs_for_tasks(db, task_ids)
    lead_runs_map = lead_diagnosis_runs_for_tasks(db, task_ids)

    snapshot_candidates: list[dict[str, Any]] = []
    match_terms = _ranking_match_terms(asset, keyword_groups) if asset else []
    for item in subtasks:
        if item.task is None:
            continue
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
            match_terms,
            asset,
        )
        keyword_group = _prompt_group_name(item.prompt or "", keyword_group_rows) or monitor_keywords
        display_keyword = (
            _resolve_prompt_monitor_keyword(item.prompt or "", keyword_group_rows)
            or str(item.prompt or "").strip()
            or str(monitor_keywords or "").strip()
            or keyword_group
        )
        snapshot_candidates.append({
            "subtask_id": item.subtask_id,
            "task_id": item.task_id,
            "platform": item.platform,
            "prompt": item.prompt,
            "keyword_group": keyword_group,
            "monitor_keyword": display_keyword,
            "schedule_label": schedule_ctx.get("schedule_label"),
            "schedule_window_key": schedule_ctx.get("schedule_window_key"),
            "detect_day": detect_dt.date().isoformat(),
            "prompt_intent": prompt_monitor_intent(item.prompt),
            "brand_rank": brand_rank,
            "brand_mentioned": brand_mentioned,
            "sentiment": _normalize_sentiment_label(item.sentiment),
            "answer_excerpt": _answer_excerpt(item.mention_context, 100),
            "page_screenshot": public_screenshot_url(item.page_screenshot),
            "source_articles": _snapshot_source_articles(item),
            "updated_at": item.updated_at.isoformat() if item.updated_at else None,
        })

    scope = str(rank_scope or "ranked").strip().lower()
    if scope not in {"ranked", "all"}:
        scope = "ranked"
    recent_snapshots = _workspace_period_snapshots(
        snapshot_candidates,
        trend_start=trend_start,
        trend_end=trend_end,
        range_end=range_end,
        limit=limit,
        rank_scope=scope,
    )
    return {
        "recent_snapshots": recent_snapshots,
        "purchased_platforms": purchased_platforms,
        "rank_scope": scope,
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
    for subtask_id, platform, updated_at in db.execute(scan_stmt):
        if purchased_set and platform not in purchased_set:
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
            if platform not in purchased_set:
                continue
            if prompt_monitor_intent(prompt) != "ranking":
                continue
            keyword = _workspace_match_monitor_keyword(prompt or "", keyword_group_rows, keywords)
            if not keyword:
                continue
            key = (keyword, platform)
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
        "source_count": sum(row["count"] for row in top_sources),
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
        for row in list_daily_stats_for_tenant(
            db,
            tenant_id,
            since=trend_start.date(),
            until=range_end.date(),
        ):
            daily_stat_by_day.setdefault(row.stat_date.isoformat(), []).append(row)

    lookback_start = trend_start - timedelta(days=max(45, trend_span_days + 14) if not use_daily_stats else 7)
    subtask_limit = 100 if use_daily_stats else 400

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
    )
    subtasks = list(db.scalars(stmt.limit(subtask_limit)))
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
        workspace_kpi_trends_from_stats(db, tenant_id, trend_start, trend_end)
        if use_daily_stats and daily_stat_by_day
        else _build_workspace_kpi_trends(daily_ranking, daily_exposure, trend_start, trend_end)
    )

    latest_day_source_map = daily_source_maps.get(latest_day or "", {})
    top_sources = sorted(latest_day_source_map.values(), key=lambda row: row["count"], reverse=True)[:5]
    if not top_sources:
        top_sources = sorted(source_map.values(), key=lambda row: row["count"], reverse=True)[:5]
    for row in top_sources:
        row["platforms"] = sort_platform_codes(row["platforms"])[:4]

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
            "brand_mention_rate": brand_mention_rate,
            "avg_brand_rank": avg_brand_rank,
            "top3_rate": top3_rate,
            "exposure_sample_count": exposure_sample_count,
            "negative_count": negative_count,
            "negative_rate": negative_rate,
            "source_count": sum(row["count"] for row in top_sources),
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
) -> None:
    """根据补录正文重算 mention_position，供聚合与健康分使用。"""
    if override_mention_position is not None:
        subtask.mention_position = override_mention_position
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

    resolution = _resolve_brand_rank_detail(subtask, task.monitor_keywords, brand_terms, asset)
    from app.services.rank_llm_service import persist_rank_resolution, resolve_rank_with_optional_llm

    resolution = resolve_rank_with_optional_llm(
        subtask=subtask,
        task=task,
        resolution=resolution,
        brand_terms=brand_terms,
        asset=asset,
    )
    persist_rank_resolution(subtask, resolution)
    rank = resolution.rank
    if rank is not None:
        subtask.mention_position = int(rank) if float(rank).is_integer() else rank
    else:
        subtask.mention_position = None
