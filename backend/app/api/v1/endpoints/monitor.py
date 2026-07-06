from datetime import date, datetime, time

from fastapi import APIRouter, Depends, HTTPException, Query, status
from kombu.exceptions import OperationalError
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentSession, get_current_session
from app.api.http_errors import molizhishu_upstream_error_detail, raise_read_endpoint_error, raise_write_endpoint_error
from app.core.database import get_db
from app.core.read_cache import (
    MANAGEMENT_OVERVIEW_CACHE_KEY,
    MANAGEMENT_OVERVIEW_CACHE_TTL,
    MONITOR_SUMMARY_CACHE_TTL,
    WORKSPACE_BRIEF_CACHE_TTL,
    get_or_build_json_cache,
    monitor_summary_cache_key,
    workspace_brief_cache_key,
)
from app.schemas.common import ApiResponse
from app.schemas.monitor import (
    MonitorTaskCreateRequest,
    SnapshotBackfillListResponse,
    SnapshotBackfillRequest,
)
from app.services.monitor_service import (
    filter_subtasks_for_customer,
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
from app.services.snapshot_backfill_service import (
    apply_snapshot_backfill,
    build_snapshot_backfill_item,
    list_snapshot_backfill_page,
)
from app.services.brand_service import get_brand_asset, keyword_group_to_dict, list_keyword_groups
from app.services.molizhishu_client import MolizhishuApiError
from app.services.menu_permission_service import require_snapshot_backfill_permission
from app.services.tenant_scope import ensure_sales_tenant_access, sales_owned_tenant_ids
from app.services.schedule_context import schedule_plan_summary, schedule_runs_for_tasks
from app.services.schedule_service import preview_scheduled_tasks, run_due_scheduled_tasks

router = APIRouter(prefix="/monitor")


def _keyword_groups_for_tenant(db: Session, tenant_id: int | None) -> list[dict]:
    if tenant_id is None:
        return []
    return [
        keyword_group_to_dict(item)
        for item in list_keyword_groups(db, tenant_id)
        if item.status and item.monitor_keyword
    ]


def _serialize_task_subtasks(db: Session, task, current: CurrentSession | None = None) -> list[dict]:
    asset = get_brand_asset(db, task.tenant_id) if task.tenant_id else None
    groups = _keyword_groups_for_tenant(db, task.tenant_id)
    subtasks = task.subtasks
    if current and current.identity.identity_type == "CUSTOMER":
        subtasks = filter_subtasks_for_customer(subtasks, task=task, db=db)
    return [
        serialize_subtask_for_display(
            item,
            monitor_keywords=task.monitor_keywords,
            asset=asset,
            keyword_groups=groups,
        )
        for item in subtasks
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
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=molizhishu_upstream_error_detail(exc),
        ) from exc
    except Exception as exc:
        db.rollback()
        raise_write_endpoint_error(exc, context="monitor.create_task")
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
    cache_key = monitor_summary_cache_key(current.identity.identity_type, tenant_key)
    try:
        data = get_or_build_json_cache(
            cache_key,
            lambda: monitor_summary(db, current),
            ttl_seconds=MONITOR_SUMMARY_CACHE_TTL,
        )
        return ApiResponse(data=data)
    except Exception as exc:
        raise_read_endpoint_error(exc, context="monitor.summary")


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
    except Exception as exc:
        raise_read_endpoint_error(exc, context="monitor.ranking_matrix")
    return ApiResponse(data=data)


@router.get("/workspace-brief", response_model=ApiResponse[dict])
def monitor_workspace_brief(
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """Return customer workspace morning briefing with intent-aware KPIs."""
    if current.identity.identity_type != "CUSTOMER" or current.identity.tenant_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="运营工作台简报仅支持客户企业账号")
    cache_key = workspace_brief_cache_key(current.identity.tenant_id)
    try:
        data = get_or_build_json_cache(
            cache_key,
            lambda: workspace_brief(db, current),
            ttl_seconds=WORKSPACE_BRIEF_CACHE_TTL,
        )
        return ApiResponse(data=data)
    except Exception as exc:
        raise_read_endpoint_error(exc, context="monitor.workspace_brief")


@router.get("/snapshot-backfill/pending", response_model=ApiResponse[SnapshotBackfillListResponse])
def monitor_snapshot_backfill_pending(
    tenant_id: int | None = None,
    all_tenants: bool = Query(
        default=False,
        description="为 true 时允许不传 tenant_id 查询全部企业（默认需指定企业以防误扫全库）",
    ),
    on_date: date | None = Query(default=None, alias="date"),
    source: str | None = Query(default=None, pattern="^(tenant_monitor|lead_diagnosis)$"),
    platform: str | None = Query(default=None),
    keyword: str | None = Query(default=None),
    keyword_group: str | None = Query(default=None),
    pending_only: bool = Query(default=False),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[SnapshotBackfillListResponse]:
    """运营端快照补录列表：可按企业、单日、来源、平台、关键词/词组筛选；默认含已有结果以便覆盖更正。"""
    require_platform(current)
    if tenant_id is None and not all_tenants:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="请指定 tenant_id，或显式传入 all_tenants=true 查询全部企业",
        )
    try:
        require_snapshot_backfill_permission(db, current, "can_export")
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    owned = sales_owned_tenant_ids(db, current)
    scoped_tenant_ids: list[int] | None = None
    if owned is not None:
        if not owned:
            return ApiResponse(data=SnapshotBackfillListResponse.model_validate({
                "items": [], "summary": {"pending": 0, "total": 0}, "total": 0, "offset": offset, "limit": limit,
            }))
        if tenant_id is not None:
            try:
                ensure_sales_tenant_access(db, current, tenant_id)
            except PermissionError as exc:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
        elif all_tenants:
            scoped_tenant_ids = owned
            tenant_id = None
        else:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请指定 tenant_id")
    payload = list_snapshot_backfill_page(
        db,
        tenant_id=tenant_id,
        tenant_ids=scoped_tenant_ids,
        detect_date=on_date,
        source=source,
        platform=platform,
        keyword=keyword,
        keyword_group=keyword_group,
        pending_only=pending_only,
        offset=offset,
        limit=limit,
    )
    return ApiResponse(data=SnapshotBackfillListResponse.model_validate(payload))


@router.post("/subtasks/{subtask_id}/snapshot-backfill", response_model=ApiResponse[dict])
def monitor_subtask_snapshot_backfill(
    subtask_id: str,
    payload: SnapshotBackfillRequest,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """运营对子任务粘贴分享链接与回答正文；可覆盖原有抓取结果并重算排名。"""
    require_platform(current)
    try:
        require_snapshot_backfill_permission(db, current, "can_update")
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    try:
        data = apply_snapshot_backfill(
            db,
            subtask_id=subtask_id,
            snapshot_url=payload.snapshot_url,
            answer_content=payload.answer_content,
            current=current,
            mention_position=payload.mention_position,
            sentiment=payload.sentiment,
            reference_urls=payload.reference_urls,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ApiResponse(data=data)


@router.get("/subtasks/{subtask_id}", response_model=ApiResponse[dict])
def monitor_subtask_detail(
    subtask_id: str,
    include_ops: bool = Query(default=False),
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """Query a single subtask with full answer content and references."""
    try:
        subtask = get_monitor_subtask(db, subtask_id, current)
        task = get_monitor_task(db, subtask.task_id, current)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    asset = get_brand_asset(db, task.tenant_id) if task.tenant_id else None
    groups = _keyword_groups_for_tenant(db, task.tenant_id)
    display = serialize_subtask_for_display(
        subtask,
        monitor_keywords=task.monitor_keywords,
        asset=asset,
        keyword_groups=groups,
    )
    if not include_ops:
        return ApiResponse(data=display)
    if current.identity.identity_type == "PLATFORM":
        try:
            require_snapshot_backfill_permission(db, current, "can_export")
        except PermissionError as exc:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    ops_meta = build_snapshot_backfill_item(db, subtask, task)
    return ApiResponse(data={**display, **ops_meta})


def _resolve_schedule_tenant_scope(
    db: Session,
    current: CurrentSession,
    tenant_id: int | None,
) -> tuple[int | None, list[int] | None]:
    """销售账号未指定 tenant 时限定为负责企业；客户账号固定自身 tenant。"""
    if current.identity.identity_type == "CUSTOMER":
        return current.identity.tenant_id, None
    require_platform(current)
    owned = sales_owned_tenant_ids(db, current)
    if tenant_id is not None:
        ensure_sales_tenant_access(db, current, tenant_id)
        return tenant_id, None
    if owned is not None:
        return None, owned
    return None, None


@router.get("/scheduled/preview", response_model=ApiResponse[list[dict]])
def scheduled_monitor_preview(
    tenant_id: int | None = None,
    max_prompts: int = 50,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[list[dict]]:
    """预览企业定时监测会提交的问题和模型平台，不调用模力指数接口。"""
    try:
        scoped_tenant_id, scoped_tenant_ids = _resolve_schedule_tenant_scope(db, current, tenant_id)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return ApiResponse(data=preview_scheduled_tasks(
        db,
        tenant_id=scoped_tenant_id,
        tenant_ids=scoped_tenant_ids,
        max_prompts=max_prompts,
    ))


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
    try:
        scoped_tenant_id, scoped_tenant_ids = _resolve_schedule_tenant_scope(db, current, tenant_id)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    try:
        result = run_due_scheduled_tasks(
            db,
            current,
            tenant_id=scoped_tenant_id,
            tenant_ids=scoped_tenant_ids,
            limit=limit,
            max_prompts=max_prompts,
            force=force,
        )
    except MolizhishuApiError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=molizhishu_upstream_error_detail(exc),
        ) from exc
    except (OperationalError, TimeoutError) as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="任务队列暂时不可用，请稍后重试",
        ) from exc
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
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    asset = get_brand_asset(db, task.tenant_id) if task.tenant_id else None
    schedule_run = schedule_runs_for_tasks(db, [task.task_id]).get(task.task_id)
    return ApiResponse(data={
        "task": serialize_task(task, schedule_run=schedule_run, asset=asset),
        "subtasks": _serialize_task_subtasks(db, task, current),
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
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except MolizhishuApiError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=molizhishu_upstream_error_detail(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return ApiResponse(data={"task": serialize_task(task), "subtasks": _serialize_task_subtasks(db, task, current)})
