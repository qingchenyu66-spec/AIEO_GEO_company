"""Tests for tenant account linkage on service stop/expiry."""

from datetime import date, timedelta
from uuid import uuid4

import pytest

from app.core.database import SessionLocal
from app.models.tenant import Tenant
from app.models.user import User
from app.models.user_identity import UserIdentity
from app.services.auth_service import active_identities
from app.services.monitor_service import _validate_tenant_service_available
from app.services.tenant_account_service import (
    disable_tenant_customer_accounts,
    expire_overdue_tenant_services,
    restore_tenant_customer_accounts,
    sync_tenant_accounts_for_service_state,
    tenant_service_is_operational,
)


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
        session.rollback()
    finally:
        session.close()


def _seed_customer(db, *, tenant: Tenant) -> tuple[User, UserIdentity]:
    suffix = uuid4().hex[:10]
    user = User(username=f"client_{suffix}", password_hash="x", display_name="客户A", status=True)
    db.add(user)
    db.flush()
    identity = UserIdentity(
        identity_code=f"pytest_customer_{suffix}",
        user_id=user.id,
        tenant_id=tenant.id,
        identity_type="CUSTOMER",
        role_code="CUSTOMER_MEMBER",
        identity_name="客户A",
        status=True,
        deleted=False,
    )
    db.add(identity)
    db.flush()
    return user, identity


def test_disable_and_restore_tenant_accounts(db):
    suffix = uuid4().hex[:8]
    tenant = Tenant(
        name=f"T1-{suffix}",
        code=f"T1{suffix}",
        status=True,
        service_end_date=date.today() + timedelta(days=30),
    )
    db.add(tenant)
    db.flush()
    user, identity = _seed_customer(db, tenant=tenant)

    disable_tenant_customer_accounts(db, tenant.id)
    db.refresh(user)
    db.refresh(identity)
    assert identity.status is False
    assert identity.deleted is True
    assert user.status is False

    tenant.status = True
    tenant.stop_reason = None
    restore_tenant_customer_accounts(db, tenant.id)
    db.refresh(user)
    db.refresh(identity)
    assert identity.status is True
    assert identity.deleted is False
    assert user.status is True


def test_sync_restores_instead_of_disabling_on_expired_contract(db):
    # 2026-08-03 - 到期仍可登录；sync 恢复历史误禁用，不再 disable
    suffix = uuid4().hex[:8]
    tenant = Tenant(
        name=f"T2-{suffix}",
        code=f"T2{suffix}",
        status=False,
        service_end_date=date.today() - timedelta(days=1),
        stop_reason="expired",
    )
    db.add(tenant)
    db.flush()
    user, identity = _seed_customer(db, tenant=tenant)
    identity.status = False
    identity.deleted = True
    user.status = False
    db.flush()

    assert tenant_service_is_operational(tenant) is False
    sync_tenant_accounts_for_service_state(db, tenant)
    db.refresh(user)
    db.refresh(identity)
    assert user.status is True
    assert identity.status is True
    assert identity.deleted is False


def test_expire_overdue_marks_but_keeps_accounts(db):
    suffix = uuid4().hex[:8]
    tenant = Tenant(
        name=f"T3-{suffix}",
        code=f"T3{suffix}",
        status=True,
        service_end_date=date.today() - timedelta(days=2),
    )
    db.add(tenant)
    db.flush()
    user, identity = _seed_customer(db, tenant=tenant)
    tenant_id = tenant.id

    expire_overdue_tenant_services(db, today=date.today())
    marked = db.get(Tenant, tenant_id)
    assert marked is not None
    assert marked.status is False
    assert marked.stop_reason == "expired"
    db.refresh(user)
    db.refresh(identity)
    assert user.status is True
    assert identity.status is True


def test_customer_identity_active_when_service_not_started(db):
    suffix = uuid4().hex[:8]
    tenant = Tenant(
        name=f"T4-{suffix}",
        code=f"T4{suffix}",
        status=False,
        service_start_date=date.today() + timedelta(days=7),
    )
    db.add(tenant)
    db.flush()
    user, identity = _seed_customer(db, tenant=tenant)
    user.identities = [identity]
    identity.tenant = tenant
    assert tenant_service_is_operational(tenant) is False
    assert active_identities(user) == [identity]


def test_molizhishu_submit_blocked_before_service_start():
    tenant = Tenant(
        name="T5",
        code="T5",
        status=False,
        service_start_date=date.today() + timedelta(days=3),
    )
    with pytest.raises(ValueError, match="尚未开始"):
        _validate_tenant_service_available(tenant)


def test_service_gate_skip_message_and_dashboard_filter():
    from app.services.tenant_account_service import (
        is_service_gate_schedule_message,
        molizhishu_submit_skip_message,
    )

    pending = Tenant(
        name="T6",
        code="T6",
        status=False,
        service_start_date=date.today() + timedelta(days=3),
    )
    msg = molizhishu_submit_skip_message(pending)
    assert msg is not None
    assert "尚未开始" in msg
    assert "暂不提交" in msg
    assert is_service_gate_schedule_message("企业服务已停止，不能提交新的监测任务")
    assert not is_service_gate_schedule_message("模力接口超时")


def test_activate_due_tenant_services_flips_pending_start(db):
    from app.services.tenant_account_service import activate_due_tenant_services

    suffix = uuid4().hex[:8]
    pending = Tenant(
        name=f"T7-{suffix}",
        code=f"T7{suffix}",
        status=False,
        service_start_date=date.today() - timedelta(days=1),
        service_end_date=date.today() + timedelta(days=30),
        stop_reason=None,
    )
    manual = Tenant(
        name=f"T8-{suffix}",
        code=f"T8{suffix}",
        status=False,
        service_start_date=date.today() - timedelta(days=1),
        service_end_date=date.today() + timedelta(days=30),
        stop_reason="manual",
    )
    future = Tenant(
        name=f"T9-{suffix}",
        code=f"T9{suffix}",
        status=False,
        service_start_date=date.today() + timedelta(days=5),
        stop_reason=None,
    )
    db.add_all([pending, manual, future])
    db.flush()

    activated = activate_due_tenant_services(db, today=date.today())
    ids = {item.id for item in activated}
    assert pending.id in ids
    assert manual.id not in ids
    assert future.id not in ids
    db.refresh(pending)
    assert pending.status is True
    assert pending.stop_reason is None


def test_brand_word_service_start_schedule_key():
    from app.services.schedule_service import brand_word_service_start_schedule_key

    assert brand_word_service_start_schedule_key(date(2026, 8, 4)) == "bwstart-20260804"
