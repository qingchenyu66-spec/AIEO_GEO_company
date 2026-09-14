"""托管 ↔ 算力自助模式切换。"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.brand import BrandAsset
from app.models.credit import BillingModeChangeLog
from app.models.permission import CustomerPosition, CustomerPositionMenu, Menu, UserIdentityMenu
from app.models.user_identity import UserIdentity
from app.models.tenant import Tenant
from app.services.credit_service import BILLING_MODE_CREDIT, BILLING_MODE_HOSTED, estimate_daily_credits, is_credit_tenant, recharge_credits

ENTERPRISE_MENU_CODES = (
    "customer.enterprise_config",
    "customer.enterprise_monitor",
    "customer.enterprise_members",
    "customer.enterprise_credit",
    "customer.enterprise_audit",
)

VIEWER_POSITION_CODE = "enterprise_viewer"


def preview_billing_mode_switch(db: Session, tenant_id: int, *, target_mode: str) -> dict[str, Any]:
    tenant = db.scalar(select(Tenant).where(Tenant.id == tenant_id, Tenant.deleted.is_(False)))
    if tenant is None:
        raise ValueError("企业不存在")
    if target_mode not in {BILLING_MODE_HOSTED, BILLING_MODE_CREDIT}:
        raise ValueError("无效的目标模式")
    asset = db.scalar(
        select(BrandAsset).where(BrandAsset.tenant_id == tenant_id, BrandAsset.deleted.is_(False))
    )
    estimate = estimate_daily_credits(db, tenant, asset) if asset else {}
    opening_credit = Decimal(str(estimate.get("credits_per_day") or 0)) * Decimal("3")
    return {
        "tenant_id": tenant_id,
        "current_mode": tenant.billing_mode,
        "target_mode": target_mode,
        "credit_balance": float(tenant.credit_balance or 0),
        "daily_estimate": estimate,
        "suggested_opening_credit": float(opening_credit),
        "platform_whitelist": list(tenant.platform_whitelist_json or []),
        "credit_policy": tenant.credit_policy_json or {},
    }


def _enterprise_menu_ids(db: Session) -> list[int]:
    return list(
        db.scalars(
            select(Menu.id).where(
                Menu.menu_code.in_(ENTERPRISE_MENU_CODES),
                Menu.deleted.is_(False),
                Menu.status.is_(True),
            )
        )
    )


def _global_customer_position(db: Session, position_code: str) -> CustomerPosition | None:
    return db.scalar(
        select(CustomerPosition).where(
            CustomerPosition.tenant_id.is_(None),
            CustomerPosition.position_code == position_code,
            CustomerPosition.deleted.is_(False),
        )
    )


def _enterprise_menu_grants_for_position(db: Session, position_id: int) -> dict[int, dict[str, bool]]:
    enterprise_ids = set(_enterprise_menu_ids(db))
    if not enterprise_ids:
        return {}
    grants: dict[int, dict[str, bool]] = {}
    rows = db.scalars(select(CustomerPositionMenu).where(CustomerPositionMenu.position_id == position_id))
    for row in rows:
        if row.menu_id not in enterprise_ids:
            continue
        grants[row.menu_id] = {
            "can_create": bool(row.can_create),
            "can_update": bool(row.can_update),
            "can_delete": bool(row.can_delete),
            "can_export": bool(row.can_export),
        }
    return grants


def resolve_enterprise_menu_grants_for_identity(db: Session, identity: UserIdentity) -> dict[str, dict[str, bool]]:
    """方案甲：按客户职位解析企业配置菜单权限（menu_code → flags）。

    非 credit 客户返回空；无 customer_position 时：
    - role_code 为租户管理员类 → enterprise_admin
    - 否则 → enterprise_viewer
    """
    if identity.identity_type != "CUSTOMER" or not identity.tenant_id:
        return {}
    tenant = db.scalar(select(Tenant).where(Tenant.id == identity.tenant_id, Tenant.deleted.is_(False)))
    if tenant is None or not is_credit_tenant(tenant):
        return {}

    position_id = int(identity.customer_position_id) if identity.customer_position_id else None
    if position_id is None:
        role = str(getattr(identity, "role_code", None) or "")
        code = (
            "enterprise_admin"
            if role in {"TENANT_ADMIN", "enterprise_admin", "customer_admin"}
            else VIEWER_POSITION_CODE
        )
        template = _global_customer_position(db, code)
        position_id = int(template.id) if template is not None else None
    if position_id is None:
        return {}

    by_id = _enterprise_menu_grants_for_position(db, position_id)
    if not by_id:
        return {}
    menus = {
        m.id: m.menu_code
        for m in db.scalars(select(Menu).where(Menu.id.in_(list(by_id.keys())), Menu.deleted.is_(False)))
    }
    return {menus[mid]: flags for mid, flags in by_id.items() if mid in menus}


def _grant_enterprise_menus_for_identity(db: Session, identity: UserIdentity) -> None:
    # 2026-09-08 - 转自助按本人客户职位注入；无职位回退只读 viewer
    # 2026-09-09 - 方案甲：侧栏/鉴权改为读时动态合并，此处仅清理/兼容旧落库，不再按姓名提权
    grants: dict[int, dict[str, bool]] = {}
    if identity.customer_position_id:
        grants = _enterprise_menu_grants_for_position(db, int(identity.customer_position_id))
    if not grants:
        viewer = _global_customer_position(db, VIEWER_POSITION_CODE)
        if viewer is not None:
            grants = _enterprise_menu_grants_for_position(db, viewer.id)
    for menu_id, flags in grants.items():
        exists = db.scalar(
            select(UserIdentityMenu.id).where(
                UserIdentityMenu.identity_id == identity.id,
                UserIdentityMenu.menu_id == menu_id,
            )
        )
        if exists:
            row = db.get(UserIdentityMenu, exists)
            if row is not None:
                row.can_create = flags["can_create"]
                row.can_update = flags["can_update"]
                row.can_delete = flags["can_delete"]
                row.can_export = flags["can_export"]
            continue
        db.add(
            UserIdentityMenu(
                identity_id=identity.id,
                menu_id=menu_id,
                can_create=flags["can_create"],
                can_update=flags["can_update"],
                can_delete=flags["can_delete"],
                can_export=flags["can_export"],
            )
        )


def _revoke_enterprise_menus(db: Session, identity_id: int) -> None:
    menu_ids = _enterprise_menu_ids(db)
    if not menu_ids:
        return
    rows = list(
        db.scalars(
            select(UserIdentityMenu).where(
                UserIdentityMenu.identity_id == identity_id,
                UserIdentityMenu.menu_id.in_(menu_ids),
            )
        )
    )
    for row in rows:
        db.delete(row)


def inject_enterprise_menus_for_tenant(db: Session, tenant_id: int) -> None:
    """转自助只清身份表里的企业配置脏授权；会话按客户职位动态合并。"""
    identities = list(
        db.scalars(
            select(UserIdentity).where(
                UserIdentity.tenant_id == tenant_id,
                UserIdentity.identity_type == "CUSTOMER",
                UserIdentity.deleted.is_(False),
                UserIdentity.status.is_(True),
            )
        )
    )
    for identity in identities:
        _revoke_enterprise_menus(db, identity.id)


def revoke_enterprise_menus_for_tenant(db: Session, tenant_id: int) -> None:
    identities = list(
        db.scalars(
            select(UserIdentity).where(
                UserIdentity.tenant_id == tenant_id,
                UserIdentity.identity_type == "CUSTOMER",
                UserIdentity.deleted.is_(False),
            )
        )
    )
    for identity in identities:
        _revoke_enterprise_menus(db, identity.id)


PENDING_BILLING_SWITCH_KEY = "_pending_billing_switch"
BILLING_SWITCH_STATUS_KEY = "_billing_switch_status"


def list_pending_billing_mode_logs(db: Session, tenant_id: int) -> list[BillingModeChangeLog]:
    return list(
        db.scalars(
            select(BillingModeChangeLog)
            .where(
                BillingModeChangeLog.tenant_id == tenant_id,
                BillingModeChangeLog.effective_policy == "next_window",
                BillingModeChangeLog.effective_at.is_(None),
            )
            .order_by(BillingModeChangeLog.id.asc())
        )
    )


def billing_mode_log_status(log: BillingModeChangeLog) -> str:
    snap = log.daily_estimate_snapshot_json if isinstance(log.daily_estimate_snapshot_json, dict) else {}
    marked = snap.get(BILLING_SWITCH_STATUS_KEY)
    if marked in {"cancelled", "superseded"}:
        return str(marked)
    if log.effective_policy == "next_window" and log.effective_at is None:
        return "pending"
    return "applied"


def serialize_billing_mode_log(log: BillingModeChangeLog) -> dict[str, Any]:
    status = billing_mode_log_status(log)
    return {
        "id": log.id,
        "from_mode": log.from_mode,
        "to_mode": log.to_mode,
        "reason": log.reason,
        "effective_policy": log.effective_policy,
        "effective_at": log.effective_at.isoformat(sep=" ", timespec="minutes") if log.effective_at else None,
        "opening_credit_amount": float(log.opening_credit_amount) if log.opening_credit_amount is not None else None,
        "status": status,
        "created_at": log.created_at.isoformat(sep=" ", timespec="minutes") if log.created_at else None,
    }


def _close_pending_billing_mode_log(
    log: BillingModeChangeLog,
    *,
    status: str,
    superseded_by: int | None = None,
    operator_user_id: int | None = None,
) -> None:
    snap = dict(log.daily_estimate_snapshot_json or {})
    snap[BILLING_SWITCH_STATUS_KEY] = status
    if superseded_by is not None:
        snap["superseded_by"] = superseded_by
    if operator_user_id is not None:
        snap["closed_by_user_id"] = operator_user_id
    log.daily_estimate_snapshot_json = snap
    log.effective_at = datetime.now()


def cancel_pending_billing_mode(db: Session, tenant_id: int, *, operator_user_id: int) -> int:
    """取消该企业全部待生效 next_window 切换（不改当前 billing_mode）。"""
    pending = list_pending_billing_mode_logs(db, tenant_id)
    if not pending:
        raise ValueError("没有待生效的模式切换")
    for log in pending:
        _close_pending_billing_mode_log(log, status="cancelled", operator_user_id=operator_user_id)
    db.flush()
    return len(pending)


def _supersede_other_pending_switches(db: Session, tenant_id: int, *, keep_log_id: int) -> int:
    closed = 0
    for log in list_pending_billing_mode_logs(db, tenant_id):
        if log.id == keep_log_id:
            continue
        _close_pending_billing_mode_log(log, status="superseded", superseded_by=keep_log_id)
        closed += 1
    return closed


def _apply_billing_mode_switch_effects(
    db: Session,
    tenant: Tenant,
    *,
    target_mode: str,
    reason: str,
    operator_user_id: int,
    opening_credit_amount: Decimal | None = None,
    credit_balance_action: str | None = None,
    platform_whitelist: list[str] | None = None,
    credit_policy: dict | None = None,
) -> None:
    if target_mode == BILLING_MODE_CREDIT:
        if opening_credit_amount is None or opening_credit_amount <= 0:
            raise ValueError("转自助须填写起步算力")
        # 2026-09-08 - 方案 A：转自助强制空白名单；配额键禁止写入
        from app.services.credit_service import assert_no_retired_quota_writes, merge_credit_policy

        assert_no_retired_quota_writes(
            credit_policy=credit_policy,
            platform_whitelist=platform_whitelist,
        )
        tenant.platform_whitelist_json = []
        if credit_policy is not None:
            tenant.credit_policy_json = merge_credit_policy({**(tenant.credit_policy_json or {}), **credit_policy})
        recharge_credits(
            db,
            tenant,
            opening_credit_amount,
            operator_user_id=operator_user_id,
            reason=_billing_switch_ledger_reason("转自助起步充值", reason),
        )
    elif target_mode == BILLING_MODE_HOSTED:
        action = credit_balance_action or "freeze"
        if action == "zero_adjust" and Decimal(str(tenant.credit_balance or 0)) > 0:
            recharge_credits(
                db,
                tenant,
                -Decimal(str(tenant.credit_balance or 0)),
                operator_user_id=operator_user_id,
                reason=_billing_switch_ledger_reason("转托管冲零", reason),
            )


def _billing_switch_ledger_reason(prefix: str, reason: str) -> str:
    note = (reason or "").strip()
    return f"{prefix}：{note}" if note else prefix


def switch_billing_mode(
    db: Session,
    tenant_id: int,
    *,
    target_mode: str,
    reason: str,
    operator_user_id: int,
    effective_policy: str = "next_window",
    opening_credit_amount: Decimal | None = None,
    credit_balance_action: str | None = None,
    contract_note: str | None = None,
    platform_whitelist: list[str] | None = None,
    credit_policy: dict | None = None,
    operator_display_name: str | None = None,
) -> BillingModeChangeLog:
    # 2026-08-27 - 模式切换必须写 change_log，禁止只改 billing_mode 字段
    tenant = db.scalar(select(Tenant).where(Tenant.id == tenant_id, Tenant.deleted.is_(False)).with_for_update())
    if tenant is None:
        raise ValueError("企业不存在")
    # 2026-09-08 - 备注选填；空串写入 change_log.reason
    reason_text = (reason or "").strip()
    from_mode = tenant.billing_mode or BILLING_MODE_HOSTED
    if from_mode == target_mode:
        raise ValueError("目标模式与当前相同")
    if target_mode == BILLING_MODE_CREDIT and (opening_credit_amount is None or opening_credit_amount <= 0):
        raise ValueError("转自助须填写起步算力")
    asset = db.scalar(select(BrandAsset).where(BrandAsset.tenant_id == tenant_id, BrandAsset.deleted.is_(False)))
    estimate = estimate_daily_credits(db, tenant, asset) if asset else {}
    immediate = effective_policy == "immediate"
    effective_at = datetime.now() if immediate else None
    pending_switch: dict[str, Any] | None = None

    if immediate:
        _apply_billing_mode_switch_effects(
            db,
            tenant,
            target_mode=target_mode,
            reason=reason_text,
            operator_user_id=operator_user_id,
            opening_credit_amount=opening_credit_amount,
            credit_balance_action=credit_balance_action,
            platform_whitelist=platform_whitelist,
            credit_policy=credit_policy,
        )
        tenant.billing_mode = target_mode
    else:
        # 2026-08-28 - next_window 仅记待生效 - billing_mode/充值/菜单等到下一窗任务再落地
        pending_switch = {
            # 2026-09-08 - 方案 A：待生效切换不再携带白名单
            "platform_whitelist": None,
            "credit_policy": credit_policy,
            "opening_credit_amount": str(opening_credit_amount) if opening_credit_amount is not None else None,
            "credit_balance_action": credit_balance_action,
            "operator_user_id": operator_user_id,
            "operator_display_name": operator_display_name,
        }

    estimate_snapshot = dict(estimate)
    if pending_switch is not None:
        estimate_snapshot[PENDING_BILLING_SWITCH_KEY] = pending_switch

    log = BillingModeChangeLog(
        tenant_id=tenant_id,
        from_mode=from_mode,
        to_mode=target_mode,
        reason=reason_text,
        contract_note=contract_note,
        operator_user_id=operator_user_id,
        effective_policy=effective_policy,
        effective_at=effective_at,
        credit_balance_action=credit_balance_action,
        opening_credit_amount=opening_credit_amount,
        daily_estimate_snapshot_json=estimate_snapshot,
    )
    db.add(log)
    db.flush()

    # 2026-09-09 - 方案甲：同租户仅一条待生效；新单覆盖旧单；立即切换也清掉 pending
    if immediate:
        for old in list_pending_billing_mode_logs(db, tenant_id):
            _close_pending_billing_mode_log(old, status="superseded", superseded_by=log.id, operator_user_id=operator_user_id)
        if target_mode == BILLING_MODE_CREDIT:
            inject_enterprise_menus_for_tenant(db, tenant_id)
        else:
            revoke_enterprise_menus_for_tenant(db, tenant_id)
        from app.services.system_notification_service import notify_billing_mode_switched, notify_billing_mode_switched_to_sales

        notify_billing_mode_switched(db, tenant, log, operator_name=operator_display_name)
        notify_billing_mode_switched_to_sales(db, tenant, log, operator_name=operator_display_name)
    else:
        _supersede_other_pending_switches(db, tenant_id, keep_log_id=log.id)
    db.flush()
    return log


def _apply_one_pending_billing_mode_log(db: Session, log: BillingModeChangeLog) -> bool:
    """落地单条 next_window 待生效记录。已是目标模式则仅盖章 effective_at。"""
    if billing_mode_log_status(log) != "pending":
        return False
    tenant = db.scalar(
        select(Tenant).where(Tenant.id == log.tenant_id, Tenant.deleted.is_(False)).with_for_update()
    )
    if tenant is None:
        return False
    if tenant.billing_mode == log.to_mode:
        log.effective_at = datetime.now()
        return True
    snapshot = log.daily_estimate_snapshot_json or {}
    pending_cfg = snapshot.get(PENDING_BILLING_SWITCH_KEY) or {}
    opening_raw = pending_cfg.get("opening_credit_amount")
    opening_credit = (
        Decimal(str(opening_raw))
        if opening_raw is not None
        else (log.opening_credit_amount if log.opening_credit_amount is not None else None)
    )
    operator_id = int(pending_cfg.get("operator_user_id") or log.operator_user_id)
    _apply_billing_mode_switch_effects(
        db,
        tenant,
        target_mode=log.to_mode,
        reason=log.reason,
        operator_user_id=operator_id,
        opening_credit_amount=opening_credit,
        credit_balance_action=pending_cfg.get("credit_balance_action") or log.credit_balance_action,
        platform_whitelist=pending_cfg.get("platform_whitelist"),
        credit_policy=pending_cfg.get("credit_policy"),
    )
    tenant.billing_mode = log.to_mode
    if log.to_mode == BILLING_MODE_CREDIT:
        inject_enterprise_menus_for_tenant(db, tenant.id)
    else:
        revoke_enterprise_menus_for_tenant(db, tenant.id)
    log.effective_at = datetime.now()
    from app.services.system_notification_service import notify_billing_mode_switched, notify_billing_mode_switched_to_sales

    operator_name = pending_cfg.get("operator_display_name")
    notify_billing_mode_switched(db, tenant, log, operator_name=operator_name)
    notify_billing_mode_switched_to_sales(db, tenant, log, operator_name=operator_name)
    return True


def apply_pending_billing_mode_for_tenant(db: Session, tenant_id: int) -> int:
    """
    落地该企业待生效的 next_window 切换。
    2026-09-08 - 真正挂在监测提交前调用；本函数自行 commit，避免闸失败回滚把模式切回去。
    2026-09-09 - 若历史叠了多条 pending，只落地最新一条，旧单标为 superseded。
    """
    pending = list_pending_billing_mode_logs(db, tenant_id)
    if not pending:
        return 0
    if len(pending) > 1:
        latest = pending[-1]
        for old in pending[:-1]:
            _close_pending_billing_mode_log(old, status="superseded", superseded_by=latest.id)
        pending = [latest]
    applied = 0
    for log in pending:
        if _apply_one_pending_billing_mode_log(db, log):
            applied += 1
    if applied:
        db.commit()
    return applied


def apply_scheduled_mode_changes(db: Session) -> int:
    """测试/脚本用：落地全部待生效 next_window。生产监测路径请用 apply_pending_billing_mode_for_tenant。"""
    tenant_ids = list(
        db.scalars(
            select(BillingModeChangeLog.tenant_id)
            .where(
                BillingModeChangeLog.effective_policy == "next_window",
                BillingModeChangeLog.effective_at.is_(None),
            )
            .distinct()
        )
    )
    applied = 0
    for tenant_id in tenant_ids:
        applied += apply_pending_billing_mode_for_tenant(db, int(tenant_id))
    return applied
