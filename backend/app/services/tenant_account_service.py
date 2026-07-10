"""企业停服/到期 → 关联客户账号联动禁用。"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.tenant import Tenant
from app.models.user import User
from app.models.user_identity import UserIdentity


def tenant_service_is_operational(tenant: Tenant | None, *, today: date | None = None) -> bool:
    """企业是否处于可服务状态（合同期内且未人工停服）。"""
    if tenant is None:
        return True
    today = today or date.today()
    if not tenant.status:
        return False
    if tenant.stop_reason in {"manual", "canceled"}:
        return False
    if tenant.service_start_date and tenant.service_start_date > today:
        return False
    if tenant.service_end_date and tenant.service_end_date < today:
        return False
    return True


def disable_tenant_customer_accounts(db: Session, tenant_id: int) -> int:
    """禁用企业下全部客户身份；用户无其它可用身份时同步禁用用户。"""
    identities = list(
        db.scalars(
            select(UserIdentity).where(
                UserIdentity.tenant_id == tenant_id,
                UserIdentity.deleted.is_(False),
            )
        )
    )
    if not identities:
        return 0

    affected_user_ids: set[int] = set()
    for identity in identities:
        identity.status = False
        identity.deleted = True
        affected_user_ids.add(identity.user_id)

    db.flush()
    disabled_users = 0
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
            if user and user.status:
                user.status = False
                disabled_users += 1
    db.flush()
    return disabled_users


def restore_tenant_customer_accounts(db: Session, tenant_id: int) -> int:
    """恢复企业下客户身份；同步恢复关联用户（未软删）。"""
    identities = list(db.scalars(select(UserIdentity).where(UserIdentity.tenant_id == tenant_id)))
    if not identities:
        return 0

    restored_users = 0
    user_ids: set[int] = set()
    for identity in identities:
        identity.status = True
        identity.deleted = False
        user_ids.add(identity.user_id)

    for user_id in user_ids:
        user = db.get(User, user_id)
        if user and not user.deleted and not user.status:
            user.status = True
            restored_users += 1
    db.flush()
    return restored_users


def mark_tenant_inactive(
    db: Session,
    tenant: Tenant,
    *,
    stop_reason: str,
    stopped_by: int | None = None,
    stopped_at: datetime | None = None,
) -> None:
    tenant.status = False
    tenant.stop_reason = stop_reason
    tenant.stopped_at = stopped_at or datetime.now()
    if stopped_by is not None:
        tenant.stopped_by = stopped_by
    disable_tenant_customer_accounts(db, tenant.id)


def sync_tenant_accounts_for_service_state(db: Session, tenant: Tenant) -> None:
    """按当前企业服务状态同步客户账号启用/禁用。"""
    if tenant_service_is_operational(tenant):
        restore_tenant_customer_accounts(db, tenant.id)
    else:
        disable_tenant_customer_accounts(db, tenant.id)


def expire_overdue_tenant_services(db: Session, *, today: date | None = None) -> int:
    """扫描合同已到期但仍可登录的企业，标记 expired 并禁用账号。返回处理企业数。"""
    today = today or date.today()
    tenants = list(
        db.scalars(
            select(Tenant).where(
                Tenant.deleted.is_(False),
                Tenant.service_end_date.is_not(None),
                Tenant.service_end_date < today,
                or_(Tenant.stop_reason.is_(None), Tenant.stop_reason.notin_(("manual", "canceled"))),
            )
        )
    )
    handled = 0
    for tenant in tenants:
        if tenant.stop_reason == "expired" and not tenant_service_is_operational(tenant):
            disable_tenant_customer_accounts(db, tenant.id)
            continue
        tenant.status = False
        tenant.stop_reason = "expired"
        if tenant.stopped_at is None:
            tenant.stopped_at = datetime.now()
        disable_tenant_customer_accounts(db, tenant.id)
        handled += 1
    return handled
