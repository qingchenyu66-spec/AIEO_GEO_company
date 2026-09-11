"""客户门户 · 企业配置（credit 专属）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentSession, get_current_session
from app.api.http_errors import raise_read_endpoint_error, raise_write_endpoint_error
from app.core.database import get_db
from app.models.permission import CustomerPosition, Menu, UserIdentityMenu
from app.models.user_identity import UserIdentity
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.brand import BrandAssetSaveRequest, BrandWordGroupsSaveRequest, CompetitorSaveRequest
from app.schemas.common import ApiResponse
from app.services.brand_service import (
    asset_to_dict,
    brand_word_group_to_dict,
    competitor_to_dict,
    editable_keyword_groups,
    get_brand_asset,
    list_brand_word_groups,
    list_competitors,
    save_brand_asset,
    save_brand_word_groups,
    save_competitor,
    delete_competitor,
)
from app.services.credit_service import (
    BILLING_MODE_CREDIT,
    estimate_daily_credits,
    estimate_brand_words_immediate_credits,
    is_credit_tenant,
    get_ledger_entry_detail,
    ledger_row_to_dict,
    merge_credit_policy,
    tenant_today_credit_deduct,
    tenant_total_credit_deduct,
    validate_credit_monitor_save,
)
from app.services.enterprise_member_service import (
    create_enterprise_member,
    remove_enterprise_member,
    reset_enterprise_member_password,
    update_enterprise_member,
)
from app.services.menu_permission_service import has_identity_menu_permission
from app.services.schedule_service import enumerate_brand_word_once_groups, submit_schedule_group
from app.services.tenant_scope import resolve_and_guard_tenant_id, resolve_customer_preview_tenant_id
from app.core.config import settings

router = APIRouter(prefix="/customer/enterprise")


def _require_credit_tenant(db: Session, tenant_id: int) -> Tenant:
    tenant = db.scalar(select(Tenant).where(Tenant.id == tenant_id, Tenant.deleted.is_(False)))
    if tenant is None:
        raise HTTPException(status_code=404, detail="企业不存在")
    if not is_credit_tenant(tenant):
        raise HTTPException(status_code=403, detail="当前企业为托管模式，请使用平台代管")
    if not tenant.status:
        raise HTTPException(status_code=403, detail="企业服务已停服")
    return tenant


def _require_menu(db: Session, current: CurrentSession, menu_code: str, action: str = "can_export") -> None:
    if not has_identity_menu_permission(db, current.identity.id, menu_code, action):
        raise HTTPException(status_code=403, detail="当前账号没有权限")


def _resolve_enterprise_tenant_id(
    db: Session,
    current: CurrentSession,
    requested_tenant_id: int | None,
) -> int:
    # 2026-08-27 - 平台预览客户门户须带 tenant_id，走企业管理查看权校验
    if current.identity.identity_type == "PLATFORM":
        if requested_tenant_id is None:
            raise HTTPException(status_code=400, detail="平台端预览需指定企业")
        return resolve_customer_preview_tenant_id(db, current, requested_tenant_id)
    return resolve_and_guard_tenant_id(db, current, requested_tenant_id)


def _require_enterprise_read(
    db: Session,
    current: CurrentSession,
    menu_code: str,
    *,
    action: str = "can_export",
) -> None:
    if current.identity.identity_type == "PLATFORM":
        return
    _require_menu(db, current, menu_code, action)


def _validate_region_write(tenant: Tenant, region_codes: list[str]) -> None:
    # 2026-09-07 - 算力自助地区不设上限、始终可改；仅余额约束消耗
    return


@router.get("/credit/summary", response_model=ApiResponse[dict])
def enterprise_credit_summary(
    tenant_id: int | None = Query(default=None),
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    _require_enterprise_read(db, current, "customer.enterprise_credit")
    tenant_id = _resolve_enterprise_tenant_id(db, current, tenant_id)
    tenant = _require_credit_tenant(db, tenant_id)
    asset = get_brand_asset(db, tenant_id)
    estimate = estimate_daily_credits(db, tenant, asset) if asset else {}
    today_deduct = tenant_today_credit_deduct(db, tenant_id)
    total_usage = tenant_total_credit_deduct(db, tenant_id)
    # 2026-09-08 - 客户 summary 不返回 reserved/pending_terms（UI 已藏；防接口侧读预扣）
    return ApiResponse(
        data={
            "balance": float(tenant.credit_balance or 0),
            "available": float((tenant.credit_balance or 0) - (tenant.credit_reserved or 0)),
            "today_deduct": float(today_deduct),
            "total_usage": float(total_usage),
            "daily_estimate": estimate,
            "billing_mode": tenant.billing_mode,
        }
    )


@router.get("/credit/ledger", response_model=ApiResponse[dict])
def enterprise_credit_ledger(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    tenant_id: int | None = Query(default=None),
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    _require_enterprise_read(db, current, "customer.enterprise_credit")
    tenant_id = _resolve_enterprise_tenant_id(db, current, tenant_id)
    _require_credit_tenant(db, tenant_id)
    from app.services.credit_service import list_credit_ledger

    return ApiResponse(
        data=list_credit_ledger(
            db,
            tenant_id=tenant_id,
            page=page,
            page_size=page_size,
            exclude_internal=True,
        )
    )


@router.get("/credit/ledger/{ledger_id}", response_model=ApiResponse[dict])
def enterprise_credit_ledger_detail(
    ledger_id: int,
    tenant_id: int | None = Query(default=None),
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    _require_enterprise_read(db, current, "customer.enterprise_credit")
    tenant_id = _resolve_enterprise_tenant_id(db, current, tenant_id)
    _require_credit_tenant(db, tenant_id)
    detail = get_ledger_entry_detail(db, tenant_id, ledger_id, customer_visible_only=True)
    if detail is None:
        raise HTTPException(status_code=404, detail="流水不存在")
    return ApiResponse(data=detail)


@router.get("/monitor", response_model=ApiResponse[dict])
def enterprise_monitor_get(
    tenant_id: int | None = Query(default=None),
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    _require_enterprise_read(db, current, "customer.enterprise_monitor")
    tenant_id = _resolve_enterprise_tenant_id(db, current, tenant_id)
    tenant = _require_credit_tenant(db, tenant_id)
    asset = get_brand_asset(db, tenant_id)
    if asset is None:
        return ApiResponse(data={"tenant_id": tenant_id, "asset": None, "policy": merge_credit_policy(tenant.credit_policy_json)})
    keyword_groups = editable_keyword_groups(db, tenant_id)
    brand_word_groups = list_brand_word_groups(db, tenant_id)
    competitors = list_competitors(db, tenant_id)
    estimate = estimate_daily_credits(db, tenant, asset)
    return ApiResponse(
        data={
            "tenant_id": tenant_id,
            "asset": asset_to_dict(asset, keyword_groups, brand_word_groups),
            "competitors": [competitor_to_dict(item) for item in competitors],
            "policy": merge_credit_policy(tenant.credit_policy_json),
            # 2026-09-08 - 方案 A：接口侧恒空，不回显历史脏白名单
            "platform_whitelist": [],
            "daily_estimate": estimate,
        }
    )


class EnterpriseMonitorSaveRequest(BrandAssetSaveRequest):
    region_codes: list[str] | None = None


@router.put("/monitor", response_model=ApiResponse[dict])
def enterprise_monitor_save(
    payload: EnterpriseMonitorSaveRequest,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    _require_menu(db, current, "customer.enterprise_monitor", "can_update")
    tenant_id = resolve_and_guard_tenant_id(db, current, payload.tenant_id)
    tenant = _require_credit_tenant(db, tenant_id)
    if payload.region_codes is not None:
        _validate_region_write(tenant, payload.region_codes)
    try:
        validate_credit_monitor_save(tenant, payload)
        asset = save_brand_asset(db, payload, current)
        if payload.region_codes is not None:
            asset.region_codes_json = list(payload.region_codes)
        db.commit()
        db.refresh(asset)
        estimate = estimate_daily_credits(db, tenant, asset)
        keyword_groups = editable_keyword_groups(db, tenant_id)
        brand_word_groups = list_brand_word_groups(db, tenant_id)
        return ApiResponse(
            data={
                "tenant_id": tenant_id,
                "asset": asset_to_dict(asset, keyword_groups, brand_word_groups),
                "daily_estimate": estimate,
            }
        )
    except (PermissionError, ValueError) as exc:
        raise HTTPException(status_code=400 if isinstance(exc, ValueError) else 403, detail=str(exc)) from exc
    except Exception as exc:
        raise_write_endpoint_error(exc, context="customer.enterprise.monitor.save")


@router.post("/monitor/estimate", response_model=ApiResponse[dict])
def enterprise_monitor_estimate(
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    _require_menu(db, current, "customer.enterprise_monitor")
    tenant_id = resolve_and_guard_tenant_id(db, current, None)
    tenant = _require_credit_tenant(db, tenant_id)
    asset = get_brand_asset(db, tenant_id)
    if asset is None:
        raise HTTPException(status_code=400, detail="请先保存监测配置")
    return ApiResponse(data=estimate_daily_credits(db, tenant, asset))


@router.post("/monitor/brand-words/estimate", response_model=ApiResponse[dict])
def enterprise_brand_words_estimate(
    payload: BrandWordGroupsSaveRequest,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    _require_menu(db, current, "customer.enterprise_monitor")
    tenant_id = resolve_and_guard_tenant_id(db, current, payload.tenant_id)
    tenant = _require_credit_tenant(db, tenant_id)
    asset = get_brand_asset(db, tenant_id)
    if asset is None:
        raise HTTPException(status_code=400, detail="请先保存监测配置")
    return ApiResponse(data=estimate_brand_words_immediate_credits(db, tenant, asset, payload.groups or []))


class BrandWordGroupsCreditSaveRequest(BrandWordGroupsSaveRequest):
    confirm_immediate: bool = False


@router.put("/monitor/brand-words", response_model=ApiResponse[dict])
def enterprise_brand_words_save(
    payload: BrandWordGroupsCreditSaveRequest,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    _require_menu(db, current, "customer.enterprise_monitor", "can_update")
    tenant_id = resolve_and_guard_tenant_id(db, current, payload.tenant_id)
    _require_credit_tenant(db, tenant_id)
    try:
        if get_brand_asset(db, tenant_id) is None:
            raise ValueError("请先保存企业资料，再配置品牌词")
        # 2026-08-28 - 立即跑须先确认 - 勿先 commit run_immediately 再拦
        if not payload.confirm_immediate:
            for group in payload.groups or []:
                if group.status and getattr(group, "run_immediately", False):
                    raise ValueError("勾选立即跑一轮时请确认预估")
        asset, submit_rows = save_brand_word_groups(db, payload, current, respect_run_immediately=True)
        submitted = []
        for item in enumerate_brand_word_once_groups(
            db,
            tenant_id=asset.tenant_id,
            groups=[brand_word_group_to_dict(g) for g in submit_rows],
            max_prompts=settings.celery_scan_submit_max_prompts,
        ):
            submitted.append(submit_schedule_group(db, current, item))
        keyword_groups = editable_keyword_groups(db, asset.tenant_id)
        brand_word_groups = list_brand_word_groups(db, asset.tenant_id)
        return ApiResponse(
            data={
                "tenant_id": asset.tenant_id,
                "asset": asset_to_dict(asset, keyword_groups, brand_word_groups),
                "once_submitted": submitted,
            }
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise_write_endpoint_error(exc, context="customer.enterprise.brand_words")


@router.get("/credit/terms/current", response_model=ApiResponse[dict])
def enterprise_terms_current(
    tenant_id: int | None = Query(default=None),
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    from app.services.announcement_sanitize import sanitize_announcement_html
    from app.services.credit_service import resolve_customer_credit_terms

    tenant_id = _resolve_enterprise_tenant_id(db, current, tenant_id)
    _require_credit_tenant(db, tenant_id)
    # 2026-09-08 - 条款仅查阅；去掉 acknowledged / ack 排队
    terms = resolve_customer_credit_terms(db, tenant_id)
    if terms is None:
        return ApiResponse(data=None)
    return ApiResponse(
        data={
            "id": terms.id,
            "version_code": terms.version_code,
            "title": terms.title,
            # 2026-09-09 - 读时再消毒，兼容历史未清洗正文
            "content_html": sanitize_announcement_html(terms.content_html or ""),
            "effective_at": terms.effective_at.isoformat(sep=" ", timespec="minutes"),
        }
    )


class MemberSaveRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=80)
    username: str = Field(min_length=3, max_length=50)
    # 2026-09-07 - 不用 Field(min_length=8)：Pydantic 英文报错；改校验器出中文
    password: str = Field(max_length=64)
    customer_position_id: int
    status: bool = True

    @field_validator("password")
    @classmethod
    def _password_min_len(cls, value: str) -> str:
        if len(value or "") < 8:
            raise ValueError("密码至少 8 位")
        return value


class MemberUpdateRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=80)
    customer_position_id: int
    status: bool = True


class MemberPasswordRequest(BaseModel):
    password: str = Field(max_length=64)

    @field_validator("password")
    @classmethod
    def _password_min_len(cls, value: str) -> str:
        if len(value or "") < 8:
            raise ValueError("密码至少 8 位")
        return value


ENTERPRISE_AUDIT_ACTIONS = (
    "企业配置",
    "品牌词配置",
    "竞品",
    "成员",
    "算力",
    "规则确认",
)


@router.get("/members", response_model=ApiResponse[dict])
def enterprise_members_list(
    tenant_id: int | None = Query(default=None),
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    _require_enterprise_read(db, current, "customer.enterprise_members")
    tenant_id = _resolve_enterprise_tenant_id(db, current, tenant_id)
    _require_credit_tenant(db, tenant_id)
    identities = list(
        db.scalars(
            select(UserIdentity).where(
                UserIdentity.tenant_id == tenant_id,
                UserIdentity.identity_type == "CUSTOMER",
                UserIdentity.deleted.is_(False),
            )
        )
    )
    users = {
        u.id: u
        for u in db.scalars(select(User).where(User.id.in_([i.user_id for i in identities] or [0])))
    }
    positions = {
        p.id: p
        for p in db.scalars(select(CustomerPosition).where(CustomerPosition.deleted.is_(False)))
    }
    return ApiResponse(
        data={
            "items": [
                {
                    "identity_id": ident.id,
                    "user_id": ident.user_id,
                    "display_name": users[ident.user_id].display_name if ident.user_id in users else "",
                    "username": users[ident.user_id].username if ident.user_id in users else "",
                    "identity_name": ident.identity_name,
                    "customer_position_id": ident.customer_position_id,
                    "position_name": positions[ident.customer_position_id].position_name
                    if ident.customer_position_id in positions
                    else "",
                    "status": ident.status,
                }
                for ident in identities
            ],
            "positions": [
                {"id": p.id, "position_code": p.position_code, "position_name": p.position_name}
                for p in positions.values()
                if p.tenant_id is None or p.tenant_id == tenant_id
            ],
        }
    )


@router.post("/members", response_model=ApiResponse[dict])
def enterprise_members_create(
    payload: MemberSaveRequest,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    _require_menu(db, current, "customer.enterprise_members", "can_create")
    tenant_id = resolve_and_guard_tenant_id(db, current, None)
    _require_credit_tenant(db, tenant_id)
    if not payload.password:
        raise HTTPException(status_code=400, detail="新建成员必须设置密码")
    try:
        identity = create_enterprise_member(
            db,
            tenant_id=tenant_id,
            display_name=payload.display_name,
            username=payload.username,
            password=payload.password,
            customer_position_id=payload.customer_position_id,
            operator_user_id=current.user.id,
        )
        return ApiResponse(data={"identity_id": identity.id})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/members/{identity_id}", response_model=ApiResponse[dict])
def enterprise_members_update(
    identity_id: int,
    payload: MemberUpdateRequest,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    _require_menu(db, current, "customer.enterprise_members", "can_update")
    tenant_id = resolve_and_guard_tenant_id(db, current, None)
    _require_credit_tenant(db, tenant_id)
    try:
        identity = update_enterprise_member(
            db,
            tenant_id=tenant_id,
            identity_id=identity_id,
            display_name=payload.display_name,
            customer_position_id=payload.customer_position_id,
            status=payload.status,
            current_identity_id=current.identity.id,
        )
        return ApiResponse(data={"identity_id": identity.id})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/members/{identity_id}/password", response_model=ApiResponse[dict])
def enterprise_members_reset_password(
    identity_id: int,
    payload: MemberPasswordRequest,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    _require_menu(db, current, "customer.enterprise_members", "can_update")
    tenant_id = resolve_and_guard_tenant_id(db, current, None)
    _require_credit_tenant(db, tenant_id)
    try:
        reset_enterprise_member_password(
            db,
            tenant_id=tenant_id,
            identity_id=identity_id,
            password=payload.password,
            current_identity_id=current.identity.id,
        )
        return ApiResponse(data={"ok": True})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/members/{identity_id}", response_model=ApiResponse[dict])
def enterprise_members_delete(
    identity_id: int,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    _require_menu(db, current, "customer.enterprise_members", "can_delete")
    tenant_id = resolve_and_guard_tenant_id(db, current, None)
    _require_credit_tenant(db, tenant_id)
    try:
        remove_enterprise_member(
            db,
            tenant_id=tenant_id,
            identity_id=identity_id,
            current_identity_id=current.identity.id,
        )
        return ApiResponse(data={"ok": True})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/monitor/competitors", response_model=ApiResponse[dict])
def enterprise_competitor_save(
    payload: CompetitorSaveRequest,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    _require_menu(db, current, "customer.enterprise_monitor", "can_update")
    tenant_id = resolve_and_guard_tenant_id(db, current, payload.tenant_id)
    _require_credit_tenant(db, tenant_id)
    try:
        row = save_competitor(db, payload, current)
        return ApiResponse(data=competitor_to_dict(row))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/monitor/competitors/{competitor_id}", response_model=ApiResponse[dict])
def enterprise_competitor_delete(
    competitor_id: int,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    _require_menu(db, current, "customer.enterprise_monitor", "can_update")
    tenant_id = resolve_and_guard_tenant_id(db, current, None)
    _require_credit_tenant(db, tenant_id)
    try:
        delete_competitor(db, current, competitor_id, tenant_id)
        return ApiResponse(data={"ok": True})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/audit", response_model=ApiResponse[dict])
def enterprise_audit_list(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    tenant_id: int | None = Query(default=None),
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    _require_enterprise_read(db, current, "customer.enterprise_audit")
    tenant_id = _resolve_enterprise_tenant_id(db, current, tenant_id)
    _require_credit_tenant(db, tenant_id)
    from app.models.ops import OperationLog

    offset = (page - 1) * page_size
    rows = list(
        db.scalars(
            select(OperationLog)
            .where(
                OperationLog.deleted.is_(False),
                OperationLog.tenant_id == tenant_id,
                OperationLog.action_type.in_(ENTERPRISE_AUDIT_ACTIONS),
            )
            .order_by(OperationLog.created_at.desc())
            .offset(offset)
            .limit(page_size)
        )
    )
    return ApiResponse(
        data={
            "items": [
                {
                    "operator_name": row.operator_name,
                    "action_type": row.action_type,
                    "description": row.description,
                    "created_at": row.created_at.isoformat(sep=" ", timespec="minutes"),
                }
                for row in rows
            ],
            "page": page,
            "page_size": page_size,
        }
    )
