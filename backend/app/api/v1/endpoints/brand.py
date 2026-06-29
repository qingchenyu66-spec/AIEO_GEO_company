from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentSession, get_current_session
from app.core.database import get_db
from app.models.permission import Menu, UserIdentityMenu
from app.schemas.brand import BrandAssetSaveRequest, CompetitorSaveRequest
from app.schemas.common import ApiResponse
from app.services.brand_service import (
    asset_to_dict,
    competitor_to_dict,
    delete_competitor,
    get_brand_asset,
    list_keyword_groups,
    list_competitors,
    resolve_tenant_id,
    save_brand_asset,
    save_competitor,
)

router = APIRouter(prefix="/brand")


def require_platform(current: CurrentSession) -> None:
    """只有平台运营端可以维护企业品牌资产和竞品库。"""
    if current.identity.identity_type != "PLATFORM":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="仅平台运营端可以维护企业配置")


def require_any_update_permission(current: CurrentSession, db: Session, menu_codes: list[str]) -> None:
    granted = db.scalar(
        select(UserIdentityMenu.id)
        .join(Menu, Menu.id == UserIdentityMenu.menu_id)
        .where(
            UserIdentityMenu.identity_id == current.identity.id,
            UserIdentityMenu.can_update.is_(True),
            Menu.menu_code.in_(menu_codes),
            Menu.status.is_(True),
            Menu.deleted.is_(False),
        )
    )
    if granted is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="当前账号没有该企业配置的编辑权限")


@router.get("/asset", response_model=ApiResponse[dict])
def brand_asset(
    tenant_id: int | None = Query(default=None),
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """读取企业品牌资产和竞品库；客户只能读取自身企业。"""
    try:
        resolved_tenant_id = resolve_tenant_id(current, tenant_id)
        asset = get_brand_asset(db, resolved_tenant_id)
        keyword_groups = list_keyword_groups(db, resolved_tenant_id) if asset else []
        competitors = list_competitors(db, resolved_tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ApiResponse(data={
        "tenant_id": resolved_tenant_id,
        "asset": asset_to_dict(asset, keyword_groups),
        "competitors": [competitor_to_dict(item) for item in competitors],
    })


@router.put("/asset", response_model=ApiResponse[dict])
def upsert_brand_asset(
    payload: BrandAssetSaveRequest,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """新增或更新企业品牌资产配置。"""
    require_any_update_permission(current, db, [
        "platform.audit",
        "platform.audit.profile",
        "platform.audit.keywords",
        "platform.audit.models",
        "platform.audit.schedule",
    ])
    try:
        asset = save_brand_asset(db, payload, current)
        keyword_groups = list_keyword_groups(db, asset.tenant_id)
        competitors = list_competitors(db, asset.tenant_id)
    except (ValueError, SQLAlchemyError) as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ApiResponse(data={
        "tenant_id": asset.tenant_id,
        "asset": asset_to_dict(asset, keyword_groups),
        "competitors": [competitor_to_dict(item) for item in competitors],
    })


@router.post("/competitors", response_model=ApiResponse[dict])
def create_competitor(
    payload: CompetitorSaveRequest,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """新增竞品。"""
    require_any_update_permission(current, db, ["platform.audit", "platform.audit.competitors"])
    try:
        competitor = save_competitor(db, payload, current)
    except (ValueError, SQLAlchemyError) as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ApiResponse(data=competitor_to_dict(competitor))


@router.put("/competitors/{competitor_id}", response_model=ApiResponse[dict])
def update_competitor(
    competitor_id: int,
    payload: CompetitorSaveRequest,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """更新竞品。"""
    require_any_update_permission(current, db, ["platform.audit", "platform.audit.competitors"])
    try:
        competitor = save_competitor(db, payload, current, competitor_id)
    except (ValueError, SQLAlchemyError) as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ApiResponse(data=competitor_to_dict(competitor))


@router.delete("/competitors/{competitor_id}", response_model=ApiResponse[dict])
def remove_competitor(
    competitor_id: int,
    tenant_id: int | None = Query(default=None),
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """逻辑删除竞品。"""
    require_platform(current)
    try:
        delete_competitor(db, current, competitor_id, tenant_id)
    except (ValueError, SQLAlchemyError) as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ApiResponse(data={"deleted": True})
