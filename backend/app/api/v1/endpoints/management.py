from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentSession, get_current_session, require_platform
from app.api.http_errors import raise_read_endpoint_error
from app.core.database import get_db
from app.core.celery_queue_monitor import format_celery_monitor_zh, get_queue_monitor_snapshot
from app.core.redis_client import redis_health
from app.core.http_rate_limit import enforce_overview_rate_limit
from app.core.read_cache import (
    MANAGEMENT_OVERVIEW_CACHE_KEY,
    MANAGEMENT_OVERVIEW_CACHE_TTL,
    get_or_build_json_cache,
)
from app.services.system_config_service import (
    list_system_configs,
    update_system_config as persist_system_config,
)
from app.models.ops import OperationLog, SystemConfig
from app.models.permission import Menu, Position, PositionMenu, Role, UserIdentityMenu
from app.models.tenant import Tenant
from app.models.brand import BrandAsset
from app.models.monitor import GeoMonitorScheduleRun, GeoMonitorSubtask, GeoMonitorTask
from app.models.menu_config import MenuConfig
from app.models.user import User
from app.models.user_identity import UserIdentity
from app.schemas.common import ApiResponse
from app.services.deepseek_balance_service import fetch_deepseek_balance
from app.services.lead_diagnosis_service import lead_diagnosis_task_displays
from app.services.molizhishu_balance_service import fetch_molizhishu_balance
from app.services.credit_service import credit_ops_summary
from app.services.monitor_service import _exclude_gap_backfill_tasks
from app.services.operation_log_service import tenant_names_by_id, write_operation_log
from app.services.operation_log_labels import humanize_action_type, humanize_description, humanize_target_module
from app.schemas.permission import (
    MenuConfigBatchItem,
    MenuConfigUpdateRequest,
    MenuGrantItem,
    MenuInfo,
    PasswordResetRequest,
    PositionInfo,
    PositionSaveRequest,
    RoleInfo,
    TenantCreateRequest,
    TenantPurgeRequest,
    TenantTransferOwnerRequest,
    TenantUpdateRequest,
    UserCreateRequest,
    UserUpdateRequest,
)
from app.services.management_service import (
    _tenant_code_from_name,
    allocate_tenant_code,
    assert_actor_can_assign_identities,
    assert_actor_can_manage_target_user,
    create_managed_user,
    delete_managed_user,
    get_managed_user,
    list_managed_users,
    list_platform_sales_users,
    raise_if_live_tenant_name_or_code_conflict,
    raise_if_new_tenant_name_unavailable,
    reset_managed_user_password,
    restore_managed_user,
    set_managed_user_status,
    tenant_name_was_purged,
    transfer_tenant_owner,
    update_managed_user,
)
from app.services.menu_permission_service import (
    has_any_identity_menu_permission,
    has_identity_menu_permission,
    position_menu_grants,
    position_menu_grants_map,
    sync_all_menus_from_configs,
    sync_identity_menus_for_position,
    sync_menu_row_from_config,
    sync_position_menu_grants,
)
from app.services.tenant_account_service import (
    mark_tenant_inactive,
    restore_tenant_customer_accounts,
    sync_tenant_accounts_for_service_state,
)
from app.services.permission_service import (
    list_menus_by_identity_type,
    list_positions_by_identity_type,
    list_roles_by_identity_type,
)
from app.services.tenant_scope import ensure_sales_tenant_access, is_platform_admin_identity, sales_owned_tenant_ids
from app.services.tenant_logo_service import (
    clear_platform_logo,
    resolve_platform_logo_path,
    resolve_tenant_logo_path,
    save_platform_logo,
    save_tenant_logo,
    serialize_platform_logo_meta,
    tenant_logo_media_type,
)
from app.services.approval_service import can_review_approvals, queue_or_run

router = APIRouter(prefix="/management")


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
    return position.position_code == "PLATFORM_SALES"


def guard_sales_tenant(db: Session, current: CurrentSession, tenant_id: int) -> None:
    try:
        ensure_sales_tenant_access(db, current, tenant_id)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


_SYSTEM_CONFIG_CATEGORIES = frozenset({"secrets", "schedule", "cache_queue", "notification", "menu"})


def require_system_config_access(
    db: Session,
    current: CurrentSession,
    *,
    category: str | None = None,
    for_update: bool = False,
) -> None:
    from app.services.menu_permission_service import has_settings_menu_permission

    action = "can_update" if for_update else "can_export"
    if not has_settings_menu_permission(db, current.identity.id, action, category=category):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="当前账号无权访问系统配置")
    if is_sales_identity(db, current.identity):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="销售账号无权访问系统配置")


def _require_platform_menu(
    db: Session,
    current: CurrentSession,
    menu_code: str,
    action: str,
    detail: str | None = None,
) -> None:
    if not has_identity_menu_permission(db, current.identity.id, menu_code, action):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail or "当前账号无权执行此操作",
        )


def _has_user_management_access(db: Session, identity_id: int) -> bool:
    checks = (
        ("platform.users.list", ("can_export", "can_update", "can_delete")),
        ("platform.users.create.platform", ("can_create",)),
        ("platform.users.create.customer", ("can_create",)),
    )
    return any(has_any_identity_menu_permission(db, identity_id, menu_code, actions) for menu_code, actions in checks)


def _require_user_assignable_read(db: Session, current: CurrentSession, detail: str) -> None:
    """用户新增/列表页加载职位、角色、菜单选项时的只读数据。"""
    identity_id = current.identity.id
    if has_identity_menu_permission(db, identity_id, "platform.positions", "can_export"):
        return
    if _has_user_management_access(db, identity_id):
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def _require_tenant_list_read(db: Session, current: CurrentSession, detail: str) -> None:
    """企业下拉等只读场景：有企业管理或用户管理权限即可。"""
    identity_id = current.identity.id
    if has_identity_menu_permission(db, identity_id, "platform.audit.list", "can_export"):
        return
    if _has_user_management_access(db, identity_id):
        return
    if has_any_identity_menu_permission(db, identity_id, "platform.snapshot_backfill", ("can_export", "can_update")):
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


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


def _brand_asset_lookup(db: Session, tenant_ids: list[int]) -> dict[int, BrandAsset]:
    ids = [int(item) for item in tenant_ids if item]
    if not ids:
        return {}
    rows = list(
        db.scalars(
            select(BrandAsset).where(
                BrandAsset.tenant_id.in_(ids),
                BrandAsset.deleted.is_(False),
            )
        )
    )
    return {asset.tenant_id: asset for asset in rows}


def _schedule_daily_count(asset: BrandAsset | None) -> int | None:
    """与监测计划一致：按实际会触发的时段数，而非写死 3。"""
    if asset is None:
        return None
    from app.services.schedule_service import schedule_times_for_asset

    return len(schedule_times_for_asset(asset))


def tenant_to_dict(
    tenant: Tenant,
    *,
    owner_lookup: dict[int, User] | None = None,
    db: Session | None = None,
    asset: BrandAsset | None = None,
) -> dict:
    owner_display_name = None
    owner_username = None
    if tenant.owner_user_id:
        owner = owner_lookup.get(tenant.owner_user_id) if owner_lookup is not None else None
        if owner is None and db is not None:
            owner = db.get(User, tenant.owner_user_id)
        if owner is not None:
            owner_display_name = owner.display_name
            owner_username = owner.username
    resolved_asset = asset
    if resolved_asset is None and db is not None:
        resolved_asset = _brand_asset_lookup(db, [tenant.id]).get(tenant.id)
    return {
        "id": tenant.id,
        "name": tenant.name,
        "code": tenant.code,
        "status": tenant.status,
        "owner_user_id": tenant.owner_user_id,
        "owner_display_name": owner_display_name,
        "owner_username": owner_username,
        "stop_reason": tenant.stop_reason,
        "stopped_at": tenant.stopped_at.isoformat(sep=" ", timespec="minutes") if tenant.stopped_at else None,
        "stopped_by": tenant.stopped_by,
        "service_start_date": tenant.service_start_date.isoformat() if tenant.service_start_date else None,
        "service_end_date": tenant.service_end_date.isoformat() if tenant.service_end_date else None,
        "schedule_frequency": _schedule_daily_count(resolved_asset),
        "has_logo": bool(tenant.logo_path),
        "logo_updated_at": tenant.logo_updated_at.isoformat(sep=" ", timespec="seconds")
        if tenant.logo_updated_at
        else None,
        "billing_mode": getattr(tenant, "billing_mode", "hosted") or "hosted",
        "credit_balance": float(tenant.credit_balance or 0) if getattr(tenant, "credit_balance", None) is not None else None,
        "credit_reserved": float(tenant.credit_reserved or 0) if getattr(tenant, "credit_reserved", None) is not None else None,
        # 2026-09-01 - 商品卡开通状态给企业管理列表/详情
        "goods_card_enabled": bool(getattr(tenant, "goods_card_enabled", False)),
    }


def _tenant_owner_lookup(db: Session, tenants: list[Tenant]) -> dict[int, User]:
    owner_ids = {tenant.owner_user_id for tenant in tenants if tenant.owner_user_id}
    if not owner_ids:
        return {}
    return {
        user.id: user
        for user in db.scalars(select(User).where(User.id.in_(owner_ids)))
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


def operation_log_to_dict(item: OperationLog, *, tenant_name: str | None = None) -> dict:
    garbled = any(is_garbled_log_text(text) for text in [item.operator_name, item.action_type, item.description, item.risk_level])
    return {
        "id": item.id,
        "operator_name": clean_log_text(item.operator_name, "历史日志" if garbled else "系统"),
        "action_type": humanize_action_type(item.action_type),
        "description": clean_log_text(
            humanize_description(item.description),
            "该条历史日志在早期编码异常时写入，原文不可恢复",
        ),
        "risk_level": clean_log_text(item.risk_level, "历史记录" if garbled else "普通"),
        "ip_address": item.ip_address,
        "target_module": humanize_target_module(item.target_module, description=item.description),
        "tenant_id": item.tenant_id,
        "tenant_name": tenant_name,
        "created_at": item.created_at.isoformat(sep=" ", timespec="minutes"),
    }


def operation_logs_to_dicts(db: Session, rows: list[OperationLog]) -> list[dict]:
    name_map = tenant_names_by_id(db, [item.tenant_id for item in rows])
    return [
        operation_log_to_dict(
            item,
            tenant_name=name_map.get(item.tenant_id) if item.tenant_id else None,
        )
        for item in rows
    ]


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
    return write_operation_log(
        db,
        current,
        action_type,
        description,
        target_module=target_module,
        target_id=target_id,
        tenant_id=tenant_id,
        risk_level=risk_level,
    )


def position_code_from_name(identity_type: str, name: str) -> str:
    import hashlib

    digest = hashlib.sha256(f"{identity_type}:{name}".encode("utf-8")).hexdigest()[:8].upper()
    return f"{identity_type}_POS_{digest}"


def _strip_purge_grant_unless_admin(position: Position, menu_grants: list | None) -> list | None:
    """2026-07-30 - 彻底删除仅 PLATFORM_ADMIN，非管理员职位保存时剥掉该授权。"""
    if not menu_grants:
        return menu_grants
    if position.position_code == "PLATFORM_ADMIN":
        return menu_grants
    filtered = []
    for item in menu_grants:
        code = getattr(item, "menu_code", None)
        if code == "platform.audit.purge":
            continue
        filtered.append(item)
    return filtered


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


def _apply_position_allowed_platforms(db: Session, position: Position, payload: PositionSaveRequest) -> None:
    from app.services.menu_permission_service import normalize_allowed_monitor_platforms

    # 2026-07-30 - 平台白名单按职位直接保存，不再依赖「编辑平台范围」总开关
    position.allowed_monitor_platforms_json = normalize_allowed_monitor_platforms(
        list(payload.allowed_monitor_platforms or [])
    )


def position_to_dict(
    position: Position,
    *,
    grants: list[MenuGrantItem] | None = None,
    db: Session | None = None,
) -> dict:
    from app.services.menu_permission_service import normalize_allowed_monitor_platforms

    resolved_grants = grants if grants is not None else (
        position_menu_grants(db, position.id) if db is not None else []
    )
    return PositionInfo(
        id=position.id,
        position_code=position.position_code,
        position_name=position.position_name,
        identity_type=position.identity_type,
        role_code=position.role_code,
        description=position.description,
        menu_ids=[item.menu_id for item in resolved_grants],
        menu_grants=resolved_grants,
        allowed_monitor_platforms=normalize_allowed_monitor_platforms(
            list(getattr(position, "allowed_monitor_platforms_json", None) or [])
        ),
    ).model_dump()


def positions_to_dicts(db: Session, positions: list[Position]) -> list[dict]:
    grants_map = position_menu_grants_map(db, [position.id for position in positions])
    return [
        position_to_dict(position, grants=grants_map.get(position.id, []))
        for position in positions
    ]


@router.get("/menus", response_model=ApiResponse[list[dict]])
def management_menus(
    identity_type: str = "PLATFORM",
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[list[dict]]:
    require_platform(current)
    _require_user_assignable_read(db, current, "当前账号无权查看菜单配置")
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
    _require_user_assignable_read(db, current, "当前账号无权查看角色配置")
    roles = list_roles_by_identity_type(db, identity_type)
    # 2026-07-30 - 非管理员不可见管理员角色，避免下拉提权
    if identity_type == "PLATFORM" and not is_platform_admin_identity(db, current.identity):
        roles = [role for role in roles if str(role.role_code or "").upper() != "PLATFORM_ADMIN"]
    data = [
        RoleInfo(
            id=role.id,
            role_code=role.role_code,
            role_name=role.role_name,
            identity_type=role.identity_type,
            data_scope=role.data_scope,
        ).model_dump()
        for role in roles
    ]
    return ApiResponse(data=data)


@router.get("/positions", response_model=ApiResponse[list[dict]])
def management_positions(
    identity_type: str = "PLATFORM",
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[list[dict]]:
    require_platform(current)
    _require_user_assignable_read(db, current, "当前账号无权查看职位列表")
    positions = list_positions_by_identity_type(db, identity_type)
    # 2026-07-30 - 非管理员不可见管理员职位，避免下拉提权
    if identity_type == "PLATFORM" and not is_platform_admin_identity(db, current.identity):
        positions = [item for item in positions if item.position_code != "PLATFORM_ADMIN"]
    return ApiResponse(data=positions_to_dicts(db, positions))


@router.post("/positions", response_model=ApiResponse[dict])
def management_create_position(
    payload: PositionSaveRequest,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    require_platform(current)
    # ponytail: 矩阵无 can_create（仅 export/update/delete）；新增与编辑共用 can_update
    _require_platform_menu(db, current, "platform.positions", "can_update", "当前账号无权新增职位")
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
        allowed_monitor_platforms_json=[],
    )
    db.add(position)
    db.flush()
    _apply_position_allowed_platforms(db, position, payload)
    sync_position_menus(
        db,
        position.id,
        payload.menu_ids,
        identity_type=payload.identity_type,
        writable=payload.identity_type == "PLATFORM",
        menu_grants=_strip_purge_grant_unless_admin(position, payload.menu_grants or None),
    )
    synced_users = sync_identity_menus_for_position(db, position.id)
    write_management_log(db, current, "职位新增", f"新增职位：{position.position_name}（已同步 {synced_users} 个身份）", target_module="职位管理", target_id=position.id)
    db.commit()
    db.refresh(position)
    return ApiResponse(data=position_to_dict(position, db=db))


@router.put("/positions/{position_id}", response_model=ApiResponse[dict])
def management_update_position(
    position_id: int,
    payload: PositionSaveRequest,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    require_platform(current)
    _require_platform_menu(db, current, "platform.positions", "can_update", "当前账号无权修改职位")
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
    _apply_position_allowed_platforms(db, position, payload)
    sync_position_menus(
        db,
        position.id,
        payload.menu_ids,
        identity_type=payload.identity_type,
        writable=payload.identity_type == "PLATFORM",
        menu_grants=_strip_purge_grant_unless_admin(position, payload.menu_grants or None),
    )
    synced_users = sync_identity_menus_for_position(db, position.id)
    write_management_log(db, current, "职位修改", f"修改职位：{position.position_name}（已同步 {synced_users} 个身份）", target_module="职位管理", target_id=position.id, risk_level="关注")
    db.commit()
    db.refresh(position)
    return ApiResponse(data=position_to_dict(position, db=db))


@router.delete("/positions/{position_id}", response_model=ApiResponse[dict])
def management_delete_position(
    position_id: int,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    require_platform(current)
    _require_platform_menu(db, current, "platform.positions", "can_delete", "当前账号无权删除职位")
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
    _require_tenant_list_read(db, current, "当前账号无权查看企业列表")
    stmt = select(Tenant).where(Tenant.deleted.is_(False)).order_by(Tenant.id.desc())
    if is_sales_identity(db, current.identity):
        stmt = stmt.where(Tenant.owner_user_id == current.user.id)
    tenant_rows = list(db.scalars(stmt))
    owner_lookup = _tenant_owner_lookup(db, tenant_rows)
    asset_lookup = _brand_asset_lookup(db, [item.id for item in tenant_rows])
    return ApiResponse(
        data=[
            tenant_to_dict(item, owner_lookup=owner_lookup, asset=asset_lookup.get(item.id))
            for item in tenant_rows
        ]
    )


@router.get("/tenants/{tenant_id}/customer-preview-menus", response_model=ApiResponse[dict])
def management_tenant_customer_preview_menus(
    tenant_id: int,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """平台预览客户门户：返回该企业客户侧实际可见菜单（含商品卡开通过滤）。"""
    # 2026-09-04 - 预览侧栏不能写死菜单，否则商品卡未开通也会出现/开通了也不出现
    require_platform(current)
    from app.api.http_errors import raise_read_endpoint_error
    from app.services.menu_permission_service import get_tenant_customer_preview_menus
    from app.services.tenant_scope import resolve_customer_preview_tenant_id

    try:
        resolved_id = resolve_customer_preview_tenant_id(db, current, tenant_id)
        menus = get_tenant_customer_preview_menus(db, resolved_id)
    except (ValueError, PermissionError) as exc:
        # 2026-08-27 - 已删/不存在企业预览勿 500 - 走统一 400/403
        raise_read_endpoint_error(exc, context="customer_preview_menus")
    from app.services.monitor_service import credit_customer_includes_today

    # 2026-08-27 - 预览算力企业须含今日口径，勿沿用平台会话「截至昨日」
    return ApiResponse(
        data={
            "menus": [item.model_dump() for item in menus],
            "customer_includes_today": credit_customer_includes_today(db, resolved_id),
        }
    )


@router.get("/tenants/name-check", response_model=ApiResponse[dict])
def management_tenant_name_check(
    name: str = Query(..., min_length=2, max_length=150),
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """新建企业前校验名称：在册重名、待审批同名单都拦。"""
    require_platform(current)
    _require_platform_menu(db, current, "platform.audit.list", "can_update", "当前账号无权新增企业")
    try:
        # 2026-08-18 - 同名也能点下一步 - 销售列表按归属过滤，这里查全库+待审
        raise_if_new_tenant_name_unavailable(db, name)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ApiResponse(data={"available": True})


@router.get("/operation-logs", response_model=ApiResponse[list[dict]])
def management_operation_logs(
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[list[dict]]:
    require_platform(current)
    _require_platform_menu(db, current, "platform.logs", "can_export", "当前账号无权查看操作日志")
    stmt = select(OperationLog).order_by(OperationLog.id.desc()).limit(100)
    owned = sales_owned_tenant_ids(db, current)
    if owned is not None:
        if not owned:
            return ApiResponse(data=[])
        stmt = stmt.where(
            or_(
                OperationLog.tenant_id.in_(owned),
                OperationLog.tenant_id.is_(None),
            )
        )
    rows = db.scalars(stmt)
    return ApiResponse(data=operation_logs_to_dicts(db, rows))


@router.get("/celery-monitor", response_model=ApiResponse[dict])
def management_celery_monitor(
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """中文版 Celery 队列与 Worker 监控数据。"""
    require_platform(current)
    require_system_config_access(db, current, category="cache_queue")
    return ApiResponse(data=format_celery_monitor_zh(get_queue_monitor_snapshot()))


@router.get("/system-configs", response_model=ApiResponse[list[dict]])
def management_system_configs(
    category: str | None = Query(default=None, description="secrets / schedule / cache_queue / notification"),
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[list[dict]]:
    from app.services.menu_permission_service import accessible_settings_categories

    require_platform(current)
    if category and category not in _SYSTEM_CONFIG_CATEGORIES - {"menu"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="无效的配置分类")
    require_system_config_access(db, current, category=category)
    data = list_system_configs(db, category=category)
    if category is None:
        allowed = accessible_settings_categories(db, current.identity.id, "can_export")
        if allowed is not None:
            data = [item for item in data if item.get("category") in allowed]
    return ApiResponse(data=data)


@router.put("/system-configs/{config_id}", response_model=ApiResponse[dict])
def management_update_system_config(
    config_id: int,
    payload: dict,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    from app.services.system_config_service import CONFIG_REGISTRY

    require_platform(current)
    existing = db.scalar(select(SystemConfig).where(SystemConfig.id == config_id))
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="配置项不存在")
    meta = CONFIG_REGISTRY.get(existing.config_key)
    require_system_config_access(
        db,
        current,
        category=meta.category if meta else None,
        for_update=True,
    )
    new_value = payload.get("config_value")
    if new_value is None or not str(new_value).strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="配置值不能为空")
    updated_by = current.user.display_name or current.identity.identity_name or current.user.username
    try:
        data = persist_system_config(db, config_id, str(new_value), updated_by=updated_by)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    write_management_log(
        db,
        current,
        "系统配置",
        f"修改系统配置「{data['config_name']}」：更新 {data['config_key']} 参数值",
        target_module="系统配置",
        target_id=config_id,
        risk_level="关注",
    )
    db.commit()
    return ApiResponse(data=data)


@router.get("/overview", response_model=ApiResponse[dict])
def management_overview(
    request: Request,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """平台运营总览聚合接口，避免首页多接口聚合导致加载慢。"""
    require_platform(current)
    enforce_overview_rate_limit(request, current)
    owned_tenant_ids = sales_owned_tenant_ids(db, current)
    cache_key = MANAGEMENT_OVERVIEW_CACHE_KEY
    if owned_tenant_ids is not None:
        cache_key = f"{MANAGEMENT_OVERVIEW_CACHE_KEY}:sales:{current.user.id}"
    try:
        data = get_or_build_json_cache(
            cache_key,
            lambda: _build_management_overview(db, tenant_ids=owned_tenant_ids),
            ttl_seconds=MANAGEMENT_OVERVIEW_CACHE_TTL,
        )
        return ApiResponse(data=data)
    except Exception as exc:
        raise_read_endpoint_error(exc, context="management.overview")


@router.get("/quota-daily-cost", response_model=ApiResponse[dict])
def management_quota_daily_cost(
    year: int | None = Query(default=None, ge=2020, le=2100),
    month: int | None = Query(default=None, ge=1, le=12),
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """监测按日消耗日历；默认当月。DeepSeek 无官方日流水，不在此返回格子。"""
    # 2026-07-31 - 费用日历要当月热力 - 独立轻量接口，避免塞进 overview 加重缓存
    require_platform(current)
    today = date.today()
    target_year = int(year or today.year)
    target_month = int(month or today.month)
    owned_tenant_ids = sales_owned_tenant_ids(db, current)
    try:
        from app.services.quota_daily_cost_service import fetch_molizhishu_daily_costs

        data = fetch_molizhishu_daily_costs(
            db,
            year=target_year,
            month=target_month,
            tenant_ids=owned_tenant_ids,
        )
        return ApiResponse(data=data)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise_read_endpoint_error(exc, context="management.quota_daily_cost")


# 方案 C：平台分布近窗；费用排行稍宽；重聚合走物理预聚合表
from app.services.ops_overview_rollup_service import (
    COST_RANKING_WINDOW_DAYS,
    PLATFORM_STATS_WINDOW_DAYS,
    load_or_refresh_overview_rollup,
)


def _empty_management_overview() -> dict:
    return {
        "kpis": {
            "today_tasks": 0,
            "today_completed_tasks": 0,
            "today_failed_tasks": 0,
            "today_cost": 0,
            "active_tenants": 0,
            "expiring_tenants": 0,
            "api_success_rate": 0,
        },
        "service_counts": {"active": 0, "pending": 0, "expired": 0, "manual_stopped": 0, "canceled": 0, "stopped": 0},
        "expiring_tenants": [],
        "platform_stats": [],
        "cost_ranking": [],
        "quota_overview": {
            "used_amount": 0,
            "today_amount": 0,
            "estimated_month_amount": 0,
            "total_subtasks": 0,
            "avg_cost_per_subtask": 0,
        },
        "customer_data": {
            "tenant_total": 0,
            "active_tenants": 0,
            "task_total": 0,
            "subtask_total": 0,
            "mention_rate": 0,
            "source_count": 0,
        },
        "recent_tasks": [],
        "alerts": [],
        "todo_items": [],
        "operation_logs": [],
        "system_health": [],
        "celery_queues": {},
        "molizhishu_balance": fetch_molizhishu_balance(),
        "deepseek_balance": fetch_deepseek_balance(),
        "meta": {
            "platform_stats_window_days": PLATFORM_STATS_WINDOW_DAYS,
            "cost_ranking_window_days": COST_RANKING_WINDOW_DAYS,
        },
    }


def _build_management_overview(db: Session, tenant_ids: list[int] | None = None) -> dict:
    if tenant_ids is not None and not tenant_ids:
        return _empty_management_overview()

    today = date.today()
    tomorrow = today + timedelta(days=1)
    thirty_days_later = today + timedelta(days=30)
    terminal_statuses = {"completed", "partial_completed", "failed", "stopped"}

    tenant_stmt = select(Tenant).where(Tenant.deleted.is_(False))
    if tenant_ids is not None:
        tenant_stmt = tenant_stmt.where(Tenant.id.in_(tenant_ids))
    tenants = list(db.scalars(tenant_stmt))
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

    today_task_stmt = select(GeoMonitorTask).where(
        GeoMonitorTask.deleted.is_(False),
        GeoMonitorTask.created_at >= datetime.combine(today, datetime.min.time()),
        GeoMonitorTask.created_at < datetime.combine(tomorrow, datetime.min.time()),
    )
    # 漏跑补录占位保留在待补录中，不作为真实监测任务统计。
    today_task_stmt = _exclude_gap_backfill_tasks(today_task_stmt)
    if tenant_ids is not None:
        today_task_stmt = today_task_stmt.where(GeoMonitorTask.tenant_id.in_(tenant_ids))
    today_task_rows = list(db.scalars(today_task_stmt))
    recent_task_stmt = (
        select(GeoMonitorTask)
        .where(GeoMonitorTask.deleted.is_(False))
        .order_by(GeoMonitorTask.created_at.desc())
        .limit(12)
    )
    recent_task_stmt = _exclude_gap_backfill_tasks(recent_task_stmt)
    if tenant_ids is not None:
        recent_task_stmt = recent_task_stmt.where(GeoMonitorTask.tenant_id.in_(tenant_ids))
    all_recent_tasks = list(db.scalars(recent_task_stmt))
    tenant_name_map = {tenant.id: tenant.name for tenant in tenants}
    recent_task_slice = all_recent_tasks[:8]
    lead_task_displays = lead_diagnosis_task_displays(db, [task.task_id for task in recent_task_slice])

    today_task_ids = [task.task_id for task in today_task_rows]
    today_cost = 0.0
    if today_task_ids:
        today_cost = float(db.scalar(
            select(func.coalesce(func.sum(GeoMonitorSubtask.amount), 0)).where(GeoMonitorSubtask.task_id.in_(today_task_ids))
        ) or 0)

    heavy = load_or_refresh_overview_rollup(
        db,
        tenant_ids=tenant_ids,
        tenant_name_map=tenant_name_map,
        service_active=service_counts.get("active", 0),
        tenant_total=len(tenants),
        today_cost=today_cost,
    )
    # today_cost 当日变化：覆盖 rollup 里可能过期的今日金额
    quota_overview = dict(heavy.get("quota_overview") or {})
    quota_overview["today_amount"] = round(today_cost, 4)
    quota_overview["estimated_month_amount"] = round(today_cost * 30, 4)
    platform_stats = heavy.get("platform_stats") or []
    cost_ranking = heavy.get("cost_ranking") or []
    customer_data = heavy.get("customer_data") or {
        "tenant_total": len(tenants),
        "active_tenants": service_counts.get("active", 0),
        "task_total": 0,
        "subtask_total": 0,
        "mention_rate": 0,
        "source_count": 0,
    }
    customer_data = {
        **customer_data,
        "tenant_total": len(tenants),
        "active_tenants": service_counts.get("active", 0),
    }
    pending_backfill = int(heavy.get("pending_backfill") or 0)
    overview_meta = heavy.get("meta") or {
        "platform_stats_window_days": PLATFORM_STATS_WINDOW_DAYS,
        "cost_ranking_window_days": COST_RANKING_WINDOW_DAYS,
    }

    # 2026-08-03 - 调度失败/成功率按「今日全量」统计；曾 limit(20) 把 5 次失败放大成 75% 成功率
    # 服务未开通导致的闸门跳过不计入「调度失败」（避免运营看板吓人）
    from app.services.tenant_account_service import is_service_gate_schedule_message

    schedule_day_start = datetime.combine(today, datetime.min.time())

    def _today_schedule_count(*, status: str | None = None) -> int:
        stmt = select(func.count()).select_from(GeoMonitorScheduleRun).where(
            GeoMonitorScheduleRun.created_at >= schedule_day_start
        )
        if tenant_ids is not None:
            stmt = stmt.where(GeoMonitorScheduleRun.tenant_id.in_(tenant_ids))
        if status is not None:
            stmt = stmt.where(GeoMonitorScheduleRun.status == status)
        return int(db.scalar(stmt) or 0)

    failed_stmt = select(GeoMonitorScheduleRun).where(
        GeoMonitorScheduleRun.created_at >= schedule_day_start,
        GeoMonitorScheduleRun.status == "failed",
    )
    if tenant_ids is not None:
        failed_stmt = failed_stmt.where(GeoMonitorScheduleRun.tenant_id.in_(tenant_ids))
    today_schedule_failed = sum(
        1
        for row in db.scalars(failed_stmt)
        if not is_service_gate_schedule_message(row.error_message)
    )
    today_schedule_submitted = _today_schedule_count(status="submitted")
    today_schedule_total = _today_schedule_count()

    log_stmt = select(OperationLog).order_by(OperationLog.created_at.desc()).limit(8)
    if tenant_ids is not None:
        log_stmt = log_stmt.where(OperationLog.tenant_id.in_(tenant_ids))
    recent_logs = list(db.scalars(log_stmt))
    failed_tasks = [
        task
        for task in all_recent_tasks
        if task.status in {"failed", "stopped"} or (task.failed_items or 0) > 0
    ]
    running_tasks = [task for task in all_recent_tasks if task.status not in terminal_statuses]
    todo_items = []
    if expiring_tenants:
        todo_items.append({"type": "renewal", "title": "客户服务即将到期", "count": len(expiring_tenants), "level": "warning"})
    if failed_tasks:
        todo_items.append({"type": "failed_task", "title": "失败任务待处理", "count": len(failed_tasks), "level": "danger"})
    if pending_backfill:
        todo_items.append({
            "type": "snapshot_backfill",
            "title": "快照待补录",
            "count": pending_backfill,
            "level": "warning",
        })
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
            "api_success_rate": round((today_schedule_submitted / max(1, today_schedule_total)) * 100, 1),
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
                "tenant_name": (
                    lead_task_displays.get(task.task_id, {}).get("tenant_name")
                    or tenant_name_map.get(task.tenant_id)
                    or "未绑定企业"
                ),
                "monitor_keywords": (
                    lead_task_displays.get(task.task_id, {}).get("monitor_keywords")
                    or task.monitor_keywords
                ),
                "status": task.status,
                "total_items": task.total_items,
                "completed_items": task.completed_items,
                "failed_items": task.failed_items,
                "created_at": task.created_at.isoformat(sep=" ", timespec="minutes"),
                "last_error": task.last_error,
            }
            for task in recent_task_slice
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
        "operation_logs": operation_logs_to_dicts(db, recent_logs),
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
        "deepseek_balance": fetch_deepseek_balance(),
        "credit_summary": credit_ops_summary(db),
        "meta": overview_meta,
    }
    return data


@router.post("/tenants", response_model=ApiResponse[dict])
def management_create_tenant(
    payload: TenantCreateRequest,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    require_platform(current)
    _require_platform_menu(db, current, "platform.audit.list", "can_update", "当前账号无权新增企业")
    validate_service_period(payload.service_start_date, payload.service_end_date)
    name = payload.name.strip()
    # 2026-07-30 - 企业重名方案 B - 在册拦截分文案；软删可再建并换 code
    preferred_code = (payload.code or _tenant_code_from_name(name)).strip()
    try:
        raise_if_new_tenant_name_unavailable(
            db, name, allow_own_pending_user_id=current.user.id,
        )
        raise_if_live_tenant_name_or_code_conflict(db, name=name, code=preferred_code)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    def _execute():
        was_purged = tenant_name_was_purged(db, name)
        code = allocate_tenant_code(db, name, preferred_code)

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
        from app.services.management_service import apply_tenant_billing_mode_on_create

        apply_tenant_billing_mode_on_create(
            db,
            tenant,
            payload.billing_mode,
            opening_credit_amount=payload.opening_credit_amount,
            operator_user_id=current.user.id,
        )
        if not tenant.status:
            if tenant.stop_reason == "expired" and tenant.stopped_at is None:
                tenant.stopped_at = datetime.now()
            sync_tenant_accounts_for_service_state(db, tenant)
        write_management_log(db, current, "企业新增", f"新增企业：{tenant.name}", target_module="企业管理", target_id=tenant.id, tenant_id=tenant.id)
        db.commit()
        db.refresh(tenant)
        data = tenant_to_dict(tenant, db=db)
        if was_purged:
            data["name_was_purged"] = True
        return data

    try:
        # 2026-08-11 - 销售确认新增企业却免审落库 - 接入已有 management.tenant.create 审批
        pending, result = queue_or_run(
            db,
            current,
            operation_key="management.tenant.create",
            module="tenant",
            action="create",
            summary=f"新增企业：{name}",
            payload={"body": payload.model_dump(mode="json")},
            executor=_execute,
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"数据库保存失败：{exc.__class__.__name__}") from exc
    return ApiResponse(data=result)


@router.put("/tenants/{tenant_id}", response_model=ApiResponse[dict])
def management_update_tenant(
    tenant_id: int,
    payload: TenantUpdateRequest,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    require_platform(current)
    _require_platform_menu(db, current, "platform.audit.list", "can_update", "当前账号无权修改企业")
    guard_sales_tenant(db, current, tenant_id)
    tenant = db.scalar(select(Tenant).where(Tenant.id == tenant_id, Tenant.deleted.is_(False)))
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="企业不存在")

    from app.services.tenant_account_service import tenant_service_is_operational

    was_operational = tenant_service_is_operational(tenant)

    old_name = tenant.name
    old_code = tenant.code
    old_start = tenant.service_start_date
    old_end = tenant.service_end_date

    validate_service_period(payload.service_start_date, payload.service_end_date)
    name = payload.name.strip()
    code = (payload.code or tenant.code or _tenant_code_from_name(name)).strip()
    try:
        raise_if_live_tenant_name_or_code_conflict(db, name=name, code=code, exclude_id=tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    tenant.name = name
    tenant.code = code
    tenant.service_start_date = payload.service_start_date
    tenant.service_end_date = payload.service_end_date

    # 2026-09-01 - 商品卡开关可随企业资料更新（平台企业管理）
    if payload.goods_card_enabled is not None:
        enabled = payload.goods_card_enabled is True
        tenant.goods_card_enabled = enabled
        from app.services.menu_permission_service import sync_goods_card_menu_for_tenant

        sync_goods_card_menu_for_tenant(db, tenant_id, enabled=enabled)
    period_status = service_status_from_period(payload.service_start_date, payload.service_end_date)
    if tenant.stop_reason in {"manual", "canceled"}:
        tenant.status = False
    else:
        tenant.status = period_status
        tenant.stop_reason = "expired" if payload.service_end_date and payload.service_end_date < date.today() else None
        if tenant.status:
            tenant.stopped_at = None
            tenant.stopped_by = None
        elif tenant.stop_reason == "expired" and tenant.stopped_at is None:
            tenant.stopped_at = datetime.now()
    sync_tenant_accounts_for_service_state(db, tenant)
    changes: list[str] = []
    if old_name != name:
        changes.append(f"名称「{old_name}」→「{name}」")
    if old_code != code:
        changes.append(f"编码「{old_code}」→「{code}」")
    if old_start != payload.service_start_date:
        changes.append("调整服务开始日期")
    if old_end != payload.service_end_date:
        changes.append("调整服务结束日期")
    detail = "；".join(changes) if changes else "更新企业服务状态"
    write_management_log(
        db,
        current,
        "企业修改",
        f"修改企业「{name}」：{detail}",
        target_module="企业管理",
        target_id=tenant.id,
        tenant_id=tenant.id,
    )
    db.commit()
    db.refresh(tenant)
    from app.services.schedule_service import maybe_kick_brand_words_after_service_became_active

    maybe_kick_brand_words_after_service_became_active(
        tenant_id=tenant.id,
        became_active=tenant_service_is_operational(tenant) and not was_operational,
    )
    return ApiResponse(data=tenant_to_dict(tenant, db=db))


@router.post("/tenants/{tenant_id}/logo", response_model=ApiResponse[dict])
async def management_upload_tenant_logo(
    tenant_id: int,
    file: UploadFile = File(...),
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """上传企业 Logo（平台端，png/jpg/webp ≤2MB）。"""
    require_platform(current)
    _require_platform_menu(db, current, "platform.audit.list", "can_update", "当前账号无权上传企业 Logo")
    guard_sales_tenant(db, current, tenant_id)
    try:
        data = await save_tenant_logo(db, current, tenant_id, file)
        write_management_log(
            db,
            current,
            "企业 Logo",
            f"上传企业 Logo：tenant_id={tenant_id}",
            target_module="企业管理",
            target_id=tenant_id,
            tenant_id=tenant_id,
        )
        db.commit()
    except PermissionError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Logo 上传失败：{exc}") from exc
    return ApiResponse(data=data)


@router.get("/tenants/{tenant_id}/logo")
def management_get_tenant_logo(
    tenant_id: int,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> FileResponse:
    """读取企业 Logo（鉴权 + 租户范围）。"""
    try:
        tenant, file_path = resolve_tenant_logo_path(db, current, tenant_id)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return FileResponse(
        path=file_path,
        media_type=tenant_logo_media_type(file_path),
        headers={"Cache-Control": "private, max-age=3600"},
    )



@router.get("/platform-brand/logo/meta", response_model=ApiResponse[dict])
def management_platform_logo_meta() -> ApiResponse[dict]:
    """平台默认 Logo 元信息（公开，供侧栏/登录/页签兜底）。"""
    # 2026-09-07 - 平台默认 Logo 后台可改 - meta 免登便于登录页与 favicon
    return ApiResponse(data=serialize_platform_logo_meta())


@router.get("/platform-brand/logo")
def management_get_platform_logo() -> FileResponse:
    """读取平台默认 Logo（公开）。"""
    try:
        file_path = resolve_platform_logo_path()
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return FileResponse(
        path=file_path,
        media_type=tenant_logo_media_type(file_path),
        headers={"Cache-Control": "public, max-age=300"},
    )


@router.post("/platform-brand/logo", response_model=ApiResponse[dict])
async def management_upload_platform_logo(
    file: UploadFile = File(...),
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """上传平台默认 Logo（系统配置权限）。"""
    require_platform(current)
    require_system_config_access(db, current, for_update=True)
    try:
        data = await save_platform_logo(file)
        write_management_log(
            db,
            current,
            "平台默认 Logo",
            "上传平台默认 Logo",
            target_module="系统配置",
            risk_level="关注",
        )
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Logo 上传失败：{exc}") from exc
    return ApiResponse(data=data)


@router.delete("/platform-brand/logo", response_model=ApiResponse[dict])
def management_clear_platform_logo(
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """恢复平台默认 Logo 为内置亦智标（删除自定义文件）。"""
    require_platform(current)
    require_system_config_access(db, current, for_update=True)
    data = clear_platform_logo()
    write_management_log(
        db,
        current,
        "平台默认 Logo",
        "恢复平台默认 Logo 为内置标",
        target_module="系统配置",
        risk_level="关注",
    )
    db.commit()
    return ApiResponse(data=data)


@router.get("/tenant-sales-owners", response_model=ApiResponse[list[dict]])
def management_tenant_sales_owners(
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[list[dict]]:
    require_platform(current)
    if not can_review_approvals(db, current):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="仅运营或管理员可转移企业归属")
    return ApiResponse(data=list_platform_sales_users(db))


@router.patch("/tenants/{tenant_id}/owner", response_model=ApiResponse[dict])
def management_transfer_tenant_owner(
    tenant_id: int,
    payload: TenantTransferOwnerRequest,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    require_platform(current)
    if not can_review_approvals(db, current):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="仅运营或管理员可转移企业归属")
    tenant = db.scalar(select(Tenant).where(Tenant.id == tenant_id, Tenant.deleted.is_(False)))
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="企业不存在")
    old_owner_id = tenant.owner_user_id
    old_owner = db.get(User, old_owner_id) if old_owner_id else None
    try:
        tenant = transfer_tenant_owner(db, tenant_id, payload.owner_user_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    new_owner = db.get(User, tenant.owner_user_id)
    old_label = old_owner.display_name if old_owner else "未指定"
    new_label = new_owner.display_name if new_owner else str(payload.owner_user_id)
    write_management_log(
        db,
        current,
        "企业归属转移",
        f"企业「{tenant.name}」归属销售：{old_label} → {new_label}",
        target_module="企业管理",
        target_id=tenant.id,
        tenant_id=tenant.id,
        risk_level="关注",
    )
    db.commit()
    db.refresh(tenant)
    return ApiResponse(data=tenant_to_dict(tenant, db=db))


@router.delete("/tenants/{tenant_id}", response_model=ApiResponse[dict])
def management_stop_tenant(
    tenant_id: int,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    require_platform(current)
    _require_platform_menu(db, current, "platform.audit.list", "can_delete", "当前账号无权停止企业服务")
    guard_sales_tenant(db, current, tenant_id)
    tenant = db.scalar(select(Tenant).where(Tenant.id == tenant_id, Tenant.deleted.is_(False)))
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="企业不存在")

    mark_tenant_inactive(
        db,
        tenant,
        stop_reason="canceled" if tenant.service_start_date and tenant.service_start_date > date.today() else "manual",
        stopped_by=current.user.id,
    )

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
    _require_platform_menu(db, current, "platform.audit.list", "can_update", "当前账号无权恢复企业服务")
    guard_sales_tenant(db, current, tenant_id)
    tenant = db.scalar(select(Tenant).where(Tenant.id == tenant_id, Tenant.deleted.is_(False)))
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="企业不存在")
    if tenant.service_end_date and tenant.service_end_date < date.today():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="服务已到期，请先延长服务期限后再恢复")

    def _execute():
        from app.services.tenant_account_service import tenant_service_is_operational

        live = db.scalar(select(Tenant).where(Tenant.id == tenant_id, Tenant.deleted.is_(False)))
        if live is None:
            raise ValueError("企业不存在")
        if live.service_end_date and live.service_end_date < date.today():
            raise ValueError("服务已到期，请先延长服务期限后再恢复")
        was_operational = tenant_service_is_operational(live)
        live.status = service_status_from_period(live.service_start_date, live.service_end_date)
        live.stop_reason = None
        live.stopped_at = None
        live.stopped_by = None
        restore_tenant_customer_accounts(db, tenant_id)

        write_management_log(db, current, "企业恢复", f"恢复企业服务：{live.name}", target_module="企业管理", target_id=live.id, tenant_id=live.id)
        db.commit()
        from app.services.schedule_service import maybe_kick_brand_words_after_service_became_active

        maybe_kick_brand_words_after_service_became_active(
            tenant_id=live.id,
            became_active=tenant_service_is_operational(live) and not was_operational,
        )
        db.refresh(live)
        return tenant_to_dict(live, db=db)

    try:
        # 2026-08-18 - 销售恢复服务也进审批，避免绕过停服管控
        pending, result = queue_or_run(
            db,
            current,
            operation_key="management.tenant.restore",
            module="tenant",
            action="restore",
            summary=f"恢复企业服务：{tenant.name}",
            payload={"tenant_id": tenant_id},
            tenant_id=tenant_id,
            target_id=tenant_id,
            executor=_execute,
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ApiResponse(data=result)


@router.post("/tenants/{tenant_id}/purge", response_model=ApiResponse[dict])
def management_purge_tenant(
    tenant_id: int,
    payload: TenantPurgeRequest,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """彻底删除：先备份，再清监测历史与客户账号，最后软删企业。"""
    require_platform(current)
    from app.services.tenant_scope import is_platform_admin_identity

    # 2026-07-30 - 彻底删除仅管理员 - 菜单权 + 职位双重校验
    if not is_platform_admin_identity(db, current.identity):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="仅平台管理员可彻底删除企业")
    _require_platform_menu(db, current, "platform.audit.purge", "can_delete", "当前账号无权彻底删除企业")
    guard_sales_tenant(db, current, tenant_id)
    tenant = db.scalar(select(Tenant).where(Tenant.id == tenant_id, Tenant.deleted.is_(False)))
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="企业不存在")
    if payload.confirm_name.strip() != tenant.name.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="确认名称与企业名称不一致")

    from app.services.tenant_purge_service import purge_tenant_thoroughly

    try:
        # 2026-07-30 - 彻底删除独立于停服；先备份再清历史与账号
        stats = purge_tenant_thoroughly(db, tenant, operator_user_id=current.user.id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    write_management_log(
        db,
        current,
        "企业彻底删除",
        f"彻底删除企业：{tenant.name}（备份 {stats.get('backup_path')}）",
        target_module="企业管理",
        target_id=tenant_id,
        tenant_id=tenant_id,
        risk_level="高危",
    )
    db.commit()
    return ApiResponse(data=stats)


@router.get("/users", response_model=ApiResponse[list[dict]])
def management_users(
    keyword: str | None = None,
    tenant_id: int | None = None,
    identity_type: str | None = None,
    position_id: int | None = None,
    enabled: bool | None = Query(default=None),
    deleted: bool = False,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[list[dict]]:
    require_platform(current)
    if tenant_id is not None:
        guard_sales_tenant(db, current, tenant_id)
    users = list_managed_users(
        db,
        current.user,
        current.identity,
        keyword=keyword,
        tenant_id=tenant_id,
        identity_type=identity_type or None,
        position_id=position_id,
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
            "phone": user.phone,
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

    def _execute():
        user = create_managed_user(db, payload, current.user, current.identity)
        write_management_log(db, current, "用户新增", f"新增用户：{user.display_name}（{user.username}）", target_module="用户管理", target_id=user.id)
        db.commit()
        return {"id": user.id, "username": user.username, "display_name": user.display_name}

    try:
        # 入队前先拦：销售/运营不能把「建管理员」送进审批
        assert_actor_can_assign_identities(db, current.identity, list(payload.identities))
        pending, result = queue_or_run(
            db,
            current,
            operation_key="management.user.create",
            module="user",
            action="create",
            summary=f"新增用户：{payload.display_name or payload.username}",
            payload={"body": payload.model_dump(mode="json")},
            executor=_execute,
        )
    except PermissionError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except IntegrityError as exc:
        # 2026-08-20 - 软删账号/编码撞库时给可读原因，勿只回 IntegrityError
        db.rollback()
        raw = str(getattr(exc, "orig", None) or exc)
        detail = "数据库保存失败：唯一约束冲突"
        if "ix_sys_user_username" in raw or "username" in raw.lower():
            detail = "登录账号已被占用（含已删除账号），请更换登录名或先恢复旧账号"
        elif "uk_user_identity_code" in raw or "identity_code" in raw.lower():
            detail = "用户身份编码冲突，请刷新后重试或联系管理员"
        elif "ix_sys_tenant_code" in raw or "sys_tenant" in raw.lower():
            detail = "企业编码冲突，请更换企业名称后重试"
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"数据库保存失败：{exc.__class__.__name__}") from exc
    return ApiResponse(data=result)


@router.put("/users/{user_id}", response_model=ApiResponse[dict])
def management_update_user(
    user_id: int,
    payload: UserUpdateRequest,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    require_platform(current)
    _require_platform_menu(db, current, "platform.users.list", "can_update", "当前账号无权修改用户")
    require_user_identity_create_permission(db, current, payload, existing_user_id=user_id)

    def _execute():
        user = update_managed_user(db, user_id, payload, current.user, current.identity)
        write_management_log(db, current, "用户修改", f"修改用户与权限：{user.display_name}（{user.username}）", target_module="用户管理", target_id=user.id, risk_level="关注")
        db.commit()
        return {"id": user.id, "username": user.username, "display_name": user.display_name}

    try:
        target = get_managed_user(db, user_id, current.user, current.identity)
        assert_actor_can_manage_target_user(db, current.identity, target)
        assert_actor_can_assign_identities(db, current.identity, list(payload.identities))
        pending, result = queue_or_run(
            db,
            current,
            operation_key="management.user.update",
            module="user",
            action="update",
            summary=f"修改用户：{payload.display_name or user_id}",
            payload={"body": payload.model_dump(mode="json"), "user_id": user_id},
            target_id=user_id,
            executor=_execute,
        )
    except PermissionError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"数据库保存失败：{exc.__class__.__name__}") from exc
    return ApiResponse(data=result)


@router.patch("/users/{user_id}/password", response_model=ApiResponse[dict])
def management_reset_password(
    user_id: int,
    payload: PasswordResetRequest,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    require_platform(current)
    _require_platform_menu(db, current, "platform.users.list", "can_update", "当前账号无权重置用户密码")
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
    _require_platform_menu(db, current, "platform.users.list", "can_update", "当前账号无权变更用户状态")
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
    _require_platform_menu(db, current, "platform.users.list", "can_delete", "当前账号无权删除用户")
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
    _require_platform_menu(db, current, "platform.users.list", "can_update", "当前账号无权恢复用户")
    try:
        user = restore_managed_user(db, user_id, current.user, current.identity)
        write_management_log(db, current, "用户恢复", f"恢复用户：{user.display_name}（{user.username}）", target_module="用户管理", target_id=user.id)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ApiResponse(data={"id": user.id, "deleted": user.deleted, "status": user.status})


def _menu_config_dict(row: MenuConfig) -> dict:
    return {
        "id": row.id,
        "menu_code": row.menu_code,
        "menu_name": row.menu_name,
        "identity_type": row.identity_type,
        "sort_order": row.sort_order,
        "is_visible": row.is_visible,
        "show_in_sidebar": bool(getattr(row, "show_in_sidebar", True)),
        "icon": row.icon,
        "route_path": row.route_path,
        "remark": row.remark,
    }


@router.get("/menus/config", response_model=ApiResponse[list[dict]])
def get_menu_configs(
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
    identity_type: str = Query(None, description="身份类型过滤"),
) -> ApiResponse[list[dict]]:
    """获取菜单配置列表"""
    require_platform(current)
    require_system_config_access(db, current, category="menu")
    stmt = select(MenuConfig).where(MenuConfig.deleted.is_(False))
    if identity_type:
        stmt = stmt.where(MenuConfig.identity_type == identity_type)
    stmt = stmt.order_by(MenuConfig.sort_order.asc(), MenuConfig.id.asc())
    rows = list(db.scalars(stmt))
    return ApiResponse(data=[_menu_config_dict(row) for row in rows])


@router.put("/menus/config/{config_id}", response_model=ApiResponse[dict])
def update_menu_config(
        config_id: int,
        payload: MenuConfigUpdateRequest,
        current: CurrentSession = Depends(get_current_session),
        db: Session = Depends(get_db),
):
    """更新菜单配置（名称、排序、可见性）"""
    require_platform(current)
    require_system_config_access(db, current, category="menu", for_update=True)
    config = db.scalar(select(MenuConfig).where(MenuConfig.id == config_id))
    if not config:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="菜单配置不存在")

    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(config, field, value)

    sync_menu_row_from_config(db, config)
    write_management_log(db, current, "菜单配置", f"修改菜单配置：{config.menu_name}", target_module="系统配置", target_id=config.id, risk_level="关注")
    db.commit()

    return ApiResponse(data=_menu_config_dict(config))


@router.delete("/menus/config/{config_id}")
def delete_menu_config(
        config_id: int,
        current: CurrentSession = Depends(get_current_session),
        db: Session = Depends(get_db),
):
    """停用菜单配置（逻辑删除）"""
    require_platform(current)
    require_system_config_access(db, current, category="menu", for_update=True)
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
    require_system_config_access(db, current, category="menu", for_update=True)
    updated_count = 0
    for item in configs:
        config = db.scalar(select(MenuConfig).where(MenuConfig.id == item.id, MenuConfig.deleted.is_(False)))
        if config:
            update_data = item.model_dump(exclude_unset=True, exclude={"id"})
            for field, value in update_data.items():
                setattr(config, field, value)
            sync_menu_row_from_config(db, config)
            updated_count += 1

    write_management_log(db, current, "菜单批量配置", f"批量更新菜单配置：{updated_count} 项", target_module="系统配置", risk_level="关注")
    db.commit()

    return ApiResponse(data={"message": f"已更新 {updated_count} 个菜单配置"})


@router.post("/menus/config/sync-to-menus", response_model=ApiResponse[dict])
def sync_menu_configs_to_menus(
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """一次性把菜单配置回写到 sys_menu，消除历史双名称漂移。"""
    require_platform(current)
    require_system_config_access(db, current, category="menu", for_update=True)
    updated = sync_all_menus_from_configs(db)
    write_management_log(
        db,
        current,
        "菜单配置同步",
        f"回写菜单配置到 sys_menu：{updated} 项",
        target_module="系统配置",
        risk_level="关注",
    )
    db.commit()
    return ApiResponse(data={"updated": updated})
