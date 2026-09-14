"""平台端 · 算力运营与企业充扣。"""

from __future__ import annotations

import csv
from datetime import datetime
from decimal import Decimal
from io import StringIO

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentSession, get_current_session, require_platform
from app.api.http_errors import raise_read_endpoint_error, raise_write_endpoint_error
from app.core.database import get_db
from app.models.credit import BillingModeChangeLog, CreditSubmitBlock, CreditTermsVersion, TenantCreditLedger
from app.models.tenant import Tenant
from app.models.user import User
from app.models.user_identity import UserIdentity
from app.models.permission import CustomerPosition
from app.schemas.common import ApiResponse
from app.services.billing_mode_service import (
    cancel_pending_billing_mode,
    preview_billing_mode_switch,
    serialize_billing_mode_log,
    switch_billing_mode,
)
from app.services.announcement_sanitize import sanitize_announcement_html
from app.services.credit_service import (
    credit_ops_summary,
    credits_from_yuan,
    dedupe_credit_tenant_list_items,
    is_credit_tenant,
    list_open_credit_reserves,
    list_price_rules,
    list_credit_ledger,
    get_ledger_entry_detail,
    ledger_row_to_dict,
    merge_credit_policy,
    recharge_credits,
    release_reserve,
    estimate_daily_credits,
    tenant_today_credit_deduct,
    upsert_price_rule,
)
from app.services.brand_service import get_brand_asset
from app.services.menu_permission_service import has_identity_menu_permission

router = APIRouter(prefix="/management/credit")

# 2026-08-28 - 算力运营页合并侧栏后，运营页读/写兼容 credit_ops_board 与旧 tenant_credit 授权
_CREDIT_OPS_READ_MENUS = ("platform.credit_ops_board", "platform.tenant_credit")
_CREDIT_OPS_WRITE_MENUS = ("platform.credit_ops_board", "platform.tenant_credit")


def _csv_row(cells: list[object]) -> str:
    """CSV 一行：全字段引号包裹，公式注入前缀加撇号。"""
    out: list[str] = []
    for cell in cells:
        text = "" if cell is None else str(cell)
        if text and text[0] in ("=", "+", "-", "@"):
            text = "'" + text
        out.append(text)
    buf = StringIO()
    csv.writer(buf, lineterminator="\n").writerow(out)
    return buf.getvalue()


def guard_sales_tenant(db: Session, current: CurrentSession, tenant_id: int) -> None:
    from app.api.v1.endpoints.management import guard_sales_tenant as _guard

    _guard(db, current, tenant_id)


def _require_menu(db: Session, current: CurrentSession, menu_code: str, action: str = "can_export") -> None:
    if not has_identity_menu_permission(db, current.identity.id, menu_code, action):
        raise HTTPException(status_code=403, detail="当前账号没有权限")


def _require_any_menu(
    db: Session,
    current: CurrentSession,
    menu_codes: tuple[str, ...],
    action: str = "can_export",
) -> None:
    # 2026-08-27 - 算力运营页合并提交拦截/企业列表，兼容旧菜单码授权
    if any(has_identity_menu_permission(db, current.identity.id, code, action) for code in menu_codes):
        return
    raise HTTPException(status_code=403, detail="当前账号没有权限")


@router.get("/ops-summary", response_model=ApiResponse[dict])
def credit_ops_summary_api(
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    require_platform(current)
    _require_any_menu(db, current, _CREDIT_OPS_READ_MENUS)
    try:
        return ApiResponse(data=credit_ops_summary(db))
    except Exception as exc:
        raise_read_endpoint_error(exc, context="management.credit.ops_summary")


@router.get("/blocks", response_model=ApiResponse[dict])
def credit_blocks_list(
    block_reason: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    require_platform(current)
    _require_any_menu(db, current, ("platform.credit_ops_board", "platform.tenant_credit_blocks"))
    stmt = select(CreditSubmitBlock).order_by(CreditSubmitBlock.created_at.desc())
    if block_reason:
        stmt = stmt.where(CreditSubmitBlock.block_reason == block_reason)
    offset = (page - 1) * page_size
    rows = list(db.scalars(stmt.offset(offset).limit(page_size)))
    tenant_map = {
        t.id: t.name
        for t in db.scalars(select(Tenant).where(Tenant.id.in_([r.tenant_id for r in rows] or [0])))
    }
    return ApiResponse(
        data={
            "items": [
                {
                    "id": row.id,
                    "tenant_id": row.tenant_id,
                    "tenant_name": tenant_map.get(row.tenant_id),
                    "window_key": row.window_key,
                    "block_reason": row.block_reason,
                    "required_credits": float(row.required_credits) if row.required_credits is not None else None,
                    "available_credits": float(row.available_credits) if row.available_credits is not None else None,
                    "platform_balance_snapshot": float(row.platform_balance_snapshot)
                    if row.platform_balance_snapshot is not None
                    else None,
                    "created_at": row.created_at.isoformat(sep=" ", timespec="minutes"),
                }
                for row in rows
            ],
            "page": page,
            "page_size": page_size,
        }
    )


@router.get("/tenants/{tenant_id}", response_model=ApiResponse[dict])
def tenant_credit_detail(
    tenant_id: int,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    require_platform(current)
    _require_any_menu(db, current, _CREDIT_OPS_READ_MENUS)
    guard_sales_tenant(db, current, tenant_id)
    tenant = db.scalar(select(Tenant).where(Tenant.id == tenant_id, Tenant.deleted.is_(False)))
    if tenant is None:
        raise HTTPException(status_code=404, detail="企业不存在")
    from app.services.brand_service import get_brand_asset
    from app.services.credit_service import estimate_daily_credits

    asset = get_brand_asset(db, tenant_id)
    estimate = estimate_daily_credits(db, tenant, asset) if asset and is_credit_tenant(tenant) else {}
    today_deduct = tenant_today_credit_deduct(db, tenant_id) if is_credit_tenant(tenant) else Decimal(0)
    return ApiResponse(
        data={
            "tenant_id": tenant.id,
            "name": tenant.name,
            "billing_mode": tenant.billing_mode,
            "credit_balance": float(tenant.credit_balance or 0),
            "credit_reserved": float(tenant.credit_reserved or 0),
            "today_deduct": float(today_deduct),
            "credit_policy": merge_credit_policy(tenant.credit_policy_json),
            "platform_whitelist": list(tenant.platform_whitelist_json or []),
            "daily_estimate": estimate,
        }
    )


class CreditAdjustRequest(BaseModel):
    amount: Decimal | None = Field(default=None, description="算力；负数扣减；与 yuan 同传时以 amount 入账")
    yuan_amount: Decimal | None = Field(default=None, description="人民币；可与 amount 同传作审计快照")
    reason: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def validate_adjust_payload(self) -> "CreditAdjustRequest":
        has_yuan = self.yuan_amount is not None and self.yuan_amount != 0
        has_amount = self.amount is not None and self.amount != 0
        if not has_yuan and not has_amount:
            raise ValueError("请填写 amount 或 yuan_amount")
        if has_yuan and self.yuan_amount is not None and self.yuan_amount < 0:
            raise ValueError("yuan_amount 必须为正")
        # 2026-08-28 - 充值备注选填 - 仅扣减仍须填写原因
        if self.amount is not None and self.amount < 0 and len(self.reason.strip()) < 2:
            raise ValueError("扣减须填写原因")
        return self


@router.post("/tenants/{tenant_id}/adjust", response_model=ApiResponse[dict])
def tenant_credit_adjust(
    tenant_id: int,
    payload: CreditAdjustRequest,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    require_platform(current)
    _require_any_menu(db, current, _CREDIT_OPS_WRITE_MENUS, "can_update")
    guard_sales_tenant(db, current, tenant_id)
    tenant = db.scalar(select(Tenant).where(Tenant.id == tenant_id, Tenant.deleted.is_(False)))
    if tenant is None:
        raise HTTPException(status_code=404, detail="企业不存在")
    if not is_credit_tenant(tenant):
        raise HTTPException(status_code=400, detail="仅算力自助企业可充扣算力")
    try:
        # 2026-09-09 - 同时传时以 amount 为准入账；yuan 写入流水 detail 供审计
        if payload.amount is not None and payload.amount != 0:
            amount = payload.amount
        else:
            amount = credits_from_yuan(tenant, payload.yuan_amount) if payload.yuan_amount else None
        if amount is None or amount == 0:
            raise HTTPException(status_code=400, detail="充值或扣减金额无效")
        detail: dict | None = None
        if payload.yuan_amount is not None and payload.yuan_amount > 0 and amount > 0:
            from app.services.credit_service import merge_credit_policy

            policy = merge_credit_policy(tenant.credit_policy_json)
            rate = float(policy.get("credits_per_yuan") or 4.2)
            detail = {
                "yuan_amount": float(payload.yuan_amount),
                "credits_per_yuan": rate,
                "amount_source": "explicit_credits" if payload.amount is not None else "yuan_converted",
            }
        row = recharge_credits(
            db,
            tenant,
            amount,
            operator_user_id=current.user.id,
            reason=payload.reason,
            detail_json=detail,
        )
        db.commit()
        return ApiResponse(
            data={
                "ledger_id": row.id,
                "balance": float(tenant.credit_balance or 0),
                "credits": float(amount),
                "yuan_amount": float(payload.yuan_amount) if payload.yuan_amount else None,
            }
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise_write_endpoint_error(exc, context="management.credit.adjust")


@router.get("/tenants/{tenant_id}/ledger", response_model=ApiResponse[dict])
def tenant_credit_ledger(
    tenant_id: int,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    exclude_internal: bool = Query(default=False, description="隐藏预扣/释放等内部账务"),
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    require_platform(current)
    _require_any_menu(db, current, _CREDIT_OPS_READ_MENUS)
    guard_sales_tenant(db, current, tenant_id)
    return ApiResponse(
        data=list_credit_ledger(
            db,
            tenant_id=tenant_id,
            page=page,
            page_size=page_size,
            exclude_internal=exclude_internal,
        )
    )


@router.get("/ledger", response_model=ApiResponse[dict])
def credit_platform_ledger(
    tenant_id: int | None = Query(default=None),
    tenant_name: str | None = Query(default=None, description="按企业名称模糊筛选"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    require_platform(current)
    _require_any_menu(db, current, _CREDIT_OPS_READ_MENUS)
    if tenant_id is not None:
        guard_sales_tenant(db, current, tenant_id)
    return ApiResponse(
        data=list_credit_ledger(
            db,
            tenant_id=tenant_id,
            tenant_name=tenant_name,
            page=page,
            page_size=page_size,
        )
    )


@router.get("/ledger/export")
def credit_platform_ledger_export(
    tenant_id: int | None = Query(default=None),
    tenant_name: str | None = Query(default=None, description="按企业名称模糊筛选"),
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
):
    require_platform(current)
    _require_any_menu(db, current, _CREDIT_OPS_READ_MENUS, "can_export")
    if tenant_id is not None:
        guard_sales_tenant(db, current, tenant_id)
    from app.services.credit_service import _ledger_tenant_filter_ids

    stmt = select(TenantCreditLedger).order_by(TenantCreditLedger.created_at.desc())
    tenant_ids = _ledger_tenant_filter_ids(db, tenant_id=tenant_id, tenant_name=tenant_name)
    if tenant_ids is not None:
        if not tenant_ids:
            rows = []
        else:
            stmt = stmt.where(TenantCreditLedger.tenant_id.in_(tenant_ids))
            rows = list(db.scalars(stmt.limit(5000)))
    else:
        rows = list(db.scalars(stmt.limit(5000)))
    tenant_map = {
        t.id: t.name
        for t in db.scalars(select(Tenant).where(Tenant.id.in_([r.tenant_id for r in rows] or [0])))
    }

    def _iter():
        yield _csv_row(
            [
                "id",
                "tenant_id",
                "tenant_name",
                "amount",
                "balance_after",
                "entry_type",
                "reason",
                "window_key",
                "platform_code",
                "keyword",
                "created_at",
            ]
        )
        for row in rows:
            yield _csv_row(
                [
                    row.id,
                    row.tenant_id,
                    tenant_map.get(row.tenant_id) or "",
                    row.amount,
                    row.balance_after,
                    row.entry_type,
                    row.reason or "",
                    row.window_key or "",
                    row.platform_code or "",
                    row.keyword or "",
                    row.created_at,
                ]
            )

    fname = f"credit-ledger-{tenant_id or 'all'}.csv"
    return StreamingResponse(_iter(), media_type="text/csv", headers={"Content-Disposition": f"attachment; filename={fname}"})


@router.get("/tenants/{tenant_id}/ledger/{ledger_id}", response_model=ApiResponse[dict])
def credit_tenant_ledger_detail(
    tenant_id: int,
    ledger_id: int,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    require_platform(current)
    _require_any_menu(db, current, _CREDIT_OPS_READ_MENUS)
    guard_sales_tenant(db, current, tenant_id)
    detail = get_ledger_entry_detail(db, tenant_id, ledger_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="流水不存在")
    return ApiResponse(data=detail)


@router.get("/tenants/{tenant_id}/billing-mode/preview", response_model=ApiResponse[dict])
def billing_mode_preview(
    tenant_id: int,
    target: str = Query(..., pattern="^(hosted|credit)$"),
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    require_platform(current)
    # 2026-09-09 - 与算力运营合并菜单对齐：board 或旧 tenant_credit 任一可写即可
    _require_any_menu(db, current, _CREDIT_OPS_WRITE_MENUS, "can_update")
    guard_sales_tenant(db, current, tenant_id)
    try:
        return ApiResponse(data=preview_billing_mode_switch(db, tenant_id, target_mode=target))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


class BillingModeSwitchRequest(BaseModel):
    target_mode: str = Field(pattern="^(hosted|credit)$")
    # 2026-09-08 - 备注改为选填，空串落库即可
    reason: str = Field(default="", max_length=500)
    effective_policy: str = Field(default="next_window", pattern="^(next_window|immediate)$")
    opening_credit_amount: Decimal | None = None
    credit_balance_action: str | None = Field(default="freeze", pattern="^(none|freeze|zero_adjust)$")
    contract_note: str | None = None
    platform_whitelist: list[str] | None = None


@router.post("/tenants/{tenant_id}/billing-mode/switch", response_model=ApiResponse[dict])
def billing_mode_switch(
    tenant_id: int,
    payload: BillingModeSwitchRequest,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    require_platform(current)
    _require_any_menu(db, current, _CREDIT_OPS_WRITE_MENUS, "can_update")
    guard_sales_tenant(db, current, tenant_id)
    try:
        # 2026-09-08 - 转自助不再收白名单；非空直接拒，避免运营以为设了限制
        from app.services.credit_service import assert_no_retired_quota_writes

        assert_no_retired_quota_writes(platform_whitelist=payload.platform_whitelist)
        log = switch_billing_mode(
            db,
            tenant_id,
            target_mode=payload.target_mode,
            reason=payload.reason,
            operator_user_id=current.user.id,
            effective_policy=payload.effective_policy,
            opening_credit_amount=payload.opening_credit_amount,
            credit_balance_action=payload.credit_balance_action,
            contract_note=payload.contract_note,
            platform_whitelist=None,
            operator_display_name=current.user.display_name,
        )
        db.commit()
        return ApiResponse(data=serialize_billing_mode_log(log))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise_write_endpoint_error(exc, context="management.credit.billing_mode_switch")


@router.post("/tenants/{tenant_id}/billing-mode/pending/cancel", response_model=ApiResponse[dict])
def billing_mode_pending_cancel(
    tenant_id: int,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    require_platform(current)
    _require_any_menu(db, current, _CREDIT_OPS_WRITE_MENUS, "can_update")
    guard_sales_tenant(db, current, tenant_id)
    try:
        closed = cancel_pending_billing_mode(db, tenant_id, operator_user_id=current.user.id)
        db.commit()
        return ApiResponse(data={"cancelled": closed})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise_write_endpoint_error(exc, context="management.credit.billing_mode_pending_cancel")


@router.get("/tenants/{tenant_id}/billing-mode/history", response_model=ApiResponse[list[dict]])
def billing_mode_history(
    tenant_id: int,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[list[dict]]:
    require_platform(current)
    _require_any_menu(db, current, _CREDIT_OPS_READ_MENUS)
    guard_sales_tenant(db, current, tenant_id)
    rows = list(
        db.scalars(
            select(BillingModeChangeLog)
            .where(BillingModeChangeLog.tenant_id == tenant_id)
            .order_by(BillingModeChangeLog.created_at.desc())
        )
    )
    return ApiResponse(data=[serialize_billing_mode_log(row) for row in rows])


class TermsPublishRequest(BaseModel):
    version_code: str
    title: str
    content_html: str
    effective_at: datetime
    notice_days: int = 7


@router.get("/terms", response_model=ApiResponse[list[dict]])
def credit_terms_list(
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[list[dict]]:
    require_platform(current)
    _require_any_menu(db, current, _CREDIT_OPS_READ_MENUS)
    from app.services.credit_service import is_offline_price_terms

    rows = list(db.scalars(select(CreditTermsVersion).order_by(CreditTermsVersion.created_at.desc())))
    # 2026-09-08 - 运营声明列表不展示改价 auto 噪声
    rows = [row for row in rows if not is_offline_price_terms(row)]
    return ApiResponse(
        data=[
            {
                "id": row.id,
                "version_code": row.version_code,
                "title": row.title,
                # 2026-09-08 - 运营台版本预览需要正文
                "content_html": sanitize_announcement_html(row.content_html or ""),
                "effective_at": row.effective_at.isoformat(sep=" ", timespec="minutes"),
                "notice_days": row.notice_days,
                "status": row.status,
                "published_at": row.published_at.isoformat(sep=" ", timespec="minutes") if row.published_at else None,
            }
            for row in rows
        ]
    )


@router.post("/terms", response_model=ApiResponse[dict])
def credit_terms_publish(
    payload: TermsPublishRequest,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    require_platform(current)
    _require_any_menu(db, current, _CREDIT_OPS_WRITE_MENUS, "can_update")
    row = CreditTermsVersion(
        version_code=payload.version_code,
        title=payload.title,
        content_html=sanitize_announcement_html(payload.content_html),
        effective_at=payload.effective_at,
        notice_days=payload.notice_days,
        status="published",
        published_at=datetime.now(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    # 2026-09-08 - 发布服务条款不再推系统通知
    return ApiResponse(data={"id": row.id})


class ReleaseReserveRequest(BaseModel):
    ref_id: str
    tenant_id: int
    reason: str | None = None


@router.post("/release-reserve", response_model=ApiResponse[dict])
def credit_release_reserve(
    payload: ReleaseReserveRequest,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    require_platform(current)
    _require_any_menu(db, current, _CREDIT_OPS_WRITE_MENUS, "can_update")
    guard_sales_tenant(db, current, payload.tenant_id)
    released = release_reserve(
        db,
        tenant_id=payload.tenant_id,
        ref_id=payload.ref_id,
        reason=payload.reason or "运营手工释放",
        detail_json={"batch_force_closed": True},
    )
    if not released:
        raise HTTPException(status_code=404, detail="未找到可释放的预扣记录")
    db.commit()
    return ApiResponse(data={"released": True})


@router.get("/tenants", response_model=ApiResponse[list[dict]])
def credit_tenants_list(
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[list[dict]]:
    require_platform(current)
    _require_any_menu(db, current, ("platform.credit_ops_board", "platform.tenant_credit"))
    from app.services.tenant_scope import sales_owned_tenant_ids

    rows = list(
        db.scalars(select(Tenant).where(Tenant.deleted.is_(False), Tenant.billing_mode == "credit"))
    )
    # 2026-09-09 - 销售仅看名下企业，与单企 guard_sales_tenant 一致
    owned = sales_owned_tenant_ids(db, current)
    if owned is not None:
        owned_set = set(owned)
        rows = [t for t in rows if t.id in owned_set]
    owners = {
        u.id: u.display_name
        for u in db.scalars(select(User).where(User.id.in_([t.owner_user_id for t in rows if t.owner_user_id] or [0])))
    }
    items = []
    for tenant in rows:
        asset = get_brand_asset(db, tenant.id)
        estimate = estimate_daily_credits(db, tenant, asset) if asset else {}
        today_deduct = tenant_today_credit_deduct(db, tenant.id)
        items.append(
            {
                "tenant_id": tenant.id,
                "name": tenant.name,
                "credit_balance": float(tenant.credit_balance or 0),
                "credit_reserved": float(tenant.credit_reserved or 0),
                "today_deduct": float(today_deduct),
                "owner_name": owners.get(tenant.owner_user_id or 0, ""),
                "daily_estimate": estimate,
            }
        )
    return ApiResponse(data=dedupe_credit_tenant_list_items(items))


@router.get("/tenants/{tenant_id}/reserves", response_model=ApiResponse[list[dict]])
def credit_tenant_open_reserves(
    tenant_id: int,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[list[dict]]:
    require_platform(current)
    _require_any_menu(db, current, _CREDIT_OPS_READ_MENUS)
    guard_sales_tenant(db, current, tenant_id)
    tenant = db.scalar(select(Tenant).where(Tenant.id == tenant_id, Tenant.deleted.is_(False)))
    if tenant is None:
        raise HTTPException(status_code=404, detail="企业不存在")
    if not is_credit_tenant(tenant):
        return ApiResponse(data=[])
    return ApiResponse(data=list_open_credit_reserves(db, tenant_id))


class TenantCreditPolicyUpdate(BaseModel):
    credit_policy: dict | None = None
    platform_whitelist: list[str] | None = None


@router.put("/tenants/{tenant_id}/policy", response_model=ApiResponse[dict])
def tenant_credit_policy_update(
    tenant_id: int,
    payload: TenantCreditPolicyUpdate,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    require_platform(current)
    # 2026-08-28 - 充值页可改汇率 - 与充值同属算力运营写权限
    _require_any_menu(db, current, _CREDIT_OPS_WRITE_MENUS, "can_update")
    guard_sales_tenant(db, current, tenant_id)
    tenant = db.scalar(select(Tenant).where(Tenant.id == tenant_id, Tenant.deleted.is_(False)))
    if tenant is None:
        raise HTTPException(status_code=404, detail="企业不存在")
    if not is_credit_tenant(tenant):
        raise HTTPException(status_code=400, detail="仅算力自助企业可配置 policy")
    old_policy = merge_credit_policy(tenant.credit_policy_json)
    try:
        # 2026-09-08 - 方案 A：废弃字段显式 400，禁止静默吞写误导运营
        from app.services.credit_service import assert_no_retired_quota_writes

        assert_no_retired_quota_writes(
            credit_policy=payload.credit_policy,
            platform_whitelist=payload.platform_whitelist,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if payload.credit_policy is not None:
        rate = payload.credit_policy.get("credits_per_yuan")
        if rate is not None:
            try:
                if float(rate) <= 0:
                    raise HTTPException(status_code=400, detail="充值汇率须大于 0")
            except (TypeError, ValueError) as exc:
                raise HTTPException(status_code=400, detail="充值汇率无效") from exc
        tenant.credit_policy_json = merge_credit_policy({**old_policy, **payload.credit_policy})
    if payload.platform_whitelist is not None:
        # 仅允许空列表（清历史脏数据）；非空已在上方 400
        tenant.platform_whitelist_json = []
    db.commit()
    db.refresh(tenant)
    return ApiResponse(
        data={
            "credit_policy": merge_credit_policy(tenant.credit_policy_json),
            "platform_whitelist": list(tenant.platform_whitelist_json or []),
        }
    )


@router.get("/tenants/{tenant_id}/members", response_model=ApiResponse[dict])
def credit_tenant_members(
    tenant_id: int,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    require_platform(current)
    _require_any_menu(db, current, _CREDIT_OPS_READ_MENUS)
    guard_sales_tenant(db, current, tenant_id)
    identities = list(
        db.scalars(
            select(UserIdentity).where(
                UserIdentity.tenant_id == tenant_id,
                UserIdentity.identity_type == "CUSTOMER",
                UserIdentity.deleted.is_(False),
            )
        )
    )
    users = {u.id: u for u in db.scalars(select(User).where(User.id.in_([i.user_id for i in identities] or [0])))}
    positions = {p.id: p for p in db.scalars(select(CustomerPosition).where(CustomerPosition.deleted.is_(False)))}
    return ApiResponse(
        data={
            "items": [
                {
                    "identity_id": ident.id,
                    "display_name": users[ident.user_id].display_name if ident.user_id in users else "",
                    "username": users[ident.user_id].username if ident.user_id in users else "",
                    "position_name": positions[ident.customer_position_id].position_name
                    if ident.customer_position_id in positions
                    else "",
                    "status": ident.status,
                }
                for ident in identities
            ]
        }
    )


@router.get("/tenants/{tenant_id}/ledger/export")
def credit_tenant_ledger_export(
    tenant_id: int,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
):
    require_platform(current)
    _require_any_menu(db, current, _CREDIT_OPS_READ_MENUS, "can_export")
    guard_sales_tenant(db, current, tenant_id)
    rows = list(
        db.scalars(
            select(TenantCreditLedger)
            .where(TenantCreditLedger.tenant_id == tenant_id)
            .order_by(TenantCreditLedger.created_at.desc())
            .limit(5000)
        )
    )

    def _iter():
        yield _csv_row(
            [
                "id",
                "amount",
                "balance_after",
                "entry_type",
                "reason",
                "window_key",
                "platform_code",
                "keyword",
                "created_at",
            ]
        )
        for row in rows:
            yield _csv_row(
                [
                    row.id,
                    row.amount,
                    row.balance_after,
                    row.entry_type,
                    row.reason or "",
                    row.window_key or "",
                    row.platform_code or "",
                    row.keyword or "",
                    row.created_at,
                ]
            )

    return StreamingResponse(_iter(), media_type="text/csv", headers={"Content-Disposition": f"attachment; filename=credit-ledger-{tenant_id}.csv"})


@router.get("/price-rules", response_model=ApiResponse[list[dict]])
def credit_price_rules_list(
    scope: str | None = Query(default=None, pattern="^(global|tenant)$"),
    tenant_id: int | None = Query(default=None),
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[list[dict]]:
    require_platform(current)
    _require_any_menu(db, current, _CREDIT_OPS_READ_MENUS)
    rows = list_price_rules(db, scope=scope, tenant_id=tenant_id)
    tenant_map = {
        t.id: t.name
        for t in db.scalars(select(Tenant).where(Tenant.id.in_([r.tenant_id for r in rows if r.tenant_id] or [0])))
    }
    return ApiResponse(
        data=[
            {
                "id": row.id,
                "scope": row.scope,
                "tenant_id": row.tenant_id,
                "tenant_name": tenant_map.get(row.tenant_id) if row.tenant_id else None,
                "platform_code": row.platform_code,
                "credits_per_subtask": float(row.credits_per_subtask),
                "status": row.status,
                "updated_at": row.updated_at.isoformat(sep=" ", timespec="minutes"),
            }
            for row in rows
        ]
    )


class PriceRuleUpsertRequest(BaseModel):
    scope: str = Field(pattern="^(global|tenant)$")
    tenant_id: int | None = None
    platform_code: str | None = None
    credits_per_subtask: Decimal = Field(gt=0)
    status: bool = True


@router.put("/price-rules", response_model=ApiResponse[dict])
def credit_price_rule_upsert(
    payload: PriceRuleUpsertRequest,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    require_platform(current)
    _require_any_menu(db, current, _CREDIT_OPS_WRITE_MENUS, "can_update")
    try:
        row = upsert_price_rule(
            db,
            scope=payload.scope,
            tenant_id=payload.tenant_id,
            platform_code=payload.platform_code,
            credits_per_subtask=payload.credits_per_subtask,
            status=payload.status,
        )
        db.commit()
        return ApiResponse(
            data={
                "id": row.id,
                "scope": row.scope,
                "platform_code": row.platform_code,
                "credits_per_subtask": float(row.credits_per_subtask),
                "terms_reminder": payload.scope == "global",
            }
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise_write_endpoint_error(exc, context="management.credit.price_rule_upsert")
