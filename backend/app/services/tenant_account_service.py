"""企业服务状态与客户账号：服务期只限模力提交，不再联动禁用登录。"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.tenant import Tenant
from app.models.user import User
from app.models.user_identity import UserIdentity


def tenant_service_is_operational(tenant: Tenant | None, *, today: date | None = None) -> bool:
    """企业是否处于可向模力提交任务的状态（合同期内且未人工停服）。"""
    if tenant is None:
        return True
    today = today or date.today()
    if tenant.service_start_date and tenant.service_start_date > today:
        return False
    if tenant.service_end_date and tenant.service_end_date < today:
        return False
    if not tenant.status:
        return False
    if tenant.stop_reason in {"manual", "canceled"}:
        return False
    return True


def molizhishu_submit_skip_message(tenant: Tenant | None, *, today: date | None = None) -> str | None:
    """不可提交模力时返回温和跳过文案；可提交返回 None。不落 failed，避免运营看板「调度失败」惊吓。"""
    # 2026-08-03 - 未开始/到期/停服：保存配置可以，提交在跑之前跳过
    if tenant is None or tenant_service_is_operational(tenant, today=today):
        return None
    today = today or date.today()
    if tenant.service_start_date and tenant.service_start_date > today:
        return f"企业服务尚未开始（{tenant.service_start_date}），监测暂不提交"
    if tenant.service_end_date and tenant.service_end_date < today:
        return f"企业服务已到期（{tenant.service_end_date}），监测暂不提交"
    return "企业服务未开通或已停服，监测暂不提交"


def is_service_gate_schedule_message(message: str | None) -> bool:
    """调度失败文案是否属于服务闸门（应从「调度失败」预警中排除）。"""
    text = str(message or "")
    markers = (
        "企业服务尚未开始",
        "企业服务已停止",
        "企业服务已到期",
        "企业服务未开通",
        "监测暂不提交",
        "不能提交新的监测任务",
    )
    return any(marker in text for marker in markers)


def disable_tenant_customer_accounts(db: Session, tenant_id: int) -> int:
    """禁用企业下全部客户身份；用户无其它可用身份时同步禁用用户。

    保留工具函数供运维脚本/测试；业务停服路径不再调用（见 sync / mark_tenant_inactive）。
    """
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
    # 2026-08-03 - 停服只改企业状态；客户账号仍可登录用非模力
    tenant.status = False
    tenant.stop_reason = stop_reason
    tenant.stopped_at = stopped_at or datetime.now()
    if stopped_by is not None:
        tenant.stopped_by = stopped_by


def sync_tenant_accounts_for_service_state(db: Session, tenant: Tenant) -> None:
    """服务状态变更时恢复历史误禁用账号；不再因未开始/到期/停服禁用。"""
    # 2026-08-03 - 旧逻辑会 disable；现改为 restore，便于已到期/未开始客户仍能登录
    restore_tenant_customer_accounts(db, tenant.id)


def expire_overdue_tenant_services(db: Session, *, today: date | None = None) -> int:
    """扫描合同已到期企业，标记 expired；不禁用客户账号。返回处理企业数。"""
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
            continue
        tenant.status = False
        tenant.stop_reason = "expired"
        if tenant.stopped_at is None:
            tenant.stopped_at = datetime.now()
        handled += 1
    db.flush()
    return handled
