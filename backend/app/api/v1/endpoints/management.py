from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentSession, get_current_session
from app.core.database import get_db
from app.models.tenant import Tenant
from app.models.permission import UserIdentityMenu
from app.schemas.common import ApiResponse
from app.schemas.permission import MenuInfo, PasswordResetRequest, RoleInfo, TenantCreateRequest, UserCreateRequest, UserUpdateRequest
from app.services.management_service import _tenant_code_from_name
from app.services.management_service import (
    create_managed_user,
    delete_managed_user,
    list_managed_users,
    reset_managed_user_password,
    restore_managed_user,
    set_managed_user_status,
    update_managed_user,
)
from app.services.permission_service import list_menus_by_identity_type, list_roles_by_identity_type

router = APIRouter(prefix="/management")


def require_platform(current: CurrentSession) -> None:
    """管理端接口只允许平台运营身份访问。"""
    if current.identity.identity_type != "PLATFORM":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="仅平台运营端可访问")


@router.get("/menus", response_model=ApiResponse[list[dict]])
def management_menus(
    identity_type: str = "PLATFORM",
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[list[dict]]:
    """新增人员时读取可分配菜单。"""
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
    """新增人员时读取可分配角色。"""
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


@router.get("/tenants", response_model=ApiResponse[list[dict]])
def management_tenants(
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[list[dict]]:
    """客户企业端账号需要绑定企业，这里提供企业下拉。"""
    require_platform(current)
    tenants = db.scalars(select(Tenant).where(Tenant.status.is_(True), Tenant.deleted.is_(False)).order_by(Tenant.id.desc()))
    return ApiResponse(data=[{"id": item.id, "name": item.name, "code": item.code} for item in tenants])


@router.post("/tenants", response_model=ApiResponse[dict])
def management_create_tenant(
    payload: TenantCreateRequest,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """平台端新增客户企业。"""
    require_platform(current)
    name = payload.name.strip()
    code = (payload.code or _tenant_code_from_name(name)).strip()
    exists = db.scalar(select(Tenant).where((Tenant.name == name) | (Tenant.code == code), Tenant.deleted.is_(False)))
    if exists is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="企业名称或企业编码已存在")
    tenant = Tenant(name=name, code=code)
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    return ApiResponse(data={"id": tenant.id, "name": tenant.name, "code": tenant.code})


@router.delete("/tenants/{tenant_id}", response_model=ApiResponse[dict])
def management_delete_tenant(
    tenant_id: int,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """平台端逻辑删除客户企业，历史任务仍保留。"""
    require_platform(current)
    tenant = db.scalar(select(Tenant).where(Tenant.id == tenant_id, Tenant.deleted.is_(False)))
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="企业不存在")
    tenant.deleted = True
    tenant.status = False
    db.commit()
    return ApiResponse(data={"id": tenant_id, "deleted": True})


@router.get("/users", response_model=ApiResponse[list[dict]])
def management_users(
    keyword: str | None = None,
    tenant_id: int | None = None,
    identity_type: str | None = None,
    enabled: bool | None = None,
    deleted: bool = False,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[list[dict]]:
    """用户列表按创建人隔离：管理员看全部，普通人员只看自己创建的。"""
    require_platform(current)
    users = list_managed_users(
        db,
        current.user,
        current.identity,
        keyword=keyword,
        tenant_id=tenant_id,
        identity_type=identity_type,
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
                    "tenant_id": identity.tenant_id,
                    "tenant_name": identity.tenant.name if identity.tenant else None,
                    "menu_ids": identity_menu_map.get(identity.id, []),
                }
                for identity in user.identities if deleted or not identity.deleted
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
    """新增人员并分配菜单权限。"""
    require_platform(current)
    try:
        user = create_managed_user(db, payload, current.user, current.identity)
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
    """修改用户资料、身份和菜单权限。"""
    require_platform(current)
    try:
        user = update_managed_user(db, user_id, payload, current.user, current.identity)
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
    """重置用户密码。"""
    require_platform(current)
    try:
        reset_managed_user_password(db, user_id, payload.password, current.user, current.identity)
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
    """启用或禁用用户账号。"""
    require_platform(current)
    try:
        user = set_managed_user_status(db, user_id, enabled, current.user, current.identity)
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
    """逻辑删除用户账号，保留审计和历史业务数据。"""
    require_platform(current)
    try:
        user = delete_managed_user(db, user_id, current.user, current.identity)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ApiResponse(data={"id": user.id, "deleted": user.deleted})


@router.patch("/users/{user_id}/restore", response_model=ApiResponse[dict])
def management_restore_user(
    user_id: int,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """恢复被逻辑删除的用户账号。"""
    require_platform(current)
    try:
        user = restore_managed_user(db, user_id, current.user, current.identity)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ApiResponse(data={"id": user.id, "deleted": user.deleted, "status": user.status})
