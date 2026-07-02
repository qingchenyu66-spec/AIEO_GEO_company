from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import case, func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentSession, get_current_session
from app.core.database import get_db
from app.core.celery_queue_monitor import format_celery_monitor_zh, get_queue_monitor_snapshot
from app.core.platform_order import sort_platform_items
from app.core.redis_client import get_json_cache, redis_health, set_json_cache
from app.models.ops import OperationLog, SystemConfig
from app.models.permission import Menu, Position, PositionMenu, Role, UserIdentityMenu
from app.models.tenant import Tenant
from app.models.monitor import GeoMonitorScheduleRun, GeoMonitorSubtask, GeoMonitorTask
from app.models.menu_config import MenuConfig
from app.models.user import User
from app.models.user_identity import UserIdentity
from app.schemas.common import ApiResponse
from app.services.molizhishu_balance_service import fetch_molizhishu_balance
from app.schemas.permission import (
    MenuConfigBatchItem,
    MenuConfigUpdateRequest,
    MenuInfo,
    PasswordResetRequest,
    PositionInfo,
    PositionSaveRequest,
    RoleInfo,
    TenantCreateRequest,
    TenantUpdateRequest,
    UserCreateRequest,
    UserUpdateRequest,
)
from app.services.management_service import (
    _tenant_code_from_name,
    create_managed_user,
    delete_managed_user,
    list_managed_users,
    reset_managed_user_password,
    restore_managed_user,
    set_managed_user_status,
    update_managed_user,
)
from app.services.menu_permission_service import (
    has_identity_menu_permission,
    position_menu_grants,
    sync_identity_menus_for_position,
    sync_position_menu_grants,
)
from app.services.permission_service import (
    list_menus_by_identity_type,
    list_positions_by_identity_type,
    list_roles_by_identity_type,
)

router = APIRouter(prefix="/management")


def require_platform(current: CurrentSession) -> None:
    if current.identity.identity_type != "PLATFORM":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="仅平台运营端可访问")


def is_sales_identity(db: Session, identity: UserIdentity) -> bool:
    if identity.identity_type != "PLATFORM" or identity.position_id is None:
        return False
    position = db.scalar(
        select(Position).where(
            Position.id == identity.position_id,
            Position.deleted.is_(False),
        )
    )
    if position is None:
        return False
    return position.position_code == "PLATFORM_SALES" or position.position_name == "销售"


def has_identity_menu_permission(db: Session, identity_id: int, menu_code: str, action: str = "can_create") -> bool:
    from app.services.menu_permission_service import has_identity_menu_permission as check_permission

    return check_permission(db, identity_id, menu_code, action)


def require_user_identity_create_permission(
    db: Session,
    current: CurrentSession,
    payload: UserCreateRequest | UserUpdateRequest,
    *,
    existing_user_id: int | None = None,
) -> None:
    requested_types = {item.identity_type for item in payload.identities}
    if existing_user_id is not None:
        existing_types = set(db.scalars(
            select(UserIdentity.identity_type).where(
                UserIdentity.user_id == existing_user_id,
                UserIdentity.deleted.is_(False),
            )
        ))
        requested_types -= existing_types
    permission_map = {
        "PLATFORM": ("platform.users.create.platform", "新增平台运营端用户"),
        "CUSTOMER": ("platform.users.create.customer", "新增客户企业端用户"),
    }
    for identity_type in requested_types:
        menu_code, label = permission_map[identity_type]
        if not has_identity_menu_permission(db, current.identity.id, menu_code):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"当前职位无权{label}")

def service_status_from_period(service_start_date: date | None, service_end_date: date | None) -> bool:
    today = date.today()
    if service_start_date and service_start_date > today:
        return False
    if service_end_date and service_end_date < today:
        return False
    return True


def validate_service_period(service_start_date: date | None, service_end_date: date | None) -> None:
    if service_start_date and service_end_date and service_end_date < service_start_date:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="服务结束日期不能早于服务开始日期")


def tenant_to_dict(tenant: Tenant) -> dict:
    return {
        "id": tenant.id,
        "name": tenant.name,
        "code": tenant.code,
        "status": tenant.status,
        "owner_user_id": tenant.owner_user_id,
        "stop_reason": tenant.stop_reason,
        "stopped_at": tenant.stopped_at.isoformat(sep=" ", timespec="minutes") if tenant.stopped_at else None,
        "stopped_by": tenant.stopped_by,
        "service_start_date": tenant.service_start_date.isoformat() if tenant.service_start_date else None,
        "service_end_date": tenant.service_end_date.isoformat() if tenant.service_end_date else None,
    }


def tenant_service_state(tenant: Tenant, today: date | None = None) -> str:
    """按合同日期和人工停服原因计算企业服务状态。"""
    today = today or date.today()
    if tenant.service_end_date and tenant.service_end_date < today:
        return "expired"
    if not tenant.status and tenant.stop_reason == "manual":
        return "manual_stopped"
    if not tenant.status and tenant.stop_reason == "canceled":
        return "canceled"
    if tenant.service_start_date and tenant.service_start_date > today:
        return "pending"
    if not tenant.status:
        return "stopped"
    return "active"


def is_garbled_log_text(value: str | None) -> bool:
    """识别早期编码异常写入的问号日志，原文已不可逆。"""
    if not value:
        return False
    question_count = value.count("?")
    return question_count >= 3 or (question_count > 0 and question_count / max(1, len(value)) > 0.25)


def clean_log_text(value: str | None, fallback: str) -> str:
    if is_garbled_log_text(value):
        return fallback
    return value or fallback


def operation_log_to_dict(item: OperationLog) -> dict:
    garbled = any(is_garbled_log_text(text) for text in [item.operator_name, item.action_type, item.description, item.risk_level])
    return {
        "id": item.id,
        "operator_name": clean_log_text(item.operator_name, "历史日志" if garbled else "系统"),
        "action_type": clean_log_text(item.action_type, "编码异常" if garbled else "系统操作"),
        "description": clean_log_text(item.description, "该条历史日志在早期编码异常时写入，原文不可恢复"),
        "risk_level": clean_log_text(item.risk_level, "历史记录" if garbled else "普通"),
        "ip_address": item.ip_address,
        "created_at": item.created_at.isoformat(sep=" ", timespec="minutes"),
    }


def write_management_log(
    db: Session,
    current: CurrentSession,
    action_type: str,
    description: str,
    *,
    target_module: str | None = None,
    target_id: int | None = None,
    tenant_id: int | None = None,
    risk_level: str = "正常",
) -> OperationLog:
    """写入平台管理操作日志，和业务变更共用同一个数据库事务。"""
    log = OperationLog(
        operator_name=current.user.display_name or current.identity.identity_name or current.user.username,
        action_type=action_type,
        description=description[:500],
        risk_level=risk_level,
        target_module=target_module,
        target_id=target_id,
        tenant_id=tenant_id,
        operator_user_id=current.user.id,
    )
    db.add(log)
    return log


def position_code_from_name(identity_type: str, name: str) -> str:
    import hashlib

    digest = hashlib.md5(f"{identity_type}:{name}".encode("utf-8")).hexdigest()[:8].upper()
    return f"{identity_type}_POS_{digest}"


def sync_position_menus(
    db: Session,
    position_id: int,
    menu_ids: list[int],
    *,
    identity_type: str,
    writable: bool,
    menu_grants=None,
) -> None:
    sync_position_menu_grants(
        db,
        position_id,
        menu_grants or [],
        identity_type=identity_type,
        menu_ids=menu_ids if not menu_grants else None,
        writable=writable,
    )


def position_to_dict(db: Session, position: Position) -> dict:
    grants = position_menu_grants(db, position.id)
    return PositionInfo(
        id=position.id,
        position_code=position.position_code,
        position_name=position.position_name,
        identity_type=position.identity_type,
        role_code=position.role_code,
        description=position.description,
        menu_ids=[item.menu_id for item in grants],
        menu_grants=grants,
    ).model_dump()


@router.get("/menus", response_model=ApiResponse[list[dict]])
def management_menus(
    identity_type: str = "PLATFORM",
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[list[dict]]:
    require_platform(current)
    menus = [
        MenuInfo(
            id=menu.id,
            menu_code=menu.menu_code,
            menu_name=menu.menu_name,
            identity_type=menu.identity_type,
            route_path=menu.route_path,
            icon=menu.icon,
            sort_order=menu.sort_order,
        ).model_dump()
        for menu in list_menus_by_identity_type(db, identity_type)
    ]
    return ApiResponse(data=menus)


@router.get("/roles", response_model=ApiResponse[list[dict]])
def management_roles(
    identity_type: str = "PLATFORM",
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[list[dict]]:
    require_platform(current)
    roles = [
        RoleInfo(
            id=role.id,
            role_code=role.role_code,
            role_name=role.role_name,
            identity_type=role.identity_type,
            data_scope=role.data_scope,
        ).model_dump()
        for role in list_roles_by_identity_type(db, identity_type)
    ]
    return ApiResponse(data=roles)


@router.get("/positions", response_model=ApiResponse[list[dict]])
def management_positions(
    identity_type: str = "PLATFORM",
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[list[dict]]:
    require_platform(current)
    positions = [
        position_to_dict(db, position)
        for position in list_positions_by_identity_type(db, identity_type)
    ]
    return ApiResponse(data=positions)


@router.post("/positions", response_model=ApiResponse[dict])
def management_create_position(
    payload: PositionSaveRequest,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    require_platform(current)
    role = db.scalar(select(Role).where(Role.role_code == payload.role_code, Role.identity_type == payload.identity_type, Role.status.is_(True), Role.deleted.is_(False)))
    if role is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="角色不存在或已停用")
    name = payload.position_name.strip()
    exists = db.scalar(select(Position).where(Position.position_name == name, Position.identity_type == payload.identity_type, Position.deleted.is_(False)))
    if exists is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="同类型下职位名称已存在")
    position = Position(
        position_code=position_code_from_name(payload.identity_type, name),
        position_name=name,
        identity_type=payload.identity_type,
        role_code=payload.role_code,
        description=(payload.description or "").strip() or None,
        status=payload.status,
    )
    db.add(position)
    db.flush()
    sync_position_menus(
        db,
        position.id,
        payload.menu_ids,
        identity_type=payload.identity_type,
        writable=payload.identity_type == "PLATFORM",
        menu_grants=payload.menu_grants or None,
    )
    write_management_log(db, current, "职位新增", f"新增职位：{position.position_name}", target_module="职位管理", target_id=position.id)
    db.commit()
    db.refresh(position)
    return ApiResponse(data=position_to_dict(db, position))


@router.put("/positions/{position_id}", response_model=ApiResponse[dict])
def management_update_position(
    position_id: int,
    payload: PositionSaveRequest,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    require_platform(current)
    position = db.scalar(select(Position).where(Position.id == position_id, Position.deleted.is_(False)))
    if position is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="职位不存在")
    role = db.scalar(select(Role).where(Role.role_code == payload.role_code, Role.identity_type == payload.identity_type, Role.status.is_(True), Role.deleted.is_(False)))
    if role is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="角色不存在或已停用")
    name = payload.position_name.strip()
    exists = db.scalar(
        select(Position).where(
            Position.position_name == name,
            Position.identity_type == payload.identity_type,
            Position.id != position_id,
            Position.deleted.is_(False),
        )
    )
    if exists is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="同类型下职位名称已存在")
    position.position_name = name
    position.identity_type = payload.identity_type
    position.role_code = payload.role_code
    position.description = (payload.description or "").strip() or None
    position.status = payload.status
    sync_position_menus(
        db,
        position.id,
        payload.menu_ids,
        identity_type=payload.identity_type,
        writable=payload.identity_type == "PLATFORM",
        menu_grants=payload.menu_grants or None,
    )
    synced_users = sync_identity_menus_for_position(db, position.id)
    write_management_log(db, current, "职位修改", f"修改职位：{position.position_name}（已同步 {synced_users} 个身份）", target_module="职位管理", target_id=position.id, risk_level="关注")
    db.commit()
    db.refresh(position)
    return ApiResponse(data=position_to_dict(db, position))


@router.delete("/positions/{position_id}", response_model=ApiResponse[dict])
def management_delete_position(
    position_id: int,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    require_platform(current)
    position = db.scalar(select(Position).where(Position.id == position_id, Position.deleted.is_(False)))
    if position is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="职位不存在")
    used_identity = db.scalar(
        select(UserIdentity.id).where(
            UserIdentity.position_id == position_id,
            UserIdentity.deleted.is_(False),
        )
    )
    if used_identity is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="该职位已有人员使用，请先调整人员职位后再删除")
    position.deleted = True
    position.status = False
    db.query(PositionMenu).filter(PositionMenu.position_id == position_id).delete(synchronize_session=False)
    write_management_log(db, current, "职位删除", f"删除职位：{position.position_name}", target_module="职位管理", target_id=position.id, risk_level="关注")
    db.commit()
    return ApiResponse(data={"id": position_id, "deleted": True})


@router.get("/tenants", response_model=ApiResponse[list[dict]])
def management_tenants(
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[list[dict]]:
    require_platform(current)
    stmt = select(Tenant).where(Tenant.deleted.is_(False)).order_by(Tenant.id.desc())
    if is_sales_identity(db, current.identity):
        stmt = stmt.where(Tenant.owner_user_id == current.user.id)
    tenants = db.scalars(stmt)
    return ApiResponse(data=[tenant_to_dict(item) for item in tenants])


@router.get("/operation-logs", response_model=ApiResponse[list[dict]])
def management_operation_logs(
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[list[dict]]:
    require_platform(current)
    rows = db.scalars(select(OperationLog).order_by(OperationLog.id.desc()).limit(100))
    return ApiResponse(data=[operation_log_to_dict(item) for item in rows])


@router.get("/celery-monitor", response_model=ApiResponse[dict])
def management_celery_monitor(
    current: CurrentSession = Depends(get_current_session),
) -> ApiResponse[dict]:
    """中文版 Celery 队列与 Worker 监控数据。"""
    require_platform(current)
    return ApiResponse(data=format_celery_monitor_zh(get_queue_monitor_snapshot()))


@router.get("/system-configs", response_model=ApiResponse[list[dict]])
def management_system_configs(
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[list[dict]]:
    require_platform(current)
    rows = db.scalars(select(SystemConfig).order_by(SystemConfig.id.asc()))
    return ApiResponse(data=[
        {
            "id": item.id,
            "config_key": item.config_key,
            "config_name": item.description or item.config_key,
            "config_value": item.config_value,
            "scope": item.scope,
            "status": "启用" if item.status else "停用",
            "remark": item.description,
            "updated_at": item.updated_at.isoformat(sep=" ", timespec="minutes"),
        }
        for item in rows
    ])


@router.get("/overview", response_model=ApiResponse[dict])
def management_overview(
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """平台运营总览聚合接口，避免首页多接口聚合导致加载慢。"""
    require_platform(current)
    cache_key = "management:overview:v1"
    cached = get_json_cache(cache_key)
    if cached is not None:
        return ApiResponse(data=cached)
    today = date.today()
    tomorrow = today + timedelta(days=1)
    thirty_days_later = today + timedelta(days=30)
    terminal_statuses = {"completed", "partial_completed", "failed", "stopped"}

    tenants = list(db.scalars(select(Tenant).where(Tenant.deleted.is_(False))))
    service_counts = {"active": 0, "pending": 0, "expired": 0, "manual_stopped": 0, "canceled": 0, "stopped": 0}
    expiring_tenants: list[dict] = []
    for tenant in tenants:
        state = tenant_service_state(tenant, today)
        service_counts[state] = service_counts.get(state, 0) + 1
        if tenant.service_end_date and today <= tenant.service_end_date <= thirty_days_later:
            expiring_tenants.append({
                "id": tenant.id,
                "name": tenant.name,
                "service_end_date": tenant.service_end_date.isoformat(),
                "days_left": (tenant.service_end_date - today).days,
            })

    today_task_rows = list(db.scalars(
        select(GeoMonitorTask).where(
            GeoMonitorTask.deleted.is_(False),
            GeoMonitorTask.created_at >= datetime.combine(today, datetime.min.time()),
            GeoMonitorTask.created_at < datetime.combine(tomorrow, datetime.min.time()),
        )
    ))
    all_recent_tasks = list(db.scalars(
        select(GeoMonitorTask)
        .where(GeoMonitorTask.deleted.is_(False))
        .order_by(GeoMonitorTask.created_at.desc())
        .limit(12)
    ))
    tenant_name_map = {tenant.id: tenant.name for tenant in tenants}

    today_task_ids = [task.task_id for task in today_task_rows]
    today_cost = 0.0
    if today_task_ids:
        today_cost = float(db.scalar(
            select(func.coalesce(func.sum(GeoMonitorSubtask.amount), 0)).where(GeoMonitorSubtask.task_id.in_(today_task_ids))
        ) or 0)

    platform_rows = db.execute(
        select(
            GeoMonitorSubtask.platform,
            func.count(GeoMonitorSubtask.id),
            func.sum(case((GeoMonitorSubtask.status.in_(terminal_statuses), 1), else_=0)),
            func.sum(case((GeoMonitorSubtask.status == "failed", 1), else_=0)),
            func.coalesce(func.sum(GeoMonitorSubtask.amount), 0),
        )
        .group_by(GeoMonitorSubtask.platform)
        .order_by(func.count(GeoMonitorSubtask.id).desc())
        .limit(12)
    ).all()
    platform_stats = sort_platform_items([
        {
            "platform": row[0],
            "total": int(row[1] or 0),
            "completed": int(row[2] or 0),
            "failed": int(row[3] or 0),
            "cost": float(row[4] or 0),
            "success_rate": round(((int(row[2] or 0) - int(row[3] or 0)) / max(1, int(row[2] or 0))) * 100, 1),
        }
        for row in platform_rows
    ])

    cost_rank_rows = db.execute(
        select(GeoMonitorTask.tenant_id, func.coalesce(func.sum(GeoMonitorSubtask.amount), 0))
        .join(GeoMonitorSubtask, GeoMonitorSubtask.task_id == GeoMonitorTask.task_id)
        .where(GeoMonitorTask.deleted.is_(False))
        .group_by(GeoMonitorTask.tenant_id)
        .order_by(func.coalesce(func.sum(GeoMonitorSubtask.amount), 0).desc())
        .limit(8)
    ).all()
    cost_ranking = [
        {"tenant_id": row[0], "tenant_name": tenant_name_map.get(row[0]) or "未绑定企业", "cost": float(row[1] or 0)}
        for row in cost_rank_rows
    ]
    total_cost = round(sum(row["cost"] for row in cost_ranking), 4)
    total_subtasks = int(db.scalar(select(func.count(GeoMonitorSubtask.id))) or 0)
    mentioned_subtasks = int(db.scalar(select(func.count(GeoMonitorSubtask.id)).where(GeoMonitorSubtask.mention_position.isnot(None))) or 0)
    source_count = int(db.scalar(select(func.count(GeoMonitorSubtask.id)).where(GeoMonitorSubtask.reference_list_json.isnot(None))) or 0)
    mention_rate = round((mentioned_subtasks / max(1, total_subtasks)) * 100, 1)
    quota_overview = {
        "used_amount": total_cost,
        "today_amount": round(today_cost, 4),
        "estimated_month_amount": round(today_cost * 30, 4),
        "total_subtasks": total_subtasks,
        "avg_cost_per_subtask": round(total_cost / max(1, total_subtasks), 4),
    }
    customer_data = {
        "tenant_total": len(tenants),
        "active_tenants": service_counts.get("active", 0),
        "task_total": int(db.scalar(select(func.count(GeoMonitorTask.id)).where(GeoMonitorTask.deleted.is_(False))) or 0),
        "subtask_total": total_subtasks,
        "mention_rate": mention_rate,
        "source_count": source_count,
    }

    schedule_rows = list(db.scalars(
        select(GeoMonitorScheduleRun)
        .where(GeoMonitorScheduleRun.created_at >= datetime.combine(today, datetime.min.time()))
        .order_by(GeoMonitorScheduleRun.created_at.desc())
        .limit(20)
    ))
    today_schedule_failed = sum(1 for row in schedule_rows if row.status == "failed")
    today_schedule_submitted = sum(1 for row in schedule_rows if row.status == "submitted")

    recent_logs = list(db.scalars(select(OperationLog).order_by(OperationLog.created_at.desc()).limit(8)))
    failed_tasks = [task for task in all_recent_tasks if task.status in {"failed", "stopped"} or task.failed_items or task.last_error]
    running_tasks = [task for task in all_recent_tasks if task.status not in terminal_statuses]
    todo_items = []
    if expiring_tenants:
        todo_items.append({"type": "renewal", "title": "客户服务即将到期", "count": len(expiring_tenants), "level": "warning"})
    if failed_tasks:
        todo_items.append({"type": "failed_task", "title": "失败任务待处理", "count": len(failed_tasks), "level": "danger"})
    if running_tasks:
        todo_items.append({"type": "sync_task", "title": "任务结果待同步", "count": len(running_tasks), "level": "normal"})
    if today_schedule_failed:
        todo_items.append({"type": "schedule_failed", "title": "今日调度失败", "count": today_schedule_failed, "level": "danger"})

    redis_status = redis_health()
    queue_snapshot = get_queue_monitor_snapshot()
    queue_alerts = queue_snapshot.get("alerts") or []
    submit_backlog = int(queue_snapshot.get("queues", {}).get("submit", {}).get("queued") or 0)
    sync_backlog = int(queue_snapshot.get("queues", {}).get("sync", {}).get("queued") or 0)
    workers_online = int(queue_snapshot.get("workers", {}).get("workers_online") or 0)
    if queue_alerts:
        for alert in queue_alerts:
            todo_items.append(
                {
                    "type": "celery_queue",
                    "title": alert.get("title") or "队列积压",
                    "count": alert.get("queued") or 0,
                    "level": "danger" if alert.get("level") == "critical" else "warning",
                }
            )
    data = {
        "kpis": {
            "today_tasks": len(today_task_rows),
            "today_completed_tasks": sum(1 for task in today_task_rows if task.status in terminal_statuses),
            "today_failed_tasks": sum(1 for task in today_task_rows if task.status in {"failed", "stopped"} or task.failed_items),
            "today_cost": round(today_cost, 4),
            "active_tenants": service_counts.get("active", 0),
            "expiring_tenants": len(expiring_tenants),
            "api_success_rate": round((today_schedule_submitted / max(1, len(schedule_rows))) * 100, 1),
        },
        "service_counts": service_counts,
        "expiring_tenants": expiring_tenants[:8],
        "platform_stats": platform_stats,
        "cost_ranking": cost_ranking,
        "quota_overview": quota_overview,
        "customer_data": customer_data,
        "recent_tasks": [
            {
                "task_id": task.task_id,
                "tenant_name": tenant_name_map.get(task.tenant_id) or "未绑定企业",
                "monitor_keywords": task.monitor_keywords,
                "status": task.status,
                "total_items": task.total_items,
                "completed_items": task.completed_items,
                "failed_items": task.failed_items,
                "created_at": task.created_at.isoformat(sep=" ", timespec="minutes"),
                "last_error": task.last_error,
            }
            for task in all_recent_tasks[:8]
        ],
        "alerts": [
            {"title": "任务失败", "value": len(failed_tasks), "level": "danger" if failed_tasks else "normal"},
            {"title": "调度失败", "value": today_schedule_failed, "level": "danger" if today_schedule_failed else "normal"},
            {"title": "即将到期", "value": len(expiring_tenants), "level": "warning" if expiring_tenants else "normal"},
            {"title": "运行中任务", "value": len(running_tasks), "level": "normal"},
            {"title": "提交队列", "value": submit_backlog, "level": "danger" if submit_backlog >= queue_snapshot.get("queues", {}).get("submit", {}).get("critical_threshold", 150) else "warning" if submit_backlog >= queue_snapshot.get("queues", {}).get("submit", {}).get("warning_threshold", 50) else "normal"},
            {"title": "同步队列", "value": sync_backlog, "level": "danger" if sync_backlog >= queue_snapshot.get("queues", {}).get("sync", {}).get("critical_threshold", 300) else "warning" if sync_backlog >= queue_snapshot.get("queues", {}).get("warning_threshold", 100) else "normal"},
        ],
        "todo_items": todo_items,
        "operation_logs": [operation_log_to_dict(row) for row in recent_logs],
        "system_health": [
            {"name": "API 服务", "status": "正常", "detail": "FastAPI 已运行"},
            {"name": "数据库", "status": "正常", "detail": "MySQL 可连接"},
            {"name": "Redis 缓存", "status": "正常" if redis_status["status"] == "ready" else "未启用" if redis_status["status"] == "disabled" else "异常", "detail": redis_status["detail"]},
            {"name": "Celery Worker", "status": "正常" if workers_online > 0 else "异常", "detail": f"{workers_online} 个 Worker 在线"},
            {"name": "任务队列", "status": "异常" if any(item.get("level") == "critical" for item in queue_alerts) else "关注" if queue_alerts else "正常", "detail": f"submit {submit_backlog} / sync {sync_backlog}"},
            {"name": "调度任务", "status": "正常" if today_schedule_failed == 0 else "异常", "detail": f"今日提交 {today_schedule_submitted} 次，失败 {today_schedule_failed} 次"},
            {"name": "结果同步", "status": "待处理" if running_tasks else "正常", "detail": f"{len(running_tasks)} 个任务未终态"},
        ],
        "celery_queues": queue_snapshot,
        "molizhishu_balance": fetch_molizhishu_balance(),
    }
    set_json_cache(cache_key, data, ttl_seconds=30)
    return ApiResponse(data=data)


@router.post("/tenants", response_model=ApiResponse[dict])
def management_create_tenant(
    payload: TenantCreateRequest,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    require_platform(current)
    validate_service_period(payload.service_start_date, payload.service_end_date)
    name = payload.name.strip()
    code = (payload.code or _tenant_code_from_name(name)).strip()
    exists = db.scalar(select(Tenant).where(or_(Tenant.name == name, Tenant.code == code), Tenant.deleted.is_(False)))
    if exists is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="企业名称或企业编码已存在")

    tenant = Tenant(
        name=name,
        code=code,
        owner_user_id=current.user.id,
        service_start_date=payload.service_start_date,
        service_end_date=payload.service_end_date,
        status=service_status_from_period(payload.service_start_date, payload.service_end_date),
        stop_reason="expired" if payload.service_end_date and payload.service_end_date < date.today() else None,
    )
    db.add(tenant)
    db.flush()
    write_management_log(db, current, "企业新增", f"新增企业：{tenant.name}", target_module="企业管理", target_id=tenant.id, tenant_id=tenant.id)
    db.commit()
    db.refresh(tenant)
    return ApiResponse(data=tenant_to_dict(tenant))


@router.put("/tenants/{tenant_id}", response_model=ApiResponse[dict])
def management_update_tenant(
    tenant_id: int,
    payload: TenantUpdateRequest,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    require_platform(current)
    tenant = db.scalar(select(Tenant).where(Tenant.id == tenant_id, Tenant.deleted.is_(False)))
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="企业不存在")

    validate_service_period(payload.service_start_date, payload.service_end_date)
    name = payload.name.strip()
    code = (payload.code or tenant.code or _tenant_code_from_name(name)).strip()
    exists = db.scalar(
        select(Tenant).where(
            or_(Tenant.name == name, Tenant.code == code),
            Tenant.id != tenant_id,
            Tenant.deleted.is_(False),
        )
    )
    if exists is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="企业名称或企业编码已存在")

    tenant.name = name
    tenant.code = code
    tenant.service_start_date = payload.service_start_date
    tenant.service_end_date = payload.service_end_date
    period_status = service_status_from_period(payload.service_start_date, payload.service_end_date)
    if tenant.stop_reason in {"manual", "canceled"}:
        tenant.status = False
    else:
        tenant.status = period_status
        tenant.stop_reason = "expired" if payload.service_end_date and payload.service_end_date < date.today() else None
        if tenant.status:
            tenant.stopped_at = None
            tenant.stopped_by = None
    write_management_log(db, current, "企业修改", f"修改企业资料：{tenant.name}", target_module="企业管理", target_id=tenant.id, tenant_id=tenant.id)
    db.commit()
    db.refresh(tenant)
    return ApiResponse(data=tenant_to_dict(tenant))


@router.delete("/tenants/{tenant_id}", response_model=ApiResponse[dict])
def management_stop_tenant(
    tenant_id: int,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    require_platform(current)
    tenant = db.scalar(select(Tenant).where(Tenant.id == tenant_id, Tenant.deleted.is_(False)))
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="企业不存在")

    tenant.status = False
    tenant.stop_reason = "canceled" if tenant.service_start_date and tenant.service_start_date > date.today() else "manual"
    tenant.stopped_at = datetime.now()
    tenant.stopped_by = current.user.id
    identities = list(db.scalars(select(UserIdentity).where(UserIdentity.tenant_id == tenant_id, UserIdentity.deleted.is_(False))))
    affected_user_ids: set[int] = set()
    for identity in identities:
        identity.status = False
        identity.deleted = True
        affected_user_ids.add(identity.user_id)

    for user_id in affected_user_ids:
        active_identity = db.scalar(
            select(UserIdentity.id).where(
                UserIdentity.user_id == user_id,
                UserIdentity.status.is_(True),
                UserIdentity.deleted.is_(False),
            )
        )
        if active_identity is None:
            user = db.get(User, user_id)
            if user:
                user.status = False

    write_management_log(db, current, "企业停服", f"停止企业服务：{tenant.name}", target_module="企业管理", target_id=tenant.id, tenant_id=tenant.id, risk_level="关注")
    db.commit()
    return ApiResponse(data={"id": tenant.id, "status": tenant.status})


@router.patch("/tenants/{tenant_id}/restore", response_model=ApiResponse[dict])
def management_restore_tenant(
    tenant_id: int,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    require_platform(current)
    tenant = db.scalar(select(Tenant).where(Tenant.id == tenant_id, Tenant.deleted.is_(False)))
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="企业不存在")
    if tenant.service_end_date and tenant.service_end_date < date.today():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="服务已到期，请先延长服务期限后再恢复")

    tenant.status = service_status_from_period(tenant.service_start_date, tenant.service_end_date)
    tenant.stop_reason = None
    tenant.stopped_at = None
    tenant.stopped_by = None

    identities = list(db.scalars(select(UserIdentity).where(UserIdentity.tenant_id == tenant_id)))
    restored_user_ids: set[int] = set()
    for identity in identities:
        identity.status = True
        identity.deleted = False
        restored_user_ids.add(identity.user_id)

    for user_id in restored_user_ids:
        user = db.get(User, user_id)
        if user and not user.deleted:
            user.status = True

    write_management_log(db, current, "企业恢复", f"恢复企业服务：{tenant.name}", target_module="企业管理", target_id=tenant.id, tenant_id=tenant.id)
    db.commit()
    db.refresh(tenant)
    return ApiResponse(data=tenant_to_dict(tenant))


@router.get("/users", response_model=ApiResponse[list[dict]])
def management_users(
    keyword: str | None = None,
    tenant_id: int | None = None,
    identity_type: str | None = None,
    enabled: bool | None = Query(default=None),
    deleted: bool = False,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[list[dict]]:
    require_platform(current)
    users = list_managed_users(
        db,
        current.user,
        current.identity,
        keyword=keyword,
        tenant_id=tenant_id,
        identity_type=identity_type or None,
        status=enabled,
        deleted=deleted,
    )
    identity_menu_rows = db.execute(select(UserIdentityMenu.identity_id, UserIdentityMenu.menu_id)).all()
    identity_menu_map: dict[int, list[int]] = {}
    for identity_id, menu_id in identity_menu_rows:
        identity_menu_map.setdefault(identity_id, []).append(menu_id)

    return ApiResponse(data=[
        {
            "id": user.id,
            "username": user.username,
            "display_name": user.display_name,
            "status": user.status,
            "deleted": user.deleted,
            "created_by": user.created_by,
            "identities": [
                {
                    "id": identity.id,
                    "identity_type": identity.identity_type,
                    "identity_name": identity.identity_name,
                    "role_code": identity.role_code,
                    "position_id": identity.position_id,
                    "tenant_id": identity.tenant_id,
                    "tenant_name": identity.tenant.name if identity.tenant else None,
                    "menu_ids": identity_menu_map.get(identity.id, []),
                }
                for identity in user.identities
                if deleted or not identity.deleted
            ],
        }
        for user in users
    ])


@router.post("/users", response_model=ApiResponse[dict])
def management_create_user(
    payload: UserCreateRequest,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    require_platform(current)
    require_user_identity_create_permission(db, current, payload)
    try:
        user = create_managed_user(db, payload, current.user, current.identity)
        write_management_log(db, current, "用户新增", f"新增用户：{user.display_name}（{user.username}）", target_module="用户管理", target_id=user.id)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"数据库保存失败：{exc.__class__.__name__}") from exc
    return ApiResponse(data={"id": user.id, "username": user.username, "display_name": user.display_name})


@router.put("/users/{user_id}", response_model=ApiResponse[dict])
def management_update_user(
    user_id: int,
    payload: UserUpdateRequest,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    require_platform(current)
    require_user_identity_create_permission(db, current, payload, existing_user_id=user_id)
    try:
        user = update_managed_user(db, user_id, payload, current.user, current.identity)
        write_management_log(db, current, "用户修改", f"修改用户与权限：{user.display_name}（{user.username}）", target_module="用户管理", target_id=user.id, risk_level="关注")
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"数据库保存失败：{exc.__class__.__name__}") from exc
    return ApiResponse(data={"id": user.id, "username": user.username, "display_name": user.display_name})


@router.patch("/users/{user_id}/password", response_model=ApiResponse[dict])
def management_reset_password(
    user_id: int,
    payload: PasswordResetRequest,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    require_platform(current)
    try:
        reset_managed_user_password(db, user_id, payload.password, current.user, current.identity)
        write_management_log(db, current, "密码重置", f"重置用户密码：用户ID {user_id}", target_module="用户管理", target_id=user_id, risk_level="关注")
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ApiResponse(data={"id": user_id})


@router.patch("/users/{user_id}/status", response_model=ApiResponse[dict])
def management_set_user_status(
    user_id: int,
    enabled: bool,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    require_platform(current)
    try:
        user = set_managed_user_status(db, user_id, enabled, current.user, current.identity)
        write_management_log(db, current, "用户状态", f"{'启用' if enabled else '禁用'}用户：{user.display_name}（{user.username}）", target_module="用户管理", target_id=user.id, risk_level="关注" if not enabled else "正常")
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ApiResponse(data={"id": user.id, "status": user.status})


@router.delete("/users/{user_id}", response_model=ApiResponse[dict])
def management_delete_user(
    user_id: int,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    require_platform(current)
    try:
        user = delete_managed_user(db, user_id, current.user, current.identity)
        write_management_log(db, current, "用户删除", f"删除用户：{user.display_name}（{user.username}）", target_module="用户管理", target_id=user.id, risk_level="高危")
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ApiResponse(data={"id": user.id, "deleted": user.deleted, "status": user.status})


@router.patch("/users/{user_id}/restore", response_model=ApiResponse[dict])
def management_restore_user(
    user_id: int,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    require_platform(current)
    try:
        user = restore_managed_user(db, user_id, current.user, current.identity)
        write_management_log(db, current, "用户恢复", f"恢复用户：{user.display_name}（{user.username}）", target_module="用户管理", target_id=user.id)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ApiResponse(data={"id": user.id, "deleted": user.deleted, "status": user.status})


@router.get("/menus/config", response_model=ApiResponse[list[dict]])
def get_menu_configs(
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
    identity_type: str = Query(None, description="身份类型过滤"),
) -> ApiResponse[list[dict]]:
    """获取菜单配置列表"""
    require_platform(current)
    stmt = select(MenuConfig).where(MenuConfig.deleted.is_(False))
    if identity_type:
        stmt = stmt.where(MenuConfig.identity_type == identity_type)
    stmt = stmt.order_by(MenuConfig.sort_order.asc(), MenuConfig.id.asc())
    rows = list(db.scalars(stmt))
    return ApiResponse(data=[{
        "id": row.id,
        "menu_code": row.menu_code,
        "menu_name": row.menu_name,
        "identity_type": row.identity_type,
        "sort_order": row.sort_order,
        "is_visible": row.is_visible,
        "icon": row.icon,
        "route_path": row.route_path,
        "remark": row.remark,
    } for row in rows])


@router.put("/menus/config/{config_id}", response_model=ApiResponse[dict])
def update_menu_config(
        config_id: int,
        payload: MenuConfigUpdateRequest,
        current: CurrentSession = Depends(get_current_session),
        db: Session = Depends(get_db),
):
    """更新菜单配置（名称、排序、可见性）"""
    require_platform(current)
    config = db.scalar(select(MenuConfig).where(MenuConfig.id == config_id))
    if not config:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="菜单配置不存在")

    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(config, field, value)

    write_management_log(db, current, "菜单配置", f"修改菜单配置：{config.menu_name}", target_module="系统配置", target_id=config.id, risk_level="关注")
    db.commit()

    return ApiResponse(data={
        "id": config.id,
        "menu_code": config.menu_code,
        "menu_name": config.menu_name,
        "identity_type": config.identity_type,
        "sort_order": config.sort_order,
        "is_visible": config.is_visible,
        "icon": config.icon,
        "route_path": config.route_path,
        "remark": config.remark,
    })


@router.delete("/menus/config/{config_id}")
def delete_menu_config(
        config_id: int,
        current: CurrentSession = Depends(get_current_session),
        db: Session = Depends(get_db),
):
    """停用菜单配置（逻辑删除）"""
    require_platform(current)
    config = db.scalar(select(MenuConfig).where(MenuConfig.id == config_id))
    if not config:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="菜单配置不存在")

    config.deleted = True
    write_management_log(db, current, "菜单停用", f"停用菜单配置：{config.menu_name}", target_module="系统配置", target_id=config.id, risk_level="关注")
    db.commit()

    return ApiResponse(data={"message": "菜单已停用"})


@router.post("/menus/config/batch-update")
def batch_update_menu_configs(
        configs: list[MenuConfigBatchItem],
        current: CurrentSession = Depends(get_current_session),
        db: Session = Depends(get_db),
):
    """批量更新菜单配置"""
    require_platform(current)
    updated_count = 0
    for item in configs:
        config = db.scalar(select(MenuConfig).where(MenuConfig.id == item.id, MenuConfig.deleted.is_(False)))
        if config:
            update_data = item.model_dump(exclude_unset=True, exclude={"id"})
            for field, value in update_data.items():
                setattr(config, field, value)
            updated_count += 1

    write_management_log(db, current, "菜单批量配置", f"批量更新菜单配置：{updated_count} 项", target_module="系统配置", risk_level="关注")
    db.commit()

    return ApiResponse(data={"message": f"已更新 {updated_count} 个菜单配置"})
