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
from app.schemas.monitor import MonitorTaskCreateRequest
from app.services.brand_service import (
    _is_industry_monitor_keyword,
    brand_exposure_terms,
    get_brand_asset,
    keyword_group_to_dict,
    list_keyword_groups,
    molizhishu_brand_payload,
    molizhishu_monitor_terms,
)
from app.services.molizhishu_client import MolizhishuClient
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


def _is_relevant_source(source: dict[str, Any], terms: list[str]) -> bool:
    """判断引用来源是否与当前企业相关，过滤搜索页热榜和同名无关公司。"""
    if not terms:
        return True
    title_site = " ".join(str(source.get(key) or "") for key in ("title", "site")).lower()
    url = str(source.get("url") or "").lower()
    noisy_tokens = ("window._", "search.quark.cn", "by2=news")
    if not title_site or any(token in title_site or token in url for token in noisy_tokens):
        return False
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
    request_body: dict[str, Any] = {
        "prompts": payload.prompts,
        "platforms": [item.model_dump() for item in payload.platforms],
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
    source_terms_by_tenant = {asset.tenant_id: _source_filter_terms(asset) for asset in asset_rows}
    purchased_platforms_by_tenant = {
        asset.tenant_id: set(asset.monitored_platforms_json or [])
        for asset in asset_rows
    }
    subtask_tenant_map = {subtask.id: task.tenant_id for task in tasks for subtask in task.subtasks}
    subtask_task_map = {subtask.id: task for task in tasks for subtask in task.subtasks}
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
        task = subtask_task_map.get(item.id)
        purchased_platforms = purchased_platforms_by_tenant.get(subtask_tenant_map.get(item.id))
        if purchased_platforms and item.platform not in purchased_platforms:
            continue
        for source in item.reference_list_json or []:
            terms = source_terms_by_tenant.get(subtask_tenant_map.get(item.id))
            if not _is_relevant_source(source, terms or []):
                continue
            url = source.get("url") or source.get("site") or source.get("title")
            if not url:
                continue
            key = str(url).split("?")[0]
            task_keywords = _split_keywords(task.monitor_keywords if task else None)
            matched_keywords = _matched_source_keywords(source, task_keywords) or task_keywords[:3]
            row = source_map.setdefault(
                key,
                {
                    "title": source.get("title") or source.get("site") or key,
                    "url": url,
                    "count": 0,
                    "platforms": [],
                    "keywords": [],
                    "questions": [],
                    "latest_time": None,
                },
            )
            row["count"] += 1
            if item.platform and item.platform not in row["platforms"]:
                row["platforms"].append(item.platform)
            for keyword in matched_keywords:
                if keyword not in row["keywords"]:
                    row["keywords"].append(keyword)
            if item.prompt and item.prompt not in row["questions"]:
                row["questions"].append(item.prompt)
            if item.updated_at and (row["latest_time"] is None or item.updated_at.isoformat() > row["latest_time"]):
                row["latest_time"] = item.updated_at.isoformat()
    source_stats = sorted(source_map.values(), key=lambda item: item["count"], reverse=True)[:12]
    for row in source_stats:
        row["platforms"] = row["platforms"][:6]
        row["keywords"] = row["keywords"][:8]
        row["questions"] = row["questions"][:5]

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
) -> dict[str, Any]:
    """转换任务为前端友好的字典。"""
    _reconcile_task_progress(task)
    payload = {
        "task_id": task.task_id,
        "tenant_id": task.tenant_id,
        "monitor_keywords": task.monitor_keywords,
        "status": task.status,
        "total_items": task.total_items,
        "completed_items": task.completed_items,
        "failed_items": task.failed_items,
        "prompts": task.prompts_json,
        "platforms": task.platforms_json,
        "callback_url": task.callback_url,
        "poll_url": task.poll_url,
        "last_error": task.last_error,
        "created_at": task.created_at.isoformat(),
        "updated_at": task.updated_at.isoformat(),
    }
    payload.update(resolve_task_schedule_context(task, schedule_run, asset))
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
    return [
        serialize_task(
            task,
            schedule_run=runs_map.get(task.task_id),
            asset=assets.get(task.tenant_id),
        )
        for task in tasks
    ]


def serialize_subtask(subtask: GeoMonitorSubtask) -> dict[str, Any]:
    """转换子任务为前端友好的字典。"""
    return {
        "subtask_id": subtask.subtask_id,
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
    monitor_keyword: str,
    exposure_terms: list[str] | None = None,
) -> bool:
    text = (prompt or "").strip()
    keyword = str(monitor_keyword or "").strip()
    if keyword and keyword in text:
        return True
    for term in exposure_terms or []:
        token = str(term or "").strip()
        if token and token in text:
            return True
    return False


def _prompt_group_name(prompt: str, groups: list[BrandKeywordGroup]) -> str | None:
    for group in groups:
        keyword = str(group.monitor_keyword or "").strip()
        if _prompt_belongs_to_group(prompt, keyword, group.exposure_terms_json or []):
            return keyword or None
    return None


def _snapshot_minute(value: datetime | None) -> str | None:
    if not value:
        return None
    bucket = value.replace(second=0, microsecond=0)
    return bucket.strftime("%Y-%m-%d %H:%M")


def _matrix_row_key(
    task_id: str,
    platform: str,
    *,
    all_platforms: bool,
    schedule_window_key: str | None,
    keyword_group: str | None,
) -> str:
    parts = [schedule_window_key or task_id, keyword_group or "", platform if all_platforms else ""]
    return "|".join(part for part in parts if part)


def _strip_html_for_match(text: str | None) -> str:
    if not text:
        return ""
    cleaned = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", cleaned).strip()


def _brand_match_terms(asset: BrandAsset | None, keyword_groups: list[dict[str, Any]] | None = None) -> list[str]:
    """Collect brand/company terms: 简称/品牌名/公司名 + 露出词，排除行业监测词。"""
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


def _brand_appears_in_text(text: str | None, brand_terms: list[str]) -> bool:
    normalized = (text or "").lower()
    if not normalized:
        return False
    for term in brand_terms:
        token = term.strip().lower()
        if len(token) >= 2 and token in normalized:
            return True
    return False


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
    return False


def _ranking_entry_value(entry: dict[str, Any]) -> int | float | None:
    for key in ("rank", "position", "rankNo", "mentionPosition"):
        value = entry.get(key)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
    return None


def _resolve_brand_rank(
    subtask: GeoMonitorSubtask,
    monitor_keywords: str | None,
    brand_terms: list[str],
    asset: BrandAsset | None = None,
) -> tuple[int | float | None, bool]:
    """Return brand list rank for ranking prompts; exposure prompts only report mention."""
    answer_text = _strip_html_for_match(subtask.answer_content)
    has_brand_in_answer = _brand_appears_in_text(answer_text, brand_terms)
    if prompt_monitor_intent(subtask.prompt) != "ranking":
        return None, has_brand_in_answer

    monitor_keyword = str(monitor_keywords or "").strip()
    is_industry_task = asset is not None and _is_industry_monitor_keyword(monitor_keyword, asset)

    for entry in subtask.all_rankings_json or []:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or entry.get("brandName") or entry.get("brand") or entry.get("keyword") or "").strip()
        if not name or not _name_matches_brand(name, brand_terms):
            continue
        if asset is not None and _is_industry_monitor_keyword(name, asset):
            continue
        rank = _ranking_entry_value(entry)
        if rank is not None and has_brand_in_answer:
            return rank, True

    if is_industry_task:
        return None, has_brand_in_answer

    if subtask.mention_position is not None and has_brand_in_answer:
        if monitor_keyword and _name_matches_brand(monitor_keyword, brand_terms):
            return subtask.mention_position, True

    return None, has_brand_in_answer


def _matrix_cell_rank(
    subtask: GeoMonitorSubtask,
    monitor_keywords: str | None,
    asset: BrandAsset | None,
    keyword_groups: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    brand_terms = _brand_match_terms(asset, keyword_groups)
    brand_rank, brand_mentioned = _resolve_brand_rank(subtask, monitor_keywords, brand_terms, asset)
    return {
        "mention_position": brand_rank,
        "raw_mention_position": subtask.mention_position,
        "brand_mentioned": brand_mentioned,
        "monitor_keyword": monitor_keywords,
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
    """Build prompt × snapshot ranking matrix for realtime monitor view."""
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
    ]
    purchased_platforms = list(asset.monitored_platforms_json or []) if asset else []
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
        selected_group = next(
            (group for group in keyword_groups if str(group.get("monitor_keyword") or "").strip() == group_filter),
            None,
        )
        if selected_group:
            subtasks = [
                item for item in subtasks
                if _prompt_belongs_to_group(
                    item.prompt or "",
                    str(selected_group.get("monitor_keyword") or ""),
                    selected_group.get("exposure_terms") or [],
                )
            ]
        else:
            keyword_text = group_filter.lower()
            subtasks = [
                item for item in subtasks
                if keyword_text in (item.prompt or "").lower()
            ]

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
        schedule_ctx = resolve_task_schedule_context(
            item.task,
            schedule_runs_map.get(task_id),
            asset,
        )
        prompt_set.setdefault(prompt, _prompt_group_name(prompt, keyword_group_rows))
        row_key = _matrix_row_key(
            task_id,
            item.platform,
            all_platforms=all_platforms,
            schedule_window_key=schedule_ctx.get("schedule_window_key"),
            keyword_group=schedule_ctx.get("keyword_group"),
        )
        bucket = task_rows.setdefault(row_key, {
            "task_id": task_id,
            "platform": item.platform if all_platforms else None,
            "latest_at": None,
            "cells": {},
            **schedule_ctx,
        })
        if item.updated_at and (
            bucket["latest_at"] is None or item.updated_at > bucket["latest_at"]
        ):
            bucket["latest_at"] = item.updated_at
        monitor_keywords = item.task.monitor_keywords if item.task else None
        rank_payload = _matrix_cell_rank(item, monitor_keywords, asset, keyword_groups)
        cell = {
            "subtask_id": item.subtask_id,
            "status": item.status,
            "page_screenshot": item.page_screenshot,
            "sentiment": item.sentiment,
            "updated_at": item.updated_at.isoformat() if item.updated_at else None,
            **rank_payload,
        }
        existing = bucket["cells"].get(prompt)
        if existing is None or (item.updated_at and (
            not existing.get("_updated_at") or item.updated_at > existing["_updated_at"]
        )):
            bucket["cells"][prompt] = {**cell, "_updated_at": item.updated_at}

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
            schedule_window_sort_key(row.get("schedule_window_key")),
            row.get("keyword_group") or "",
            row.get("platform") or "",
        ),
        reverse=True,
    )[:limit_rows]
    rows = []
    for bucket in sorted_tasks:
        cells = bucket["cells"]
        rows.append({
            "task_id": bucket["task_id"],
            "platform": bucket.get("platform"),
            "schedule_key": bucket.get("schedule_key"),
            "schedule_window_key": bucket.get("schedule_window_key"),
            "schedule_label": bucket.get("schedule_label"),
            "schedule_source": bucket.get("schedule_source"),
            "keyword_group": bucket.get("keyword_group"),
            "snapshot_at": bucket.get("schedule_label"),
            "cells": {
                prompt: {
                    "subtask_id": payload["subtask_id"],
                    "mention_position": payload["mention_position"],
                    "raw_mention_position": payload["raw_mention_position"],
                    "brand_mentioned": payload["brand_mentioned"],
                    "monitor_keyword": payload["monitor_keyword"],
                    "prompt_intent": payload.get("prompt_intent"),
                    "status": payload["status"],
                    "page_screenshot": payload["page_screenshot"],
                    "sentiment": payload["sentiment"],
                    "updated_at": payload["updated_at"],
                }
                for prompt, payload in cells.items()
            },
        })

    schedule_round_count = len({
        row.get("schedule_window_key")
        for row in rows
        if row.get("schedule_window_key")
    })

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
            {
                "monitor_keyword": str(group.get("monitor_keyword") or "").strip(),
                "exposure_terms": [
                    str(term or "").strip()
                    for term in (group.get("exposure_terms") or [])
                    if str(term or "").strip()
                ],
            }
            for group in keyword_groups
            if str(group.get("monitor_keyword") or "").strip()
        ],
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


def _resolve_sentiment_tenant_id(current: CurrentSession, tenant_id: int | None) -> int | None:
    if current.identity.identity_type == "CUSTOMER":
        return current.identity.tenant_id
    return tenant_id


def sentiment_overview(
    db: Session,
    current: CurrentSession,
    *,
    platform: str | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    monitor_group: str | None = None,
    schedule_window_key: str | None = None,
    sentiment_filter: str | None = None,
    tenant_id: int | None = None,
    item_limit: int = 200,
) -> dict[str, Any]:
    """Aggregate exposure-prompt sentiment stats and sample list for sentiment monitor page."""
    resolved_tenant_id = _resolve_sentiment_tenant_id(current, tenant_id)
    if resolved_tenant_id is None:
        raise ValueError("请使用企业账号登录，或指定 tenant_id")

    now = datetime.now()
    range_start = start_at or (now - timedelta(days=7))
    range_end = end_at or now
    if range_start > range_end:
        range_start, range_end = range_end, range_start

    asset = get_brand_asset(db, resolved_tenant_id)
    keyword_group_rows = list_keyword_groups(db, resolved_tenant_id)
    keyword_groups = [
        keyword_group_to_dict(item)
        for item in keyword_group_rows
        if item.status and item.monitor_keyword
    ]
    purchased_platforms = list(asset.monitored_platforms_json or []) if asset else []
    platform_filter = str(platform or "").strip()
    all_platforms = not platform_filter or platform_filter.lower() == "all"
    selected_platform = None if all_platforms else platform_filter
    schedule_filter = str(schedule_window_key or "").strip() or None

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
                GeoMonitorSubtask.answer_content,
                GeoMonitorSubtask.mention_position,
                GeoMonitorSubtask.all_rankings_json,
                GeoMonitorSubtask.sentiment,
                GeoMonitorSubtask.updated_at,
            ),
        )
        .where(
            GeoMonitorTask.deleted.is_(False),
            GeoMonitorTask.tenant_id == resolved_tenant_id,
            GeoMonitorSubtask.updated_at >= range_start,
            GeoMonitorSubtask.updated_at <= range_end,
            GeoMonitorSubtask.status.in_(("completed", "partial_completed")),
        )
        .order_by(GeoMonitorSubtask.updated_at.desc())
    )
    if selected_platform:
        stmt = stmt.where(GeoMonitorSubtask.platform == selected_platform)

    subtasks = list(db.scalars(stmt.limit(5000)))
    group_filter = str(monitor_group or "").strip()
    selected_group = None
    if group_filter:
        selected_group = next(
            (
                group for group in keyword_groups
                if str(group.get("monitor_keyword") or "").strip() == group_filter
            ),
            None,
        )
        if selected_group:
            subtasks = [
                item for item in subtasks
                if _prompt_belongs_to_group(
                    item.prompt or "",
                    str(selected_group.get("monitor_keyword") or ""),
                    selected_group.get("exposure_terms") or [],
                )
            ]
        else:
            keyword_text = group_filter.lower()
            subtasks = [item for item in subtasks if keyword_text in (item.prompt or "").lower()]

    exposure_subtasks = [
        item for item in subtasks
        if prompt_monitor_intent(item.prompt) == "exposure" and item.task is not None
    ]

    task_ids = list({item.task_id for item in exposure_subtasks if item.task_id})
    schedule_runs_map = schedule_runs_for_tasks(db, task_ids)
    brand_terms = _brand_match_terms(asset, keyword_groups)

    sentiment_counts = {"正面": 0, "中性": 0, "负面": 0, "未知": 0}
    platform_bucket: dict[str, dict[str, Any]] = {}
    trend_bucket: dict[str, dict[str, int]] = {}
    schedule_option_map: dict[str, str] = {}
    serialized_items: list[dict[str, Any]] = []

    for item in exposure_subtasks:
        schedule_ctx = resolve_task_schedule_context(
            item.task,
            schedule_runs_map.get(item.task_id or ""),
            asset,
        )
        window_key = schedule_ctx.get("schedule_window_key")
        schedule_label = schedule_ctx.get("schedule_label")
        if window_key and schedule_label:
            schedule_option_map.setdefault(str(window_key), str(schedule_label))
        if schedule_filter and str(window_key or "") != schedule_filter:
            continue

        label = _normalize_sentiment_label(item.sentiment)
        sentiment_counts[label] += 1

        platform_key = item.platform or "unknown"
        bucket = platform_bucket.setdefault(
            platform_key,
            {"platform": platform_key, "sample_count": 0, "counts": {"正面": 0, "中性": 0, "负面": 0, "未知": 0}},
        )
        bucket["sample_count"] += 1
        bucket["counts"][label] += 1

        if item.updated_at:
            day_label = item.updated_at.strftime("%m-%d")
            day_row = trend_bucket.setdefault(day_label, {"positive": 0, "neutral": 0, "negative": 0, "unknown": 0})
            if label == "正面":
                day_row["positive"] += 1
            elif label == "负面":
                day_row["negative"] += 1
            elif label == "中性":
                day_row["neutral"] += 1
            else:
                day_row["unknown"] += 1

        _, brand_mentioned = _resolve_brand_rank(
            item,
            item.task.monitor_keywords if item.task else None,
            brand_terms,
            asset,
        )
        keyword_group = _prompt_group_name(item.prompt or "", keyword_group_rows) or (
            item.task.monitor_keywords if item.task else None
        )
        serialized_items.append({
            "subtask_id": item.subtask_id,
            "platform": item.platform,
            "prompt": item.prompt,
            "keyword_group": keyword_group,
            "schedule_label": schedule_label,
            "schedule_window_key": window_key,
            "schedule_source": schedule_ctx.get("schedule_source"),
            "sentiment": label,
            "sentiment_raw": item.sentiment,
            "brand_mentioned": brand_mentioned,
            "prompt_intent": "exposure",
            "answer_excerpt": _answer_excerpt(item.answer_content),
            "updated_at": item.updated_at.isoformat() if item.updated_at else None,
        })

    recognized = sentiment_counts["正面"] + sentiment_counts["中性"] + sentiment_counts["负面"]
    positive_rate = round(sentiment_counts["正面"] / recognized * 100, 1) if recognized else 0.0
    negative_rate = round(sentiment_counts["负面"] / recognized * 100, 1) if recognized else 0.0
    neutral_rate = round(sentiment_counts["中性"] / recognized * 100, 1) if recognized else 0.0

    platform_stats = []
    for bucket in platform_bucket.values():
        counts = bucket["counts"]
        total = counts["正面"] + counts["中性"] + counts["负面"]
        platform_stats.append({
            "platform": bucket["platform"],
            "sample_count": bucket["sample_count"],
            "positive_rate": round(counts["正面"] / total * 100, 1) if total else 0.0,
            "negative_rate": round(counts["负面"] / total * 100, 1) if total else 0.0,
            "neutral_rate": round(counts["中性"] / total * 100, 1) if total else 0.0,
            "negative_count": counts["负面"],
        })
    platform_stats.sort(key=lambda row: (row["negative_rate"], row["negative_count"]), reverse=True)

    sorted_day_keys = sorted(
        trend_bucket.keys(),
        key=lambda label: datetime.strptime(f"2000-{label}", "%Y-%m-%d"),
    )
    sentiment_trend = [
        {"label": label, **trend_bucket[label]}
        for label in sorted_day_keys[-14:]
    ]

    schedule_options = [
        {"schedule_window_key": key, "schedule_label": label}
        for key, label in sorted(
            schedule_option_map.items(),
            key=lambda pair: schedule_window_sort_key(pair[0]),
            reverse=True,
        )
    ]

    tab = str(sentiment_filter or "all").strip().lower()
    filtered_items = serialized_items
    if tab in ("negative", "负面"):
        filtered_items = [item for item in serialized_items if item["sentiment"] == "负面"]
    elif tab in ("positive", "正面"):
        filtered_items = [item for item in serialized_items if item["sentiment"] == "正面"]
    elif tab in ("neutral", "中性"):
        filtered_items = [item for item in serialized_items if item["sentiment"] == "中性"]

    return {
        "tenant_id": resolved_tenant_id,
        "brand_name": asset.brand_name if asset else None,
        "start_at": range_start.isoformat(),
        "end_at": range_end.isoformat(),
        "sample_count": len(exposure_subtasks),
        "recognized_count": recognized,
        "unknown_count": sentiment_counts["未知"],
        "negative_count": sentiment_counts["负面"],
        "sentiment_counts": sentiment_counts,
        "positive_rate": positive_rate,
        "negative_rate": negative_rate,
        "neutral_rate": neutral_rate,
        "platform_stats": platform_stats,
        "sentiment_trend": sentiment_trend,
        "schedule_options": schedule_options,
        "keyword_group_options": [
            {
                "monitor_keyword": str(group.get("monitor_keyword") or "").strip(),
                "exposure_terms": [
                    str(term or "").strip()
                    for term in (group.get("exposure_terms") or [])
                    if str(term or "").strip()
                ],
            }
            for group in keyword_groups
            if str(group.get("monitor_keyword") or "").strip()
        ],
        "purchased_platforms": purchased_platforms,
        "schedule_plan": schedule_plan_summary(asset),
        "items": filtered_items[: max(1, min(item_limit, 500))],
    }
