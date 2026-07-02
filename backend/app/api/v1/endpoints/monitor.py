from datetime import date, datetime, time

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentSession, get_current_session
from app.core.database import get_db
from app.core.redis_client import get_json_cache, set_json_cache
from app.schemas.common import ApiResponse
from app.schemas.monitor import MonitorTaskCreateRequest
from app.services.monitor_service import (
    get_monitor_subtask,
    get_monitor_task,
    list_monitor_tasks,
    monitor_summary,
    ranking_matrix,
    workspace_brief,
    serialize_subtask_for_display,
    serialize_task,
    serialize_tasks_for_display,
    submit_monitor_task,
    sync_monitor_task,
)
from app.services.brand_service import get_brand_asset, keyword_group_to_dict, list_keyword_groups
from app.services.molizhishu_client import MolizhishuApiError
from app.services.schedule_context import schedule_plan_summary, schedule_runs_for_tasks
router = APIRouter(prefix="/monitor")


def _keyword_groups_for_tenant(db: Session, tenant_id: int | None) -> list[dict]:
    if tenant_id is None:
        return []
    return [
        keyword_group_to_dict(item)
        for item in list_keyword_groups(db, tenant_id)
        if item.status and item.monitor_keyword
    ]


def _serialize_task_subtasks(db: Session, task) -> list[dict]:
    asset = get_brand_asset(db, task.tenant_id) if task.tenant_id else None
    groups = _keyword_groups_for_tenant(db, task.tenant_id)
    return [
        serialize_subtask_for_display(
            item,
            monitor_keywords=task.monitor_keywords,
            asset=asset,
            keyword_groups=groups,
        )
        for item in task.subtasks
    ]


def require_platform(current: CurrentSession) -> None:
    """定时监测由平台运营端统一触发，客户侧只查看结果。"""
    if current.identity.identity_type != "PLATFORM":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="仅平台运营端可以执行定时监测任务")


@router.post("/tasks", response_model=ApiResponse[dict])
def create_monitor_task(
    payload: MonitorTaskCreateRequest,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """提交模力指数检测任务，并把任务摘要保存到本地库。"""
    try:
        task = submit_monitor_task(db, payload, current)
    except MolizhishuApiError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except (ValueError, SQLAlchemyError) as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ApiResponse(data=serialize_task(task))


@router.get("/tasks", response_model=ApiResponse[list[dict]])
def monitor_tasks(
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[list[dict]]:
    """查询本地任务列表；这里不请求模力指数远端接口。"""
    tasks = list_monitor_tasks(db, current)
    return ApiResponse(data=serialize_tasks_for_display(db, tasks))


@router.get("/summary", response_model=ApiResponse[dict])
def monitor_dashboard_summary(
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """Read aggregated real monitoring data for customer and platform dashboards."""
    tenant_key = current.identity.tenant_id or "platform"
    cache_key = f"monitor:summary:v1:{current.identity.identity_type}:{tenant_key}"
    cached = get_json_cache(cache_key)
    if cached is not None:
        return ApiResponse(data=cached)
    data = monitor_summary(db, current)
    set_json_cache(cache_key, data, ttl_seconds=20)
    return ApiResponse(data=data)


@router.get("/ranking-matrix", response_model=ApiResponse[dict])
def monitor_ranking_matrix(
    platform: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    keyword: str | None = None,
    monitor_group: str | None = None,
    keyword_group: str | None = None,
    monitor_keyword: str | None = None,
    exposure_term: str | None = None,
    limit_rows: int = 120,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """Return prompt × snapshot ranking matrix for customer realtime monitor."""
    start_at = datetime.combine(start_date, time.min) if start_date else None
    end_at = datetime.combine(end_date, time.max) if end_date else None
    try:
        data = ranking_matrix(
            db,
            current,
            platform=platform,
            start_at=start_at,
            end_at=end_at,
            keyword=keyword,
            monitor_group=monitor_group,
            keyword_group=keyword_group,
            monitor_keyword=monitor_keyword,
            exposure_term=exposure_term,
            limit_rows=limit_rows,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ApiResponse(data=data)


@router.get("/workspace-brief", response_model=ApiResponse[dict])
def monitor_workspace_brief(
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """Return customer workspace morning briefing with intent-aware KPIs."""
    try:
        data = workspace_brief(db, current)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ApiResponse(data=data)


@router.get("/subtasks/{subtask_id}", response_model=ApiResponse[dict])
def monitor_subtask_detail(
    subtask_id: str,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """Query a single subtask with full answer content and references."""
    try:
        subtask = get_monitor_subtask(db, subtask_id, current)
        task = get_monitor_task(db, subtask.task_id, current)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    asset = get_brand_asset(db, task.tenant_id) if task.tenant_id else None
    groups = _keyword_groups_for_tenant(db, task.tenant_id)
    return ApiResponse(data=serialize_subtask_for_display(
        subtask,
        monitor_keywords=task.monitor_keywords,
        asset=asset,
        keyword_groups=groups,
    ))


@router.get("/scheduled/preview", response_model=ApiResponse[list[dict]])
def scheduled_monitor_preview(
    tenant_id: int | None = None,
    max_prompts: int = 50,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[list[dict]]:
    """预览企业定时监测会提交的问题和模型平台，不调用模力指数接口。"""
    if current.identity.identity_type == "CUSTOMER":
        tenant_id = current.identity.tenant_id
    else:
        require_platform(current)
    return ApiResponse(data=preview_scheduled_tasks(db, tenant_id=tenant_id, max_prompts=max_prompts))


@router.post("/scheduled/run-due", response_model=ApiResponse[list[dict]])
def scheduled_monitor_run_due(
    tenant_id: int | None = None,
    limit: int = 10,
    max_prompts: int = 50,
    force: bool = False,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[list[dict]]:
    """执行到期的企业定时监测任务；force=true 用于人工立即执行一次。"""
    require_platform(current)
    try:
        result = run_due_scheduled_tasks(db, current, tenant_id=tenant_id, limit=limit, max_prompts=max_prompts, force=force)
    except MolizhishuApiError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return ApiResponse(data=result)


@router.get("/tasks/{task_id}", response_model=ApiResponse[dict])
def monitor_task_detail(
    task_id: str,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """查询本地任务详情；这里不请求模力指数远端接口。"""
    try:
        task = get_monitor_task(db, task_id, current)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    asset = get_brand_asset(db, task.tenant_id) if task.tenant_id else None
    schedule_run = schedule_runs_for_tasks(db, [task.task_id]).get(task.task_id)
    return ApiResponse(data={
        "task": serialize_task(task, schedule_run=schedule_run, asset=asset),
        "subtasks": _serialize_task_subtasks(db, task),
    })


@router.post("/tasks/{task_id}/sync", response_model=ApiResponse[dict])
def monitor_task_sync(
    task_id: str,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """手动同步远端任务状态和已完成结果；只有这个接口会主动请求 status/result。"""
    try:
        task = sync_monitor_task(db, task_id, current)
    except MolizhishuApiError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return ApiResponse(data={"task": serialize_task(task), "subtasks": _serialize_task_subtasks(db, task)})
