from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentSession, get_current_session
from app.core.database import get_db
from app.schemas.common import ApiResponse
from app.schemas.monitor import MonitorTaskCreateRequest
from app.services.monitor_service import (
    get_monitor_task,
    list_monitor_tasks,
    monitor_summary,
    serialize_subtask,
    serialize_task,
    submit_monitor_task,
    sync_monitor_task,
)
from app.services.molizhishu_client import MolizhishuApiError
from app.services.schedule_service import preview_scheduled_tasks, run_due_scheduled_tasks

router = APIRouter(prefix="/monitor")


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
    return ApiResponse(data=[serialize_task(task) for task in list_monitor_tasks(db, current)])


@router.get("/summary", response_model=ApiResponse[dict])
def monitor_dashboard_summary(
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """Read aggregated real monitoring data for customer and platform dashboards."""
    return ApiResponse(data=monitor_summary(db, current))


@router.get("/scheduled/preview", response_model=ApiResponse[list[dict]])
def scheduled_monitor_preview(
    tenant_id: int | None = None,
    max_prompts: int = 50,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[list[dict]]:
    """预览企业定时监测会提交的问题和模型平台，不调用模力指数接口。"""
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
    return ApiResponse(data={"task": serialize_task(task), "subtasks": [serialize_subtask(item) for item in task.subtasks]})


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
    return ApiResponse(data={"task": serialize_task(task), "subtasks": [serialize_subtask(item) for item in task.subtasks]})
