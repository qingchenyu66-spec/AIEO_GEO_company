import re
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, load_only

from app.api.dependencies import CurrentSession
from app.core.config import settings
from app.models.brand import BrandAsset, BrandKeywordGroup
from app.models.monitor import GeoMonitorScheduleRun, GeoMonitorSubtask, GeoMonitorTask
from app.models.tenant import Tenant
from app.schemas.monitor import MonitorTaskCreateRequest, PlatformConfig
from app.services.molizhishu_platforms import filter_submittable_platforms
from app.services.brand_service import (
    _is_industry_monitor_keyword,
    active_keyword_groups,
    brand_exposure_terms,
    collect_exposure_term_options,
    get_brand_asset,
    keyword_group_display_label,
    keyword_group_monitor_keywords,
    keyword_group_primary_keyword,
    keyword_group_to_dict,
    list_competitors,
    list_keyword_groups,
    molizhishu_brand_payload,
    molizhishu_monitor_terms,
)
from app.services.molizhishu_client import MolizhishuClient
from app.services.ranking_parser import find_best_brand_rank, normalize_structured_rankings, parse_answer_rankings
from app.services.schedule_context import (
    prompt_monitor_intent,
    resolve_task_schedule_context,
    schedule_plan_summary,
    schedule_runs_for_tasks,
    schedule_window_sort_key,
)

TERMINAL_STATUSES = {"completed", "partial_completed", "failed", "stopped"}
NON_TERMINAL_STATUSES = {"pending", "processing", "running", "queued"}


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
    abnormal_count = sum(1 for item in subtasks if item.status in {"failed", "stopped"} or item.error_message)
    success_count = sum(1 for item in subtasks if item.status in {"completed", "partial_completed"} or item.answer_content)
    task.total_items = task.total_items or len(subtasks)
    task.completed_items = max(task.completed_items or 0, terminal_count)
    task.failed_items = max(task.failed_items or 0, abnormal_count)
    if terminal_count >= len(subtasks):
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


def _is_valid_citation_source(source: dict[str, Any]) -> bool:
    """判断是否为可纳入统计的 AI 引用来源（排除搜索热榜等噪音）。"""
    title_site = " ".join(str(source.get(key) or "") for key in ("title", "site")).lower()
    url = str(source.get("url") or source.get("site") or "").lower()
    noisy_tokens = ("window._", "search.quark.cn", "by2=news")
    if not title_site.strip() and not url.strip():
        return False
    return not any(token in title_site or token in url for token in noisy_tokens)


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
        raise ValueError("未配置模力指数支持的监测平台")
    platform_items = [
        item for item in payload.platforms if item.platform in submittable_codes
    ]
    request_body: dict[str, Any] = {
        "prompts": payload.prompts,
        "platforms": [item.model_dump() for item in platform_items],
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
        request_body["regionCode"] = payload.region_code
    callback_url = str(payload.callback_url) if payload.callback_url else settings.molizhishu_callback_url.strip()
    if callback_url:
        request_body["callbackUrl"] = callback_url
    return request_body


def _upsert_subtask(db: Session, task_id: str, item: dict[str, Any]) -> GeoMonitorSubtask:
    """按 subTaskId 幂等保存子任务摘要或完整结果。"""
    subtask_id = str(item.get("subTaskId") or "")
    if not subtask_id:
        raise ValueError("模力指数子任务缺少 subTaskId")
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
    subtask.mention_position = item.get("mentionPosition")
    subtask.mention_context = item.get("mentionContext")
    subtask.sentiment = item.get("sentiment")
    subtask.competitor_rankings_json = item.get("competitorRankings")
    subtask.all_rankings_json = item.get("allRankings")
    subtask.raw_result_json = item
    return subtask


def submit_monitor_task(db: Session, payload: MonitorTaskCreateRequest, current: CurrentSession) -> GeoMonitorTask:
    """提交模力指数任务并保存主任务与初始子任务。"""
    tenant_id = _effective_tenant_id(current, payload.tenant_id)
    if tenant_id is None:
        raise ValueError("请先选择或绑定企业，再提交 GEO 检测任务")
    tenant = db.scalar(select(Tenant).where(Tenant.id == tenant_id, Tenant.deleted.is_(False)))
    if tenant is None:
        raise ValueError("所属企业不存在")
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
        raise ValueError("模力指数提交成功但未返回 taskId")
    existing = db.scalar(select(GeoMonitorTask).where(GeoMonitorTask.task_id == task_id))
    if existing is not None:
        raise ValueError(f"任务已存在：{task_id}")
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
        platforms_json=[item.model_dump() for item in payload.platforms],
        region_code_json=payload.region_code,
        callback_url=data.get("callbackUrl"),
        poll_url=data.get("pollUrl"),
        raw_request_json=request_body,
        raw_response_json=response,
    )
    db.add(task)
    for subtask in data.get("subTaskList") or []:
        _upsert_subtask(db, task_id, subtask)
    db.commit()
    db.refresh(task)
    return task


def list_monitor_tasks(db: Session, current: CurrentSession) -> list[GeoMonitorTask]:
    """读取本地任务列表，不隐式调用模力指数远端。"""
    stmt = select(GeoMonitorTask).where(GeoMonitorTask.deleted.is_(False)).order_by(GeoMonitorTask.id.desc())
    if current.identity.identity_type == "CUSTOMER":
        stmt = stmt.where(GeoMonitorTask.tenant_id == current.identity.tenant_id)
    return list(db.scalars(stmt))


def monitor_summary(db: Session, current: CurrentSession) -> dict[str, Any]:
    """Build a read-only dashboard summary from stored Molizhishu task results."""
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
    tasks = list(db.scalars(stmt).unique())
    tenant_rows = list(db.scalars(select(Tenant).where(Tenant.deleted.is_(False))))
    tenant_map = {item.id: item.name for item in tenant_rows}
    tenant_ids = [task.tenant_id for task in tasks if task.tenant_id]
    asset_rows = list(db.scalars(select(BrandAsset).where(BrandAsset.tenant_id.in_(tenant_ids), BrandAsset.deleted.is_(False)))) if tenant_ids else []
    purchased_platforms_by_tenant = {
        asset.tenant_id: set(asset.monitored_platforms_json or [])
        for asset in asset_rows
    }
    exposure_terms_by_tenant = {
        asset.tenant_id: brand_exposure_terms(asset, active_keyword_groups(db, asset.tenant_id))
        for asset in asset_rows
    }
    subtask_tenant_map = {subtask.id: task.tenant_id for task in tasks for subtask in task.subtasks}
    subtasks = [subtask for task in tasks for subtask in task.subtasks]
    completed = [item for item in subtasks if item.status in TERMINAL_STATUSES]
    completed_ids = {item.id for item in completed}
    mentioned = [item for item in completed if item.mention_position is not None]
    total_cost = sum(float(item.amount or 0) for item in subtasks)
    mention_rate = round(len(mentioned) / len(completed) * 100, 1) if completed else 0.0
    avg_rank = round(sum(item.mention_position for item in mentioned) / len(mentioned), 1) if mentioned else 0.0

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
    platform_stats.sort(key=lambda item: (item["mention_rate"], -(item["avg_rank"] or 99)), reverse=True)

    source_map: dict[str, dict[str, Any]] = {}
    for item in completed:
        purchased_platforms = purchased_platforms_by_tenant.get(subtask_tenant_map.get(item.id))
        if purchased_platforms and item.platform not in purchased_platforms:
            continue
        for source in item.reference_list_json or []:
            if not _is_valid_citation_source(source):
                continue
            url = source.get("url") or source.get("site") or source.get("title")
            if not url:
                continue
            key = str(url).split("?")[0]
            tenant_id = subtask_tenant_map.get(item.id)
            exposure_terms = exposure_terms_by_tenant.get(tenant_id, [])
            matched_exposure = _matched_source_keywords(source, exposure_terms)
            if not matched_exposure:
                continue
            row = source_map.setdefault(
                key,
                {
                    "title": source.get("title") or source.get("site") or key,
                    "url": url,
                    "count": 0,
                    "platforms": [],
                    "exposure_terms": [],
                    "questions": [],
                    "latest_time": None,
                },
            )
            row["count"] += 1
            if item.platform and item.platform not in row["platforms"]:
                row["platforms"].append(item.platform)
            for term in matched_exposure:
                if term not in row["exposure_terms"]:
                    row["exposure_terms"].append(term)
            if item.prompt and item.prompt not in row["questions"]:
                row["questions"].append(item.prompt)
            if item.updated_at and (row["latest_time"] is None or item.updated_at.isoformat() > row["latest_time"]):
                row["latest_time"] = item.updated_at.isoformat()
    source_stats = sorted(source_map.values(), key=lambda item: item["count"], reverse=True)
    for row in source_stats:
        row["platforms"] = row["platforms"][:6]
        row["exposure_terms"] = row["exposure_terms"][:8]
        row["questions"] = row["questions"][:8]

    today = datetime.now().date()
    day_labels = []
    daily_trend = []
    for offset in range(6, -1, -1):
        day = today - timedelta(days=offset)
        value = sum(1 for item in mentioned if item.updated_at and item.updated_at.date() == day)
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
        "scope": current.identity.identity_type,
        "tenant_id": current.identity.tenant_id,
        "tenant_count": len(tenant_rows) if current.identity.identity_type == "PLATFORM" else 1,
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
    return task


def get_monitor_subtask(db: Session, subtask_id: str, current: CurrentSession) -> GeoMonitorSubtask:
    """读取单个子任务详情，并按身份做租户隔离。"""
    stmt = (
        select(GeoMonitorSubtask)
        .join(GeoMonitorTask, GeoMonitorTask.task_id == GeoMonitorSubtask.task_id)
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
    return subtask


def sync_monitor_task(db: Session, task_id: str, current: CurrentSession) -> GeoMonitorTask:
    """手动同步远端状态和结果，只有显式调用该接口才请求模力指数。"""
    task = get_monitor_task(db, task_id, current)
    client = MolizhishuClient()
    try:
        status_response = client.get_task_status(task_id)
        status_data = status_response.get("data") or {}
        task.status = status_data.get("status") or task.status
        task.total_items = status_data.get("totalItems") or task.total_items
        task.completed_items = status_data.get("completedItems") or task.completed_items
        task.failed_items = status_data.get("failedItems") or task.failed_items
        task.remote_created_at = status_data.get("createdAt") or task.remote_created_at
        task.remote_completed_at = status_data.get("completedAt") or task.remote_completed_at
        for subtask in status_data.get("subTaskList") or []:
            _upsert_subtask(db, task_id, subtask)
        if task.status in TERMINAL_STATUSES or task.completed_items > 0:
            result_response = client.get_task_result(task_id)
            result_data = result_response.get("data") or {}
            task.status = result_data.get("status") or task.status
            task.total_items = result_data.get("totalItems") or task.total_items
            task.completed_items = result_data.get("completedItems") or task.completed_items
            task.failed_items = result_data.get("failedItems") or task.failed_items
            for subtask in result_data.get("subTaskList") or []:
                _upsert_subtask(db, task_id, subtask)
        task.last_error = None
        _reconcile_task_progress(task)
    except Exception as exc:
        task.last_error = str(exc)
        db.commit()
        raise
    db.commit()
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
        "page_screenshot": subtask.page_screenshot,
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
        "page_screenshot": subtask.page_screenshot,
        "reference_count": reference_count,
        "reference_list": [],
        "error_message": subtask.error_message,
        "mention_position": subtask.mention_position,
        "mention_context": subtask.mention_context,
        "sentiment": subtask.sentiment,
        "amount": float(subtask.amount) if subtask.amount is not None else None,
        "updated_at": subtask.updated_at.isoformat() if subtask.updated_at else None,
    }


def _resolve_matrix_tenant_id(current: CurrentSession) -> int | None:
    if current.identity.identity_type == "CUSTOMER":
        return current.identity.tenant_id
    return None


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


def _prompt_group_name(prompt: str, groups: list[BrandKeywordGroup]) -> str | None:
    for group in groups:
        keywords = keyword_group_monitor_keywords(group)
        if _prompt_belongs_to_group(prompt, keywords, group.exposure_terms_json or []):
            return keyword_group_display_label(group) or keyword_group_primary_keyword(group) or None
    return None


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


def _matrix_day_key(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.date().isoformat()


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
    if max_samples and max_samples > 0 and len(ordered) > max_samples:
        ordered = ordered[:max_samples]
    return ordered


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
        "updated_at": sample.get("updated_at"),
        "status": sample.get("status"),
        "page_screenshot": sample.get("page_screenshot"),
        "sentiment": sample.get("sentiment"),
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
        for fragment in _brand_term_match_fragments(term):
            token = fragment.lower()
            if len(token) >= 2 and token in normalized:
                return True
    return False


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
            if len(token) >= 2 and (token in normalized or normalized in token):
                return True
    return False


def _find_brand_in_rankings(
    subtask: GeoMonitorSubtask,
    brand_terms: list[str],
    asset: BrandAsset | None,
) -> tuple[int | float | None, bool]:
    """Match exposure terms in structured or parsed answer rankings (category-local rank)."""

    def match_name(name: str) -> bool:
        return _name_matches_brand(name, brand_terms)

    def skip_name(name: str) -> bool:
        return asset is not None and _is_industry_monitor_keyword(name, asset)

    text = _subtask_answer_plaintext(subtask)
    for entries in (
        normalize_structured_rankings(subtask.all_rankings_json or []),
        parse_answer_rankings(text),
    ):
        if not entries:
            continue
        rank, matched = find_best_brand_rank(entries, match_name, skip_name=skip_name)
        if rank is not None:
            return rank, True
        if matched:
            return None, True
    return None, False


def _appearance_order_rank(text: str, brand_terms: list[str]) -> int | None:
    """When answer has no category/numbered list, rank by first short-line appearance order."""
    order = 0
    for raw_line in text.splitlines():
        line = re.sub(r"<[^>]+>", " ", raw_line)
        line = re.sub(r"\s+", " ", line).strip()
        if not line or len(line) > 120:
            continue
        if _is_category_header_line(line):
            continue
        order += 1
        if _brand_appears_in_text(line, brand_terms):
            return order
    return None


def _is_category_header_line(line: str) -> bool:
    from app.services.ranking_parser import _is_category_header
    return _is_category_header(line)


def _resolve_brand_rank(
    subtask: GeoMonitorSubtask,
    monitor_keywords: str | None,
    brand_terms: list[str],
    asset: BrandAsset | None = None,
) -> tuple[int | float | None, bool]:
    """Return brand list rank for ranking prompts; exposure prompts only report mention."""
    combined_text = _subtask_brand_text(subtask)
    has_brand_in_text = _brand_appears_in_text(combined_text, brand_terms)
    if prompt_monitor_intent(subtask.prompt) != "ranking":
        return None, has_brand_in_text

    monitor_keyword = str(monitor_keywords or "").strip()
    is_industry_task = asset is not None and _is_industry_monitor_keyword(monitor_keyword, asset)

    rank_from_list, in_ranking_list = _find_brand_in_rankings(subtask, brand_terms, asset)
    if rank_from_list is not None:
        return rank_from_list, True
    if in_ranking_list:
        return None, True

    if is_industry_task:
        return None, has_brand_in_text

    # Fallback: plain appearance order in answer when no list/category rank was parsed.
    if has_brand_in_text:
        appearance_rank = _appearance_order_rank(_subtask_answer_plaintext(subtask), brand_terms)
        if appearance_rank is not None:
            return appearance_rank, True

    if subtask.mention_position is not None:
        return subtask.mention_position, True

    return None, has_brand_in_text


def _matrix_cell_rank(
    subtask: GeoMonitorSubtask,
    monitor_keywords: str | None,
    asset: BrandAsset | None,
    keyword_groups: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    ranking_terms = _ranking_match_terms(asset, keyword_groups)
    brand_rank, brand_mentioned = _resolve_brand_rank(subtask, monitor_keywords, ranking_terms, asset)
    return {
        "mention_position": brand_rank,
        "raw_mention_position": subtask.mention_position,
        "brand_mentioned": brand_mentioned,
        "monitor_keyword": monitor_keywords,
        "ranking_terms": ranking_terms,
        "prompt_intent": prompt_monitor_intent(subtask.prompt),
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
    if asset is None:
        return data
    rank_payload = _matrix_cell_rank(subtask, monitor_keywords, asset, keyword_groups)
    data["raw_mention_position"] = rank_payload["raw_mention_position"]
    data["brand_mentioned"] = rank_payload["brand_mentioned"]
    data["brand_rank"] = rank_payload["mention_position"]
    data["mention_position"] = rank_payload["mention_position"]
    data["prompt_intent"] = rank_payload["prompt_intent"]
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
    limit_rows: int = 120,
) -> dict[str, Any]:
    """Build prompt × daily-average ranking matrix for realtime monitor view."""
    tenant_id = _resolve_matrix_tenant_id(current)
    if tenant_id is None:
        raise ValueError("排名矩阵仅支持客户侧查看，请使用企业账号登录")

    now = datetime.now()
    range_start = start_at or (now - timedelta(days=7))
    range_end = end_at or now
    if range_start > range_end:
        range_start, range_end = range_end, range_start

    asset = get_brand_asset(db, tenant_id)
    keyword_group_rows = list_keyword_groups(db, tenant_id)
    keyword_groups = [
        keyword_group_to_dict(item)
        for item in keyword_group_rows
        if item.status and item.monitor_keyword
    ] if keyword_group_rows else active_keyword_groups(db, tenant_id)
    purchased_platforms = list(asset.monitored_platforms_json or []) if asset else []
    daily_sample_cap = int(getattr(asset, "schedule_frequency", 0) or 0) or None
    platform_filter = str(platform or "").strip()
    all_platforms = not platform_filter or platform_filter.lower() == "all"
    selected_platform = None if all_platforms else platform_filter

    stmt = (
        select(GeoMonitorSubtask)
        .join(GeoMonitorTask, GeoMonitorTask.task_id == GeoMonitorSubtask.task_id)
        .options(
            joinedload(GeoMonitorSubtask.task).load_only(
                GeoMonitorTask.monitor_keywords,
                GeoMonitorTask.created_at,
            ),
            load_only(
                GeoMonitorSubtask.subtask_id,
                GeoMonitorSubtask.task_id,
                GeoMonitorSubtask.platform,
                GeoMonitorSubtask.prompt,
                GeoMonitorSubtask.status,
                GeoMonitorSubtask.page_screenshot,
                GeoMonitorSubtask.mention_position,
                GeoMonitorSubtask.mention_context,
                GeoMonitorSubtask.all_rankings_json,
                GeoMonitorSubtask.sentiment,
                GeoMonitorSubtask.updated_at,
            )
        )
        .where(
            GeoMonitorTask.deleted.is_(False),
            GeoMonitorTask.tenant_id == tenant_id,
            GeoMonitorSubtask.updated_at >= range_start,
            GeoMonitorSubtask.updated_at <= range_end,
            GeoMonitorSubtask.status.in_(("completed", "partial_completed")),
        )
        .order_by(GeoMonitorSubtask.updated_at.desc())
    )
    if selected_platform:
        stmt = stmt.where(GeoMonitorSubtask.platform == selected_platform)

    subtasks = list(db.scalars(stmt.limit(5000)))
    group_filter = (monitor_group or keyword or "").strip()
    if group_filter:
        subtasks = _filter_subtasks_by_monitor_group(subtasks, group_filter, keyword_groups)

    if not all_platforms and subtasks:
        selected_platform = subtasks[0].platform

    task_ids = list({item.task_id for item in subtasks if item.task_id})
    schedule_runs_map = schedule_runs_for_tasks(db, task_ids)

    prompt_set: dict[str, str | None] = {}
    task_rows: dict[str, dict[str, Any]] = {}

    for item in subtasks:
        prompt = (item.prompt or "").strip()
        task_id = (item.task_id or "").strip()
        if not prompt or not task_id or item.task is None:
            continue
        if prompt_monitor_intent(prompt) != "ranking":
            continue
        day_key = _matrix_day_key(item.updated_at)
        if not day_key:
            continue
        schedule_ctx = resolve_task_schedule_context(
            item.task,
            schedule_runs_map.get(task_id),
            asset,
        )
        keyword_group = schedule_ctx.get("keyword_group")
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
            "status": item.status,
            "page_screenshot": item.page_screenshot,
            "sentiment": item.sentiment,
            "updated_at": item.updated_at.isoformat() if item.updated_at else None,
            **rank_payload,
            "_updated_at": item.updated_at,
        }
        bucket["cell_samples"].setdefault(prompt, []).append(cell)

    columns = [
        {"prompt": prompt, "group_name": prompt_set[prompt]}
        for prompt in sorted(prompt_set.keys(), key=lambda text: (prompt_set[text] or "zzz", text))
    ]

    group_map: dict[str, list[str]] = {}
    for column in columns:
        group_name = column["group_name"] or "其他监测问题"
        group_map.setdefault(group_name, []).append(column["prompt"])
    prompt_groups = [{"name": name, "prompts": prompts} for name, prompts in group_map.items()]

    sorted_tasks = sorted(
        task_rows.values(),
        key=lambda row: (
            row.get("day_key") or "",
            row.get("keyword_group") or "",
            row.get("platform") or "",
        ),
        reverse=True,
    )[:limit_rows]
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

    schedule_round_count = len({row.get("day_key") for row in rows if row.get("day_key")})

    return {
        "platform": selected_platform,
        "all_platforms": all_platforms,
        "brand_name": asset.brand_name if asset else None,
        "start_at": range_start.isoformat(),
        "end_at": range_end.isoformat(),
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


def workspace_brief(db: Session, current: CurrentSession) -> dict[str, Any]:
    """Customer workspace dashboard: schedule round, intent-aware KPIs, snapshots, top sources."""
    if current.identity.identity_type != "CUSTOMER" or current.identity.tenant_id is None:
        raise ValueError("运营工作台简报仅支持客户企业账号")

    tenant_id = current.identity.tenant_id
    now = datetime.now()
    range_start = now - timedelta(days=7)

    asset = get_brand_asset(db, tenant_id)
    keyword_group_rows = list_keyword_groups(db, tenant_id)
    keyword_groups = [
        keyword_group_to_dict(item)
        for item in keyword_group_rows
        if item.status and item.monitor_keyword
    ] if keyword_group_rows else active_keyword_groups(db, tenant_id)
    purchased_platforms = list(asset.monitored_platforms_json or []) if asset else []
    purchased_set = set(purchased_platforms)

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
                GeoMonitorSubtask.answer_content,
                GeoMonitorSubtask.mention_context,
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
            GeoMonitorSubtask.updated_at >= range_start,
            GeoMonitorSubtask.status.in_(("completed", "partial_completed")),
        )
        .order_by(GeoMonitorSubtask.updated_at.desc())
    )
    subtasks = list(db.scalars(stmt.limit(3000)))
    if purchased_set:
        subtasks = [item for item in subtasks if item.platform in purchased_set]

    task_ids = list({item.task_id for item in subtasks if item.task_id})
    schedule_runs_map = schedule_runs_for_tasks(db, task_ids)

    schedule_buckets: dict[str, dict[str, Any]] = {}
    window_ranking: dict[str, list[dict[str, Any]]] = {}
    window_exposure: dict[str, list[dict[str, Any]]] = {}
    ranking_rows: list[dict[str, Any]] = []
    exposure_rows: list[dict[str, Any]] = []
    daily_ranking: dict[str, list[dict[str, Any]]] = {}
    daily_exposure: dict[str, list[dict[str, Any]]] = {}
    source_map: dict[str, dict[str, Any]] = {}
    snapshot_candidates: list[dict[str, Any]] = []

    for item in subtasks:
        if item.task is None:
            continue
        intent = prompt_monitor_intent(item.prompt)
        schedule_ctx = resolve_task_schedule_context(
            item.task,
            schedule_runs_map.get(item.task_id or ""),
            asset,
        )
        window_key = str(schedule_ctx.get("schedule_window_key") or item.task_id or "")
        bucket = schedule_buckets.setdefault(
            window_key,
            {
                "schedule_window_key": window_key,
                "schedule_label": schedule_ctx.get("schedule_label"),
                "completed_subtasks": 0,
                "total_subtasks": 0,
            },
        )
        bucket["total_subtasks"] += 1
        bucket["completed_subtasks"] += 1

        monitor_keywords = item.task.monitor_keywords
        brand_rank, brand_mentioned = _resolve_brand_rank(
            item,
            monitor_keywords,
            _ranking_match_terms(asset, keyword_groups),
            asset,
        )
        keyword_group = _prompt_group_name(item.prompt or "", keyword_group_rows) or monitor_keywords
        sentiment_label = _normalize_sentiment_label(item.sentiment)

        row_payload = {
            "subtask_id": item.subtask_id,
            "task_id": item.task_id,
            "platform": item.platform,
            "prompt": item.prompt,
            "keyword_group": keyword_group,
            "schedule_label": schedule_ctx.get("schedule_label"),
            "schedule_window_key": window_key,
            "prompt_intent": intent,
            "brand_rank": brand_rank,
            "brand_mentioned": brand_mentioned,
            "sentiment": sentiment_label,
            "answer_excerpt": _answer_excerpt(item.answer_content, 100),
            "updated_at": item.updated_at.isoformat() if item.updated_at else None,
        }
        snapshot_candidates.append(row_payload)

        if intent == "ranking":
            ranking_rows.append(row_payload)
            window_ranking.setdefault(window_key, []).append(row_payload)
            if item.updated_at:
                day_key = item.updated_at.date().isoformat()
                daily_ranking.setdefault(day_key, []).append(row_payload)

        else:
            exposure_rows.append(row_payload)
            window_exposure.setdefault(window_key, []).append(row_payload)
            if item.updated_at:
                day_key = item.updated_at.date().isoformat()
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

    latest_key = None
    previous_key = None
    latest_schedule = None
    previous_schedule = None
    round_comparison: dict[str, Any] = {
        "has_previous": False,
        "latest_schedule_label": None,
        "previous_schedule_label": None,
        "avg_brand_rank_delta": None,
        "mention_rate_delta": None,
        "top3_rate_delta": None,
        "negative_count_delta": None,
    }
    if schedule_buckets:
        sorted_windows = sorted(schedule_buckets.keys(), key=schedule_window_sort_key)
        latest_key = sorted_windows[-1]
        latest_schedule = schedule_buckets[latest_key]
        latest_metrics = _round_metrics_from_rows(
            window_ranking.get(latest_key, []),
            window_exposure.get(latest_key, []),
        )
        round_comparison["latest_schedule_label"] = latest_schedule.get("schedule_label")
        if len(sorted_windows) >= 2:
            previous_key = sorted_windows[-2]
            previous_schedule = schedule_buckets[previous_key]
            previous_metrics = _round_metrics_from_rows(
                window_ranking.get(previous_key, []),
                window_exposure.get(previous_key, []),
            )
            round_comparison["has_previous"] = True
            round_comparison["previous_schedule_label"] = previous_schedule.get("schedule_label")
            if latest_metrics["avg_brand_rank"] is not None and previous_metrics["avg_brand_rank"] is not None:
                round_comparison["avg_brand_rank_delta"] = round(
                    latest_metrics["avg_brand_rank"] - previous_metrics["avg_brand_rank"],
                    1,
                )
            round_comparison["mention_rate_delta"] = round(
                latest_metrics["brand_mention_rate"] - previous_metrics["brand_mention_rate"],
                1,
            )
            round_comparison["top3_rate_delta"] = round(
                latest_metrics["top3_rate"] - previous_metrics["top3_rate"],
                1,
            )
            round_comparison["negative_count_delta"] = (
                latest_metrics["negative_count"] - previous_metrics["negative_count"]
            )

    ranking_total = len(ranking_rows)
    ranking_mentioned = sum(1 for row in ranking_rows if row.get("brand_mentioned"))
    rank_values = [float(row["brand_rank"]) for row in ranking_rows if row.get("brand_rank") is not None]
    competitor_count = len(list_competitors(db, tenant_id))

    brand_mention_rate = round(ranking_mentioned / ranking_total * 100, 1) if ranking_total else 0.0
    avg_brand_rank = round(sum(rank_values) / len(rank_values), 1) if rank_values else None
    top3_rate = _top3_rate_from_ranking_rows(ranking_rows)

    exposure_recognized = [row for row in exposure_rows if row.get("sentiment") in ("正面", "中性", "负面")]
    negative_count = sum(1 for row in exposure_rows if row.get("sentiment") == "负面")
    negative_rate = round(negative_count / len(exposure_recognized) * 100, 1) if exposure_recognized else 0.0

    latest_platform_stats = _platform_stats_from_ranking_rows(
        window_ranking.get(latest_key, []) if latest_key else ranking_rows
    )
    previous_platform_stats = _platform_stats_from_ranking_rows(
        window_ranking.get(previous_key, []) if previous_key else []
    )
    platform_highlights = [
        _platform_highlight_entry(
            code,
            latest_platform_stats.get(code),
            previous_platform_stats.get(code) if round_comparison.get("has_previous") else None,
        )
        for code in purchased_platforms
    ]
    kpi_trends = _build_workspace_kpi_trends(daily_ranking, daily_exposure, range_start, now)

    top_sources = sorted(source_map.values(), key=lambda row: row["count"], reverse=True)[:5]
    for row in top_sources:
        row["platforms"] = row["platforms"][:4]

    recent_snapshots = snapshot_candidates[:6]

    alerts: list[dict[str, str]] = []
    if not subtasks:
        alerts.append({
            "level": "info",
            "message": "近 7 日暂无已完成检测结果，请等待定时监测任务返回。",
        })
    elif negative_count > 0:
        alerts.append({
            "level": "warn",
            "message": f"近 7 日口碑类问题中有 {negative_count} 条负面样本，建议查看实时检测详情。",
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
                "message": f"较上一轮，推荐类露出率下降 {abs(mention_delta):.1f}%。",
            })
        neg_delta = round_comparison.get("negative_count_delta")
        if neg_delta is not None and neg_delta > 0:
            alerts.append({
                "level": "warn",
                "message": f"较上一轮，负面样本增加 {neg_delta} 条。",
            })
    for highlight in platform_highlights:
        if highlight["sample_count"] == 0 and highlight["platform"] in purchased_set:
            alerts.append({
                "level": "info",
                "message": f"平台 {highlight['platform']} 近 7 日暂无推荐类返回，请确认监测配置。",
            })

    plan = schedule_plan_summary(asset)
    schedule_times = plan.get("schedule_times") or []
    next_schedule_hint = f"每日 {('、'.join(schedule_times))}" if schedule_times else plan.get("schedule_type_label")

    return {
        "tenant_id": tenant_id,
        "brand_name": asset.brand_name if asset else None,
        "company_name": asset.company_full_name if asset else None,
        "start_at": range_start.isoformat(),
        "end_at": now.isoformat(),
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
            "exposure_sample_count": len(exposure_rows),
            "negative_count": negative_count,
            "negative_rate": negative_rate,
            "source_count": sum(row["count"] for row in source_map.values()),
            "keyword_group_count": len(keyword_groups),
            "competitor_count": competitor_count,
        },
        "purchased_platforms": purchased_platforms,
        "platform_highlights": platform_highlights,
        "top_sources": top_sources,
        "recent_snapshots": recent_snapshots,
        "alerts": alerts,
    }
