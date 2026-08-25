from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentSession, get_current_session, require_platform
from app.api.http_errors import raise_read_endpoint_error, raise_write_endpoint_error
from app.core.database import get_db
from app.models.permission import Menu, UserIdentityMenu
from app.schemas.brand import BrandAssetSaveRequest, BrandWordGroupsSaveRequest, CompetitorSaveRequest
from app.schemas.common import ApiResponse
from app.services.brand_service import (
    asset_to_dict,
    brand_word_group_to_dict,
    competitor_to_dict,
    delete_competitor,
    editable_keyword_groups,
    get_brand_asset,
    list_brand_word_groups,
    list_competitors,
    sanitize_brand_asset_payload_for_grants,
    save_brand_asset_maybe_bootstrap,
    save_brand_word_groups,
    save_competitor,
)
from app.services.approval_preview_service import brand_asset_has_changes
from app.services.approval_service import queue_or_run, requires_sales_approval
from app.services.management_service import raise_if_new_tenant_name_unavailable
from app.services.schedule_service import enumerate_brand_word_once_groups, submit_schedule_group
from app.services.tenant_scope import resolve_and_guard_tenant_id, resolve_customer_preview_tenant_id
from app.services.tenant_logo_service import (
    maybe_apply_logo_staging_from_body,
    resolve_logo_staging_path,
    save_logo_staging,
    tenant_logo_media_type,
)
from app.core.config import settings

router = APIRouter(prefix="/brand")


def _brand_asset_response(db: Session, tenant_id: int) -> dict:
    asset = get_brand_asset(db, tenant_id)
    if asset is None:
        return {"tenant_id": tenant_id, "asset": None, "competitors": []}
    keyword_groups = editable_keyword_groups(db, tenant_id)
    brand_word_groups = list_brand_word_groups(db, tenant_id)
    competitors = list_competitors(db, tenant_id)
    return {
        "tenant_id": tenant_id,
        "asset": asset_to_dict(asset, keyword_groups, brand_word_groups),
        "competitors": [competitor_to_dict(item) for item in competitors],
    }


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
        if current.identity.identity_type == "PLATFORM" and tenant_id is not None:
            resolved_tenant_id = resolve_customer_preview_tenant_id(db, current, tenant_id)
        else:
            resolved_tenant_id = resolve_and_guard_tenant_id(db, current, tenant_id)
        asset = get_brand_asset(db, resolved_tenant_id)
        keyword_groups = editable_keyword_groups(db, resolved_tenant_id) if asset else []
        brand_word_groups = list_brand_word_groups(db, resolved_tenant_id) if asset else []
        competitors = list_competitors(db, resolved_tenant_id)
    except Exception as exc:
        raise_read_endpoint_error(exc, context="brand.asset")
    # 2026-08-07 - 观察号读资产时收窄平台展示，勿改库内已购全集
    from app.services.observer_account import observer_platforms_for_session, scope_asset_platforms_dict

    asset_payload = asset_to_dict(asset, keyword_groups, brand_word_groups)
    asset_payload = scope_asset_platforms_dict(asset_payload, observer_platforms_for_session(current))
    return ApiResponse(data={
        "tenant_id": resolved_tenant_id,
        "asset": asset_payload,
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
        "platform.audit.regions",
        "platform.audit.keywords",
        "platform.audit.models",
        "platform.audit.schedule",
    ])
    # 2026-07-30 - 无地区/平台权勿进审批假 diff - 先按授权回填库内原值
    payload = sanitize_brand_asset_payload_for_grants(db, current, payload)
    tenant_id = payload.tenant_id

    def _execute():
        asset = save_brand_asset_maybe_bootstrap(
            db, payload, current, owner_user_id=current.user.id,
        )
        # 2026-08-25 - Logo 随企业资料进审批 - 免审直执时同步落库
        maybe_apply_logo_staging_from_body(
            db,
            tenant_id=asset.tenant_id,
            body=payload,
            owner_user_id=current.user.id,
        )
        keyword_groups = editable_keyword_groups(db, asset.tenant_id)
        brand_word_groups = list_brand_word_groups(db, asset.tenant_id)
        competitors = list_competitors(db, asset.tenant_id)
        return {
            "tenant_id": asset.tenant_id,
            "asset": asset_to_dict(asset, keyword_groups, brand_word_groups),
            "competitors": [competitor_to_dict(item) for item in competitors],
        }

    try:
        body = payload.model_dump(mode="json")
        if tenant_id is None:
            # 2026-08-18 - 销售入队前不落库，同名单会进审批 - 提交前拦在册/他人待审重名
            raise_if_new_tenant_name_unavailable(
                db,
                payload.company_full_name or payload.brand_name,
                allow_own_pending_user_id=current.user.id,
            )
        # 2026-07-29 - 销售无变更仍进空审批单：完整 diff 确认无变化后直接成功返回
        if (
            tenant_id is not None
            and requires_sales_approval(db, current)
            and not brand_asset_has_changes(db, tenant_id, body)
        ):
            return ApiResponse(data=_brand_asset_response(db, tenant_id))
        pending, result = queue_or_run(
            db,
            current,
            operation_key="brand.asset.upsert",
            module="brand",
            action="update" if tenant_id is not None else "create",
            summary=(
                f"新增企业：{payload.company_full_name or payload.brand_name}"
                if tenant_id is None
                else f"保存企业配置：{payload.company_full_name or payload.brand_name}"
            ),
            payload={"body": body},
            tenant_id=tenant_id,
            executor=_execute,
        )
    except Exception as exc:
        db.rollback()
        raise_write_endpoint_error(exc, context="brand.upsert")
    return ApiResponse(data=result)


@router.post("/logo-staging", response_model=ApiResponse[dict])
async def upload_brand_logo_staging(
    file: UploadFile = File(...),
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """销售保存企业资料前暂存 Logo，随审批单 payload 提交。"""
    require_any_update_permission(current, db, [
        "platform.audit",
        "platform.audit.profile",
    ])
    try:
        data = await save_logo_staging(current, file)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ApiResponse(data=data)


@router.get("/logo-staging/{staging_key}")
def get_brand_logo_staging(
    staging_key: str,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> FileResponse:
    """读取 Logo 暂存图（申请人或审批人）。"""
    try:
        _, file_path = resolve_logo_staging_path(db, current, staging_key=staging_key)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return FileResponse(
        file_path,
        media_type=tenant_logo_media_type(file_path),
        filename=file_path.name,
    )


@router.put("/brand-word-groups", response_model=ApiResponse[dict])
def upsert_brand_word_groups(
    payload: BrandWordGroupsSaveRequest,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """保存品牌词配置；启用词组（once/weekly）保存后立刻提交一轮；weekly 仍保留周一调度。"""
    require_any_update_permission(current, db, [
        "platform.audit",
        "platform.audit.keywords",
    ])
    tenant_id = resolve_and_guard_tenant_id(db, current, payload.tenant_id)
    # 2026-08-10 - 销售入队前就校验资产，避免无企业资料的品牌词审批单
    if get_brand_asset(db, tenant_id) is None:
        raise ValueError("请先保存企业资料，再配置品牌词")

    def _execute():
        asset, submit_rows = save_brand_word_groups(db, payload, current)
        submit_dicts = [brand_word_group_to_dict(item) for item in submit_rows]
        submitted: list[dict] = []
        for item in enumerate_brand_word_once_groups(
            db,
            tenant_id=asset.tenant_id,
            groups=submit_dicts,
            max_prompts=settings.celery_scan_submit_max_prompts,
        ):
            submitted.append(submit_schedule_group(db, current, item))
        keyword_groups = editable_keyword_groups(db, asset.tenant_id)
        brand_word_groups = list_brand_word_groups(db, asset.tenant_id)
        competitors = list_competitors(db, asset.tenant_id)
        return {
            "tenant_id": asset.tenant_id,
            "asset": asset_to_dict(asset, keyword_groups, brand_word_groups),
            "competitors": [competitor_to_dict(item) for item in competitors],
            "once_submitted": submitted,
        }

    try:
        pending, result = queue_or_run(
            db,
            current,
            operation_key="brand.brand_word_groups.upsert",
            module="brand",
            action="update",
            summary="保存品牌词配置",
            payload={"body": payload.model_dump(mode="json")},
            tenant_id=tenant_id,
            executor=_execute,
        )
    except Exception as exc:
        db.rollback()
        raise_write_endpoint_error(exc, context="brand.brand_word_groups")
    return ApiResponse(data=result)


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
    except Exception as exc:
        db.rollback()
        raise_write_endpoint_error(exc, context="brand.create_competitor")
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
    except Exception as exc:
        db.rollback()
        raise_write_endpoint_error(exc, context="brand.update_competitor")
    return ApiResponse(data=competitor_to_dict(competitor))


@router.delete("/competitors/{competitor_id}", response_model=ApiResponse[dict])
def remove_competitor(
    competitor_id: int,
    tenant_id: int | None = Query(default=None),
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """逻辑删除竞品。"""
    require_any_update_permission(current, db, ["platform.audit", "platform.audit.competitors"])
    try:
        delete_competitor(db, current, competitor_id, tenant_id)
    except Exception as exc:
        db.rollback()
        raise_write_endpoint_error(exc, context="brand.delete_competitor")
    return ApiResponse(data={"deleted": True})
