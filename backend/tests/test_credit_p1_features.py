"""算力 P1：删管理员守卫。"""
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.models.permission import CustomerPosition
from app.models.tenant import Tenant
from app.services.credit_service import BILLING_MODE_CREDIT
from app.services.enterprise_member_service import create_enterprise_member, remove_enterprise_member

ADMIN_CODE = "enterprise_admin"




def test_remove_last_admin_blocked(db):
    suffix = uuid4().hex[:8]
    tenant = Tenant(name="m", code=f"M{suffix}", billing_mode=BILLING_MODE_CREDIT, status=True)
    db.add(tenant)
    db.flush()
    admin_pos = db.scalar(
        select(CustomerPosition).where(
            CustomerPosition.position_code == ADMIN_CODE,
            CustomerPosition.deleted.is_(False),
        )
    )
    if admin_pos is None:
        pytest.skip("enterprise_admin position missing")
    ident = create_enterprise_member(
        db,
        tenant_id=tenant.id,
        display_name="管理员",
        username=f"admin_{suffix}",
        password="Password1!",
        customer_position_id=admin_pos.id,
        operator_user_id=1,
    )
    with pytest.raises(ValueError, match="管理员"):
        remove_enterprise_member(
            db,
            tenant_id=tenant.id,
            identity_id=ident.id,
            current_identity_id=ident.id + 999,
        )
