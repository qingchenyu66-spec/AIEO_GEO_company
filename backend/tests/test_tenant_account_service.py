"""Tests for tenant account linkage on service stop/expiry."""

from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.tenant import Tenant
from app.models.user import User
from app.models.user_identity import UserIdentity
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
    suffix = str(tenant.id)
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
    tenant = Tenant(name="T1", code="T1", status=True, service_end_date=date.today() + timedelta(days=30))
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


def test_sync_disables_on_expired_contract(db):
    tenant = Tenant(
        name="T2",
        code="T2",
        status=True,
        service_end_date=date.today() - timedelta(days=1),
        stop_reason="expired",
    )
    db.add(tenant)
    db.flush()
    user, identity = _seed_customer(db, tenant=tenant)

    assert tenant_service_is_operational(tenant) is False
    sync_tenant_accounts_for_service_state(db, tenant)
    db.refresh(user)
    db.refresh(identity)
    assert user.status is False
    assert identity.status is False


def test_expire_overdue_tenant_services_marks_and_disables(db):
    tenant = Tenant(
        name="T3",
        code="T3",
        status=True,
        service_end_date=date.today() - timedelta(days=2),
    )
    db.add(tenant)
    db.flush()
    user, _ = _seed_customer(db, tenant=tenant)

    count = expire_overdue_tenant_services(db, today=date.today())
    db.refresh(tenant)
    db.refresh(user)
    assert count == 1
    assert tenant.status is False
    assert tenant.stop_reason == "expired"
    assert user.status is False
